"""Instrumenting `crystalline.events`'s router and a `crystalline.agents.
Agent` with `crystalline.monitoring`.

Needs `crystalline.agents` (concretely, `claude_agent_sdk`'s message
shapes), `crystalline.events` (`Router`/`RuleBasedRouter`/`AgentHandoff`/
`Event`), and `crystalline.monitoring` (`SessionStore`/`Session`/`Turn`/
`SessionEvent`) all at once — that combination is a wiring concern, same
as `agent_wiring.py` bridging `crystalline.tools`+`crystalline.agents`,
so it lives here rather than inside `crystalline.monitoring` or
`crystalline.events` themselves (both of which stay dependency-light per
the architecture doc's dependency table).

**Session/Turn/SessionEvent ownership, end to end:**

- `Session` is owned by the CLI, not by anything in this module — one
  `session_id` spans an entire CLI invocation (every `/reload` within
  it), via `start_monitoring_session`/`end_monitoring_session` called
  once each from `crystalline/cli/main.py`/`repl.py`. Neither
  `MonitoredAgent` nor `MonitoredRouter` starts or ends a session.
- `Turn` is owned by whoever first routes the originating `Event` —
  `MonitoredRouter.route()` always opens one and records a
  `route_decision` event first, no matter how the event ends up being
  handled. For a direct tool/skill dispatch, `MonitoredRouter` also
  records the `tool_call`/`tool_result` events and closes the turn
  itself. For an agent handoff, the turn is handed to a `MonitoredAgent`
  via `continue_turn(turn_id)` *before* the caller's next `send()` — the
  agent appends `user_message`/`assistant_text`/`tool_call`/`tool_result`
  events to that same turn and closes it once a `ResultMessage` arrives.
  This is what makes "did a rule handle this, or did it fall through to
  the agent" a queryable property of the turn's own event sequence,
  instead of something only inferable after the fact.
- `MonitoredAgent` also still supports being used *without* a router in
  front of it (tests, or a future non-CLI caller) — if nothing ever calls
  `continue_turn()`, `send()` falls back to starting (and, on the next
  `send()`/`disconnect()`, closing) its own turn, exactly as the original
  single-tier-agent design did.

Message parsing is two plain, swappable functions (`claude_message_recorder`
for per-step events, `claude_turn_outcome` for turn-ending outcomes),
not hard-wired into `MonitoredAgent`'s logic, so a different backend could
plug in its own without a speculative class hierarchy now.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from crystalline.agents import Agent
from crystalline.monitoring import (
    EVENT_KIND_ASSISTANT_TEXT,
    EVENT_KIND_MESSAGE,
    EVENT_KIND_ROUTE_DECISION,
    EVENT_KIND_TOOL_CALL,
    EVENT_KIND_TOOL_RESULT,
    EVENT_KIND_USER_MESSAGE,
    TURN_STATUS_COMPLETED,
    TURN_STATUS_ERROR,
    Session,
    SessionEvent,
    SessionStore,
    Turn,
)
from crystalline.tools import to_jsonable

if TYPE_CHECKING:
    # Deferred (not imported at module load time): crystalline.events.router
    # does an absolute `from crystalline.project import Project`, so this
    # module importing crystalline.events back at the top level would be a
    # genuine bidirectional circular import between the two packages, not
    # just an ordering issue `__init__.py` reordering can fix. `Event`/
    # `AgentHandoff`/`RuleBasedRouter` are only ever actually constructed/
    # isinstance-checked inside function bodies below, via a local import
    # there — `from __future__ import annotations` already makes every
    # annotation in this file a deferred string, so TYPE_CHECKING is only
    # needed for a type checker's sake, not to avoid a runtime error.
    from crystalline.events import AgentHandoff, Event, RouteResult, RuleBasedRouter

    from .project import Project

MessageRecorder = Callable[[Any], list[tuple[str, dict[str, Any]]]]
"""Given one raw message yielded by `Agent.receive()`, return zero or more
`(kind, data)` pairs to persist as events — `session_id`/`turn_id` aren't
the recorder's concern, `MonitoredAgent` fills those in. Returns `[]` for
a message that ends a turn (`claude_turn_outcome` handles that instead) or
that carries no event-worthy content."""

TurnOutcomeExtractor = Callable[[Any], dict[str, Any] | None]
"""Given one raw message, return `end_turn(...)` kwargs if this message
concludes the current turn, else `None`."""


def claude_message_recorder(message: Any) -> list[tuple[str, dict[str, Any]]]:
    """Default `MessageRecorder`, for `claude_agent_sdk` message shapes."""
    records: list[tuple[str, dict[str, Any]]] = []

    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                records.append((EVENT_KIND_ASSISTANT_TEXT, {"text": block.text}))
            elif isinstance(block, ToolUseBlock):
                records.append(
                    (
                        EVENT_KIND_TOOL_CALL,
                        {"id": block.id, "name": block.name, "input": block.input},
                    )
                )
        return records

    if isinstance(message, UserMessage):
        content = message.content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, ToolResultBlock):
                    records.append(
                        (
                            EVENT_KIND_TOOL_RESULT,
                            {
                                "tool_use_id": block.tool_use_id,
                                "content": block.content,
                                "is_error": block.is_error,
                            },
                        )
                    )
        return records or [(EVENT_KIND_MESSAGE, {"type": "UserMessage"})]

    if isinstance(message, ResultMessage):
        # Turn-ending: claude_turn_outcome handles this one, not an event.
        return []

    # Unrecognized message type: record *something* rather than silently
    # dropping it, so future SDK message types don't vanish unnoticed.
    return [(EVENT_KIND_MESSAGE, {"type": type(message).__name__})]


def claude_turn_outcome(message: Any) -> dict[str, Any] | None:
    """Default `TurnOutcomeExtractor`: `ResultMessage` -> `end_turn(...)`
    kwargs, everything else -> `None` (doesn't end the turn)."""
    if not isinstance(message, ResultMessage):
        return None
    return {
        "status": TURN_STATUS_ERROR if message.is_error else TURN_STATUS_COMPLETED,
        "duration_ms": message.duration_ms,
        "total_cost_usd": message.total_cost_usd,
        "usage": message.usage,
        "result": message.result,
        "errors": message.errors,
    }


def start_monitoring_session(
    project: Project, session_id: str, *, principal: str | None = None
) -> None:
    """Start the one `Session` an entire CLI invocation shares, if the
    project has a `monitoring_store` configured. A no-op otherwise, so
    callers don't need to check `project.monitoring_store is not None`
    themselves."""
    if project.monitoring_store is None:
        return
    project.monitoring_store.start_session(
        Session(
            id=session_id,
            project_name=project.name,
            principal=principal,
            metadata={"agent": project.agent_config.get("type", "?")},
        )
    )


def end_monitoring_session(project: Project, session_id: str) -> None:
    """Inverse of `start_monitoring_session`; also a no-op if monitoring
    isn't configured."""
    if project.monitoring_store is None:
        return
    project.monitoring_store.end_session(session_id)


class MonitoredAgent(Agent):
    def __init__(
        self,
        inner: Agent,
        store: SessionStore,
        *,
        session_id: str | None = None,
        message_recorder: MessageRecorder = claude_message_recorder,
        turn_outcome_extractor: TurnOutcomeExtractor = claude_turn_outcome,
    ) -> None:
        self._inner = inner
        self._store = store
        self._session_id = session_id or uuid.uuid4().hex
        self._message_recorder = message_recorder
        self._turn_outcome_extractor = turn_outcome_extractor
        self._current_turn_id: str | None = None
        self._turn_attached_externally = False

    @property
    def session_id(self) -> str:
        return self._session_id

    def continue_turn(self, turn_id: str) -> None:
        """Attach to a turn already started elsewhere (typically a
        `MonitoredRouter`, before handing an `AgentHandoff` back) so the
        next `send()` appends to *that* turn instead of starting a new
        one. Without a prior call to this, `send()` self-manages its own
        turn — standalone use (no router in front of this agent) still
        works exactly as before."""
        self._current_turn_id = turn_id
        self._turn_attached_externally = True

    def _close_open_turn(self, *, status: str, errors: list[str] | None = None) -> None:
        if self._current_turn_id is None:
            return
        turn = self._store.get_turn(self._current_turn_id)
        if turn is not None and turn.ended_at is None:
            self._store.end_turn(self._current_turn_id, status=status, errors=errors)

    # ---- plain pass-throughs: name/system_prompt/model ----

    @property
    def name(self) -> str:
        return self._inner.name

    @name.setter
    def name(self, value: str) -> None:
        self._inner.name = value

    @property
    def system_prompt(self) -> str | None:
        return self._inner.system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str | None) -> None:
        self._inner.system_prompt = value

    @property
    def model(self) -> str | None:
        return self._inner.model

    @model.setter
    def model(self, value: str | None) -> None:
        self._inner.model = value

    # ---- tools ----

    def add_tool(self, tool: Any) -> Any:
        return self._inner.add_tool(tool)

    def register_tool(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.register_tool(*args, **kwargs)

    def get_tool(self, name: str) -> Any:
        return self._inner.get_tool(name)

    def remove_tool(self, name: str) -> Any:
        return self._inner.remove_tool(name)

    def update_tool(self, name: str, **changes: Any) -> Any:
        return self._inner.update_tool(name, **changes)

    @property
    def tools(self) -> list[Any]:
        return self._inner.tools

    # ---- skills ----

    def add_skill(self, skill: Any) -> Any:
        return self._inner.add_skill(skill)

    def get_skill(self, name: str) -> Any:
        return self._inner.get_skill(name)

    def remove_skill(self, name: str) -> Any:
        return self._inner.remove_skill(name)

    def update_skill(self, name: str, **changes: Any) -> Any:
        return self._inner.update_skill(name, **changes)

    @property
    def skills(self) -> list[Any]:
        return self._inner.skills

    # ---- properties ----

    def set_property(self, key: str, value: Any) -> None:
        self._inner.set_property(key, value)

    def get_property(self, key: str, default: Any = None) -> Any:
        return self._inner.get_property(key, default)

    def remove_property(self, key: str) -> Any:
        return self._inner.remove_property(key)

    @property
    def properties(self) -> dict[str, Any]:
        return self._inner.properties

    # ---- instrumented conversation lifecycle ----

    @property
    def is_connected(self) -> bool:
        return self._inner.is_connected

    async def connect(self) -> None:
        # No session side effects here — the session is owned by the CLI
        # (start_monitoring_session), since it spans more than one
        # connect()/disconnect() cycle (every /reload rebuilds the agent).
        await self._inner.connect()

    async def disconnect(self) -> None:
        self._close_open_turn(
            status=TURN_STATUS_ERROR, errors=["session disconnected before turn completed"]
        )
        await self._inner.disconnect()

    async def send(self, prompt: str) -> None:
        if self._turn_attached_externally:
            # A router already opened this turn and recorded the
            # route_decision event; consume the attachment so the *next*
            # send() (if any) goes back to self-managing its own turn.
            self._turn_attached_externally = False
        else:
            self._close_open_turn(
                status=TURN_STATUS_ERROR,
                errors=["superseded by a new turn before completion"],
            )
            turn_id = uuid.uuid4().hex
            self._store.start_turn(Turn(id=turn_id, session_id=self._session_id))
            self._current_turn_id = turn_id

        self._store.append_event(
            SessionEvent(
                session_id=self._session_id,
                turn_id=self._current_turn_id,
                kind=EVENT_KIND_USER_MESSAGE,
                data={"text": prompt},
            )
        )
        await self._inner.send(prompt)

    async def receive(self) -> AsyncIterator[Any]:
        async for message in self._inner.receive():
            outcome = self._turn_outcome_extractor(message)
            if outcome is not None and self._current_turn_id is not None:
                self._store.end_turn(self._current_turn_id, **outcome)
            elif self._current_turn_id is not None:
                for kind, data in self._message_recorder(message):
                    self._store.append_event(
                        SessionEvent(
                            session_id=self._session_id,
                            turn_id=self._current_turn_id,
                            kind=kind,
                            data=data,
                        )
                    )
            yield message

    async def run(self, prompt: str) -> str:
        # Reimplemented in terms of this wrapper's own connect/send/receive
        # (not `self._inner.run()`) so recording happens regardless of
        # entry point.
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


class MonitoredRouter:
    """Wraps a `RuleBasedRouter`, opening a `Turn` for *every* event it
    routes — the originating event always lands in the session, no matter
    how it's handled or what type it is. Structurally implements
    `Router`'s single `route(event)` method without formally subclassing
    it, since `crystalline.events.router` already does an absolute
    `from crystalline.project import Project` — this module also importing
    `crystalline.events` at the top level would make the two packages
    genuinely circularly dependent, not just import-order-fragile. `Event`/
    `RuleBasedRouter` are deferred to `TYPE_CHECKING` (safe at runtime:
    `from __future__ import annotations` makes every annotation in this
    file a string); `AgentHandoff` is imported locally inside `route()`,
    the one place it's actually constructed.
    """

    def __init__(self, inner: RuleBasedRouter, store: SessionStore, *, session_id: str) -> None:
        self._inner = inner
        self._store = store
        self._session_id = session_id

    async def route(self, event: Event) -> RouteResult:
        from crystalline.events import AgentHandoff

        turn_id = uuid.uuid4().hex
        self._store.start_turn(Turn(id=turn_id, session_id=self._session_id))

        tool = self._inner.resolve(event)
        self._store.append_event(
            SessionEvent(
                session_id=self._session_id,
                turn_id=turn_id,
                kind=EVENT_KIND_ROUTE_DECISION,
                data={
                    "event_type": event.type,
                    "decision": "agent_handoff" if tool is None else "direct_dispatch",
                    "basis": "exact_type_match",
                    "matched": tool.name if tool is not None else None,
                },
            )
        )

        if tool is None:
            # Turn stays open — whoever receives this AgentHandoff is
            # responsible for continuing it (see MonitoredAgent.continue_turn).
            return AgentHandoff(event, turn_id=turn_id)

        self._store.append_event(
            SessionEvent(
                session_id=self._session_id,
                turn_id=turn_id,
                kind=EVENT_KIND_TOOL_CALL,
                data={"name": tool.name, "input": to_jsonable(event.payload)},
            )
        )
        try:
            data = tool.input_model.model_validate(event.payload)
            if event.token is not None:
                from crystalline.security import bind_token

                with bind_token(event.token):
                    result = await tool.invoke(data)
            else:
                result = await tool.invoke(data)
        except Exception as exc:
            self._store.append_event(
                SessionEvent(
                    session_id=self._session_id,
                    turn_id=turn_id,
                    kind=EVENT_KIND_TOOL_RESULT,
                    data={"error": str(exc)},
                )
            )
            self._store.end_turn(turn_id, status=TURN_STATUS_ERROR, errors=[str(exc)])
            raise

        self._store.append_event(
            SessionEvent(
                session_id=self._session_id,
                turn_id=turn_id,
                kind=EVENT_KIND_TOOL_RESULT,
                data={"result": to_jsonable(result)},
            )
        )
        self._store.end_turn(turn_id, status=TURN_STATUS_COMPLETED)
        return result


def build_router(project: Project, *, session_id: str | None = None) -> Any:
    """`RuleBasedRouter(project)`, wrapped in a `MonitoredRouter` if
    `project.monitoring_store` (and a `session_id` to record into) are
    both available — mirrors `build_agent`'s conditional `MonitoredAgent`
    wrapping exactly."""
    from crystalline.events import RuleBasedRouter

    router = RuleBasedRouter(project)
    if project.monitoring_store is not None and session_id is not None:
        return MonitoredRouter(router, project.monitoring_store, session_id=session_id)
    return router
