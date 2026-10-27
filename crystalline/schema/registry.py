"""Registry mapping string names to data types for a project.

Tools, skills, events, and config-file-driven wiring all reference a
project's types by name rather than by Python import, so the registry
protects name collisions by default instead of silently overwriting a
previous registration (unlike the simpler dict-overwrite CRUD used for
agent tools/skills, where a later `add` intentionally wins).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import overload

from pydantic import BaseModel


class SchemaRegistry:
    """Name -> Pydantic model registry for a project's data types."""

    def __init__(self) -> None:
        self._types: dict[str, type[BaseModel]] = {}

    @overload
    def register(
        self, model: type[BaseModel], *, name: str | None = None, replace: bool = False
    ) -> type[BaseModel]: ...

    @overload
    def register(
        self, model: None = None, *, name: str | None = None, replace: bool = False
    ) -> Callable[[type[BaseModel]], type[BaseModel]]: ...

    def register(
        self,
        model: type[BaseModel] | None = None,
        *,
        name: str | None = None,
        replace: bool = False,
    ) -> type[BaseModel] | Callable[[type[BaseModel]], type[BaseModel]]:
        """Register `model` under `name` (defaults to `model.__name__`).

        Can be used directly (`registry.register(Foo)`) or as a decorator
        (`@registry.register()` or `@registry.register(name="Foo")`).
        Raises `ValueError` if `name` is already registered to a
        different model, unless `replace=True`.
        """
        if model is None:

            def decorator(m: type[BaseModel]) -> type[BaseModel]:
                self.register(m, name=name, replace=replace)
                return m

            return decorator

        key = name or model.__name__
        existing = self._types.get(key)
        if existing is not None and existing is not model and not replace:
            raise ValueError(
                f"Schema type {key!r} is already registered to {existing!r}; "
                "pass replace=True to overwrite"
            )
        self._types[key] = model
        return model

    def get(self, name: str) -> type[BaseModel] | None:
        return self._types.get(name)

    def remove(self, name: str) -> type[BaseModel] | None:
        return self._types.pop(name, None)

    @property
    def types(self) -> dict[str, type[BaseModel]]:
        return dict(self._types)

    def __contains__(self, name: str) -> bool:
        return name in self._types

    def __iter__(self) -> Iterator[str]:
        return iter(self._types)

    def __len__(self) -> int:
        return len(self._types)
