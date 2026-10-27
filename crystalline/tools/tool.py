"""`Tool`: a project-level, schema-typed callable.

This is the source of truth for "what can be done" in a project — the
project-level counterpart to the generic, agent-facing
`crystalline.agents.Tool`. `crystalline.project.agent_wiring` is the
adapter between the two, per the relationship flagged in
`docs/architecture.md`: this one knows about Pydantic input/output models
and a required security scope; the agent-facing one knows about raw
dict-in/dict-out MCP handlers and nothing about either.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from crystalline.security import check_scope, current_token

ToolHandler = Callable[[BaseModel], Awaitable[Any]]


@dataclass
class Tool:
    name: str
    input_model: type[BaseModel]
    handler: ToolHandler
    description: str = ""
    output_model: type[BaseModel] | None = None
    scope: str | None = None
    group: str = "crystalline"
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    async def invoke(self, data: BaseModel) -> Any:
        """Check `scope` (if set) against the ambient token, then call
        `handler`. This is the one true call path — both the MCP-facing
        wrapper (`crystalline.project.agent_wiring`) and CLI commands call
        through here, so the scope check can't be bypassed by invoking
        the handler directly from one of them.
        """
        if not self.enabled:
            raise PermissionError(f"Tool {self.name!r} is disabled")
        if self.scope is not None:
            check_scope(current_token(), self.scope)
        return await self.handler(data)
