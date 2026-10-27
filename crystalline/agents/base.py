"""Abstract base class for talking to a coding agent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class Tool:
    """A capability an agent can invoke.

    Set `handler` for a tool the agent framework implements itself
    in-process. Leave it unset to reference a tool the underlying agent
    runtime already knows about by name (a built-in tool, or one exposed
    by an externally configured server).
    """

    name: str
    description: str = ""
    input_schema: dict[str, Any] | None = None
    handler: ToolHandler | None = None
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Skill:
    """A packaged capability (prompt + resources) an agent can draw on."""

    name: str
    description: str = ""
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class Agent(ABC):
    """Base abstraction for talking to a coding agent.

    Subclasses adapt a concrete agent runtime (Claude Code, etc.) to this
    interface: CRUD for tools/skills/properties plus a minimal
    connect/send/receive lifecycle for conversing with the agent.
    """

    def __init__(
        self,
        name: str,
        *,
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self._tools: dict[str, Tool] = {}
        self._skills: dict[str, Skill] = {}
        self._properties: dict[str, Any] = {}

    # ---- tools ----

    def add_tool(self, tool: Tool) -> Tool:
        self._tools[tool.name] = tool
        return tool

    def register_tool(
        self,
        name: str,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        *,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> Callable[[ToolHandler], ToolHandler]:
        """Decorator sugar for defining and adding an in-process tool.

        async def handler(args: dict) -> dict:
            ...

        @agent.register_tool("add", "Add two numbers", {"a": float, "b": float})
        async def add(args):
            return {"content": [{"type": "text", "text": str(args["a"] + args["b"])}]}
        """

        def decorator(handler: ToolHandler) -> ToolHandler:
            self.add_tool(
                Tool(
                    name=name,
                    description=description,
                    input_schema=input_schema,
                    handler=handler,
                    enabled=enabled,
                    metadata=metadata or {},
                )
            )
            return handler

        return decorator

    def get_tool(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def remove_tool(self, name: str) -> Tool | None:
        return self._tools.pop(name, None)

    def update_tool(self, name: str, **changes: Any) -> Tool:
        tool_ = self._tools.get(name)
        if tool_ is None:
            raise KeyError(f"Unknown tool: {name!r}")
        for key, value in changes.items():
            setattr(tool_, key, value)
        return tool_

    @property
    def tools(self) -> list[Tool]:
        return list(self._tools.values())

    # ---- skills ----

    def add_skill(self, skill: Skill) -> Skill:
        self._skills[skill.name] = skill
        return skill

    def get_skill(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def remove_skill(self, name: str) -> Skill | None:
        return self._skills.pop(name, None)

    def update_skill(self, name: str, **changes: Any) -> Skill:
        skill = self._skills.get(name)
        if skill is None:
            raise KeyError(f"Unknown skill: {name!r}")
        for key, value in changes.items():
            setattr(skill, key, value)
        return skill

    @property
    def skills(self) -> list[Skill]:
        return list(self._skills.values())

    # ---- arbitrary properties (model, cwd, permission mode, hooks, ...) ----

    def set_property(self, key: str, value: Any) -> None:
        self._properties[key] = value

    def get_property(self, key: str, default: Any = None) -> Any:
        return self._properties.get(key, default)

    def remove_property(self, key: str) -> Any:
        return self._properties.pop(key, None)

    @property
    def properties(self) -> dict[str, Any]:
        return dict(self._properties)

    # ---- conversation lifecycle ----

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether a session with the underlying agent is currently open."""

    @abstractmethod
    async def connect(self) -> None:
        """Start a session with the underlying agent."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Tear down the current session."""

    @abstractmethod
    async def send(self, prompt: str) -> None:
        """Send a prompt within the current session."""

    @abstractmethod
    def receive(self) -> AsyncIterator[Any]:
        """Stream raw response messages for the most recently sent prompt."""

    @abstractmethod
    async def run(self, prompt: str) -> str:
        """Send a prompt and return the final text reply, managing the
        connection lifecycle automatically if one isn't already open."""

    async def __aenter__(self) -> Agent:
        await self.connect()
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.disconnect()
