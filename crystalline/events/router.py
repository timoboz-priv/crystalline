"""Decides, per `Event`: a direct tool/skill call, or an agent handoff.

`RuleBasedRouter` is the first (and currently only) implementation:
explicit name matching — `event.type` equal to a registered tool/skill
name in the target project dispatches straight to it; anything else,
including the reserved `TEXT_EVENT_TYPE` (checked first, so it can never
be shadowed by a same-named tool/skill), falls back to an agent handoff.
No LLM-based classification — the architecture doc is explicit about
keeping the common path deterministic and debuggable for now. Kept
behind the `Router` ABC so a smarter (e.g. embedding- or LLM-based)
router can be swapped in later without changing callers.

Lives alongside `Event` in `crystalline.events` (rather than its own
`crystalline.router` package) since a router has nothing to be without an
event to route — splitting them into separate packages just added an
import hop with no real boundary behind it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from crystalline.project import Project
from crystalline.security import bind_token
from crystalline.tools import Tool

from .event import TEXT_EVENT_TYPE, Event


@dataclass(frozen=True)
class AgentHandoff:
    """Returned by `Router.route` when no rule matches. Driving the
    actual agent conversation (e.g. streaming a reply) is left to
    whatever produced the event — that's a UI-layer concern the router
    itself has no opinion on. `turn_id` is set by a monitoring-aware
    router (`crystalline.project.monitoring_wiring.MonitoredRouter`) that
    already opened a `Turn` for this event — a plain `RuleBasedRouter`
    (no monitoring) leaves it `None`, since there's no turn to hand off."""

    event: Event
    turn_id: str | None = None


RouteResult = Any
"""Either a direct tool/skill invocation result, or an `AgentHandoff`."""


class Router(ABC):
    @abstractmethod
    async def route(self, event: Event) -> RouteResult: ...


class RuleBasedRouter(Router):
    """Routes against one project's `tools`/`skills` registries, by name."""

    def __init__(self, project: Project) -> None:
        self.project = project

    def resolve(self, event: Event) -> Tool | None:
        """The tool/skill `event.type` names, or `None` if nothing
        matches (meaning: fall back to an agent handoff). Pure lookup, no
        side effects — split out from `route()` so a monitoring-aware
        wrapper (`MonitoredRouter`) can record the routing decision and
        the resulting tool call/result as separate events, instead of
        `route()`'s dispatch being an opaque single step."""
        if event.project_name != self.project.name:
            raise ValueError(
                f"Event is for project {event.project_name!r}, but this "
                f"router serves {self.project.name!r}"
            )
        if event.type == TEXT_EVENT_TYPE:
            return None
        return self.project.tools.get_tool(event.type) or self.project.skills.get_tool(
            event.type
        )

    async def route(self, event: Event) -> RouteResult:
        tool = self.resolve(event)
        if tool is None:
            return AgentHandoff(event)

        data = tool.input_model.model_validate(event.payload)
        if event.token is not None:
            with bind_token(event.token):
                return await tool.invoke(data)
        return await tool.invoke(data)
