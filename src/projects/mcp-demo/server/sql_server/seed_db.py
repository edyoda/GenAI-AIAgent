"""Build data/sales.db: a small, deterministic retail dataset (same rows on every run)."""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta

from common.config import DB_PATH

SCHEMA = """
CREATE TABLE regions (
    region_id   INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    country     TEXT NOT NULL
);
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    segment     TEXT NOT NULL CHECK (segment IN ('Consumer', 'SMB', 'Enterprise')),
    region_id   INTEGER NOT NULL REFERENCES regions(region_id),
    signup_date TEXT NOT NULL
);
CREATE TABLE products (
    product_id  INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    unit_price  REAL NOT NULL,
    unit_cost   REAL NOT NULL
);
CREATE TABLE orders (
    order_id    INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date  TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('completed', 'shipped', 'cancelled', 'returned')),
    channel     TEXT NOT NULL CHECK (channel IN ('web', 'mobile', 'partner'))
);
CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL CHECK (quantity > 0),
    unit_price    REAL NOT NULL,
    discount_pct  REAL NOT NULL DEFAULT 0
);
CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_items_order ON order_items(order_id);
"""

REGIONS = [("North", "India"), ("South", "India"), ("West", "India"), ("East", "India"), ("APAC-Intl", "Singapore")]
PRODUCTS = [  # name, category, price, cost
    ("Laptop Pro 14", "Computers", 1450, 1050), ("Laptop Air 13", "Computers", 999, 720),
    ("Desktop Tower", "Computers", 1199, 860), ("Mini PC", "Computers", 549, 380),
    ("4K Monitor 27", "Displays", 429, 290), ("Monitor 24", "Displays", 199, 130),
    ("Ultrawide 34", "Displays", 649, 450), ("Wireless Mouse", "Accessories", 39, 14),
    ("Mechanical Keyboard", "Accessories", 119, 55), ("USB-C Dock", "Accessories", 189, 95),
    ("Webcam HD", "Accessories", 79, 35), ("Laptop Sleeve", "Accessories", 29, 9),
    ("Noise-Cancel Headphones", "Audio", 299, 170), ("Earbuds", "Audio", 149, 70),
    ("Bluetooth Speaker", "Audio", 99, 45), ("Office Chair", "Furniture", 349, 210),
    ("Standing Desk", "Furniture", 599, 380), ("Monitor Arm", "Furniture", 89, 40),
    ("Cloud Backup (1y)", "Software", 99, 20), ("Office Suite (1y)", "Software", 129, 30),
    ("Antivirus (1y)", "Software", 49, 8), ("Design Suite (1y)", "Software", 399, 90),
]
FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Isha", "Vikram", "Ananya", "Arjun", "Sara",
         "Nikhil", "Priya", "Dev", "Kavya", "Rahul", "Tara", "Aditya", "Neha", "Karan", "Riya"]
LAST = ["Sharma", "Iyer", "Patel", "Reddy", "Gupta", "Nair", "Singh", "Das", "Mehta", "Rao"]


def seed(path=DB_PATH, n_customers: int = 240, n_orders: int = 900) -> dict[str, int]:
    rng = random.Random(42)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    conn.executemany("INSERT INTO regions(name, country) VALUES (?, ?)", REGIONS)
    conn.executemany("INSERT INTO products(name, category, unit_price, unit_cost) VALUES (?, ?, ?, ?)", PRODUCTS)

    start = date(2025, 1, 1)
    customers = []
    for i in range(1, n_customers + 1):
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        segment = rng.choices(["Consumer", "SMB", "Enterprise"], weights=[60, 30, 10])[0]
        customers.append((name, f"{name.lower().replace(' ', '.')}.{i}@example.com", segment,
                          rng.choices(range(1, 6), weights=[25, 30, 25, 12, 8])[0],
                          (start - timedelta(days=rng.randint(0, 700))).isoformat()))
    conn.executemany("INSERT INTO customers(name, email, segment, region_id, signup_date) VALUES (?,?,?,?,?)",
                     customers)

    items = []
    for oid in range(1, n_orders + 1):
        # 18 months, with a Q4 festive-season bump
        d = start + timedelta(days=rng.randint(0, 545))
        if rng.random() < 0.15:
            d = date(2025, rng.choice([10, 11]), rng.randint(1, 28))
        status = rng.choices(["completed", "shipped", "cancelled", "returned"], weights=[78, 8, 8, 6])[0]
        conn.execute("INSERT INTO orders(customer_id, order_date, status, channel) VALUES (?,?,?,?)",
                     (rng.randint(1, n_customers), d.isoformat(), status,
                      rng.choices(["web", "mobile", "partner"], weights=[55, 30, 15])[0]))
        for pid in rng.sample(range(1, len(PRODUCTS) + 1), k=rng.choices([1, 2, 3, 4], weights=[40, 35, 18, 7])[0]):
            price = PRODUCTS[pid - 1][2]
            items.append((oid, pid, rng.choices([1, 2, 3, 5], weights=[70, 18, 8, 4])[0], price,
                          rng.choices([0, 5, 10, 15], weights=[65, 18, 12, 5])[0]))
    conn.executemany(
        "INSERT INTO order_items(order_id, product_id, quantity, unit_price, discount_pct) VALUES (?,?,?,?,?)", items)
    conn.commit()
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("regions", "customers", "products", "orders", "order_items")}
    conn.close()
    return counts


if __name__ == "__main__":
    print(seed())
