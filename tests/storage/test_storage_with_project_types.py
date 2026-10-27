from __future__ import annotations

import pytest

from crystalline.project.fields import build_model_from_field_spec
from crystalline.schema import SchemaRegistry
from crystalline.storage import InMemoryStorage, SQLiteStorage


@pytest.fixture(params=["memory", "sqlite"])
def storage(request):
    store = InMemoryStorage() if request.param == "memory" else SQLiteStorage(":memory:")
    yield store
    if isinstance(store, SQLiteStorage):
        store.close()


def test_store_and_retrieve_order_with_nested_items(storage):
    # A minimal schema mirroring examples/demo_shop's Order/OrderItem
    # shape, built standalone rather than loading the real demo project
    # (which is the user's own live demo — never touch it for testing).
    schema = SchemaRegistry()
    OrderItem = build_model_from_field_spec(
        "OrderItem",
        {"product_id": "str", "count": "int", "subtotal": "float"},
        schema,
    )
    schema.register(OrderItem, name="OrderItem")
    Order = build_model_from_field_spec(
        "Order",
        {
            "id": "str",
            "customer_id": "str",
            "items": "list[OrderItem]",
            "total": "float",
        },
        schema,
    )
    schema.register(Order, name="Order")

    order = Order(
        id="o1",
        customer_id="c1",
        items=[OrderItem(product_id="p1", count=2, subtotal=19.98)],
        total=19.98,
    )
    storage.create(order)

    fetched = storage.get(Order, "o1")
    assert fetched == order
    assert isinstance(fetched.items[0], OrderItem)
    assert fetched.items[0].count == 2

    updated = storage.update(Order, "o1", total=25.0)
    assert updated.total == 25.0
    assert updated.items[0].product_id == "p1"
