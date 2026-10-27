import pytest

from crystalline.monitoring import SQLiteSessionStore
from crystalline.project.monitoring_config import (
    build_monitoring_store,
    describe_monitoring_store,
    register_monitoring_backend,
)


def test_build_monitoring_store_none_config_means_disabled():
    assert build_monitoring_store(None) is None


def test_build_monitoring_store_sqlite(tmp_path):
    store = build_monitoring_store({"type": "sqlite", "path": str(tmp_path / "m.db")})
    try:
        assert isinstance(store, SQLiteSessionStore)
        assert store.path == str(tmp_path / "m.db")
    finally:
        store.close()


def test_build_monitoring_store_unknown_type_raises():
    with pytest.raises(ValueError):
        build_monitoring_store({"type": "nope"})


def test_describe_monitoring_store_none():
    assert describe_monitoring_store(None) is None


def test_describe_monitoring_store_sqlite(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "m.db"))
    try:
        assert describe_monitoring_store(store) == {
            "type": "sqlite",
            "path": str(tmp_path / "m.db"),
        }
    finally:
        store.close()


def test_describe_monitoring_store_relativizes_against_base_dir(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "m.db"))
    try:
        assert describe_monitoring_store(store, base_dir=tmp_path) == {
            "type": "sqlite",
            "path": "m.db",
        }
    finally:
        store.close()


def test_register_monitoring_backend():
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        return SQLiteSessionStore(":memory:")

    register_monitoring_backend("fake", factory)
    try:
        store = build_monitoring_store({"type": "fake", "extra": 1})
        assert calls == [{"extra": 1}]
    finally:
        store.close()
