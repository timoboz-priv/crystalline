from crystalline.agents import Agent, ClaudeCodeAgent
from crystalline.monitoring import SQLiteSessionStore
from crystalline.project import Project, build_agent, build_agent_config, describe_agent_config
from crystalline.project.agent import register_agent_backend
from crystalline.project.fields import build_model_from_field_spec
from crystalline.project.monitoring_wiring import MonitoredAgent


def test_build_agent_config_defaults_to_claude_code():
    config = build_agent_config(None)
    assert config == {"type": "claude_code"}


def test_build_agent_config_passthrough():
    config = build_agent_config({"type": "claude_code", "model": "claude-sonnet-5-5"})
    assert config == {"type": "claude_code", "model": "claude-sonnet-5-5"}


def test_describe_agent_config_round_trips():
    config = {"type": "claude_code", "model": "claude-sonnet-5-5"}
    assert describe_agent_config(build_agent_config(config)) == config


def test_project_defaults_to_claude_code_agent_config():
    project = Project("demo", "0.1.0")
    assert project.agent_config == {"type": "claude_code"}


def test_project_custom_agent_config():
    project = Project("demo", "0.1.0", agent_config={"type": "claude_code", "model": "x"})
    assert project.agent_config == {"type": "claude_code", "model": "x"}


def test_build_agent_constructs_claude_code_agent_with_model():
    project = Project(
        "demo", "0.1.0", agent_config={"type": "claude_code", "model": "claude-sonnet-5-5"}
    )
    Customer = build_model_from_field_spec("Customer", {"id": "str"}, project.schema)
    project.schema.register(Customer, name="Customer")
    project.sync_tools()

    agent = build_agent(project)

    assert isinstance(agent, ClaudeCodeAgent)
    assert agent.name == "demo"
    assert agent.model == "claude-sonnet-5-5"
    assert "demo" in agent.system_prompt
    assert any(t.name == "create_customer" for t in agent.tools)


def test_build_agent_without_monitoring_store_is_unwrapped():
    project = Project("demo", "0.1.0")
    agent = build_agent(project)
    assert isinstance(agent, ClaudeCodeAgent)
    assert not isinstance(agent, MonitoredAgent)


def test_build_agent_with_monitoring_store_wraps_in_monitored_agent(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "m.db"))
    try:
        project = Project("demo", "0.1.0", monitoring_store=store)
        agent = build_agent(project, session_id="s1")
        assert isinstance(agent, MonitoredAgent)
        assert isinstance(agent._inner, ClaudeCodeAgent)
        assert agent.session_id == "s1"
    finally:
        store.close()


def test_build_agent_unknown_type_raises():
    project = Project("demo", "0.1.0", agent_config={"type": "nope"})
    try:
        build_agent(project)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_register_agent_backend():
    calls = []

    class FakeAgent(Agent):
        def __init__(self, **kwargs) -> None:
            super().__init__(kwargs.get("name", "fake"))
            calls.append(kwargs)

        @property
        def is_connected(self) -> bool:
            return False

        async def connect(self) -> None:
            pass

        async def disconnect(self) -> None:
            pass

        async def send(self, prompt: str) -> None:
            pass

        async def receive(self):
            return
            yield  # pragma: no cover

        async def run(self, prompt: str) -> str:
            return ""

    register_agent_backend("fake", FakeAgent)
    try:
        project = Project("demo", "0.1.0", agent_config={"type": "fake", "flavor": "test"})
        agent = build_agent(project)
        assert isinstance(agent, FakeAgent)
        assert calls[-1]["flavor"] == "test"
    finally:
        pass  # "fake" left registered is harmless, same convention as storage backend tests
