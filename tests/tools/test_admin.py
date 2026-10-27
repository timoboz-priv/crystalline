import asyncio

import pytest

from crystalline.schema import CrystallineModel, SchemaRegistry
from crystalline.security import SecurityPolicy, Token, User, bind_token, create_user
from crystalline.storage import InMemoryStorage
from crystalline.tools import ADMIN_GROUP, generate_admin_tools


class Customer(CrystallineModel):
    id: str
    name: str


def _schema() -> SchemaRegistry:
    schema = SchemaRegistry()
    schema.register(Customer)
    schema.register(User, name="User")
    return schema


def _admin_token() -> Token:
    return Token(sub="admin", scopes=["*:*"])


def test_all_admin_tools_in_admin_group():
    schema = _schema()
    storage = InMemoryStorage()
    security = SecurityPolicy()
    tools = generate_admin_tools(storage, security, schema)
    assert all(t.group == ADMIN_GROUP for t in tools)
    names = {t.name for t in tools}
    assert {
        "list_users",
        "get_user",
        "create_user",
        "update_user",
        "delete_user",
        "list_roles",
        "get_role",
        "create_role",
        "update_role",
        "delete_role",
        "list_scopes",
    } <= names


def test_user_tools_never_expose_password_hash():
    schema = _schema()
    storage = InMemoryStorage()
    security = SecurityPolicy()
    tools = {t.name: t for t in generate_admin_tools(storage, security, schema)}
    create_user(storage, "ada", "hunter2", roles=["editor"])

    async def run():
        with bind_token(_admin_token()):
            listed = await tools["list_users"].invoke(tools["list_users"].input_model())
            GetInput = tools["get_user"].input_model
            fetched = await tools["get_user"].invoke(GetInput(id="ada"))
            return listed, fetched

    listed, fetched = asyncio.run(run())
    assert listed == [{"id": "ada", "roles": ["editor"], "disabled": False}]
    assert fetched == {"id": "ada", "roles": ["editor"], "disabled": False}
    assert "password_hash" not in str(listed)
    assert "password_hash" not in str(fetched)


def test_create_user_tool_hashes_password():
    schema = _schema()
    storage = InMemoryStorage()
    security = SecurityPolicy()
    tools = {t.name: t for t in generate_admin_tools(storage, security, schema)}

    async def run():
        with bind_token(_admin_token()):
            CreateInput = tools["create_user"].input_model
            await tools["create_user"].invoke(
                CreateInput(id="bob", password="secret", roles=["viewer"])
            )

    asyncio.run(run())
    stored = storage.get(User, "bob")
    assert stored.password_hash != "secret"


def test_update_user_tool_changes_password_roles_disabled():
    schema = _schema()
    storage = InMemoryStorage()
    security = SecurityPolicy()
    tools = {t.name: t for t in generate_admin_tools(storage, security, schema)}
    create_user(storage, "ada", "old-pw", roles=["viewer"])

    async def run():
        with bind_token(_admin_token()):
            UpdateInput = tools["update_user"].input_model
            return await tools["update_user"].invoke(
                UpdateInput(id="ada", password="new-pw", roles=["editor"], disabled=True)
            )

    result = asyncio.run(run())
    assert result == {"id": "ada", "roles": ["editor"], "disabled": True}

    from crystalline.security import verify_password

    stored = storage.get(User, "ada")
    assert verify_password("new-pw", stored.password_hash)


def test_delete_user_tool():
    schema = _schema()
    storage = InMemoryStorage()
    security = SecurityPolicy()
    tools = {t.name: t for t in generate_admin_tools(storage, security, schema)}
    create_user(storage, "ada", "pw")

    async def run():
        with bind_token(_admin_token()):
            DeleteInput = tools["delete_user"].input_model
            return await tools["delete_user"].invoke(DeleteInput(id="ada"))

    assert asyncio.run(run()) is True
    assert storage.get(User, "ada") is None


def test_role_tools_create_update_delete():
    schema = _schema()
    storage = InMemoryStorage()
    security = SecurityPolicy()
    tools = {t.name: t for t in generate_admin_tools(storage, security, schema)}

    async def run():
        with bind_token(_admin_token()):
            RoleInput = tools["create_role"].input_model
            await tools["create_role"].invoke(RoleInput(name="support", scopes=["Order:read"]))

            with pytest.raises(ValueError):
                await tools["create_role"].invoke(
                    RoleInput(name="support", scopes=["Order:read"])
                )

            GetInput = tools["get_role"].input_model
            assert await tools["get_role"].invoke(GetInput(name="support")) == ["Order:read"]

            await tools["update_role"].invoke(
                RoleInput(name="support", scopes=["Order:read", "Order:update"])
            )
            assert await tools["get_role"].invoke(GetInput(name="support")) == [
                "Order:read",
                "Order:update",
            ]

            with pytest.raises(KeyError):
                await tools["update_role"].invoke(RoleInput(name="nope", scopes=[]))

            DeleteInput = tools["delete_role"].input_model
            assert await tools["delete_role"].invoke(DeleteInput(name="support")) is True
            assert await tools["delete_role"].invoke(DeleteInput(name="support")) is False

    asyncio.run(run())


def test_list_scopes_includes_type_actions_and_wildcards():
    schema = _schema()
    storage = InMemoryStorage()
    security = SecurityPolicy()
    tools = {t.name: t for t in generate_admin_tools(storage, security, schema)}

    async def run():
        with bind_token(_admin_token()):
            return await tools["list_scopes"].invoke(tools["list_scopes"].input_model())

    scopes = asyncio.run(run())
    assert "Customer:create" in scopes
    assert "User:read" in scopes
    assert "*:*" in scopes
    assert "*:read" in scopes


def test_list_scopes_requires_no_scope():
    assert generate_admin_tools(
        InMemoryStorage(), SecurityPolicy(), _schema()
    )[-1].scope is None


def test_editor_cannot_manage_users_or_roles():
    schema = _schema()
    storage = InMemoryStorage()
    security = SecurityPolicy()
    tools = {t.name: t for t in generate_admin_tools(storage, security, schema)}
    editor_token = Token(sub="ed", scopes=security.scopes_for(["editor"]))

    async def run():
        with bind_token(editor_token):
            with pytest.raises(PermissionError):
                await tools["list_users"].invoke(tools["list_users"].input_model())
            with pytest.raises(PermissionError):
                RoleInput = tools["create_role"].input_model
                await tools["create_role"].invoke(RoleInput(name="x", scopes=[]))

    asyncio.run(run())
