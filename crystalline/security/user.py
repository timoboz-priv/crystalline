"""The `User` schema type.

This is framework-provided and reserved: `crystalline.project.Project`
auto-registers it under the name `"User"` in every project's schema
registry, so a project file cannot redeclare a type by that name.

`password_hash` must never be included in whatever output shape
`crystalline.tools` eventually generates for reading/listing `User`
records over MCP — flagged in `docs/architecture.md`.
"""

from __future__ import annotations

from pydantic import Field

from crystalline.schema import CrystallineModel


class User(CrystallineModel):
    id: str
    roles: list[str] = Field(default_factory=list)
    password_hash: str
    disabled: bool = False


RESERVED_TYPE_NAMES = frozenset({"User", "Role"})
"""Schema type names owned by the framework; a project may not redeclare
them, and generic CRUD tool generation (`crystalline.tools`) skips them
in favor of purpose-built tools that don't leak e.g. `password_hash`.
`"Role"` isn't an actual schema type (role policy lives in
`SecurityPolicy`, not `Storage`) — it's reserved anyway, matching
`crystalline.security.scopes.PROTECTED_TYPES`, so a project can't declare
its own `Role` schema type whose generated `create_role`/etc. CRUD tools
would otherwise be silently overwritten by `crystalline.tools.admin`'s
role-policy tools of the same name (`Project.sync_tools()` always applies
admin tools after storage CRUD tools)."""
