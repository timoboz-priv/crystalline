"""Abstract storage: generic CRUD for any Pydantic model.

Not tied to `crystalline.schema` — any `pydantic.BaseModel` with an `id`
field works, which is also what makes it a natural fit for the types in a
project's `SchemaRegistry` later (`crystalline.tools` will build one MCP
server per registered type, with tool functions calling through here).

Convention: a model used with `Storage` must declare an `id` field, used
as the record's primary key. Records are bucketed by `model.__name__`, so
a single `Storage` instance should be scoped to one schema namespace
(e.g. one project) — two unrelated types sharing a name would collide.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Protocol, TypeVar, cast

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class HasId(Protocol):
    """Structural shape of a `BaseModel` that actually has an `id` field.

    `T` stays bound to plain `BaseModel` (not this protocol) because
    `Storage` is deliberately usable with *any* Pydantic model, not just
    ones that subclass a dedicated base — the `id`-field requirement is a
    runtime contract (`_require_id_field`), not something expressible as
    a static bound without forcing that subclassing. `HasId` exists so the
    handful of places that actually read `.id` off a `T` can say so via a
    narrow, explicit `cast` instead of a blanket `# type: ignore` on the
    whole line.
    """

    id: Any


class Storage(ABC):
    """Generic CRUD storage for Pydantic models identified by an `id` field."""

    @classmethod
    def _collection_name(cls, model: type[BaseModel]) -> str:
        name = model.__name__
        if not _IDENTIFIER_RE.match(name):
            raise ValueError(f"Invalid storage collection name: {name!r}")
        return name

    @staticmethod
    def _require_id_field(model: type[BaseModel]) -> None:
        if "id" not in model.model_fields:
            raise ValueError(
                f"{model.__name__} has no 'id' field; Storage requires one"
            )

    @staticmethod
    def _id_of(instance: BaseModel) -> Any:
        return cast(HasId, instance).id

    @classmethod
    def _apply_changes(cls, existing: T, changes: dict[str, Any]) -> T:
        """Merge `changes` into `existing` and re-validate the result."""
        if "id" in changes and changes["id"] != cls._id_of(existing):
            raise ValueError("Cannot change a record's id via update()")
        merged = {**existing.model_dump(), **changes}
        return type(existing).model_validate(merged)

    @abstractmethod
    def create(self, instance: T) -> T:
        """Insert a new record. Raises `ValueError` if its id is already in use."""

    @abstractmethod
    def get(self, model: type[T], record_id: Any) -> T | None:
        """Return the record with this id, or None if there isn't one."""

    @abstractmethod
    def update(self, model: type[T], record_id: Any, **changes: Any) -> T:
        """Apply a partial update and return the new record.

        `record_id` is a positional parameter (not `id`) specifically so
        `id` remains free to appear in `**changes`, which `_apply_changes`
        then rejects with a clear error instead of a `TypeError` from
        argument collision.

        Raises `KeyError` if no record with this id exists.
        """

    @abstractmethod
    def delete(self, model: type[T], record_id: Any) -> bool:
        """Delete the record with this id. Returns whether it existed."""

    @abstractmethod
    def list(self, model: type[T], **filters: Any) -> list[T]:
        """Return records of this type whose fields match `filters`
        exactly (no filters: return everything). Order is unspecified
        beyond "backends return records in a consistent, stable order".
        """
