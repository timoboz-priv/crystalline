"""Build/describe a project's `Storage` from a declarative config.

A project file's `storage` section is just `{type: <backend>, ...}`,
where everything besides `type` is passed through as keyword arguments to
that backend's constructor (e.g. `path` for `sqlite`). This module is the
adapter between that config shape and real `crystalline.storage.Storage`
instances — `crystalline.storage` itself has no notion of "backend names"
or project config.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from crystalline.storage import InMemoryStorage, SQLiteStorage, Storage

StorageFactory = Callable[..., Storage]

_BACKENDS: dict[str, StorageFactory] = {
    "memory": lambda **properties: InMemoryStorage(**properties),
    "sqlite": lambda **properties: SQLiteStorage(**properties),
}


def register_storage_backend(name: str, factory: StorageFactory) -> None:
    """Make `build_storage`/project files able to use `{"type": name, ...}`."""
    _BACKENDS[name] = factory


def resolve_storage_paths(config: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """Resolve a relative `path` property against `base_dir` (the project
    file's directory), so a project file's storage path is relative to
    the file, not to wherever the process happens to be run from."""
    config = dict(config)
    path = config.get("path")
    if isinstance(path, str) and path != ":memory:" and not Path(path).is_absolute():
        config["path"] = str(base_dir / path)
    return config


def build_storage(config: dict[str, Any] | None) -> Storage:
    """Build a `Storage` from `{"type": "sqlite", "path": "...", ...}`.
    Defaults to an in-memory backend when `config` is None."""
    if config is None:
        return InMemoryStorage()
    config = dict(config)
    backend_type = config.pop("type", "memory")
    factory = _BACKENDS.get(backend_type)
    if factory is None:
        raise ValueError(f"Unknown storage backend type: {backend_type!r}")
    return factory(**config)


def describe_storage(storage: Storage, base_dir: Path | None = None) -> dict[str, Any]:
    """Inverse of `build_storage`, for saving a project back out.

    `storage.path` is always absolute (`resolve_storage_paths` resolved
    it that way on load) — when `base_dir` (the directory the project
    file is being saved *to*) is given and the path sits under it, write
    it back out relative to `base_dir`, the same convention `load_project`
    reads it with. Without this, round-tripping through save/load would
    silently turn a portable relative `path` into a machine-specific
    absolute one on the first save.
    """
    if isinstance(storage, InMemoryStorage):
        return {"type": "memory"}
    if isinstance(storage, SQLiteStorage):
        path = storage.path
        if base_dir is not None and path != ":memory:":
            absolute = Path(path)
            if absolute.is_absolute() and absolute.is_relative_to(base_dir):
                path = str(absolute.relative_to(base_dir))
        return {"type": "sqlite", "path": path}
    raise ValueError(f"Cannot describe unknown storage backend: {storage!r}")
