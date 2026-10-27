import asyncio

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from crystalline.agents import Agent as AgentBase
from crystalline.monitoring import Session, SQLiteSessionStore
from crystalline.project.monitoring_wiring import (
    MonitoredAgent,
    claude_message_recorder,
    claude_turn_outcome,
    end_monitoring_session,
    start_monitoring_session,
)


class FakeInnerAgent(AgentBase):
    def __init__(self, messages=None):
        super().__init__("fake-inner", system_prompt="sp", model="m1")
        self.connected = False
        self.sent: list[str] = []
        self._messages = messages or []

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def send(self, prompt: str) -> None:
        self.sent.append(prompt)

    async def receive(self):
        for message in self._messages:
            yield message

    async def run(self, prompt: str) -> str:
        raise AssertionError("MonitoredAgent.run() must not delegate to inner.run()")


RESULT_MESSAGE = ResultMessage(
    subtype="success",
    duration_ms=100,
    duration_api_ms=80,
    is_error=False,
    num_turns=1,
    session_id="sdk-session",
    stop_reason="end_turn",
    total_cost_usd=0.01,
    usage={"input_tokens": 10},
    result="done",
    errors=None,
)


@pytest.fixture
def store():
    with SQLiteSessionStore(":memory:") as store:
        store.start_session(Session(id="s1", project_name="demo"))
        yield store


def _agent(store, **kwargs) -> MonitoredAgent:
    inner = kwargs.pop("inner", None) or FakeInnerAgent(messages=kwargs.pop("messages", None))
    return MonitoredAgent(inner, store, session_id="s1", **kwargs), inner


async def _connect_send_drain(agent, prompt="hello there"):
    await agent.connect()
    await agent.send(prompt)
    return [m async for m in agent.receive()]


def test_connect_and_disconnect_do_not_touch_the_session(store):
    # Session lifecycle is owned by the CLI (start_monitoring_session/
    # end_monitoring_session), not by MonitoredAgent.
    agent, inner = _agent(store)

    async def run():
        await agent.connect()
        await agent.disconnect()

    asyncio.run(run())

    session = store.get_session("s1")
    assert session.ended_at is None  # untouched by connect()/disconnect()
    assert inner.connected is False


def test_send_self_manages_a_turn_when_nothing_attached_one(store):
    agent, inner = _agent(store)

    async def run():
        await agent.connect()
        await agent.send("hello there")

    asyncio.run(run())

    turn_id = agent._current_turn_id
    turn = store.get_turn(turn_id)
    assert turn is not None
    assert turn.status == "in_progress"
    assert turn.session_id == "s1"

    events = store.list_events(turn_id=turn_id)
    assert events[-1].kind == "user_message"
    assert events[-1].data == {"text": "hello there"}
    assert inner.sent == ["hello there"]


def test_continue_turn_makes_send_append_to_the_existing_turn(store):
    from crystalline.monitoring import Turn

    store.start_turn(Turn(id="pre-existing", session_id="s1"))
    agent, inner = _agent(store)
    agent.continue_turn("pre-existing")

    asyncio.run(agent.send("hello there"))

    assert agent._current_turn_id == "pre-existing"
    events = store.list_events(turn_id="pre-existing")
    assert len(events) == 1
    assert events[0].kind == "user_message"
    # Turn must not have been (re)started — start_turn with the same id
    # again would have raised ValueError, so reaching here already proves
    # it wasn't, but assert the turn is still open too.
    assert store.get_turn("pre-existing").status == "in_progress"


def test_continue_turn_attachment_is_consumed_after_one_send(store):
    from crystalline.monitoring import Turn

    store.start_turn(Turn(id="pre-existing", session_id="s1"))
    agent, inner = _agent(store)
    agent.continue_turn("pre-existing")

    async def run():
        await agent.send("first")
        # ResultMessage never arrived, so "pre-existing" is still open;
        # a second send() must self-manage (close it, start a new one),
        # not silently append onto "pre-existing" again.
        await agent.send("second")

    asyncio.run(run())

    assert agent._current_turn_id != "pre-existing"
    assert store.get_turn("pre-existing").status == "error"
    assert store.get_turn(agent._current_turn_id).status == "in_progress"


def test_receive_records_assistant_text_and_tool_call_under_the_turn(store):
    messages = [
        AssistantMessage(
            content=[
                TextBlock(text="thinking..."),
                ToolUseBlock(id="t1", name="get_product", input={"id": "p1"}),
            ],
            model="claude",
        )
    ]
    agent, inner = _agent(store, messages=messages)

    received = asyncio.run(_connect_send_drain(agent))

    assert received == messages  # passthrough, unmodified
    turn_id = agent._current_turn_id
    events = store.list_events(turn_id=turn_id)
    kinds = [e.kind for e in events]
    assert "assistant_text" in kinds
    assert "tool_call" in kinds
    text_event = next(e for e in events if e.kind == "assistant_text")
    assert text_event.data == {"text": "thinking..."}
    tool_event = next(e for e in events if e.kind == "tool_call")
    assert tool_event.data == {"id": "t1", "name": "get_product", "input": {"id": "p1"}}
    assert store.get_turn(turn_id).status == "in_progress"


def test_receive_records_tool_result(store):
    messages = [
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="42", is_error=False)])
    ]
    agent, inner = _agent(store, messages=messages)

    asyncio.run(_connect_send_drain(agent))

    events = store.list_events(turn_id=agent._current_turn_id)
    tool_result = next(e for e in events if e.kind == "tool_result")
    assert tool_result.data == {"tool_use_id": "t1", "content": "42", "is_error": False}


def test_receive_result_message_ends_the_turn_not_an_event(store):
    agent, inner = _agent(store, messages=[RESULT_MESSAGE])

    asyncio.run(_connect_send_drain(agent))

    turn_id = agent._current_turn_id
    turn = store.get_turn(turn_id)
    assert turn.status == "completed"
    assert turn.total_cost_usd == 0.01
    assert turn.result == "done"
    assert turn.usage == {"input_tokens": 10}
    assert turn.ended_at is not None

    events = store.list_events(turn_id=turn_id)
    assert all(e.kind != "message" for e in events)
    assert len(events) == 1  # just the initial user_message


def test_receive_result_message_with_is_error_marks_turn_errored(store):
    error_result = RESULT_MESSAGE.__class__(**{**RESULT_MESSAGE.__dict__, "is_error": True})
    agent, inner = _agent(store, messages=[error_result])

    asyncio.run(_connect_send_drain(agent))

    assert store.get_turn(agent._current_turn_id).status == "error"


def test_receive_records_unrecognized_message_as_message_kind(store):
    agent, inner = _agent(store, messages=[object()])

    asyncio.run(_connect_send_drain(agent))

    events = store.list_events(turn_id=agent._current_turn_id)
    message_events = [e for e in events if e.kind == "message"]
    assert message_events[0].data == {"type": "object"}


def test_a_new_send_closes_a_still_open_previous_turn(store):
    agent, inner = _agent(store)

    async def run():
        await agent.connect()
        await agent.send("first")
        first_turn_id = agent._current_turn_id
        await agent.send("second")
        return first_turn_id

    first_turn_id = asyncio.run(run())

    first_turn = store.get_turn(first_turn_id)
    assert first_turn.status == "error"
    assert first_turn.ended_at is not None
    assert store.get_turn(agent._current_turn_id).status == "in_progress"


def test_disconnect_closes_a_still_open_turn(store):
    agent, inner = _agent(store)

    async def run():
        await agent.connect()
        await agent.send("hello")
        return agent._current_turn_id

    turn_id = asyncio.run(run())
    asyncio.run(agent.disconnect())

    turn = store.get_turn(turn_id)
    assert turn.status == "error"
    assert turn.ended_at is not None


def test_run_does_not_delegate_to_inner_run(store):
    messages = [AssistantMessage(content=[TextBlock(text="final answer")], model="claude")]
    agent, inner = _agent(store, messages=messages)

    result = asyncio.run(agent.run("hi"))

    assert result == "final answer"
    assert inner.sent == ["hi"]
    assert inner.connected is False  # run() owns + tears down its own connection


def test_tools_skills_properties_delegate_to_inner(store):
    from pydantic import BaseModel

    from crystalline.tools import Tool

    class Input(BaseModel):
        pass

    async def handler(data):
        return 1

    agent, inner = _agent(store)

    tool = Tool(name="answer", input_model=Input, handler=handler)
    agent.add_tool(tool)
    assert inner.get_tool("answer") is tool
    assert agent.get_tool("answer") is tool
    assert [t.name for t in agent.tools] == ["answer"]

    agent.set_property("cwd", "/tmp")
    assert inner.get_property("cwd") == "/tmp"
    assert agent.properties == {"cwd": "/tmp"}


def test_name_system_prompt_model_delegate_to_inner(store):
    agent, inner = _agent(store)

    assert agent.name == "fake-inner"
    assert agent.system_prompt == "sp"
    assert agent.model == "m1"

    agent.model = "m2"
    assert inner.model == "m2"


def test_default_recorders_are_the_claude_ones(store):
    agent, inner = _agent(store)
    assert agent._message_recorder is claude_message_recorder
    assert agent._turn_outcome_extractor is claude_turn_outcome


def test_custom_message_recorder_is_used(store):
    def custom_recorder(message):
        return [("custom_kind", {"raw": str(message)})]

    def custom_outcome(message):
        return None

    agent, inner = _agent(
        store,
        messages=["anything"],
        message_recorder=custom_recorder,
        turn_outcome_extractor=custom_outcome,
    )

    asyncio.run(_connect_send_drain(agent))

    events = store.list_events(turn_id=agent._current_turn_id)
    assert events[-1].kind == "custom_kind"


# ---- session helpers (crystalline.project.monitoring_wiring) ----


def test_start_monitoring_session_is_a_noop_without_a_store():
    from crystalline.project import Project

    project = Project("demo", "0.1.0")
    start_monitoring_session(project, "s1", principal="ada")  # should not raise


def test_end_monitoring_session_is_a_noop_without_a_store():
    from crystalline.project import Project

    project = Project("demo", "0.1.0")
    end_monitoring_session(project, "s1")  # should not raise


def test_start_and_end_monitoring_session_with_a_store(tmp_path):
    from crystalline.project import Project

    monitoring_store = SQLiteSessionStore(str(tmp_path / "m.db"))
    try:
        project = Project("demo", "0.1.0", monitoring_store=monitoring_store)
        start_monitoring_session(project, "s1", principal="ada")

        session = monitoring_store.get_session("s1")
        assert session is not None
        assert session.principal == "ada"
        assert session.project_name == "demo"

        end_monitoring_session(project, "s1")
        assert monitoring_store.get_session("s1").ended_at is not None
    finally:
        monitoring_store.close()
