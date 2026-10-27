"""SQLite-backed `SessionStore`.

Own schema (three tables: `sessions`, `turns`, `session_events`), not
built on `crystalline.storage.SQLiteStorage` — see `store.py`'s
docstring for why.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .session import Session, SessionEvent, Turn, _utcnow
from .store import SessionStore


def _dump_time(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _load_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _dump_json(value: Any) -> str | None:
    return json.dumps(value) if value is not None else None


def _load_json(value: str | None) -> Any:
    return json.loads(value) if value is not None else None


class SQLiteSessionStore(SessionStore):
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._path = str(path)
        self._conn = sqlite3.connect(self._path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                principal TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                metadata TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS sessions_project_started "
            "ON sessions (project_name, started_at)"
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS turns (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                duration_ms INTEGER,
                total_cost_usd REAL,
                usage TEXT,
                result TEXT,
                errors TEXT,
                metadata TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS turns_session ON turns (session_id)"
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_events (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                parent_event_id TEXT,
                kind TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS session_events_turn ON session_events (turn_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS session_events_session "
            "ON session_events (session_id)"
        )
        self._conn.commit()

    @property
    def path(self) -> str:
        return self._path

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SQLiteSessionStore:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # ---- row <-> model ----

    def _row_to_session(self, row: tuple[Any, ...]) -> Session:
        id_, project_name, principal, started_at, ended_at, metadata = row
        return Session(
            id=id_,
            project_name=project_name,
            principal=principal,
            started_at=_load_time(started_at),
            ended_at=_load_time(ended_at),
            metadata=_load_json(metadata) or {},
        )

    def _row_to_turn(self, row: tuple[Any, ...]) -> Turn:
        (
            id_,
            session_id,
            status,
            started_at,
            ended_at,
            duration_ms,
            total_cost_usd,
            usage,
            result,
            errors,
            metadata,
        ) = row
        return Turn(
            id=id_,
            session_id=session_id,
            status=status,
            started_at=_load_time(started_at),
            ended_at=_load_time(ended_at),
            duration_ms=duration_ms,
            total_cost_usd=total_cost_usd,
            usage=_load_json(usage),
            result=result,
            errors=_load_json(errors),
            metadata=_load_json(metadata) or {},
        )

    def _row_to_event(self, row: tuple[Any, ...]) -> SessionEvent:
        session_id, turn_id, parent_event_id, kind, data, id_, created_at = row
        return SessionEvent(
            session_id=session_id,
            turn_id=turn_id,
            parent_event_id=parent_event_id,
            kind=kind,
            data=_load_json(data) or {},
            id=id_,
            created_at=_load_time(created_at),
        )

    # ---- sessions ----

    def start_session(self, session: Session) -> Session:
        exists = self._conn.execute(
            "SELECT 1 FROM sessions WHERE id = ?", (session.id,)
        ).fetchone()
        if exists:
            raise ValueError(f"Session with id={session.id!r} already exists")
        self._conn.execute(
            "INSERT INTO sessions (id, project_name, principal, started_at, "
            "ended_at, metadata) VALUES (?, ?, ?, ?, ?, ?)",
            (
                session.id,
                session.project_name,
                session.principal,
                _dump_time(session.started_at),
                _dump_time(session.ended_at),
                _dump_json(session.metadata),
            ),
        )
        self._conn.commit()
        return session

    def end_session(self, session_id: str, *, ended_at: datetime | None = None) -> Session:
        existing = self.get_session(session_id)
        if existing is None:
            raise KeyError(f"No session with id={session_id!r}")
        updated = existing.model_copy(update={"ended_at": ended_at or _utcnow()})
        self._conn.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ?",
            (_dump_time(updated.ended_at), session_id),
        )
        self._conn.commit()
        return updated

    def get_session(self, session_id: str) -> Session | None:
        row = self._conn.execute(
            "SELECT id, project_name, principal, started_at, ended_at, metadata "
            "FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return self._row_to_session(row) if row else None

    def list_sessions(
        self,
        *,
        project_name: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[Session]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_name is not None:
            clauses.append("project_name = ?")
            params.append(project_name)
        if since is not None:
            clauses.append("started_at >= ?")
            params.append(_dump_time(since))
        if until is not None:
            clauses.append("started_at <= ?")
            params.append(_dump_time(until))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            "SELECT id, project_name, principal, started_at, ended_at, metadata "
            f"FROM sessions {where} ORDER BY started_at",
            params,
        ).fetchall()
        return [self._row_to_session(row) for row in rows]

    # ---- turns ----

    def start_turn(self, turn: Turn) -> Turn:
        if self.get_session(turn.session_id) is None:
            raise KeyError(f"No session with id={turn.session_id!r}")
        exists = self._conn.execute(
            "SELECT 1 FROM turns WHERE id = ?", (turn.id,)
        ).fetchone()
        if exists:
            raise ValueError(f"Turn with id={turn.id!r} already exists")
        self._conn.execute(
            "INSERT INTO turns (id, session_id, status, started_at, ended_at, "
            "duration_ms, total_cost_usd, usage, result, errors, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                turn.id,
                turn.session_id,
                turn.status,
                _dump_time(turn.started_at),
                _dump_time(turn.ended_at),
                turn.duration_ms,
                turn.total_cost_usd,
                _dump_json(turn.usage),
                turn.result,
                _dump_json(turn.errors),
                _dump_json(turn.metadata),
            ),
        )
        self._conn.commit()
        return turn

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
        existing = self.get_turn(turn_id)
        if existing is None:
            raise KeyError(f"No turn with id={turn_id!r}")
        updated = existing.model_copy(
            update={
                "status": status,
                "ended_at": ended_at or _utcnow(),
                "duration_ms": duration_ms,
                "total_cost_usd": total_cost_usd,
                "usage": usage,
                "result": result,
                "errors": errors,
            }
        )
        self._conn.execute(
            "UPDATE turns SET status = ?, ended_at = ?, duration_ms = ?, "
            "total_cost_usd = ?, usage = ?, result = ?, errors = ? WHERE id = ?",
            (
                updated.status,
                _dump_time(updated.ended_at),
                updated.duration_ms,
                updated.total_cost_usd,
                _dump_json(updated.usage),
                updated.result,
                _dump_json(updated.errors),
                turn_id,
            ),
        )
        self._conn.commit()
        return updated

    def get_turn(self, turn_id: str) -> Turn | None:
        row = self._conn.execute(
            "SELECT id, session_id, status, started_at, ended_at, duration_ms, "
            "total_cost_usd, usage, result, errors, metadata FROM turns WHERE id = ?",
            (turn_id,),
        ).fetchone()
        return self._row_to_turn(row) if row else None

    def list_turns(self, session_id: str) -> list[Turn]:
        rows = self._conn.execute(
            "SELECT id, session_id, status, started_at, ended_at, duration_ms, "
            "total_cost_usd, usage, result, errors, metadata FROM turns "
            "WHERE session_id = ? ORDER BY started_at",
            (session_id,),
        ).fetchall()
        return [self._row_to_turn(row) for row in rows]

    # ---- events ----

    def append_event(self, event: SessionEvent) -> SessionEvent:
        if self.get_turn(event.turn_id) is None:
            raise KeyError(f"No turn with id={event.turn_id!r}")
        exists = self._conn.execute(
            "SELECT 1 FROM session_events WHERE id = ?", (event.id,)
        ).fetchone()
        if exists:
            raise ValueError(f"Session event with id={event.id!r} already exists")
        self._conn.execute(
            "INSERT INTO session_events (id, session_id, turn_id, parent_event_id, "
            "kind, data, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event.id,
                event.session_id,
                event.turn_id,
                event.parent_event_id,
                event.kind,
                _dump_json(event.data),
                _dump_time(event.created_at),
            ),
        )
        self._conn.commit()
        return event

    def list_events(
        self, *, turn_id: str | None = None, session_id: str | None = None
    ) -> list[SessionEvent]:
        if (turn_id is None) == (session_id is None):
            raise ValueError("Pass exactly one of turn_id or session_id")
        column = "turn_id" if turn_id is not None else "session_id"
        value = turn_id if turn_id is not None else session_id
        rows = self._conn.execute(
            "SELECT session_id, turn_id, parent_event_id, kind, data, id, created_at "
            f"FROM session_events WHERE {column} = ? ORDER BY rowid",
            (value,),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]
