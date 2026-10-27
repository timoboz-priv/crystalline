"""`SessionStore`: storage-agnostic contract for persisting sessions.

Sync, not async — matching `crystalline.storage.Storage`'s convention
(this is a storage layer, like that one), not the async convention of
`crystalline.tools`/`crystalline.agents`/`crystalline.events.Router`
(which are I/O-bound on an external model, not on local persistence).

Deliberately not built on `crystalline.storage.Storage`: that contract is
generic id-based CRUD with exact-match filtering only, and this needs
ordered appends plus a project/time-range query — a different enough
shape that forcing it through `Storage`'s id+JSON-blob model would fight
the abstraction rather than reuse it. This also matches the architecture
doc's dependency table: `crystalline.monitoring` depends on `events`
only, not `storage`.

Note: `claude_agent_sdk` exports its own, unrelated `SessionStore` (for
the SDK's own session-resumption feature) — no code collision, since
they're in different namespaces, but don't confuse the two. Same
situation as `crystalline.agents.Skill` vs `crystalline.skills.Skill`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from .session import Session, SessionEvent, Turn


class SessionStore(ABC):
    # ---- sessions ----

    @abstractmethod
    def start_session(self, session: Session) -> Session:
        """Persist a new session. Raises `ValueError` if its id is
        already in use."""

    @abstractmethod
    def end_session(self, session_id: str, *, ended_at: datetime | None = None) -> Session:
        """Mark a session ended (`ended_at` defaults to now) and return
        the updated session. Raises `KeyError` if no such session exists.
        """

    @abstractmethod
    def get_session(self, session_id: str) -> Session | None:
        """Return the session with this id, or None if there isn't one."""

    @abstractmethod
    def list_sessions(
        self,
        *,
        project_name: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[Session]:
        """Sessions matching all given filters (`since`/`until` bound
        `started_at`), ordered oldest-first. No filters: every session."""

    # ---- turns ----

    @abstractmethod
    def start_turn(self, turn: Turn) -> Turn:
        """Persist a new turn. Raises `ValueError` if its id is already
        in use, `KeyError` if its session doesn't exist."""

    @abstractmethod
    def end_turn(
        self,
        turn_id: str,
        *,
        status: str,
        ended_at: datetime | None = None,
        duration_ms: int | None = None,
        total_cost_usd: float | None = None,
        usage: dict[str, Any] | None = None,
        result: str | None = None,
        errors: list[str] | None = None,
    ) -> Turn:
        """Record a turn's outcome (`ended_at` defaults to now) and
        return the updated turn. Raises `KeyError` if no such turn
        exists."""

    @abstractmethod
    def get_turn(self, turn_id: str) -> Turn | None:
        """Return the turn with this id, or None if there isn't one."""

    @abstractmethod
    def list_turns(self, session_id: str) -> list[Turn]:
        """Every turn for one session, oldest first."""

    # ---- events ----

    @abstractmethod
    def append_event(self, event: SessionEvent) -> SessionEvent:
        """Append one event to its turn, in arrival order."""

    @abstractmethod
    def list_events(
        self, *, turn_id: str | None = None, session_id: str | None = None
    ) -> list[SessionEvent]:
        """Events in arrival order, for one turn (`turn_id`) or every
        turn in one session (`session_id`). Exactly one of the two must
        be given."""
