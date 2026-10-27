"""SQLite-backed `Storage`.

Each model type gets its own table, storing records as `id` + a JSON blob
of the full model (`model.model_dump_json()` / `model.model_validate_json()`).
That sidesteps mapping every possible field type (lists, nested models,
dicts, ...) onto SQL columns — the trade-off is that `list(**filters)`
filters in Python after loading all rows of that type, not in SQL. Fine
for a first implementation; revisit if a project's data outgrows it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from .base import Storage

T = TypeVar("T", bound=BaseModel)


class SQLiteStorage(Storage):
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._path = str(path)
        self._conn = sqlite3.connect(self._path)
        self._known_tables: set[str] = set()

    @property
    def path(self) -> str:
        return self._path

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SQLiteStorage:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def _ensure_table(self, model: type[BaseModel]) -> str:
        table = self._collection_name(model)
        if table not in self._known_tables:
            self._conn.execute(
                f'CREATE TABLE IF NOT EXISTS "{table}" (id TEXT PRIMARY KEY, data TEXT NOT NULL)'
            )
            self._conn.commit()
            self._known_tables.add(table)
        return table

    def create(self, instance: T) -> T:
        model = type(instance)
        self._require_id_field(model)
        id_ = self._id_of(instance)
        table = self._ensure_table(model)
        exists = self._conn.execute(
            f'SELECT 1 FROM "{table}" WHERE id = ?', (str(id_),)
        ).fetchone()
        if exists:
            raise ValueError(f"{model.__name__} record with id={id_!r} already exists")
        self._conn.execute(
            f'INSERT INTO "{table}" (id, data) VALUES (?, ?)',
            (str(id_), instance.model_dump_json()),
        )
        self._conn.commit()
        return instance

    def get(self, model: type[T], record_id: Any) -> T | None:
        table = self._ensure_table(model)
        row = self._conn.execute(
            f'SELECT data FROM "{table}" WHERE id = ?', (str(record_id),)
        ).fetchone()
        return model.model_validate_json(row[0]) if row else None

    def update(self, model: type[T], record_id: Any, **changes: Any) -> T:
        existing = self.get(model, record_id)
        if existing is None:
            raise KeyError(f"No {model.__name__} record with id={record_id!r}")
        updated = self._apply_changes(existing, changes)
        table = self._ensure_table(model)
        self._conn.execute(
            f'UPDATE "{table}" SET data = ? WHERE id = ?',
            (updated.model_dump_json(), str(record_id)),
        )
        self._conn.commit()
        return updated

    def delete(self, model: type[T], record_id: Any) -> bool:
        table = self._ensure_table(model)
        cursor = self._conn.execute(f'DELETE FROM "{table}" WHERE id = ?', (str(record_id),))
        self._conn.commit()
        return cursor.rowcount > 0

    def list(self, model: type[T], **filters: Any) -> list[T]:
        table = self._ensure_table(model)
        rows = self._conn.execute(f'SELECT data FROM "{table}" ORDER BY rowid').fetchall()
        records = [model.model_validate_json(row[0]) for row in rows]
        if filters:
            records = [
                r for r in records if all(getattr(r, k, None) == v for k, v in filters.items())
            ]
        return records
