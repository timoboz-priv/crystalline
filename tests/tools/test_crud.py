import asyncio

import pytest

from crystalline.schema import CrystallineModel, SchemaRegistry
from crystalline.security import RESERVED_TYPE_NAMES, Token, User, bind_token
from crystalline.storage import InMemoryStorage
from crystalline.tools import STORAGE_GROUP, generate_storage_tools, sync_storage_tools
from crystalline.tools.registry import ToolRegistry


class Customer(CrystallineModel):
    id: str
    name: str
    email: str


class OrderItem(CrystallineModel):
    product_id: str
    count: int


def _schema_with_customer() -> SchemaRegistry:
    schema = SchemaRegistry()
    schema.register(Customer)
    schema.register(User, name="User")
    schema.register(OrderItem)
    return schema


def _admin_token(scopes=("*:*",)) -> Token:
    return Token(sub="admin", scopes=list(scopes))


def test_generates_five_tools_per_type_with_id():
    schema = _schema_with_customer()
    storage = InMemoryStorage()
    tools = generate_storage_tools(schema, storage)
    names = {t.name for t in tools}
    assert names == {
        "create_customer",
        "get_customer",
        "update_customer",
        "delete_customer",
        "list_customer",
    }


def test_skips_reserved_and_idless_types():
    schema = _schema_with_customer()
    storage = InMemoryStorage()
    tools = generate_storage_tools(schema, storage)
    for tool in tools:
        assert "user" not in tool.name
        assert "order_item" not in tool.name
    assert "User" in RESERVED_TYPE_NAMES


def test_tools_use_scopes_matching_type_name():
    schema = _schema_with_customer()
    storage = InMemoryStorage()
    tools = {t.name: t for t in generate_storage_tools(schema, storage)}
    assert tools["create_customer"].scope == "Customer:create"
    assert tools["get_customer"].scope == "Customer:read"
    assert tools["update_customer"].scope == "Customer:update"
    assert tools["delete_customer"].scope == "Customer:delete"
    assert tools["list_customer"].scope == "Customer:read"
    assert all(t.group == STORAGE_GROUP for t in tools.values())


def test_crud_round_trip_through_generated_tools():
    schema = _schema_with_customer()
    storage = InMemoryStorage()
    tools = {t.name: t for t in generate_storage_tools(schema, storage)}

    async def run():
        with bind_token(_admin_token()):
            created = await tools["create_customer"].invoke(
                Customer(id="c1", name="Ada", email="ada@example.com")
            )
            assert created.id == "c1"

            GetInput = tools["get_customer"].input_model
            fetched = await tools["get_customer"].invoke(GetInput(id="c1"))
            assert fetched == created

            UpdateInput = tools["update_customer"].input_model
            updated = await tools["update_customer"].invoke(
                UpdateInput(id="c1", name="Ada Lovelace")
            )
            assert updated.name == "Ada Lovelace"
            assert updated.email == "ada@example.com"

            ListInput = tools["list_customer"].input_model
            listed = await tools["list_customer"].invoke(ListInput())
            assert listed == [updated]

            DeleteInput = tools["delete_customer"].input_model
            assert await tools["delete_customer"].invoke(DeleteInput(id="c1")) is True
            assert await tools["get_customer"].invoke(GetInput(id="c1")) is None

    asyncio.run(run())


def test_scope_enforced_for_generated_tools():
    schema = _schema_with_customer()
    storage = InMemoryStorage()
    tools = {t.name: t for t in generate_storage_tools(schema, storage)}

    async def run():
        with bind_token(Token(sub="viewer", scopes=["*:read"])):
            with pytest.raises(PermissionError):
                await tools["create_customer"].invoke(
                    Customer(id="c1", name="Ada", email="a@b.com")
                )

    asyncio.run(run())


def test_sync_storage_tools_is_idempotent_and_updates_registry():
    schema = _schema_with_customer()
    storage = InMemoryStorage()
    registry = ToolRegistry()

    sync_storage_tools(registry, schema, storage)
    first = registry.get_tool("create_customer")
    assert first is not None

    sync_storage_tools(registry, schema, storage)
    second = registry.get_tool("create_customer")
    assert second is not None  # re-sync succeeds (replace=True), doesn't raise
