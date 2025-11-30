import json
import os
import tempfile
from typing import List, Dict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
ORDERS_FILE = DATA_DIR / "orders.json"


def ensure_data_dir_exists():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not ORDERS_FILE.exists():
        ORDERS_FILE.write_text("[]", encoding="utf-8")


def read_orders() -> List[Dict]:
    ensure_data_dir_exists()
    try:
        with ORDERS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except:
        return []


def write_orders(orders: List[Dict]):
    ensure_data_dir_exists()
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR))
    os.close(fd)
    try:
        with open(tmp, "w") as f:
            json.dump(orders, f, indent=2)
        os.replace(tmp, ORDERS_FILE)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except:
                pass


def append_order(order: Dict):
    orders = read_orders()
    orders.append(order)
    write_orders(orders)
