"""In-memory `Storage` backend: a dict of dicts, gone when the process exits."""

from __future__ import annotations

from typing import Any, TypeVar, cast

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
        # `_table(model)` is `dict[Any, BaseModel]` (one shared value type
        # across every model stored this way), but every value actually
        # stored under `model`'s collection name is a `T` — `model` is
        # what the caller used to select this bucket in the first place.
        return cast("T | None", self._table(model).get(record_id))

    def update(self, model: type[T], record_id: Any, **changes: Any) -> T:
        table = self._table(model)
        existing = table.get(record_id)
        if existing is None:
            raise KeyError(f"No {model.__name__} record with id={record_id!r}")
        updated = self._apply_changes(cast(T, existing), changes)
        table[record_id] = updated
        return updated

    def delete(self, model: type[T], record_id: Any) -> bool:
        return self._table(model).pop(record_id, None) is not None

    def list(self, model: type[T], **filters: Any) -> list[T]:
        records = list(self._table(model).values())
        if filters:
            records = [
                r for r in records if all(getattr(r, k, None) == v for k, v in filters.items())
            ]
        return cast("list[T]", records)
