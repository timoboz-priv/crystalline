import asyncio

import pytest
from claude_agent_sdk import ResultMessage

from crystalline.agents import Agent as AgentBase
from crystalline.crystallization import (
    CrystallizationContext,
    CrystallizationPlugin,
    CrystallizationProposal,
    CrystallizationRegistry,
    FileChange,
)
from crystalline.monitoring import SQLiteSessionStore
from crystalline.project import Project
from crystalline.project.crystallization_wiring import (
    apply_crystallization,
    run_crystallization,
)

RESULT_MESSAGE = ResultMessage(
    subtype="success",
    duration_ms=100,
    duration_api_ms=80,
    is_error=False,
    num_turns=1,
    session_id="sdk-session",
    stop_reason="end_turn",
    total_cost_usd=0.02,
    usage={"input_tokens": 10},
    result="done",
    errors=None,
)


class _FakeCodegenAgent(AgentBase):
    def __init__(self) -> None:
        super().__init__("fake-codegen")
        self.connected = False

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def send(self, prompt: str) -> None:
        pass

    async def receive(self):
        yield RESULT_MESSAGE

    def describe_message(self, message):
        return []

    async def run(self, prompt: str) -> str:
        raise AssertionError("MonitoredAgent.run() must not delegate to inner.run()")


_PROPOSAL = CrystallizationProposal(
    plugin="session",
    title="Dashboard skill",
    rationale="Chains a few tool calls together.",
    changes=[FileChange(path="skill_dashboard.py", action="create", content="x = 1\n")],
)


class _FakePlugin(CrystallizationPlugin):
    name = "session"

    async def propose(self, ctx: CrystallizationContext) -> CrystallizationProposal | None:
        await ctx.agent.run("analyze this session")
        return _PROPOSAL


class _NothingPlugin(CrystallizationPlugin):
    name = "nothing"

    async def propose(self, ctx: CrystallizationContext) -> CrystallizationProposal | None:
        return None


@pytest.fixture
def project(tmp_path):
    extensions_dir = tmp_path / "extensions"
    extensions_dir.mkdir()
    with SQLiteSessionStore(":memory:") as store:
        p = Project("demo", "0.1.0", monitoring_store=store, extensions_dir=str(extensions_dir))
        from crystalline.monitoring import Session

        store.start_session(Session(id="s1", project_name="demo"))
        yield p


@pytest.fixture
def registry():
    registry = CrystallizationRegistry()
    registry.register(_FakePlugin())
    registry.register(_NothingPlugin())
    return registry


def _agent_factory(_project):
    return _FakeCodegenAgent()


def test_run_crystallization_returns_plugin_proposal_and_rolls_up_cost(project, registry):
    proposal = asyncio.run(
        run_crystallization(
            project,
            session_id="s1",
            mode="session",
            registry=registry,
            agent_factory=_agent_factory,
        )
    )
    assert proposal is _PROPOSAL

    turns = project.monitoring_store.list_turns("s1")
    [turn] = turns
    assert turn.status == "completed"
    assert turn.total_cost_usd == 0.02
    assert turn.metadata == {"kind": "crystallization", "plugin": "session"}


def test_run_crystallization_none_proposal(project, registry):
    proposal = asyncio.run(
        run_crystallization(
            project,
            session_id="s1",
            mode="nothing",
            registry=registry,
            agent_factory=_agent_factory,
        )
    )
    assert proposal is None


def test_run_crystallization_unknown_mode_raises(project, registry):
    with pytest.raises(KeyError):
        asyncio.run(
            run_crystallization(
                project, session_id="s1", mode="bogus", registry=registry
            )
        )


def test_run_crystallization_requires_monitoring(registry):
    project = Project("demo", "0.1.0")
    with pytest.raises(RuntimeError):
        asyncio.run(
            run_crystallization(
                project, session_id="s1", mode="session", registry=registry
            )
        )


def test_run_crystallization_unknown_session_raises(project, registry):
    with pytest.raises(KeyError):
        asyncio.run(
            run_crystallization(
                project,
                session_id="no-such-session",
                mode="session",
                registry=registry,
                agent_factory=_agent_factory,
            )
        )


def test_apply_crystallization_writes_create_modify_delete(project):
    existing = project.extensions_dir
    from pathlib import Path

    Path(existing, "skill_old.py").write_text("old = 1\n")

    proposal = CrystallizationProposal(
        plugin="session",
        title="t",
        rationale="r",
        changes=[
            FileChange(path="skill_new.py", action="create", content="new = 1\n"),
            FileChange(path="skill_old.py", action="modify", content="old = 2\n"),
        ],
    )
    apply_crystallization(project, proposal)
    assert Path(existing, "skill_new.py").read_text() == "new = 1\n"
    assert Path(existing, "skill_old.py").read_text() == "old = 2\n"

    delete_proposal = CrystallizationProposal(
        plugin="session", title="t", rationale="r",
        changes=[FileChange(path="skill_old.py", action="delete")],
    )
    apply_crystallization(project, delete_proposal)
    assert not Path(existing, "skill_old.py").exists()


def test_apply_crystallization_requires_extensions_dir():
    project = Project("demo", "0.1.0")
    proposal = CrystallizationProposal(
        plugin="session", title="t", rationale="r",
        changes=[FileChange(path="skill_x.py", action="create", content="x = 1\n")],
    )
    with pytest.raises(RuntimeError):
        apply_crystallization(project, proposal)


def test_apply_crystallization_rejects_path_escaping_extensions_dir(project):
    proposal = CrystallizationProposal(
        plugin="session", title="t", rationale="r",
        changes=[FileChange(path="../escape.py", action="create", content="x = 1\n")],
    )
    with pytest.raises(ValueError):
        apply_crystallization(project, proposal)
