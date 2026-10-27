"""Auto-generated tools for managing users, roles, and scopes.

Deliberately separate from `crystalline.tools.crud`'s generic per-type
CRUD generation: `User` is excluded there specifically so it doesn't get
naive generic exposure (which would leak `password_hash`). These tools
are hand-curated instead — user tools never read or accept a raw
`password_hash`, only a plaintext `password` to hash on the way in.

All of these sit in their own `"admin"` group/MCP server, and are scoped
against the `User`/`Role` pseudo-types, which `crystalline.security.scopes`
protects from partial wildcards the same way — only `admin`'s literal
`*:*`, or an explicit grant, reaches them.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from crystalline.schema import CrystallineModel, SchemaRegistry
from crystalline.security import SecurityPolicy, User, create_user, hash_password
from crystalline.storage import Storage

from .registry import ToolRegistry
from .tool import Tool

ADMIN_GROUP = "admin"


class _NoInput(CrystallineModel):
    pass


class _UserIdInput(CrystallineModel):
    id: str


class _CreateUserInput(CrystallineModel):
    id: str
    password: str
    roles: list[str] = Field(default_factory=list)


class _UpdateUserInput(CrystallineModel):
    id: str
    password: str | None = None
    roles: list[str] | None = None
    disabled: bool | None = None


class _RoleNameInput(CrystallineModel):
    name: str


class _RoleInput(CrystallineModel):
    name: str
    scopes: list[str] = Field(default_factory=list)


def _safe_user(user: User) -> dict[str, Any]:
    """`User` minus `password_hash` — the only shape these tools ever return."""
    return {"id": user.id, "roles": user.roles, "disabled": user.disabled}


def generate_user_tools(storage: Storage) -> list[Tool]:
    async def list_users(_: BaseModel) -> list[dict[str, Any]]:
        return [_safe_user(u) for u in storage.list(User)]

    async def get_user(data: _UserIdInput) -> dict[str, Any] | None:
        user = storage.get(User, data.id)
        return _safe_user(user) if user is not None else None

    async def create_user_tool(data: _CreateUserInput) -> dict[str, Any]:
        user = create_user(storage, data.id, data.password, roles=data.roles)
        return _safe_user(user)

    async def update_user(data: _UpdateUserInput) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        if data.password is not None:
            changes["password_hash"] = hash_password(data.password)
        if data.roles is not None:
            changes["roles"] = data.roles
        if data.disabled is not None:
            changes["disabled"] = data.disabled
        updated = storage.update(User, data.id, **changes)
        return _safe_user(updated)

    async def delete_user(data: _UserIdInput) -> bool:
        return storage.delete(User, data.id)

    return [
        Tool(
            name="list_users",
            description="List all users (without password hashes).",
            input_model=_NoInput,
            handler=list_users,
            scope="User:read",
            group=ADMIN_GROUP,
        ),
        Tool(
            name="get_user",
            description="Get a user by id (without its password hash).",
            input_model=_UserIdInput,
            handler=get_user,
            scope="User:read",
            group=ADMIN_GROUP,
        ),
        Tool(
            name="create_user",
            description="Create a new user with a password and roles.",
            input_model=_CreateUserInput,
            handler=create_user_tool,
            scope="User:create",
            group=ADMIN_GROUP,
        ),
        Tool(
            name="update_user",
            description=(
                "Update a user's password, roles, and/or disabled status. "
                "Only fields provided are changed."
            ),
            input_model=_UpdateUserInput,
            handler=update_user,
            scope="User:update",
            group=ADMIN_GROUP,
        ),
        Tool(
            name="delete_user",
            description="Delete a user by id.",
            input_model=_UserIdInput,
            handler=delete_user,
            scope="User:delete",
            group=ADMIN_GROUP,
        ),
    ]


def generate_role_tools(security: SecurityPolicy) -> list[Tool]:
    async def list_roles(_: BaseModel) -> dict[str, list[str]]:
        return security.roles

    async def get_role(data: _RoleNameInput) -> list[str] | None:
        return security.get_role(data.name)

    async def create_role(data: _RoleInput) -> list[str]:
        if security.get_role(data.name) is not None:
            raise ValueError(f"Role {data.name!r} already exists")
        security.add_role(data.name, data.scopes)
        return data.scopes

    async def update_role(data: _RoleInput) -> list[str]:
        if security.get_role(data.name) is None:
            raise KeyError(f"No role named {data.name!r}")
        security.add_role(data.name, data.scopes)
        return data.scopes

    async def delete_role(data: _RoleNameInput) -> bool:
        return security.remove_role(data.name) is not None

    return [
        Tool(
            name="list_roles",
            description="List all roles and the scopes each one grants.",
            input_model=_NoInput,
            handler=list_roles,
            scope="Role:read",
            group=ADMIN_GROUP,
        ),
        Tool(
            name="get_role",
            description="Get the scopes granted by a role, by name.",
            input_model=_RoleNameInput,
            handler=get_role,
            scope="Role:read",
            group=ADMIN_GROUP,
        ),
        Tool(
            name="create_role",
            description="Create a new role with the given granted scopes.",
            input_model=_RoleInput,
            handler=create_role,
            scope="Role:create",
            group=ADMIN_GROUP,
        ),
        Tool(
            name="update_role",
            description="Replace an existing role's granted scopes.",
            input_model=_RoleInput,
            handler=update_role,
            scope="Role:update",
            group=ADMIN_GROUP,
        ),
        Tool(
            name="delete_role",
            description="Delete a role by name.",
            input_model=_RoleNameInput,
            handler=delete_role,
            scope="Role:delete",
            group=ADMIN_GROUP,
        ),
    ]


def generate_scope_tools(schema: SchemaRegistry) -> list[Tool]:
    async def list_scopes(_: BaseModel) -> list[str]:
        actions = ("create", "read", "update", "delete")
        scopes = [f"{type_name}:{action}" for type_name in schema for action in actions]
        scopes.extend(f"*:{action}" for action in actions)
        scopes.append("*:*")
        return scopes

    return [
        Tool(
            name="list_scopes",
            description="List every scope string the system currently understands.",
            input_model=_NoInput,
            handler=list_scopes,
            scope=None,
            group=ADMIN_GROUP,
        )
    ]


def generate_admin_tools(
    storage: Storage, security: SecurityPolicy, schema: SchemaRegistry
) -> list[Tool]:
    return [
        *generate_user_tools(storage),
        *generate_role_tools(security),
        *generate_scope_tools(schema),
    ]


def sync_admin_tools(
    registry: ToolRegistry,
    storage: Storage,
    security: SecurityPolicy,
    schema: SchemaRegistry,
) -> None:
    for tool in generate_admin_tools(storage, security, schema):
        registry.add_tool(tool, replace=True)
