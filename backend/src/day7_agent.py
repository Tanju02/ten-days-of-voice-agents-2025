#!/usr/bin/env python3
"""
Updated DailyMart agent (agent.py)
- bcrypt password hashing
- atomic writes with locks
- asyncio.to_thread wrappers for blocking I/O
- Cart class replaces list-based cart
- Catalog compatibility loader
- Safe email sending with HTML + plaintext fallback
- Unique order IDs with UTC timestamp + uuid suffix
- Order status history tracking
- Maintains LiveKit Agent integration and function_tool endpoints
"""

import asyncio
import json
import logging
import os
import smtplib
import tempfile
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from threading import Lock
from typing import Annotated, Dict, List, Optional, Any
from dataclasses import dataclass

import bcrypt
from dotenv import load_dotenv
from pydantic import Field
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    function_tool,
    RunContext,
)
from livekit.plugins import deepgram, google, murf, silero

# Load environment variables
load_dotenv(".env.local")

logger = logging.getLogger("grocymate-agent")
logging.basicConfig(level=logging.INFO)

# File paths
USERS_FILE = "users.json"
ORDERS_FILE = "orders.json"
CATALOG_FILE = "catalog.json"
ORDERS_DIR = "orders"

# Locks for safe writes
_USERS_LOCK = Lock()
_ORDERS_LOCK = Lock()

# Default pricing rules
DEFAULT_DELIVERY_CHARGE = 50
DEFAULT_FREE_DELIVERY_THRESHOLD = 1000
DEFAULT_DISCOUNT_THRESHOLD = 5000
DEFAULT_DISCOUNT_PERCENTAGE = 10


# -------------------- Utilities --------------------

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_sync(path: str, data: Any) -> None:
    """Write JSON data atomically to prevent corruption."""
    dirn = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dirn)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


async def atomic_write(path: str, data: Any) -> None:
    await asyncio.to_thread(atomic_write_sync, path, data)


def ensure_orders_dir_sync():
    os.makedirs(ORDERS_DIR, exist_ok=True)
    # create orders.json if missing
    if not os.path.exists(ORDERS_FILE):
        atomic_write_sync(ORDERS_FILE, {})
    # ensure orders directory history file exists
    history_path = os.path.join(ORDERS_DIR, "history.json")
    if not os.path.exists(history_path):
        atomic_write_sync(history_path, {"orders": []})


async def ensure_orders_dir() -> None:
    await asyncio.to_thread(ensure_orders_dir_sync)


def load_json_sync(path: str) -> Any:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def load_json(path: str) -> Any:
    return await asyncio.to_thread(load_json_sync, path)


def safe_timestamp_for_filename() -> str:
    # Compact UTC timestamp for filenames
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# -------------------- Cart --------------------

class Cart:
    """Robust cart representation."""

    def __init__(self):
        # item_id -> {item: <catalog item dict>, quantity: int}
        self.lines: Dict[str, Dict[str, Any]] = {}

    def add(self, item: Dict[str, Any], qty: int = 1):
        if qty <= 0:
            return
        iid = item["id"]
        if iid in self.lines:
            self.lines[iid]["quantity"] += qty
        else:
            # keep a small snapshot of item fields we need
            self.lines[iid] = {
                "id": iid,
                "name": item.get("name", ""),
                "price": item.get("price", 0),
                "quantity": qty,
                "brand": item.get("brand", ""),
                "size": item.get("size", ""),
            }

    def remove(self, item_id: str, qty: Optional[int] = None):
        if item_id not in self.lines:
            raise KeyError("item not in cart")
        if qty is None or qty >= self.lines[item_id]["quantity"]:
            del self.lines[item_id]
        else:
            self.lines[item_id]["quantity"] -= qty

    def update(self, item_id: str, qty: int):
        if qty <= 0:
            self.remove(item_id)
        else:
            if item_id in self.lines:
                self.lines[item_id]["quantity"] = qty
            else:
                raise KeyError("item not in cart")

    def list(self) -> List[Dict[str, Any]]:
        return [v.copy() for v in self.lines.values()]

    def subtotal(self) -> float:
        return sum(v["quantity"] * v["price"] for v in self.lines.values())

    def is_empty(self) -> bool:
        return len(self.lines) == 0

    def clear(self):
        self.lines.clear()


# -------------------- Catalog loader --------------------

def load_catalog_sync(path: str = CATALOG_FILE) -> Dict[str, Any]:
    """Load catalog and normalize to category-based structure.

    Accepts:
      - flat format: { "store_name": "...", "items": [ ... ] }
      - category format: { "categories": { key: { name, items: [...] } }, "recipes": {...} }
    Returns normalized catalog with 'categories' and 'recipes' keys.
    """
    if not os.path.exists(path):
        return {"categories": {}, "recipes": {}}
    with open(path, "r", encoding="utf-8") as f:
        c = json.load(f)
    if "categories" in c and isinstance(c.get("categories"), dict):
        # already category-based
        c.setdefault("recipes", {})
        return c
    # If 'items' flat list present, put into default category 'All'
    if "items" in c and isinstance(c.get("items"), list):
        return {
            "store_name": c.get("store_name", "GrocyMate"),
            "categories": {
                "all": {"name": "All Items", "items": c["items"]},
            },
            "recipes": c.get("recipes", {}),
        }
    # fallback empty
    return {"categories": {}, "recipes": {}}


async def load_catalog(path: str = CATALOG_FILE) -> Dict[str, Any]:
    return await asyncio.to_thread(load_catalog_sync, path)


# -------------------- Password helpers --------------------

def normalize_password_for_speech(password: str) -> str:
    """Normalize spoken numbers to digits; keep tokenized replacement to avoid accidental replacements."""
    import re

    password = password.strip().lower()
    tokens = re.split(r"\s+", password)
    mapping = {
        "zero": "0",
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
    }
    normalized = "".join(mapping.get(tok, tok) for tok in tokens)
    # remove spaces/special whitespace
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def hash_password(plain_password: str) -> str:
    pw = plain_password.encode("utf-8")
    hashed = bcrypt.hashpw(pw, bcrypt.gensalt())
    return hashed.decode("utf-8")


def check_password(plain_password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# -------------------- DailyMartAgent --------------------

class DailyMartAgent:
    def __init__(self):
        self.current_user: Optional[str] = None  # email
        self.cart = Cart()
        self.catalog = {}  # loaded via async loader at session start (we'll load synchronously here)
        # load catalogs & state synchronously for object creation convenience
        try:
            self.catalog = load_catalog_sync(CATALOG_FILE)
        except Exception:
            self.catalog = {"categories": {}, "recipes": {}}
        # users and orders are maintained in memory, persisted to JSON
        self.users: Dict[str, Any] = {}
        self.orders: Dict[str, Any] = {}
        self.pending_order: Optional[Dict[str, Any]] = None
        self.customer_name_used = False
        self.budget_limit: Optional[int] = None
        self.dietary_filter: Optional[str] = None
        self.order_statuses = [
            "received",
            "confirmed",
            "being_prepared",
            "out_for_delivery",
            "delivered",
        ]

        # Pricing rules
        self.DELIVERY_CHARGE = int(os.getenv("DELIVERY_CHARGE", DEFAULT_DELIVERY_CHARGE))
        self.FREE_DELIVERY_THRESHOLD = int(
            os.getenv("FREE_DELIVERY_THRESHOLD", DEFAULT_FREE_DELIVERY_THRESHOLD)
        )
        self.DISCOUNT_THRESHOLD = int(os.getenv("DISCOUNT_THRESHOLD", DEFAULT_DISCOUNT_THRESHOLD))
        self.DISCOUNT_PERCENTAGE = int(
            os.getenv("DISCOUNT_PERCENTAGE", DEFAULT_DISCOUNT_PERCENTAGE)
        )

        # Load persisted data
        self._load_users_sync()
        self._load_orders_sync()
        # ensure orders dir and files exist
        ensure_orders_dir_sync()

    # -------------------- Persistence: synchronous primitives used via threads --------------------
    def _load_users_sync(self):
        if os.path.exists(USERS_FILE):
            try:
                with open(USERS_FILE, "r", encoding="utf-8") as f:
                    self.users = json.load(f)
            except Exception as e:
                logger.error("Failed loading users.json: %s", e)
                self.users = {}
        else:
            self.users = {}

    async def load_users_async(self):
        await asyncio.to_thread(self._load_users_sync)

    def _save_users_sync(self):
        with _USERS_LOCK:
            atomic_write_sync(USERS_FILE, self.users)
            logger.info("Saved users to %s", USERS_FILE)

    async def save_users_async(self):
        await asyncio.to_thread(self._save_users_sync)

    def _load_orders_sync(self):
        # Orders stored in ORDERS_FILE as dict {order_id: order_obj}
        if os.path.exists(ORDERS_FILE):
            try:
                with open(ORDERS_FILE, "r", encoding="utf-8") as f:
                    self.orders = json.load(f)
            except Exception as e:
                logger.error("Failed loading orders.json: %s", e)
                self.orders = {}
        else:
            self.orders = {}

    async def load_orders_async(self):
        await asyncio.to_thread(self._load_orders_sync)

    def _save_orders_sync(self):
        with _ORDERS_LOCK:
            atomic_write_sync(ORDERS_FILE, self.orders)
            logger.info("Saved orders to %s", ORDERS_FILE)
            # also append to history file inside orders/
            history_path = os.path.join(ORDERS_DIR, "history.json")
            try:
                history = load_json_sync(history_path)
            except FileNotFoundError:
                history = {"orders": []}
            # refresh history entries to include minimal order summary
            # We'll ensure every order present in orders.json is also in history (append-only unique by order_id)
            existing_ids = {o["order_id"] for o in history.get("orders", [])}
            new_entries = []
            for oid, order in self.orders.items():
                if oid not in existing_ids:
                    new_entries.append(
                        {
                            "order_id": oid,
                            "timestamp": order.get("timestamp", utcnow_iso()),
                            "status": order.get("status", ""),
                            "total": order.get("total", 0),
                        }
                    )
            if new_entries:
                history["orders"].extend(new_entries)
                atomic_write_sync(history_path, history)

    async def save_orders_async(self):
        await asyncio.to_thread(self._save_orders_sync)

    # -------------------- Catalog utilities --------------------
    def find_item_by_name(self, item_name: str) -> Optional[Dict[str, Any]]:
        item_name_lower = item_name.lower().strip()
        # search items across categories
        for category in self.catalog.get("categories", {}).values():
            for item in category.get("items", []):
                if item_name_lower in item.get("name", "").lower():
                    return item
        # Try token partial match
        tokens = item_name_lower.split()
        for category in self.catalog.get("categories", {}).values():
            for item in category.get("items", []):
                name_low = item.get("name", "").lower()
                if any(tok and tok in name_low for tok in tokens):
                    return item
        return None

    def get_recipe_ingredients(self, recipe_name: str):
        recipe_name_lower = recipe_name.lower().strip()
        for recipe_key, recipe_data in self.catalog.get("recipes", {}).items():
            # match by key or recipe 'name' field
            if recipe_name_lower in recipe_key.lower() or recipe_name_lower in recipe_data.get(
                "name", ""
            ).lower():
                ingredients = []
                for ingredient_id in recipe_data.get("ingredients", []):
                    # find item by id
                    for category in self.catalog.get("categories", {}).values():
                        for item in category.get("items", []):
                            if item.get("id") == ingredient_id:
                                ingredients.append(item)
                                break
                return ingredients, recipe_data.get("serves", 0)
        return [], 0

    # -------------------- Pricing helpers --------------------
    def calculate_cart_subtotal(self) -> float:
        return float(self.cart.subtotal())

    def calculate_delivery_charge(self, subtotal: float) -> float:
        if subtotal >= self.FREE_DELIVERY_THRESHOLD:
            return 0.0
        return float(self.DELIVERY_CHARGE)

    def calculate_discount(self, subtotal: float) -> float:
        if subtotal >= self.DISCOUNT_THRESHOLD:
            return float(subtotal * (self.DISCOUNT_PERCENTAGE / 100.0))
        return 0.0

    def calculate_order_total(self) -> Dict[str, float]:
        subtotal = self.calculate_cart_subtotal()
        delivery = self.calculate_delivery_charge(subtotal)
        discount = self.calculate_discount(subtotal)
        total = subtotal + delivery - discount
        return {"subtotal": subtotal, "delivery_charge": delivery, "discount": discount, "total": total}

    # -------------------- Order helpers --------------------
    def _generate_order_id(self) -> str:
        # UTC timestamp + 6 hex chars
        short = uuid.uuid4().hex[:6]
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"ORD_{ts}_{short}"

    async def send_confirmation_email_async(self, order: Dict[str, Any]) -> bool:
        """Send confirmation email in thread (non-blocking)."""
        return await asyncio.to_thread(self._send_confirmation_email_sync, order)

    def _send_confirmation_email_sync(self, order: Dict[str, Any]) -> bool:
        """Blocking email sender used inside a thread."""
        try:
            smtp_server = os.getenv("SMTP_SERVER")
            smtp_port = int(os.getenv("SMTP_PORT", 587))
            sender_email = os.getenv("SENDER_EMAIL")
            sender_password = os.getenv("SENDER_PASSWORD")
            sender_name = os.getenv("SENDER_NAME", "GrocyMate")

            if not all([smtp_server, sender_email, sender_password]):
                logger.warning("SMTP configuration incomplete; skipping email send.")
                return False

            customer = self.users.get(order["customer_email"], {})
            customer_name = customer.get("name", "Customer")
            customer_email = customer.get("email", order.get("customer_email"))

            # Build HTML and plaintext content
            items_html = ""
            for item in order.get("items", []):
                item_total = item.get("quantity", 0) * item.get("price", 0)
                items_html += f"""
                    <div class="item-row">
                        <div class="item-details">
                            <div class="item-name">{item.get('name')}</div>
                            <div class="item-meta">{item.get('brand','')} • {item.get('size','')} • Qty: {item.get('quantity')}</div>
                        </div>
                        <div class="item-price">
                            ₹{item.get('price')} × {item.get('quantity')}<br><strong>₹{item_total}</strong>
                        </div>
                    </div>
                """

            # Plaintext fallback
            plain_items = ""
            for item in order.get("items", []):
                item_total = item.get("quantity", 0) * item.get("price", 0)
                plain_items += f"- {item.get('quantity')}x {item.get('name')} @ ₹{item.get('price')} each = ₹{item_total}\n"

            subtotal = order.get("subtotal", order.get("total", 0))
            delivery = order.get("delivery_charge", 0)
            discount = order.get("discount", 0)

            # Simple HTML template (kept minimal here so we don't bloat)
            html_content = f"""\
                <html>
                  <body>
                    <h2>GrocyMate — Order Confirmation</h2>
                    <p>Hi {customer_name},</p>
                    <p>Thanks for your order. Order ID: <strong>{order['order_id']}</strong></p>
                    <h3>Items</h3>
                    {items_html}
                    <hr>
                    <p>Subtotal: ₹{subtotal}</p>
                    <p>Delivery: {'FREE' if delivery==0 else '₹'+str(delivery)}</p>
                    {'<p>Discount: -₹{}</p>'.format(discount) if discount else ''}
                    <p><strong>Total: ₹{order['total']}</strong></p>
                    <p>Delivery Address: {order.get('delivery_address', 'Not provided')}</p>
                    <p>Thanks! — GrocyMate</p>
                  </body>
                </html>
            """

            plain_content = f"""GrocyMate — Order Confirmation

Order ID: {order['order_id']}
Customer: {customer_name}
Items:
{plain_items}

Subtotal: ₹{subtotal}
Delivery: {'FREE' if delivery==0 else '₹'+str(delivery)}
{'Discount: -₹' + str(discount) if discount else ''}
Total: ₹{order['total']}
Delivery Address: {order.get('delivery_address', 'Not provided')}

Thank you for shopping with GrocyMate!
"""

            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"Order Confirmation - {order['order_id']}"
            msg["From"] = f"{sender_name} <{sender_email}>"
            msg["To"] = customer_email

            part1 = MIMEText(plain_content, "plain")
            part2 = MIMEText(html_content, "html")
            msg.attach(part1)
            msg.attach(part2)

            # send
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
            try:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg)
                logger.info("Confirmation email sent for order %s", order["order_id"])
                return True
            finally:
                try:
                    server.quit()
                except Exception:
                    pass

        except Exception as e:
            logger.exception("Failed to send confirmation email: %s", e)
            return False

    def update_order_status_sync(self, order_id: str) -> bool:
        """Synchronous status advancement used when called from thread."""
        if order_id not in self.orders:
            return False
        order = self.orders[order_id]
        current_status = order.get("status", "received")
        if current_status in self.order_statuses:
            idx = self.order_statuses.index(current_status)
            if idx < len(self.order_statuses) - 1:
                next_status = self.order_statuses[idx + 1]
                # push history
                order.setdefault("status_history", []).append(
                    {"status": current_status, "at": order.get("last_updated", utcnow_iso())}
                )
                order["status"] = next_status
                order["last_updated"] = utcnow_iso()
                # persist
                self._save_orders_sync()
                return True
        return False

    async def update_order_status(self, order_id: str) -> bool:
        return await asyncio.to_thread(self.update_order_status_sync, order_id)


# -------------------- Function tools (LiveKit) --------------------

@dataclass
class Userdata:
    """User session data"""
    agent: DailyMartAgent


# function_tool endpoints:

@function_tool
async def register_new_customer(
    ctx: RunContext[Userdata],
    name: Annotated[str, Field(description="Customer's full name")],
    email: Annotated[str, Field(description="Customer's email address")],
    password: Annotated[str, Field(description="Customer's chosen password")],
    address: Annotated[str, Field(description="Customer's delivery address")],
    mobile: Annotated[str, Field(description="Customer's mobile number")],
) -> str:
    agent = ctx.userdata.agent
    email = email.strip().lower()
    if email in agent.users:
        return f"Email {email} is already registered. Please try logging in instead."

    normalized_pass = normalize_password_for_speech(password)
    hashed = hash_password(normalized_pass)

    agent.users[email] = {
        "name": name.strip(),
        "email": email,
        "password": hashed,
        "address": address.strip(),
        "mobile": mobile.strip(),
        "created_at": utcnow_iso(),
    }
    await agent.save_users_async()
    agent.current_user = email
    return f"Welcome {name}! Your account has been created successfully. You're now logged in and ready to shop."


@function_tool
async def login_customer(
    ctx: RunContext[Userdata],
    email: Annotated[str, Field(description="Customer's email address")],
    password: Annotated[str, Field(description="Customer's password")],
) -> str:
    agent = ctx.userdata.agent
    email = email.strip().lower()
    if email not in agent.users:
        return "Email not found. Please check your email or register as a new customer."

    normalized_pass = normalize_password_for_speech(password)
    hashed = agent.users[email]["password"]
    if not check_password(normalized_pass, hashed):
        return "Incorrect password. Please try again."

    agent.current_user = email
    user_name = agent.users[email]["name"]
    return f"Welcome back {user_name}! You're now logged in and ready to shop."


@function_tool
async def add_item_to_cart(
    ctx: RunContext[Userdata],
    item_name: Annotated[str, Field(description="Name of the item to add")],
    quantity: Annotated[int, Field(description="Quantity of the item")] = 1,
) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first to start shopping."

    item = agent.find_item_by_name(item_name)
    if not item:
        return f"Sorry, I couldn't find '{item_name}' in our catalog. Could you try a different name?"

    # Dietary filter (strict)
    if agent.dietary_filter:
        item_tags = [tag.lower() for tag in item.get("tags", [])]
        if agent.dietary_filter not in item_tags:
            return f"Sorry, {item['name']} doesn't match your {agent.dietary_filter} dietary preference."

    # Budget warning (informational only)
    budget_warning = ""
    if agent.budget_limit:
        current_total = agent.calculate_cart_subtotal()
        new_total = current_total + (quantity * item.get("price", 0))
        if new_total > agent.budget_limit:
            budget_warning = f" Note: This exceeds your budget limit of ₹{agent.budget_limit}. New total: ₹{new_total}."

    # Add item via Cart
    agent.cart.add(item, quantity)
    total_price = quantity * item.get("price", 0)
    return f"Added {quantity} x {item['name']} to your cart (₹{total_price}){budget_warning}"


@function_tool
async def add_recipe_ingredients(
    ctx: RunContext[Userdata],
    recipe_name: Annotated[str, Field(description="Name of the recipe or dish")],
) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first to start shopping."

    ingredients, serves = agent.get_recipe_ingredients(recipe_name)
    if not ingredients:
        return f"Sorry, I don't have a recipe for '{recipe_name}'. Try asking for specific ingredients instead."

    added_items = []
    total_cost = 0
    for ingredient in ingredients:
        agent.cart.add(ingredient, 1)
        added_items.append(ingredient.get("name"))
        total_cost += ingredient.get("price", 0)

    return f"Added ingredients for {recipe_name} (serves {serves}): {', '.join(added_items)}. Total: ₹{total_cost}"


@function_tool
async def show_catalog(
    ctx: RunContext[Userdata],
    category: Annotated[
        str,
        Field(description="Category to show: groceries, spices, snacks, prepared_food, beverages, sweets, or all"),
    ] = "all",
) -> str:
    agent = ctx.userdata.agent
    if category.lower() == "all":
        catalog_text = "Here are our available categories:\n\n"
        for cat_key, cat_data in agent.catalog.get("categories", {}).items():
            catalog_text += f"📂 {cat_data.get('name','Unnamed')} ({len(cat_data.get('items',[]))} items)\n"
        catalog_text += "\nWhich category would you like to see? Say 'show groceries' or 'show snacks' etc."
        return catalog_text

    category_lower = category.lower()
    matching = None
    for cat_key, cat_data in agent.catalog.get("categories", {}).items():
        if category_lower in cat_key.lower() or category_lower in cat_data.get("name", "").lower():
            matching = cat_data
            break
    if not matching:
        available = ", ".join([c.get("name", "") for c in agent.catalog.get("categories", {}).values()])
        return f"Category not found. Available categories: {available}"

    catalog_text = f"📂 {matching.get('name')}:\n\n"
    for item in matching.get("items", []):
        catalog_text += f"• {item.get('name')} - ₹{item.get('price')} ({item.get('brand','')}, {item.get('size','')})\n"
    catalog_text += f"\nTotal {len(matching.get('items', []))} items available. Say 'add [item name]' to add to cart."
    return catalog_text


@function_tool
async def remove_item_from_cart(
    ctx: RunContext[Userdata], item_name: Annotated[str, Field(description="Name of the item to remove")]
) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first."

    # find matching item id in cart
    for iid, cart_item in list(agent.cart.lines.items()):
        if item_name.lower() in cart_item["name"].lower():
            agent.cart.remove(iid)
            return f"Removed {cart_item['name']} from your cart"
    return f"'{item_name}' not found in your cart"


@function_tool
async def update_item_quantity(
    ctx: RunContext[Userdata],
    item_name: Annotated[str, Field(description="Name of the item to update")],
    new_quantity: Annotated[int, Field(description="New quantity for the item")],
) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first."

    for iid, cart_item in list(agent.cart.lines.items()):
        if item_name.lower() in cart_item["name"].lower():
            if new_quantity <= 0:
                agent.cart.remove(iid)
                return f"Removed {cart_item['name']} from your cart"
            agent.cart.update(iid, new_quantity)
            total_price = new_quantity * cart_item["price"]
            return f"Updated {cart_item['name']} quantity to {new_quantity} (₹{total_price})"
    return f"'{item_name}' not found in your cart"


@function_tool
async def view_cart(ctx: RunContext[Userdata]) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first."
    if agent.cart.is_empty():
        return "Your cart is empty. Start adding some items!"
    cart_summary = "Your cart contains:\n"
    total = 0
    for line in agent.cart.list():
        item_total = line["quantity"] * line["price"]
        total += item_total
        cart_summary += f"- {line['quantity']}x {line['name']} (₹{line['price']} each) = ₹{item_total}\n"
    cart_summary += f"\nSubtotal: ₹{total}"
    return cart_summary


@function_tool
async def review_order_details(ctx: RunContext[Userdata]) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first."
    if agent.cart.is_empty():
        return "Your cart is empty. Add some items before placing an order."

    customer = agent.users.get(agent.current_user, {})
    pricing = agent.calculate_order_total()
    order_id = agent._generate_order_id()
    agent.pending_order = {
        "order_id": order_id,
        "customer_email": agent.current_user,
        "customer_name": customer.get("name", ""),
        "items": agent.cart.list(),
        "subtotal": pricing["subtotal"],
        "delivery_charge": pricing["delivery_charge"],
        "discount": pricing["discount"],
        "total": pricing["total"],
        "status": "pending_confirmation",
        "timestamp": utcnow_iso(),
        "delivery_address": customer.get("address", ""),
    }

    review_text = f"Please review your order details:\n\n"
    review_text += f"Name: {customer.get('name')}\n"
    review_text += f"Email: {customer.get('email')}\n"
    review_text += f"Delivery Address: {customer.get('address')}\n\n"
    review_text += f"Order Items:\n"
    for item in agent.cart.list():
        item_total = item["quantity"] * item["price"]
        review_text += f"- {item['quantity']}x {item['name']} = ₹{item_total}\n"
    review_text += f"\nSubtotal: ₹{pricing['subtotal']}"
    review_text += f"\nDelivery Charge: {'FREE' if pricing['delivery_charge']==0 else '₹'+str(pricing['delivery_charge'])}"
    if pricing["discount"] > 0:
        review_text += f"\nDiscount ({agent.DISCOUNT_PERCENTAGE}%): -₹{pricing['discount']}"
    review_text += f"\n\nTotal Amount: ₹{pricing['total']}\n\n"
    review_text += "Are all these details correct? Say 'yes' to confirm your order or 'no' to make changes."
    return review_text


@function_tool
async def reset_password(
    ctx: RunContext[Userdata],
    email: Annotated[str, Field(description="Customer's email address")],
    new_password: Annotated[str, Field(description="Customer's new password")],
) -> str:
    agent = ctx.userdata.agent
    email = email.strip().lower()
    if email not in agent.users:
        return "Email not found. Please register as a new customer."

    normalized = normalize_password_for_speech(new_password)
    agent.users[email]["password"] = hash_password(normalized)
    await agent.save_users_async()
    return f"Password reset successfully for {email}. You can now log in with your new password."


@function_tool
async def show_order_history(ctx: RunContext[Userdata]) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first."

    customer_orders = [o for o in agent.orders.values() if o.get("customer_email") == agent.current_user]
    if not customer_orders:
        return "You have no orders yet. Start shopping to place your first order!"
    recent_orders = sorted(customer_orders, key=lambda x: x.get("timestamp", ""), reverse=True)[:5]
    summary = f"You have {len(customer_orders)} order(s). Here are your recent orders:\n\n"
    for idx, order in enumerate(recent_orders, 1):
        order_date = order.get("timestamp", "")
        try:
            order_date = datetime.fromisoformat(order_date).strftime("%B %d, %Y")
        except Exception:
            pass
        summary += f"{idx}. Order ID: {order['order_id']}\n"
        summary += f"   Date: {order_date}\n"
        summary += f"   Status: {order.get('status','').replace('_',' ').title()}\n"
        summary += f"   Total: ₹{order.get('total')}\n"
        items_list = [f"{it['quantity']}x {it['name']}" for it in order.get("items", [])[:3]]
        summary += f"   Items: {', '.join(items_list)}"
        if len(order.get("items", [])) > 3:
            summary += f" and {len(order.get('items', [])) - 3} more"
        summary += "\n\n"

    summary += "To reorder any of these, just say 'reorder my last order' or 'reorder order number 2' or provide the Order ID."
    return summary


@function_tool
async def show_last_order(ctx: RunContext[Userdata]) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first."

    customer_orders = [o for o in agent.orders.values() if o.get("customer_email") == agent.current_user]
    if not customer_orders:
        return "You don't have any previous orders yet. Start shopping to place your first order!"
    last_order = sorted(customer_orders, key=lambda x: x.get("timestamp", ""), reverse=True)[0]
    try:
        order_date = datetime.fromisoformat(last_order.get("timestamp", "")).strftime("%B %d, %Y at %I:%M %p")
    except Exception:
        order_date = last_order.get("timestamp", "")
    summary = "Here's your last order:\n\n"
    summary += f"Order ID: {last_order['order_id']}\n"
    summary += f"Date: {order_date}\n"
    summary += f"Status: {last_order.get('status','').replace('_',' ').title()}\n"
    summary += f"Delivery Address: {last_order.get('delivery_address')}\n\n"
    summary += "Items:\n"
    for item in last_order.get("items", []):
        item_total = item.get("quantity", 0) * item.get("price", 0)
        summary += f"- {item.get('quantity')}x {item.get('name')} (₹{item.get('price')} each) = ₹{item_total}\n"
    summary += f"\nTotal: ₹{last_order.get('total')}"
    summary += f"\n\nWould you like to reorder this? Just say 'reorder my last order'."
    return summary


@function_tool
async def reorder_last_order(ctx: RunContext[Userdata]) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first."
    customer_orders = [o for o in agent.orders.values() if o.get("customer_email") == agent.current_user]
    if not customer_orders:
        return "You don't have any previous orders to reorder. Start shopping to place your first order!"
    last_order = sorted(customer_orders, key=lambda x: x.get("timestamp", ""), reverse=True)[0]

    added_items = []
    total_cost = 0
    for item in last_order.get("items", []):
        # if already present, increase qty
        agent.cart.add(item, item.get("quantity", 1))
        added_items.append(f"{item.get('quantity')}x {item.get('name')}")
        total_cost += item.get("quantity", 0) * item.get("price", 0)

    order_date = last_order.get("timestamp", "")
    try:
        order_date = datetime.fromisoformat(order_date).strftime("%B %d, %Y")
    except Exception:
        pass
    return f"Great! I've added items from your last order ({last_order['order_id']} placed on {order_date}) to your cart: {', '.join(added_items)}. Total added: ₹{total_cost}. Say 'show cart' to review."


@function_tool
async def reorder_previous_order(
    ctx: RunContext[Userdata], order_id: Annotated[str, Field(description="Order ID to reorder")]
) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first."
    if order_id not in agent.orders:
        return f"I couldn't find order {order_id}. Please say 'show my orders' to see your order history."
    order = agent.orders[order_id]
    if order.get("customer_email") != agent.current_user:
        return "Order not found or doesn't belong to you."
    added_items = []
    total_cost = 0
    for item in order.get("items", []):
        agent.cart.add(item, item.get("quantity", 1))
        added_items.append(f"{item.get('quantity')}x {item.get('name')}")
        total_cost += item.get("quantity", 0) * item.get("price", 0)
    order_date = order.get("timestamp", "")
    try:
        order_date = datetime.fromisoformat(order_date).strftime("%B %d, %Y")
    except Exception:
        pass
    return f"Perfect! I've added items from order {order_id} (placed on {order_date}) to your cart: {', '.join(added_items)}. Total added: ₹{total_cost}. Say 'show cart' to review."


@function_tool
async def check_order_status(
    ctx: RunContext[Userdata], order_id: Annotated[str, Field(description="Order ID to check")]
) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first."
    if order_id in agent.orders:
        order = agent.orders[order_id]
        if order.get("customer_email") == agent.current_user:
            return f"Order {order_id}: Status is '{order.get('status')}'. Total: ₹{order.get('total')}"
        return "Order not found or doesn't belong to you."
    return f"Order {order_id} not found."


@function_tool
async def set_budget_limit(
    ctx: RunContext[Userdata], budget: Annotated[int, Field(description="Budget limit in rupees")]
) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first."
    agent.budget_limit = budget
    return f"Budget limit set to ₹{budget}. I'll help you stay within this limit."


@function_tool
async def set_dietary_filter(
    ctx: RunContext[Userdata], filter_type: Annotated[str, Field(description="Dietary filter: vegan, vegetarian, gluten-free, or none")]
) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first."
    if filter_type.lower() == "none":
        agent.dietary_filter = None
        return "Dietary filter removed. All items are now available."
    agent.dietary_filter = filter_type.lower()
    return f"Dietary filter set to {filter_type}. I'll only suggest {filter_type} items."


@function_tool
async def get_recommendations(ctx: RunContext[Userdata]) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first."
    # Frequent items calculation (top 3)
    item_counts = {}
    customer_orders = [o for o in agent.orders.values() if o.get("customer_email") == agent.current_user]
    for order in customer_orders:
        for item in order.get("items", []):
            iid = item.get("id")
            item_counts[iid] = item_counts.get(iid, 0) + item.get("quantity", 0)
    sorted_items = sorted(item_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    if not sorted_items:
        return "You don't have enough order history for recommendations yet. Try browsing our catalog!"
    recommendations = "Based on your order history, you might like:\n"
    for iid, _ in sorted_items:
        # find item meta
        found = None
        for cat in agent.catalog.get("categories", {}).values():
            for it in cat.get("items", []):
                if it.get("id") == iid:
                    found = it
                    break
            if found:
                break
        if found:
            recommendations += f"• {found.get('name')} - ₹{found.get('price')} ({found.get('brand','')})\n"
    recommendations += "\nWould you like to add any of these to your cart?"
    return recommendations


@function_tool
async def check_delivery_charges(ctx: RunContext[Userdata]) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first."
    if agent.cart.is_empty():
        return "Your cart is empty. Add items to check delivery charges."
    pricing = agent.calculate_order_total()
    if pricing["delivery_charge"] == 0:
        return f"Great news! Your order qualifies for FREE delivery as it's above ₹{agent.FREE_DELIVERY_THRESHOLD}. Current subtotal: ₹{pricing['subtotal']}"
    remaining = int(agent.FREE_DELIVERY_THRESHOLD - pricing["subtotal"])
    if remaining < 0:
        remaining = 0
    return f"Delivery charge is ₹{pricing['delivery_charge']}. Add items worth ₹{remaining} more to get FREE delivery! Current subtotal: ₹{pricing['subtotal']}"


@function_tool
async def check_discount_eligibility(ctx: RunContext[Userdata]) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first."
    if agent.cart.is_empty():
        return "Your cart is empty. Add items to check discount eligibility."
    pricing = agent.calculate_order_total()
    if pricing["discount"] > 0:
        return f"Congratulations! You're getting a {agent.DISCOUNT_PERCENTAGE}% discount of ₹{int(pricing['discount'])} on your order of ₹{int(pricing['subtotal'])}. Discounts are available on orders above ₹{agent.DISCOUNT_THRESHOLD} and during festival seasons!"
    remaining = int(agent.DISCOUNT_THRESHOLD - pricing["subtotal"])
    if remaining < 0:
        remaining = 0
    return f"Currently, discounts are available only during festival seasons and on orders above ₹{agent.DISCOUNT_THRESHOLD}. Add items worth ₹{remaining} more to qualify for {agent.DISCOUNT_PERCENTAGE}% discount! Current subtotal: ₹{pricing['subtotal']}"


@function_tool
async def advance_order_status(
    ctx: RunContext[Userdata], order_id: Annotated[str, Field(description="Order ID to advance status")]
) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user:
        return "Please log in first."
    ok = await agent.update_order_status(order_id)
    if ok:
        order = agent.orders.get(order_id)
        return f"Order {order_id} status updated to: {order.get('status')}"
    return f"Could not advance status for order {order_id}"


@function_tool
async def confirm_order(
    ctx: RunContext[Userdata], confirmation: Annotated[str, Field(description="Customer's confirmation response (yes/no)")]
) -> str:
    agent = ctx.userdata.agent
    if not agent.current_user or not agent.pending_order:
        return "No pending order to confirm. Please review your order first."

    confirmation_lower = confirmation.lower()
    if "yes" in confirmation_lower or "confirm" in confirmation_lower or "correct" in confirmation_lower:
        order = agent.pending_order
        order["status"] = "received"
        order["last_updated"] = utcnow_iso()
        # persist
        agent.orders[order["order_id"]] = order
        await agent.save_orders_async()

        # Send email (non-blocking)
        try:
            email_sent = await agent.send_confirmation_email_async(order)
        except Exception:
            email_sent = False

        # clear cart and pending order
        agent.cart.clear()
        agent.pending_order = None

        email_msg = " A confirmation email has been sent to your registered email address." if email_sent else ""
        return f"Order confirmed successfully! Order ID: {order['order_id']}. Total: ₹{int(order['total'])}. We'll deliver to {order.get('delivery_address')}.{email_msg} Thank you for choosing GrocyMate!"

    elif "no" in confirmation_lower or "change" in confirmation_lower or "incorrect" in confirmation_lower:
        agent.pending_order = None
        return "Order cancelled. You can continue shopping and modify your cart, or update your profile details if needed."
    else:
        return "Please say 'yes' to confirm your order or 'no' to make changes."


# -------------------- LiveKit Agent class & entrypoint --------------------

class DailyMartVoiceAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
            You are a friendly GrocyMate grocery ordering assistant. ONLY speak in English.

            GREETING: Always start with a warm introduction:
           " Hello! Welcome to GrocyMate, your friendly grocery and essentials partner. I can help you order groceries, spices, snacks, and prepared foods. Are you a new customer or do you already have an account with us?"

            IMPORTANT: Only use customer's name ONCE after login/registration. Don't repeat their name in every response.

            CUSTOMER FLOW:
            - For new: collect name, email, password, address, mobile for registration
            - For existing: ask email and password to log in

            PASSWORD HANDLING:
            - Accept spoken numbers like "two two three three" as "2233"
            - Be flexible with password input

            ORDER HISTORY & REORDERING:
            - When user asks "show my previous orders" or "show my orders" - use show_order_history() function
            - When user asks "show my last order" or "what was my last order" - use show_last_order() function (NO ORDER ID NEEDED)
            - When user says "reorder my last order" or "order again" or "same order" - use reorder_last_order() function (NO ORDER ID NEEDED)
            - When user provides specific Order ID like "reorder ORD_123" - use reorder_previous_order() function
            - If user says "reorder" without specifying, ALWAYS use reorder_last_order() first
            - When user asks "where is my order" or order status - use check_order_status() function
            - When user asks for recommendations - use get_recommendations() function
            - NEVER ask for Order ID when user says "show last order" or "reorder" - handle it automatically

            BUDGET & DIETARY:
            - When user sets budget limit like "keep it under 1000" - use set_budget_limit() function
            - Budget limits are WARNINGS only - still add items if user insists (says "continue", "yes", "add anyway")
            - When user wants dietary filter like "only vegan items" - use set_dietary_filter() function
            - Dietary filters are STRICT - don't add items that don't match
            - If user says "continue" or "yes" after budget warning, proceed with adding the item

            DELIVERY CHARGES & DISCOUNTS:
            - When user asks about delivery charges - use check_delivery_charges() function
            - Delivery is ₹50, but FREE on orders above ₹1000
            - When user asks about discounts - use check_discount_eligibility() function
            - Discounts are available ONLY during festival seasons AND on orders above ₹5000 (10% off)
            - Always mention both conditions: festival season + order value
            - The view_cart and review_order_details functions automatically show delivery and discount

            Once logged in, help with:
            - Browse catalog (use show_catalog function)
            - Add/remove items from cart
            - Handle 'ingredients for X' requests for Indian recipes
            - Cart management (view, update quantities, remove items)
            - Order history and reordering
            - Check delivery charges and discount eligibility

            Available categories: Groceries, Spices & Masalas, Snacks & Namkeen, Ready to Eat, Beverages, Sweets & Desserts.
            All prices in Indian Rupees. Always confirm actions clearly but don't overuse customer's name.
            """,
            tools=[
                register_new_customer,
                login_customer,
                reset_password,
                set_budget_limit,
                set_dietary_filter,
                show_catalog,
                add_item_to_cart,
                add_recipe_ingredients,
                remove_item_from_cart,
                update_item_quantity,
                view_cart,
                review_order_details,
                confirm_order,
                show_order_history,
                show_last_order,
                check_order_status,
                reorder_last_order,
                reorder_previous_order,
                get_recommendations,
                check_delivery_charges,
                check_discount_eligibility,
                advance_order_status,
            ],
        )


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    # Create user session data with agent
    userdata = Userdata(agent=DailyMartAgent())

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-IN-anusha",
            style="Conversation",
            text_pacing=True,
        ),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )

    await session.start(agent=DailyMartVoiceAgent(), room=ctx.room)

    await ctx.connect()

    # Give initial greeting
    await asyncio.sleep(1)
    await session.agent_publication.say(
        "Hello! Welcome to GrocyMate, your friendly neighborhood grocery store. I can help you order groceries, spices, snacks, and prepared foods. Are you a new customer or do you already have an account with us?",
        allow_interruptions=True,
    )


if __name__ == "__main__":
    # note: run via LiveKit CLI as before
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
