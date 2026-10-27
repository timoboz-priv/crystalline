"""Claude Code implementation of the `Agent` abstraction, built on the
Claude Agent SDK (https://code.claude.com/docs/en/agent-sdk/python).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionMode,
    TextBlock,
    create_sdk_mcp_server,
    tool as sdk_tool,
)

from .base import Agent


class ClaudeCodeAgent(Agent):
    """Talks to Claude Code via the Claude Agent SDK.

    Tools added without a `handler` are treated as references to tools the
    Claude Code CLI already knows about (built-ins like "Read"/"Bash", or
    tools exposed by an MCP server registered with `add_mcp_server`). Tools
    added with a `handler` are bundled into an in-process MCP server and
    exposed automatically — one server per distinct `tool.metadata["group"]`
    value (default `"crystalline"` if unset), so e.g.
    `crystalline.project.wire_tools` can keep a project's "storage" and
    "admin" tool groups as separate MCP servers.

    Anything not covered by a dedicated constructor argument can be set
    with `set_property` using the matching `ClaudeAgentOptions` field name
    (e.g. `agent.set_property("agents", {...})` for subagents, or
    `"hooks"`, `"sandbox"`, `"effort"`, `"thinking"`) and it will be passed
    straight through when building options.
    """

    _TOOL_SERVER_NAME = "crystalline"

    def __init__(
        self,
        name: str = "claude-code",
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        cwd: str | Path | None = None,
        permission_mode: PermissionMode | None = "default",
        max_turns: int | None = None,
    ) -> None:
        super().__init__(name, system_prompt=system_prompt, model=model)
        self.cwd = cwd
        self.permission_mode = permission_mode
        self.max_turns = max_turns
        self._mcp_servers: dict[str, Any] = {}
        self._client: ClaudeSDKClient | None = None

    # ---- MCP servers (external, by config) ----

    def add_mcp_server(self, name: str, config: Any) -> None:
        """Register an external MCP server, e.g.:

        agent.add_mcp_server("weather", {
            "type": "stdio", "command": "python", "args": ["weather_server.py"],
        })
        """
        self._mcp_servers[name] = config

    def get_mcp_server(self, name: str) -> Any | None:
        return self._mcp_servers.get(name)

    def remove_mcp_server(self, name: str) -> Any | None:
        return self._mcp_servers.pop(name, None)

    @property
    def mcp_servers(self) -> dict[str, Any]:
        return dict(self._mcp_servers)

    # ---- option building ----

    def _build_options(self) -> ClaudeAgentOptions:
        allowed_tools: list[str] = []
        disallowed_tools: list[str] = []
        in_process_tools_by_group: dict[str, list[Any]] = {}

        for t in self._tools.values():
            if t.handler is not None:
                group = t.metadata.get("group", self._TOOL_SERVER_NAME)
                wrapped = sdk_tool(
                    t.name, t.description, t.input_schema or {}
                )(t.handler)
                in_process_tools_by_group.setdefault(group, []).append(wrapped)
                qualified_name = f"mcp__{group}__{t.name}"
            else:
                qualified_name = t.name
            (allowed_tools if t.enabled else disallowed_tools).append(qualified_name)

        mcp_servers = dict(self._mcp_servers)
        for group, group_tools in in_process_tools_by_group.items():
            mcp_servers[group] = create_sdk_mcp_server(name=group, tools=group_tools)

        skill_names = [s.name for s in self._skills.values() if s.enabled]

        kwargs: dict[str, Any] = {
            "system_prompt": self.system_prompt,
            "model": self.model,
            "cwd": self.cwd,
            "permission_mode": self.permission_mode,
            "max_turns": self.max_turns,
            "allowed_tools": allowed_tools,
            "disallowed_tools": disallowed_tools,
            "mcp_servers": mcp_servers,
            "skills": skill_names or None,
        }
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        kwargs.update(self._properties)
        return ClaudeAgentOptions(**kwargs)

    # ---- conversation lifecycle ----

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        if self._client is not None:
            return
        self._client = ClaudeSDKClient(options=self._build_options())
        await self._client.connect()

    async def disconnect(self) -> None:
        if self._client is None:
            return
        client, self._client = self._client, None
        await client.disconnect()

    def _require_client(self) -> ClaudeSDKClient:
        if self._client is None:
            raise RuntimeError(
                f"{self.name} is not connected; call connect() or use 'async with'"
            )
        return self._client

    async def send(self, prompt: str) -> None:
        await self._require_client().query(prompt)

    async def receive(self) -> AsyncIterator[Any]:
        async for message in self._require_client().receive_response():
            yield message

    async def run(self, prompt: str) -> str:
        owns_connection = not self.is_connected
        if owns_connection:
            await self.connect()
        try:
            await self.send(prompt)
            chunks: list[str] = []
            async for message in self.receive():
                if isinstance(message, AssistantMessage):
                    chunks.extend(
                        block.text
                        for block in message.content
                        if isinstance(block, TextBlock)
                    )
            return "".join(chunks)
        finally:
            if owns_connection:
                await self.disconnect()
