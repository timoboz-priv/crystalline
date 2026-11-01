from crystalline.crystallization import (
    CrystallizationContext,
    CrystallizationPlugin,
    CrystallizationProposal,
    CrystallizationRegistry,
)


class _FakePlugin(CrystallizationPlugin):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def propose(self, ctx: CrystallizationContext) -> CrystallizationProposal | None:
        return None


def test_register_and_get_by_name():
    registry = CrystallizationRegistry()
    plugin = _FakePlugin("session")
    registry.register(plugin)
    assert registry.get("session") is plugin


def test_get_unknown_mode_returns_none():
    registry = CrystallizationRegistry()
    assert registry.get("nope") is None


def test_iteration_and_len():
    registry = CrystallizationRegistry()
    registry.register(_FakePlugin("a"))
    registry.register(_FakePlugin("b"))
    assert len(registry) == 2
    assert {p.name for p in registry} == {"a", "b"}


def test_registering_same_name_replaces():
    registry = CrystallizationRegistry()
    registry.register(_FakePlugin("session"))
    second = _FakePlugin("session")
    registry.register(second)
    assert registry.get("session") is second
    assert len(registry) == 1
