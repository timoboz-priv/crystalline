"""One-time/idempotent seed data for the demo_shop project: 30 customers,
10 products, and 100 orders referencing them.

Run with:
    python examples/demo_shop/seed_data.py

Safe to re-run: existing records (matched by id) are left untouched, only
missing ones are created — same "fill gaps, don't overwrite" convention
as the project file's `users:` seeding.
"""

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crystalline.project import load_project

PROJECT_PATH = Path(__file__).parent / "project.yaml"

# Anchor for every "days ago" offset below — computed once per run, not
# per record, so a single seeding pass is internally consistent. Customer/
# product offsets are spread deterministically (not randomly) so a fresh
# database always has the same relative ordering; orders are generated
# from a seeded RNG for the same reason — same seed, same output, every
# run, without hand-writing 100 literal records.
_NOW = datetime.now(timezone.utc)


def _days_ago(n: int) -> datetime:
    return _NOW - timedelta(days=n)


CUSTOMERS = [
    {"id": "c1", "name": "Ada Lovelace", "email": "ada@example.com", "created_at": _days_ago(118)},
    {"id": "c2", "name": "Grace Hopper", "email": "grace@example.com", "created_at": _days_ago(114)},
    {"id": "c3", "name": "Alan Turing", "email": "alan@example.com", "created_at": _days_ago(110)},
    {"id": "c4", "name": "Katherine Johnson", "email": "katherine@example.com", "created_at": _days_ago(106)},
    {"id": "c5", "name": "Margaret Hamilton", "email": "margaret@example.com", "created_at": _days_ago(102)},
    {"id": "c6", "name": "Tim Berners-Lee", "email": "tim@example.com", "created_at": _days_ago(98)},
    {"id": "c7", "name": "Hedy Lamarr", "email": "hedy@example.com", "created_at": _days_ago(94)},
    {"id": "c8", "name": "Dennis Ritchie", "email": "dennis@example.com", "created_at": _days_ago(90)},
    {"id": "c9", "name": "Barbara Liskov", "email": "barbara@example.com", "created_at": _days_ago(86)},
    {"id": "c10", "name": "Radia Perlman", "email": "radia@example.com", "created_at": _days_ago(82)},
    {"id": "c11", "name": "Donald Knuth", "email": "donald@example.com", "created_at": _days_ago(78)},
    {"id": "c12", "name": "John von Neumann", "email": "john@example.com", "created_at": _days_ago(74)},
    {"id": "c13", "name": "Edsger Dijkstra", "email": "edsger@example.com", "created_at": _days_ago(70)},
    {"id": "c14", "name": "Claude Shannon", "email": "claude@example.com", "created_at": _days_ago(66)},
    {"id": "c15", "name": "Vint Cerf", "email": "vint@example.com", "created_at": _days_ago(62)},
    {"id": "c16", "name": "Linus Torvalds", "email": "linus@example.com", "created_at": _days_ago(58)},
    {"id": "c17", "name": "Guido van Rossum", "email": "guido@example.com", "created_at": _days_ago(54)},
    {"id": "c18", "name": "Ken Thompson", "email": "ken@example.com", "created_at": _days_ago(50)},
    {"id": "c19", "name": "Brian Kernighan", "email": "brian@example.com", "created_at": _days_ago(46)},
    {"id": "c20", "name": "Whitfield Diffie", "email": "whitfield@example.com", "created_at": _days_ago(42)},
    {"id": "c21", "name": "Martin Hellman", "email": "martin@example.com", "created_at": _days_ago(38)},
    {"id": "c22", "name": "Shafi Goldwasser", "email": "shafi@example.com", "created_at": _days_ago(34)},
    {"id": "c23", "name": "Leslie Lamport", "email": "leslie@example.com", "created_at": _days_ago(30)},
    {"id": "c24", "name": "Butler Lampson", "email": "butler@example.com", "created_at": _days_ago(26)},
    {"id": "c25", "name": "Niklaus Wirth", "email": "niklaus@example.com", "created_at": _days_ago(22)},
    {"id": "c26", "name": "John McCarthy", "email": "jmccarthy@example.com", "created_at": _days_ago(18)},
    {"id": "c27", "name": "Marvin Minsky", "email": "marvin@example.com", "created_at": _days_ago(14)},
    {"id": "c28", "name": "Seymour Cray", "email": "seymour@example.com", "created_at": _days_ago(10)},
    {"id": "c29", "name": "Steve Wozniak", "email": "steve@example.com", "created_at": _days_ago(6)},
    {"id": "c30", "name": "Bjarne Stroustrup", "email": "bjarne@example.com", "created_at": _days_ago(2)},
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
    {
        "id": "p6",
        "name": "Thingamajig",
        "description": "A mysterious thingamajig",
        "price": 34.99,
        "created_at": _days_ago(65),
    },
    {
        "id": "p7",
        "name": "Whatchamacallit",
        "description": "A versatile whatchamacallit",
        "price": 59.99,
        "created_at": _days_ago(75),
    },
    {
        "id": "p8",
        "name": "Doodad",
        "description": "A handy doodad",
        "price": 12.75,
        "created_at": _days_ago(85),
    },
    {
        "id": "p9",
        "name": "Gubbins",
        "description": "A miscellaneous assortment of gubbins",
        "price": 17.25,
        "created_at": _days_ago(95),
    },
    {
        "id": "p10",
        "name": "Flummox",
        "description": "A puzzling flummox",
        "price": 44.00,
        "created_at": _days_ago(5),
    },
]

# Generated rather than hand-written: 100 literal order records would
# dwarf the rest of the file. Fixed seed keeps a fresh database's content
# identical across runs.
_rng = random.Random(1234)

ORDERS = []
for _i in range(1, 101):
    _customer = _rng.choice(CUSTOMERS)
    _chosen_products = _rng.sample(PRODUCTS, _rng.randint(1, 3))
    _items = []
    _total = 0.0
    for _product in _chosen_products:
        _count = _rng.randint(1, 5)
        _subtotal = round(_product["price"] * _count, 2)
        _items.append({"product_id": _product["id"], "count": _count, "subtotal": _subtotal})
        _total += _subtotal
    ORDERS.append(
        {
            "id": f"o{_i}",
            "customer_id": _customer["id"],
            "items": _items,
            "total": round(_total, 2),
            "placed_at": _days_ago(_rng.randint(1, 120)),
        }
    )


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
