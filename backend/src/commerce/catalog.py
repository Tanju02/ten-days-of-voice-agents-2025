from typing import List, Dict

PRODUCTS: List[Dict] = [
    {
        "id": "mug-001",
        "name": "Stoneware Coffee Mug",
        "description": "Classic stoneware mug, holds 350ml. Durable and dishwasher safe.",
        "price": 350,
        "currency": "INR",
        "category": "mug",
        "color": "white",
        "attributes": {"capacity_ml": 350},
    },
    {
        "id": "mug-002",
        "name": "Matte Black Coffee Mug",
        "description": "Matte finish black ceramic mug with premium grip.",
        "price": 450,
        "currency": "INR",
        "category": "mug",
        "color": "black",
        "attributes": {"capacity_ml": 350},
    },
    {
        "id": "tshirt-001",
        "name": "Classic Cotton T-Shirt",
        "description": "100% cotton everyday t-shirt. Comfortable and breathable.",
        "price": 799,
        "currency": "INR",
        "category": "t-shirt",
        "color": "white",
        "attributes": {"sizes": ["S", "M", "L", "XL"]},
    },
    {
        "id": "tshirt-002",
        "name": "Premium Graphic T-Shirt",
        "description": "Soft cotton tee with premium graphic print.",
        "price": 999,
        "currency": "INR",
        "category": "t-shirt",
        "color": "black",
        "attributes": {"sizes": ["S", "M", "L", "XL"]},
    },
    {
        "id": "hoodie-001",
        "name": "Soft Fleece Hoodie",
        "description": "Comfort-fit fleece hoodie, great for chilly mornings.",
        "price": 1499,
        "currency": "INR",
        "category": "hoodie",
        "color": "grey",
        "attributes": {"sizes": ["S", "M", "L", "XL"]},
    },
    {
        "id": "hoodie-002",
        "name": "Oversized Black Hoodie",
        "description": "Oversized fit black hoodie with kangaroo pocket.",
        "price": 1799,
        "currency": "INR",
        "category": "hoodie",
        "color": "black",
        "attributes": {"sizes": ["M", "L", "XL"]},
    },
    {
        "id": "bottle-001",
        "name": "Stainless Steel Water Bottle",
        "description": "Double-wall insulated water bottle, 500ml.",
        "price": 699,
        "currency": "INR",
        "category": "bottle",
        "color": "silver",
        "attributes": {"capacity_ml": 500},
    },
    {
        "id": "notebook-001",
        "name": "Daily Notes Notebook",
        "description": "A5, 120 pages, ruled notebook for daily journaling.",
        "price": 299,
        "currency": "INR",
        "category": "stationery",
        "color": "blue",
        "attributes": {"pages": 120},
    },
]


def get_product_by_id(product_id: str) -> Dict | None:
    for p in PRODUCTS:
        if p["id"] == product_id:
            return p
    return None
