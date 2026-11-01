"""`CrystallizationPlugin`: the extension point for "how do we turn a
monitored session into a proposal".

Depends directly on `crystalline.project.Project` (not a pre-extracted
snapshot of its tools/skills/extension files) — a plugin deciding
whether to reuse an existing tool/skill or build something new needs
live access to the project's current state, not a copy the wiring layer
decided was worth passing along. `CrystallizationContext` is a plain
dataclass (in-process only, never serialized), same convention as
`crystalline.events.Event`/`crystalline.agents.Tool`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from crystalline.agents import Agent
from crystalline.monitoring import Session, SessionEvent, Turn

from .models import CrystallizationProposal

if TYPE_CHECKING:
    from crystalline.project import Project


@dataclass
class CrystallizationContext:
    project: Project
    session: Session
    turns: list[Turn]
    events: list[SessionEvent]
    agent: Agent
    """A bare, tool-less one-shot agent for the plugin's own reasoning/
    codegen (call `await ctx.agent.run(prompt)`) — distinct from
    anything in `ctx.project.agent_config`, which describes the
    project's own user-facing agent, not this plugin's scratch one."""


class CrystallizationPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """The mode string `/crystallize <mode>` selects this plugin by."""

    @abstractmethod
    async def propose(self, ctx: CrystallizationContext) -> CrystallizationProposal | None:
        """Return a proposal, or `None` if there's nothing worth
        crystallizing — including when the session's pattern is already
        fully covered by an existing tool/skill."""
