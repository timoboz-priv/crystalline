"""One-time/idempotent seed data for the demo_shop project: 10 customers,
5 products, and a handful of orders referencing them.

Run with:
    python examples/demo_shop/seed_data.py

Safe to re-run: existing records (matched by id) are left untouched, only
missing ones are created — same "fill gaps, don't overwrite" convention
as the project file's `users:` seeding.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from crystalline.project import load_project

PROJECT_PATH = Path(__file__).parent / "project.yaml"

# Anchor for every "days ago" offset below — computed once per run, not
# per record, so a single seeding pass is internally consistent. Spread
# deterministically (not randomly) so re-running against a fresh
# database always produces the same relative ordering.
_NOW = datetime.now(timezone.utc)


def _days_ago(n: int) -> datetime:
    return _NOW - timedelta(days=n)


CUSTOMERS = [
    {"id": "c1", "name": "Ada Lovelace", "email": "ada@example.com", "created_at": _days_ago(58)},
    {"id": "c2", "name": "Grace Hopper", "email": "grace@example.com", "created_at": _days_ago(52)},
    {"id": "c3", "name": "Alan Turing", "email": "alan@example.com", "created_at": _days_ago(47)},
    {"id": "c4", "name": "Katherine Johnson", "email": "katherine@example.com", "created_at": _days_ago(41)},
    {"id": "c5", "name": "Margaret Hamilton", "email": "margaret@example.com", "created_at": _days_ago(35)},
    {"id": "c6", "name": "Tim Berners-Lee", "email": "tim@example.com", "created_at": _days_ago(29)},
    {"id": "c7", "name": "Hedy Lamarr", "email": "hedy@example.com", "created_at": _days_ago(24)},
    {"id": "c8", "name": "Dennis Ritchie", "email": "dennis@example.com", "created_at": _days_ago(18)},
    {"id": "c9", "name": "Barbara Liskov", "email": "barbara@example.com", "created_at": _days_ago(12)},
    {"id": "c10", "name": "Radia Perlman", "email": "radia@example.com", "created_at": _days_ago(5)},
]

PRODUCTS = [
    {"id": "p1", "name": "Widget", "description": "A sturdy widget", "price": 9.99, "created_at": _days_ago(50)},
    {"id": "p2", "name": "Gadget", "description": "A useful gadget", "price": 19.99, "created_at": _days_ago(40)},
    {"id": "p3", "name": "Gizmo", "description": "A clever gizmo", "price": 14.50, "created_at": _days_ago(30)},
    {
        "id": "p4",
        "name": "Doohickey",
        "description": "An essential doohickey",
        "price": 24.00,
        "created_at": _days_ago(20),
    },
    {
        "id": "p5",
        "name": "Contraption",
        "description": "An elaborate contraption",
        "price": 49.99,
        "created_at": _days_ago(10),
    },
]

# Deliberately split across the 30-day boundary (o1-o3 inside, o4-o5
# outside) so "revenue in the last 30 days" and "all-time revenue" give
# visibly different numbers in the demo.
ORDERS = [
    {
        "id": "o1",
        "customer_id": "c1",
        "items": [{"product_id": "p1", "count": 2, "subtotal": 19.98}],
        "total": 19.98,
        "placed_at": _days_ago(3),
    },
    {
        "id": "o2",
        "customer_id": "c2",
        "items": [
            {"product_id": "p2", "count": 1, "subtotal": 19.99},
            {"product_id": "p3", "count": 1, "subtotal": 14.50},
        ],
        "total": 34.49,
        "placed_at": _days_ago(10),
    },
    {
        "id": "o3",
        "customer_id": "c3",
        "items": [{"product_id": "p4", "count": 1, "subtotal": 24.00}],
        "total": 24.00,
        "placed_at": _days_ago(25),
    },
    {
        "id": "o4",
        "customer_id": "c5",
        "items": [
            {"product_id": "p1", "count": 3, "subtotal": 29.97},
            {"product_id": "p5", "count": 1, "subtotal": 49.99},
        ],
        "total": 79.96,
        "placed_at": _days_ago(40),
    },
    {
        "id": "o5",
        "customer_id": "c8",
        "items": [{"product_id": "p3", "count": 2, "subtotal": 29.00}],
        "total": 29.00,
        "placed_at": _days_ago(55),
    },
]


def main() -> None:
    project = load_project(PROJECT_PATH)
    storage = project.storage

    Customer = project.schema.get("Customer")
    Product = project.schema.get("Product")
    Order = project.schema.get("Order")

    created = {"Customer": 0, "Product": 0, "Order": 0}
    skipped = {"Customer": 0, "Product": 0, "Order": 0}

    for row in CUSTOMERS:
        if storage.get(Customer, row["id"]) is None:
            storage.create(Customer(**row))
            created["Customer"] += 1
        else:
            skipped["Customer"] += 1

    for row in PRODUCTS:
        if storage.get(Product, row["id"]) is None:
            storage.create(Product(**row))
            created["Product"] += 1
        else:
            skipped["Product"] += 1

    for row in ORDERS:
        if storage.get(Order, row["id"]) is None:
            storage.create(Order(**row))
            created["Order"] += 1
        else:
            skipped["Order"] += 1

    storage.close()

    for type_name in ("Customer", "Product", "Order"):
        print(
            f"{type_name}: created {created[type_name]}, "
            f"already present {skipped[type_name]}"
        )


if __name__ == "__main__":
    main()
