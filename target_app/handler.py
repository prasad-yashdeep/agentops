"""
E-Commerce Business Logic Handler
Products, orders, users, analytics, checkout.
"""
import json
import os
import time
from datetime import datetime

# ─── In-memory Database ──────────────────────────────────────────────

PRODUCTS = [
    {"id": 1, "name": "Wireless Headphones Pro", "price": 149.99, "category": "electronics", "stock": 45, "rating": 4.7},
    {"id": 2, "name": "Organic Coffee Beans 1kg", "price": 24.99, "category": "food", "stock": 200, "rating": 4.5},
    {"id": 3, "name": "Running Shoes Ultra", "price": 119.99, "category": "sports", "stock": 78, "rating": 4.8},
    {"id": 4, "name": "Mechanical Keyboard RGB", "price": 89.99, "category": "electronics", "stock": 120, "rating": 4.6},
    {"id": 5, "name": "Yoga Mat Premium", "price": 39.99, "category": "sports", "stock": 300, "rating": 4.3},
    {"id": 6, "name": "Protein Powder Vanilla 2lb", "price": 34.99, "category": "food", "stock": 150, "rating": 4.4},
    {"id": 7, "name": "USB-C Hub 7-in-1", "price": 49.99, "category": "electronics", "stock": 95, "rating": 4.2},
    {"id": 8, "name": "Cast Iron Skillet 12in", "price": 44.99, "category": "home", "stock": 60, "rating": 4.9},
]

USERS = [
    {"id": 1, "name": "Alice Chen", "email": "alice@example.com", "role": "customer", "active": True, "joined": "2024-01-15"},
    {"id": 2, "name": "Bob Smith", "email": "bob@example.com", "role": "customer", "active": True, "joined": "2024-03-22"},
    {"id": 3, "name": "Carol Williams", "email": "carol@example.com", "role": "admin", "active": True, "joined": "2023-11-01"},
    {"id": 4, "name": "Dave Johnson", "email": "dave@example.com", "role": "customer", "active": False, "joined": "2024-06-10"},
    {"id": 5, "name": "Eva Martinez", "email": "eva@example.com", "role": "customer", "active": True, "joined": "2024-08-05"},
]

ORDERS = [
    {"id": 1001, "user_id": 1, "items": [{"product_id": 1, "qty": 1}, {"product_id": 4, "qty": 1}], "total": 239.98, "status": "delivered", "date": "2025-01-20"},
    {"id": 1002, "user_id": 2, "items": [{"product_id": 3, "qty": 1}], "total": 125.98, "status": "shipped", "date": "2025-02-01"},
    {"id": 1003, "user_id": 5, "items": [{"product_id": 2, "qty": 2}, {"product_id": 6, "qty": 1}], "total": 90.96, "status": "processing", "date": "2025-02-10"},
    {"id": 1004, "user_id": 1, "items": [{"product_id": 8, "qty": 1}, {"product_id": 5, "qty": 2}], "total": 130.96, "status": "delivered", "date": "2025-02-12"},
]

_next_order_id = 1005
_next_user_id = 6

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def _load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


# ─── Health ──────────────────────────────────────────────────────────

def validate():
    """Health check — verifies all subsystems are operational."""
    config = _load_config()
    assert config.get("database_url"), "Database URL not configured"
    assert len(PRODUCTS) > 0, "Product catalog is empty"
    assert len(USERS) > 0, "User database is empty"
    return True


# ─── Products ────────────────────────────────────────────────────────

def get_products(category=None):
    """List products, optionally filtered by category."""
    if category:
        return [p for p in PRODUCTS if p["category"] == category]
    return PRODUCTS


def get_product_by_id(product_id):
    """Get a single product by ID."""
    for p in PRODUCTS:
        if p["id"] == product_id:
            return p
    return None


# ─── Users ───────────────────────────────────────────────────────────

def get_users():
    """List active users."""
    return [u for u in USERS if u["active"]]


def create_user(data):
    """Register a new user."""
    global _next_user_id
    if not data.get("name") or not data.get("email"):
        raise ValueError("Missing required fields: name, email")
    user = {
        "id": _next_user_id,
        "name": data["name"],
        "email": data["email"],
        "role": "customer",
        "active": True,
        "joined": datetime.now().strftime("%Y-%m-%d"),
    }
    USERS.append(user)
    _next_user_id += 1
    return user


# ─── Orders ──────────────────────────────────────────────────────────

def get_orders():
    """List all orders."""
    return ORDERS


def create_order(data):
    """Create a new order."""
    global _next_order_id
    user_id = data.get("user_id")
    items = data.get("items", [])

    if not user_id:
        raise ValueError("Missing user_id")
    if not items:
        raise ValueError("Order must contain at least one item")

    # Validate user exists
    user = next((u for u in USERS if u["id"] == user_id), None)
    if not user:
        raise ValueError(f"User {user_id} not found")

    # Calculate total
    config = _load_config()
    tax_rate = config.get("tax_rate", 0.08875)
    shipping = config.get("shipping_flat_rate", 5.99)

    subtotal = 0
    for item in items:
        product = get_product_by_id(item["product_id"])
        if not product:
            raise ValueError(f"Product {item['product_id']} not found")
        if product["stock"] < item.get("qty", 1):
            raise ValueError(f"Insufficient stock for {product['name']}")
        subtotal += product["price"] * item.get("qty", 1)

    tax = subtotal * tax_rate
    total = subtotal + tax + shipping

    order = {
        "id": _next_order_id,
        "user_id": user_id,
        "items": items,
        "subtotal": round(subtotal, 2),
        "tax": round(tax, 2),
        "shipping": shipping,
        "total": round(total, 2),
        "status": "processing",
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    ORDERS.append(order)
    _next_order_id += 1
    return order


# ─── Checkout ────────────────────────────────────────────────────────

def process_checkout(data):
    """Process a full checkout: validate cart, calculate totals, create order."""
    cart = data.get("cart", [])
    user_id = data.get("user_id")
    payment_method = data.get("payment_method", "card")

    if not cart:
        raise ValueError("Cart is empty")

    # Build order items and validate everything
    items = []
    subtotal = 0
    for cart_item in cart:
        product = get_product_by_id(cart_item["product_id"])
        if not product:
            raise ValueError(f"Product {cart_item['product_id']} not found")
        qty = cart_item.get("qty", 1)
        if product["stock"] < qty:
            raise ValueError(f"Only {product['stock']} units of '{product['name']}' available")
        items.append({"product_id": product["id"], "name": product["name"], "qty": qty, "price": product["price"]})
        subtotal += product["price"] * qty

    config = _load_config()
    tax = subtotal * config.get("tax_rate", 0.08875)
    shipping = config.get("shipping_flat_rate", 5.99)
    total = subtotal + tax + shipping

    global _next_order_id

    # Deduct stock
    for cart_item in cart:
        product = get_product_by_id(cart_item["product_id"])
        product["stock"] -= cart_item.get("qty", 1)

    # Create the order and add to orders list
    order = {
        "id": _next_order_id,
        "user_id": user_id or 1,
        "items": [{"product_id": i["product_id"], "qty": i["qty"]} for i in items],
        "subtotal": round(subtotal, 2),
        "tax": round(tax, 2),
        "shipping": shipping,
        "total": round(total, 2),
        "status": "processing",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "payment_method": payment_method,
    }
    ORDERS.append(order)
    _next_order_id += 1

    return {
        "status": "success",
        "order_id": order["id"],
        "items": items,
        "subtotal": round(subtotal, 2),
        "tax": round(tax, 2),
        "shipping": shipping,
        "total": round(total, 2),
        "payment_method": payment_method,
        "estimated_delivery": "3-5 business days",
    }


# ─── Analytics ───────────────────────────────────────────────────────

def compute_analytics():
    """Compute business analytics dashboard data."""
    total_revenue = sum(o["total"] for o in ORDERS)
    avg_order_value = total_revenue / len(ORDERS) if ORDERS else 0

    # Revenue by category
    category_revenue = {}
    for order in ORDERS:
        for item in order["items"]:
            product = get_product_by_id(item["product_id"])
            if product:
                cat = product["category"]
                rev = product["price"] * item.get("qty", 1)
                category_revenue[cat] = category_revenue.get(cat, 0) + rev

    # Top products
    product_sales = {}
    for order in ORDERS:
        for item in order["items"]:
            pid = item["product_id"]
            product_sales[pid] = product_sales.get(pid, 0) + item.get("qty", 1)

    top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]
    top_product_names = []
    for pid, qty in top_products:
        product = get_product_by_id(pid)
        if product:
            top_product_names.append({"name": product["name"], "units_sold": qty})

    # User metrics
    active_users = len([u for u in USERS if u["active"]])
    total_users = len(USERS)

    return {
        "total_revenue": round(total_revenue, 2),
        "total_orders": len(ORDERS),
        "avg_order_value": round(avg_order_value, 2),
        "category_revenue": {k: round(v, 2) for k, v in category_revenue.items()},
        "top_products": top_product_names,
        "active_users": active_users,
        "total_users": total_users,
        "conversion_rate": round(len(ORDERS) / max(active_users, 1) * 100, 1),
    }
