"""`Skill`: a named, typed workflow that chains tool calls (and
optionally agentic steps).

Structurally identical to `crystalline.tools.Tool` — same Pydantic
input/output, same single optional `scope`, same `invoke()` call path.
The distinction is purely about what the handler *does*: a Tool's
handler is one atomic operation (typically a single `Storage` call); a
Skill's handler orchestrates other tools, usually via their own
`.invoke()` (which already enforces each step's own scope on the ambient
token — a skill's declared `scope` is a fail-fast gate on top of that,
not a replacement for it; see `docs/architecture.md`'s security
principle: enforcement happens per-call, not "trust the caller already
checked"). There's no declarative step list — the workflow is just a
plain async function, same as any Tool handler, calling into other
`Tool.invoke()`s directly.

Reusing `Tool`'s shape (rather than a parallel implementation) means
`crystalline.project.agent_wiring.wire_tools` and every CLI rendering
helper already know how to handle a `Skill` with no extra code.
"""

from __future__ import annotations

from dataclasses import dataclass

from crystalline.tools import Tool


@dataclass
class Skill(Tool):
    group: str = "skills"
