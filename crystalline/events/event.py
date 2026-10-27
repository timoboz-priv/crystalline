"""`Event`: the unit that flows from a UI layer (CLI, HTTP, chat, ...)
into this package's `router` module.

A plain dataclass, not a Pydantic model — like `crystalline.agents.Tool`/
`Skill`, it's an in-process runtime object that doesn't itself cross a
process boundary or need validation (a `payload`'s own shape, when the
router dispatches it to a tool, is validated against that tool's
`input_model` — that's where Pydantic does its job).

`project_name` is a bare reference, not a live `Project` — *this module*
only depends on `security` (for `Token`); it's `router.py`, elsewhere in
this same package, that depends on `crystalline.project` too in order to
resolve a name to an actual project (Event and Router are kept in one
package specifically because a router has nothing to do without an event
to route — there's no meaningful boundary to split them across).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from crystalline.security import Token

TEXT_EVENT_TYPE = "text"
"""Reserved `Event.type` for free-form text input (what a chat-style UI
like the CLI sends for a plain message). `crystalline.events.Router`
always falls back to an agent handoff for this type, regardless of what
tools/skills a project registers — the one route a project can rely on
existing even with zero rules configured."""


@dataclass(frozen=True)
class Event:
    type: str
    payload: Any
    project_name: str
    session_id: str
    token: Token | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
