"""Bridging `crystalline.crystallization` and a live `Project`: gathering
a session's monitored turns/events, running a plugin against the
project's current state, and — only after a human has approved the
result — writing the proposal out. A `FileChange` lands under
`project.extensions_dir`; a `SchemaChange` lands on `project.schema`
directly (it's config, not a file) and, since `/reload` re-reads the
*project file* from disk afterward (discarding anything only held in
memory), must also be persisted back to it via `save_project` — the
caller (the CLI's `/crystallize`) is the one place that already knows
that path, so it's passed in rather than stored on `Project` itself.

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
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from crystalline.agents import Agent, ClaudeCodeAgent
from crystalline.crystallization import (
    CrystallizationContext,
    CrystallizationProposal,
    CrystallizationRegistry,
    SessionReplayPlugin,
)
from crystalline.monitoring import TURN_STATUS_ERROR, Turn
from crystalline.schema import SchemaRegistry
from crystalline.security import RESERVED_TYPE_NAMES

from .fields import build_model_from_field_spec, field_spec_from_model
from .io import save_project
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


def read_schema_field_specs(project: Project) -> dict[str, dict[str, Any]]:
    """Current `{field_name: type_expr}` spec of every non-reserved
    registered schema type, keyed by type name — the `SchemaChange`
    counterpart to `read_extension_files`, used to build `render_diff`/
    `summarize_changes`'s "before" side for schema changes."""
    return {
        name: field_spec_from_model(model, project.schema)
        for name, model in project.schema.types.items()
        if name not in RESERVED_TYPE_NAMES
    }


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


def apply_crystallization(
    project: Project,
    proposal: CrystallizationProposal,
    *,
    project_path: str | Path | None = None,
) -> None:
    """Apply every approved `SchemaChange`, then write every approved
    `FileChange` to disk under `project.extensions_dir`. Call
    `crystalline.project.apply_extensions` (or `/reload`) afterward to
    actually load the file changes — this function registers schema
    changes directly onto the live `project.schema` (so a `FileChange` in
    the same proposal can immediately `project.schema.get(...)` a type it
    just added), but never touches `project.tools`/`project.skills`
    itself.

    `project_path` is required whenever `proposal.schema_changes` is
    non-empty: unlike an extension file, a schema type has nowhere else
    to live than the project's own config file, and `/reload` re-reads
    that file from disk — a schema change that only ever touched the
    in-memory `project.schema` would silently vanish on the very reload
    `/crystallize` triggers right after approval.

    Everything is validated before anything is mutated or written: a bad
    `FileChange` path or an unresolvable field-type expression raises
    before any schema change reaches `project.schema`/disk, or any file
    reaches `extensions_dir` — half-applying a proposal would leave the
    live project (and, for schema changes, the saved project file) in a
    state the human reviewer never actually approved.
    """
    if proposal.schema_changes and project_path is None:
        raise RuntimeError(
            "Crystallization needs the project file's path to persist schema "
            "changes (schema types live in the project config file, not under "
            "extensions_dir) — pass project_path=..."
        )

    targets: list[tuple[str, str, Path]] = []
    if proposal.changes:
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
            targets.append((change.action, change.content or "", target))

    # Validate every SchemaChange against a scratch copy of the current
    # registry (so a later block can still reference an earlier block's
    # new type by name, same as the real apply below) before touching
    # `project.schema` at all — `build_model_from_field_spec` raises
    # `FieldSpecError` (a `ValueError`) on an unresolvable type
    # expression, and that must not land only the first N changes.
    scratch = SchemaRegistry()
    for name, existing_model in project.schema.types.items():
        scratch.register(existing_model, name=name)
    models: dict[str, type[BaseModel]] = {}
    for change in proposal.schema_changes:
        if change.action == "delete":
            scratch.remove(change.type_name)
            continue
        model = build_model_from_field_spec(change.type_name, change.field_spec or {}, scratch)
        scratch.register(model, name=change.type_name, replace=True)
        models[change.type_name] = model

    for change in proposal.schema_changes:
        if change.action == "delete":
            project.schema.remove(change.type_name)
        else:
            project.schema.register(models[change.type_name], name=change.type_name, replace=True)
    if proposal.schema_changes:
        project.sync_tools()
        save_project(project, project_path)  # type: ignore[arg-type]

    for action, content, target in targets:
        if action == "delete":
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
