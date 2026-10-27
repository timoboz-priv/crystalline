"""One-time/idempotent seed data for the demo_shop project: 10 customers,
5 products, and a handful of orders referencing them.

Run with:
    python examples/demo_shop/seed_data.py

Safe to re-run: existing records (matched by id) are left untouched, only
missing ones are created — same "fill gaps, don't overwrite" convention
as the project file's `users:` seeding.
"""

from pathlib import Path

from crystalline.project import load_project

PROJECT_PATH = Path(__file__).parent / "project.yaml"

CUSTOMERS = [
    {"id": "c1", "name": "Ada Lovelace", "email": "ada@example.com"},
    {"id": "c2", "name": "Grace Hopper", "email": "grace@example.com"},
    {"id": "c3", "name": "Alan Turing", "email": "alan@example.com"},
    {"id": "c4", "name": "Katherine Johnson", "email": "katherine@example.com"},
    {"id": "c5", "name": "Margaret Hamilton", "email": "margaret@example.com"},
    {"id": "c6", "name": "Tim Berners-Lee", "email": "tim@example.com"},
    {"id": "c7", "name": "Hedy Lamarr", "email": "hedy@example.com"},
    {"id": "c8", "name": "Dennis Ritchie", "email": "dennis@example.com"},
    {"id": "c9", "name": "Barbara Liskov", "email": "barbara@example.com"},
    {"id": "c10", "name": "Radia Perlman", "email": "radia@example.com"},
]

PRODUCTS = [
    {"id": "p1", "name": "Widget", "description": "A sturdy widget", "price": 9.99},
    {"id": "p2", "name": "Gadget", "description": "A useful gadget", "price": 19.99},
    {"id": "p3", "name": "Gizmo", "description": "A clever gizmo", "price": 14.50},
    {
        "id": "p4",
        "name": "Doohickey",
        "description": "An essential doohickey",
        "price": 24.00,
    },
    {
        "id": "p5",
        "name": "Contraption",
        "description": "An elaborate contraption",
        "price": 49.99,
    },
]

ORDERS = [
    {
        "id": "o1",
        "customer_id": "c1",
        "items": [{"product_id": "p1", "count": 2, "subtotal": 19.98}],
        "total": 19.98,
    },
    {
        "id": "o2",
        "customer_id": "c2",
        "items": [
            {"product_id": "p2", "count": 1, "subtotal": 19.99},
            {"product_id": "p3", "count": 1, "subtotal": 14.50},
        ],
        "total": 34.49,
    },
    {
        "id": "o3",
        "customer_id": "c3",
        "items": [{"product_id": "p4", "count": 1, "subtotal": 24.00}],
        "total": 24.00,
    },
    {
        "id": "o4",
        "customer_id": "c5",
        "items": [
            {"product_id": "p1", "count": 3, "subtotal": 29.97},
            {"product_id": "p5", "count": 1, "subtotal": 49.99},
        ],
        "total": 79.96,
    },
    {
        "id": "o5",
        "customer_id": "c8",
        "items": [{"product_id": "p3", "count": 2, "subtotal": 29.00}],
        "total": 29.00,
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
