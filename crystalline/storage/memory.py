"""In-memory `Storage` backend: a dict of dicts, gone when the process exits."""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from .base import Storage

T = TypeVar("T", bound=BaseModel)


class InMemoryStorage(Storage):
    def __init__(self) -> None:
        self._tables: dict[str, dict[Any, BaseModel]] = {}

    def _table(self, model: type[BaseModel]) -> dict[Any, BaseModel]:
        return self._tables.setdefault(self._collection_name(model), {})

    def create(self, instance: T) -> T:
        model = type(instance)
        self._require_id_field(model)
        id_ = self._id_of(instance)
        table = self._table(model)
        if id_ in table:
            raise ValueError(f"{model.__name__} record with id={id_!r} already exists")
        table[id_] = instance
        return instance

    def get(self, model: type[T], record_id: Any) -> T | None:
        return self._table(model).get(record_id)  # type: ignore[return-value]

    def update(self, model: type[T], record_id: Any, **changes: Any) -> T:
        table = self._table(model)
        existing = table.get(record_id)
        if existing is None:
            raise KeyError(f"No {model.__name__} record with id={record_id!r}")
        updated = self._apply_changes(existing, changes)  # type: ignore[arg-type]
        table[record_id] = updated
        return updated  # type: ignore[return-value]

    def delete(self, model: type[T], record_id: Any) -> bool:
        return self._table(model).pop(record_id, None) is not None

    def list(self, model: type[T], **filters: Any) -> list[T]:
        records = list(self._table(model).values())
        if filters:
            records = [
                r for r in records if all(getattr(r, k, None) == v for k, v in filters.items())
            ]
        return records  # type: ignore[return-value]
