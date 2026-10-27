"""Session data model: what `crystalline.monitoring` persists.

Three tiers, modeled after how observability tools built for this exact
problem (Langfuse's Session/Trace/Observation, OpenAI's
Conversation/Response/Item) structure it — converging independently on
the same shape: a long-lived container, a unit-of-work with status/cost/
duration, and the steps within it.

- `Session`: one CLI invocation (login to quit) — a single `session_id`
  spans every `/reload` within it, since from the user's perspective
  it's still one continuous session even though the underlying
  `Project`/`Agent` get rebuilt. Rolls up nothing itself — totals are a
  query over its turns, never stored redundantly here.
- `Turn`: one user-initiated action, from the moment a UI layer builds a
  `crystalline.events.Event` and hands it to the router through to
  however it ends up being resolved — whether that's a direct tool/skill
  dispatch (a `route_decision` event followed by `tool_call`/
  `tool_result`) or an agent handoff (`route_decision` followed by the
  usual `user_message`/`assistant_text`/`tool_call`/`tool_result`
  sequence). Every turn starts with a `route_decision` event no matter
  which way it's handled — that's what makes "how often did a rule
  handle this vs. the agent" a queryable property instead of something
  only inferable after the fact. This is also the tier that carries
  status/cost/usage/duration — every framework surveyed puts those on the
  *middle* tier, not the session, and that's the gap this redesign closes
  (an earlier flat `SessionRecord` design had no object grouping
  "everything that happened answering this one prompt").
- `SessionEvent`: one step within a turn (a user message, an assistant
  text chunk, a tool call, a tool result, ...). Named `SessionEvent`, not
  `Event`, specifically to avoid colliding with `crystalline.events.Event`
  — unlike the `Skill`/`SessionStore` naming overlaps elsewhere (ours vs.
  an unrelated third-party concept), this would be two of *our own*
  packages using the identical name for related-but-different things,
  which is a sharper collision than those precedents.

`Session`/`Turn`/`SessionEvent` are Pydantic models, not dataclasses —
unlike `crystalline.events.Event` (an in-process dispatch envelope that's
never itself serialized), these are the things actually written to a
`SessionStore`, i.e. they cross a storage boundary, which is exactly the
case CLAUDE.md's "Pydantic for anything that crosses a boundary" rule is
about.

One flexible `SessionEvent` shape, not a rigid subclass per kind —
"events in, decisions made, tool/skill/agent invocations" (the
architecture doc's own list, minus "outcomes", which now live on `Turn`)
all fit as `{kind, data}`, which keeps room for `crystallization` to mine
whatever kinds show up later without a schema migration. The
`EVENT_KIND_*` constants below are the kinds `crystalline.project.
monitoring_wiring` currently produces — not a closed enum; nothing stops
a future producer from using its own. `parent_event_id` (nullable, so it
costs nothing today) borrows Langfuse's nestable-observations idea — a
tool result can be recorded as a child of its tool call rather than a
same-level sibling, once a producer bothers to populate it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

EVENT_KIND_ROUTE_DECISION = "route_decision"
"""Always the first event in a turn — the originating event a UI layer
handed to the router, annotated with what the router decided and (for
future, smarter routers) what that decision was based on. Recorded no
matter how the turn ends up being handled, so a turn that went straight
to a tool/skill is just as visible to `crystallization` as one that went
to the agent."""
EVENT_KIND_USER_MESSAGE = "user_message"
EVENT_KIND_ASSISTANT_TEXT = "assistant_text"
EVENT_KIND_TOOL_CALL = "tool_call"
EVENT_KIND_TOOL_RESULT = "tool_result"
EVENT_KIND_MESSAGE = "message"
"""Catch-all kind for a raw message type a recorder doesn't explicitly
parse, so a message is never silently dropped just because nothing
recognizes its shape yet."""

TURN_STATUS_IN_PROGRESS = "in_progress"
TURN_STATUS_COMPLETED = "completed"
TURN_STATUS_ERROR = "error"


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Session(BaseModel):
    id: str
    project_name: str
    principal: str | None = None
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Turn(BaseModel):
    id: str
    session_id: str
    status: str = TURN_STATUS_IN_PROGRESS
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None
    duration_ms: int | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    result: str | None = None
    errors: list[str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionEvent(BaseModel):
    session_id: str
    turn_id: str
    kind: str
    data: dict[str, Any] = Field(default_factory=dict)
    parent_event_id: str | None = None
    id: str = Field(default_factory=_new_id)
    created_at: datetime = Field(default_factory=_utcnow)
