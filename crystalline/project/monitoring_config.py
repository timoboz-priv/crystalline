"""Build/describe a project's monitoring `SessionStore` from a
declarative config.

Mirrors `crystalline.project.storage`'s relationship to
`crystalline.storage`: a project file's `monitoring:` section is just
`{type: <backend>, ...}`, with everything besides `type` passed through
as keyword arguments to that backend's constructor (e.g. `path` for
`sqlite`). Unlike storage, there's no sensible always-on default — a
project with no `monitoring:` section simply isn't monitored, so `None`
(not an in-memory store) is what an absent config means.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from crystalline.monitoring import SessionStore, SQLiteSessionStore

MonitoringStoreFactory = Callable[..., SessionStore]

_BACKENDS: dict[str, MonitoringStoreFactory] = {
    "sqlite": lambda **properties: SQLiteSessionStore(**properties),
}


def register_monitoring_backend(name: str, factory: MonitoringStoreFactory) -> None:
    """Make `build_monitoring_store`/project files able to use
    `{"type": name, ...}`."""
    _BACKENDS[name] = factory


def build_monitoring_store(config: dict[str, Any] | None) -> SessionStore | None:
    """Build a `SessionStore` from `{"type": "sqlite", "path": "...", ...}`.
    `None` (monitoring disabled) when `config` is `None`."""
    if config is None:
        return None
    config = dict(config)
    backend_type = config.pop("type", "sqlite")
    factory = _BACKENDS.get(backend_type)
    if factory is None:
        raise ValueError(f"Unknown monitoring backend type: {backend_type!r}")
    return factory(**config)


def describe_monitoring_store(
    store: SessionStore | None, *, base_dir: Path | None = None
) -> dict[str, Any] | None:
    """Inverse of `build_monitoring_store`, for saving a project back out.
    `base_dir` re-relativizes `path` the same way `crystalline.project.
    storage.describe_storage` does, for the same round-tripping reason."""
    if store is None:
        return None
    if isinstance(store, SQLiteSessionStore):
        path = store.path
        if base_dir is not None and path != ":memory:":
            absolute = Path(path)
            if absolute.is_absolute() and absolute.is_relative_to(base_dir):
                path = str(absolute.relative_to(base_dir))
        return {"type": "sqlite", "path": path}
    raise ValueError(f"Cannot describe unknown monitoring backend: {store!r}")
