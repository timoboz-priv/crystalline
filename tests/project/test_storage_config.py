from pathlib import Path

import pytest

from crystalline.project.storage import (
    build_storage,
    describe_storage,
    register_storage_backend,
    resolve_storage_paths,
)
from crystalline.storage import InMemoryStorage, SQLiteStorage, Storage


def test_build_storage_defaults_to_memory():
    storage = build_storage(None)
    assert isinstance(storage, InMemoryStorage)


def test_build_storage_memory_explicit():
    storage = build_storage({"type": "memory"})
    assert isinstance(storage, InMemoryStorage)


def test_build_storage_sqlite():
    storage = build_storage({"type": "sqlite", "path": ":memory:"})
    assert isinstance(storage, SQLiteStorage)
    assert storage.path == ":memory:"
    storage.close()


def test_build_storage_unknown_type_raises():
    with pytest.raises(ValueError):
        build_storage({"type": "nope"})


def test_describe_storage_round_trips():
    memory = InMemoryStorage()
    assert describe_storage(memory) == {"type": "memory"}

    sqlite = SQLiteStorage(":memory:")
    assert describe_storage(sqlite) == {"type": "sqlite", "path": ":memory:"}
    sqlite.close()


def test_resolve_storage_paths_relative(tmp_path):
    config = {"type": "sqlite", "path": "data.db"}
    resolved = resolve_storage_paths(config, tmp_path)
    assert resolved["path"] == str(tmp_path / "data.db")


def test_resolve_storage_paths_absolute_untouched(tmp_path):
    absolute = str(tmp_path / "data.db")
    config = {"type": "sqlite", "path": absolute}
    resolved = resolve_storage_paths(config, Path("/somewhere/else"))
    assert resolved["path"] == absolute


def test_resolve_storage_paths_memory_sentinel_untouched():
    config = {"type": "sqlite", "path": ":memory:"}
    resolved = resolve_storage_paths(config, Path("/anywhere"))
    assert resolved["path"] == ":memory:"


def test_register_storage_backend():
    calls = []

    class FakeStorage(Storage):
        def create(self, instance):
            raise NotImplementedError

        def get(self, model, record_id):
            raise NotImplementedError

        def update(self, model, record_id, **changes):
            raise NotImplementedError

        def delete(self, model, record_id):
            raise NotImplementedError

        def list(self, model, **filters):
            raise NotImplementedError

    def factory(**properties):
        calls.append(properties)
        return FakeStorage()

    # "fake" is a throwaway name no other test/code uses, so leaving it
    # registered in the module-level registry afterwards is harmless.
    register_storage_backend("fake", factory)
    storage = build_storage({"type": "fake", "flavor": "test"})
    assert isinstance(storage, FakeStorage)
    assert calls == [{"flavor": "test"}]


def test_register_storage_backend_with_describe_round_trips():
    class FakeDescribableStorage(Storage):
        def __init__(self, flavor: str) -> None:
            self.flavor = flavor

        def create(self, instance):
            raise NotImplementedError

        def get(self, model, record_id):
            raise NotImplementedError

        def update(self, model, record_id, **changes):
            raise NotImplementedError

        def delete(self, model, record_id):
            raise NotImplementedError

        def list(self, model, **filters):
            raise NotImplementedError

    # "fake_describable" is a throwaway name no other test/code uses, so
    # leaving it registered in the module-level registry afterwards is
    # harmless.
    register_storage_backend(
        "fake_describable",
        lambda **properties: FakeDescribableStorage(**properties),
        storage_cls=FakeDescribableStorage,
        describe=lambda storage, base_dir: {"flavor": storage.flavor},
    )
    storage = build_storage({"type": "fake_describable", "flavor": "test"})
    assert describe_storage(storage) == {"type": "fake_describable", "flavor": "test"}


def test_describe_storage_unregistered_backend_raises():
    class UnregisteredStorage(Storage):
        def create(self, instance):
            raise NotImplementedError

        def get(self, model, record_id):
            raise NotImplementedError

        def update(self, model, record_id, **changes):
            raise NotImplementedError

        def delete(self, model, record_id):
            raise NotImplementedError

        def list(self, model, **filters):
            raise NotImplementedError

    with pytest.raises(ValueError):
        describe_storage(UnregisteredStorage())
