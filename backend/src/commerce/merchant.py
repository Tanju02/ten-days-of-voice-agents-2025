from typing import List, Dict, Optional
from uuid import uuid4
from datetime import datetime, timezone

from .catalog import PRODUCTS, get_product_by_id
from .storage import read_orders, append_order


def _matches_filters(product: Dict, filters: Dict) -> bool:
    if not filters:
        return True
    if filters.get("category") and product["category"] != filters["category"]:
        return False
    if filters.get("color") and product["color"] != filters["color"]:
        return False
    if filters.get("max_price") is not None:
        if product["price"] > filters["max_price"]:
            return False
    if filters.get("q"):
        q = filters["q"].lower()
        if q not in product["name"].lower() and q not in product["description"].lower():
            return False
    return True


def list_products(filters: Optional[Dict] = None, limit: Optional[int] = None):
    filters = filters or {}
    results = [p.copy() for p in PRODUCTS if _matches_filters(p, filters)]
    return results[:limit] if limit else results


def create_order(line_items: List[Dict], buyer: Optional[Dict] = None) -> Dict:
    items = []
    total = 0
    currency = "INR"

    for li in line_items:
        pid = li["product_id"]
        qty = int(li.get("quantity", 1))
        product = get_product_by_id(pid)
        if not product:
            raise ValueError(f"Product not found: {pid}")

        unit = product["price"]
        currency = product["currency"]
        line_total = unit * qty
        total += line_total

        items.append({
            "product_id": pid,
            "name": product["name"],
            "unit_amount": unit,
            "quantity": qty,
            "line_total": line_total,
            "currency": currency,
        })

    order = {
        "id": f"ord_{uuid4().hex[:10]}",
        "items": items,
        "total": total,
        "currency": currency,
        "buyer": buyer or {},
        "status": "CONFIRMED",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    append_order(order)
    return order


def get_last_order():
    orders = read_orders()
    return orders[-1] if orders else None
