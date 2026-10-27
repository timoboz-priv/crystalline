from __future__ import annotations

import pytest
from pydantic import ValidationError

from crystalline.schema import CrystallineModel
from crystalline.storage import InMemoryStorage, SQLiteStorage


class Widget(CrystallineModel):
    id: str
    name: str
    price: float


class Gadget(CrystallineModel):
    id: str
    label: str


@pytest.fixture(params=["memory", "sqlite"])
def storage(request):
    store = InMemoryStorage() if request.param == "memory" else SQLiteStorage(":memory:")
    yield store
    if isinstance(store, SQLiteStorage):
        store.close()


def test_create_and_get(storage):
    widget = Widget(id="w1", name="Widget", price=9.99)
    assert storage.create(widget) == widget
    assert storage.get(Widget, "w1") == widget


def test_get_missing_returns_none(storage):
    assert storage.get(Widget, "missing") is None


def test_create_duplicate_raises(storage):
    storage.create(Widget(id="w1", name="A", price=1.0))
    with pytest.raises(ValueError):
        storage.create(Widget(id="w1", name="B", price=2.0))


def test_update_merges_fields(storage):
    storage.create(Widget(id="w1", name="A", price=1.0))
    updated = storage.update(Widget, "w1", price=5.0)
    assert updated.name == "A"
    assert updated.price == 5.0
    assert storage.get(Widget, "w1").price == 5.0


def test_update_missing_raises(storage):
    with pytest.raises(KeyError):
        storage.update(Widget, "nope", price=1.0)


def test_update_cannot_change_id(storage):
    storage.create(Widget(id="w1", name="A", price=1.0))
    with pytest.raises(ValueError):
        storage.update(Widget, "w1", id="w2")


def test_update_rejects_unknown_field(storage):
    storage.create(Widget(id="w1", name="A", price=1.0))
    with pytest.raises(ValidationError):
        storage.update(Widget, "w1", bogus=True)


def test_delete(storage):
    storage.create(Widget(id="w1", name="A", price=1.0))
    assert storage.delete(Widget, "w1") is True
    assert storage.get(Widget, "w1") is None
    assert storage.delete(Widget, "w1") is False


def test_list_all_and_filtered(storage):
    storage.create(Widget(id="w1", name="A", price=1.0))
    storage.create(Widget(id="w2", name="B", price=2.0))
    storage.create(Widget(id="w3", name="A", price=3.0))

    assert {w.id for w in storage.list(Widget)} == {"w1", "w2", "w3"}
    assert {w.id for w in storage.list(Widget, name="A")} == {"w1", "w3"}
    assert storage.list(Widget, name="nope") == []


def test_types_are_isolated(storage):
    storage.create(Widget(id="1", name="A", price=1.0))
    storage.create(Gadget(id="1", label="shared id, different type"))

    assert storage.get(Widget, "1").name == "A"
    assert storage.get(Gadget, "1").label == "shared id, different type"


def test_create_without_id_field_raises(storage):
    class NoId(CrystallineModel):
        name: str

    with pytest.raises(ValueError):
        storage.create(NoId(name="x"))
