"""Bridging `crystalline.crystallization` and a live `Project`: gathering
a session's monitored turns/events, running a plugin against the
project's current state, and — only after a human has approved the
result — writing the proposal to `project.extensions_dir`.

Needs `crystalline.crystallization` (`CrystallizationRegistry`/
`CrystallizationContext`/`CrystallizationProposal`), `crystalline.agents`
(to build the plugin's one-shot codegen agent), and this package's own
`monitoring_wiring` (`MonitoredAgent`, so the codegen call's own cost
rolls into the session like any other turn) all at once — a wiring
concern, same as `agent_wiring.py`/`monitoring_wiring.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from crystalline.agents import Agent, ClaudeCodeAgent
from crystalline.crystallization import (
    CrystallizationContext,
    CrystallizationProposal,
    CrystallizationRegistry,
    SessionReplayPlugin,
)
from crystalline.monitoring import TURN_STATUS_ERROR, Turn

from .monitoring_wiring import MonitoredAgent

if TYPE_CHECKING:
    from .project import Project

AgentFactory = Callable[["Project"], Agent]


def build_crystallization_registry() -> CrystallizationRegistry:
    """The default set of plugins: just `SessionReplayPlugin`, under
    mode `"session"`, for now — future plugins register here too."""
    registry = CrystallizationRegistry()
    registry.register(SessionReplayPlugin())
    return registry


def _default_codegen_agent(project: Project) -> Agent:
    # No tools/skills added: this agent only ever reasons over the prompt
    # text handed to it and replies with text, same as any one-shot
    # `agent.run(prompt)` call — it has nothing to call Write/Bash/etc.
    # with, by construction, not by permission configuration.
    return ClaudeCodeAgent(name="crystallization", model=project.agent_config.get("model"))


def read_extension_files(project: Project) -> dict[str, str]:
    """Current content of every `*.py` under `project.extensions_dir`,
    keyed by filename — used both to build `render_diff`'s "before" side
    and (by `SessionReplayPlugin`) to decide what's already there."""
    if project.extensions_dir is None:
        return {}
    directory = Path(project.extensions_dir)
    if not directory.is_dir():
        return {}
    return {path.name: path.read_text() for path in sorted(directory.glob("*.py"))}


async def run_crystallization(
    project: Project,
    *,
    session_id: str,
    mode: str,
    registry: CrystallizationRegistry,
    agent_factory: AgentFactory | None = None,
) -> CrystallizationProposal | None:
    plugin = registry.get(mode)
    if plugin is None:
        known = ", ".join(sorted(p.name for p in registry)) or "(none registered)"
        raise KeyError(f"Unknown crystallization mode {mode!r}; known modes: {known}")

    store = project.monitoring_store
    if store is None:
        raise RuntimeError(
            "Crystallization requires monitoring to be configured for this project "
            "(add a `monitoring:` section to the project file)"
        )

    session = store.get_session(session_id)
    if session is None:
        raise KeyError(f"No monitoring session with id={session_id!r}")
    turns = store.list_turns(session_id)
    events = store.list_events(session_id=session_id)

    raw_agent = (agent_factory or _default_codegen_agent)(project)

    turn = Turn(
        id=uuid.uuid4().hex,
        session_id=session_id,
        metadata={"kind": "crystallization", "plugin": mode},
    )
    store.start_turn(turn)
    monitored_agent = MonitoredAgent(raw_agent, store, session_id=session_id)
    monitored_agent.continue_turn(turn.id)

    ctx = CrystallizationContext(
        project=project, session=session, turns=turns, events=events, agent=monitored_agent
    )
    try:
        return await plugin.propose(ctx)
    finally:
        # A `ResultMessage` reaching `MonitoredAgent.receive()` already
        # closed the turn in the success path; this only fires if
        # `agent.run()` itself raised (e.g. a connection error) or the
        # plugin raised before/without ever calling it.
        current = store.get_turn(turn.id)
        if current is not None and current.ended_at is None:
            store.end_turn(turn.id, status=TURN_STATUS_ERROR, errors=["crystallization failed"])


def apply_crystallization(project: Project, proposal: CrystallizationProposal) -> None:
    """Write every approved `FileChange` to disk under
    `project.extensions_dir`. Call `crystalline.project.apply_extensions`
    (or `/reload`) afterward to actually load the result — this function
    only touches files, never the live `project.tools`/`project.skills`.
    """
    if project.extensions_dir is None:
        raise RuntimeError(
            "Crystallization needs project.extensions_dir set (add an `extensions:` "
            "section to the project file) before a proposal can be applied"
        )
    directory = Path(project.extensions_dir).resolve()
    for change in proposal.changes:
        target = (directory / change.path).resolve()
        if not target.is_relative_to(directory):
            raise ValueError(f"FileChange path {change.path!r} escapes extensions_dir")
        if change.action == "delete":
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change.content or "")
