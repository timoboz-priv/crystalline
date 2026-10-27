"""The `Project` config object: the top-level entity in Crystalline."""

from __future__ import annotations

from typing import Any

from crystalline.monitoring import SessionStore
from crystalline.schema import SchemaRegistry
from crystalline.security import SecurityPolicy, User
from crystalline.skills import SkillRegistry
from crystalline.storage import InMemoryStorage, Storage
from crystalline.tools import ToolRegistry, sync_admin_tools, sync_storage_tools


class Project:
    """A Crystalline project: name, version, the registry of data types,
    the storage backend those types are persisted to, the security
    policy (roles/scopes) guarding them, the tools derived from all
    three, the hand-written skills built on top of those tools, and
    which agent backend talks to it — everything else (events, ...) will
    act against these once those components exist.

    Every project auto-registers `crystalline.security.User` in its
    schema under the reserved name `"User"`, since authentication is
    expected to work the same way everywhere: users are just another
    stored type, with roles resolved against `security`.

    `tools` starts empty and is *generated*, not independently declared —
    call `sync_tools()` after the schema is done changing (`load_project`
    does this automatically) to (re)populate it with CRUD tools for every
    registered type plus user/role/scope admin tools. Unlike
    `properties`, it's not meant to be hand-populated as config.

    `skills` also starts empty, but unlike `tools` there's nothing to
    generate it from — a skill orchestrates other tools via custom logic,
    so it's always hand-written. A project file's `extensions:` section
    names a directory of `tool_*.py`/`skill_*.py` files (one tool/skill
    per file, each with a `build_tool(project) -> Tool` /
    `build_skill(project) -> Skill` function) — `extensions_dir` holds
    that path (already resolved against the project file's directory), as
    plain data. `load_project` does *not* scan or execute it — see
    `crystalline.project.extensions.apply_extensions`, which the CLI
    calls automatically right after loading (and again on `/reload`),
    since by the time something is about to run a project at all, it
    already trusts it with far more than "also run the Python files it
    points to." See `examples/demo_shop/extensions/` for worked examples.

    `agent_config` is a plain `{"type": ..., ...}` dict, not a live
    `Agent` instance — unlike `storage`, an agent carries async
    connection state that doesn't belong on a static config object.
    `crystalline.project.build_agent(project)` constructs the actual
    `Agent` it names, with tools, skills, and system prompt already wired.

    `monitoring_store` is a live `crystalline.monitoring.SessionStore`
    (unlike `agent_config`, it's fine to hold as a static object — a
    store is just storage, no async connection state) or `None` if a
    project file has no `monitoring:` section, since unlike `storage`
    there's no sensible "monitor by default" backend. When set,
    `build_agent(project)` wraps the constructed `Agent` in a
    `crystalline.project.monitoring_wiring.MonitoredAgent` automatically.

    Anything not yet modeled with a dedicated field can be stashed in
    `properties` (same escape-hatch pattern as `crystalline.agents.Agent`)
    so config files can carry forward-compatible settings before the
    component that interprets them is built.
    """

    def __init__(
        self,
        name: str,
        version: str,
        *,
        description: str | None = None,
        schema: SchemaRegistry | None = None,
        storage: Storage | None = None,
        security: SecurityPolicy | None = None,
        tools: ToolRegistry | None = None,
        skills: SkillRegistry | None = None,
        agent_config: dict[str, Any] | None = None,
        extensions_dir: str | None = None,
        monitoring_store: SessionStore | None = None,
    ) -> None:
        self.name = name
        self.version = version
        self.description = description
        self.schema = schema if schema is not None else SchemaRegistry()
        self.schema.register(User, name="User")
        self.storage: Storage = storage if storage is not None else InMemoryStorage()
        self.security = security if security is not None else SecurityPolicy()
        self.tools = tools if tools is not None else ToolRegistry()
        self.skills = skills if skills is not None else SkillRegistry()
        self.agent_config: dict[str, Any] = (
            dict(agent_config) if agent_config is not None else {"type": "claude_code"}
        )
        self.extensions_dir = extensions_dir
        self.monitoring_store = monitoring_store
        self._properties: dict[str, Any] = {}

    def sync_tools(self) -> None:
        """(Re)generate storage CRUD tools for every current schema type,
        plus user/role/scope admin tools, into `self.tools`."""
        sync_storage_tools(self.tools, self.schema, self.storage)
        sync_admin_tools(self.tools, self.storage, self.security, self.schema)

    # ---- arbitrary properties (forward-compat escape hatch) ----

    def set_property(self, key: str, value: Any) -> None:
        self._properties[key] = value

    def get_property(self, key: str, default: Any = None) -> Any:
        return self._properties.get(key, default)

    def remove_property(self, key: str) -> Any:
        return self._properties.pop(key, None)

    @property
    def properties(self) -> dict[str, Any]:
        return dict(self._properties)

    def __repr__(self) -> str:
        return (
            f"Project(name={self.name!r}, version={self.version!r}, "
            f"types={list(self.schema)!r})"
        )
