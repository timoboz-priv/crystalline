import asyncio

import pytest

from crystalline.events import TEXT_EVENT_TYPE, AgentHandoff, Event, RuleBasedRouter
from crystalline.monitoring import Session, SQLiteSessionStore
from crystalline.project import Project, build_router
from crystalline.project.fields import build_model_from_field_spec
from crystalline.project.monitoring_wiring import MonitoredRouter
from crystalline.security import Token


def _project_with_customer() -> Project:
    project = Project("demo", "0.1.0")
    Customer = build_model_from_field_spec(
        "Customer", {"id": "str", "name": "str"}, project.schema
    )
    project.schema.register(Customer, name="Customer")
    project.sync_tools()
    return project


def _event(project: Project, **overrides) -> Event:
    defaults = dict(
        type=TEXT_EVENT_TYPE,
        payload="hi",
        project_name=project.name,
        session_id="s1",
    )
    defaults.update(overrides)
    return Event(**defaults)


@pytest.fixture
def store():
    with SQLiteSessionStore(":memory:") as store:
        store.start_session(Session(id="s1", project_name="demo"))
        yield store


def test_text_event_opens_a_turn_with_route_decision_then_agent_handoff(store):
    project = _project_with_customer()
    router = MonitoredRouter(RuleBasedRouter(project), store, session_id="s1")
    event = _event(project, type=TEXT_EVENT_TYPE, payload="hello there")

    result = asyncio.run(router.route(event))

    assert isinstance(result, AgentHandoff)
    assert result.turn_id is not None

    turn = store.get_turn(result.turn_id)
    assert turn.status == "in_progress"  # left open for the agent to continue

    events = store.list_events(turn_id=result.turn_id)
    assert len(events) == 1
    assert events[0].kind == "route_decision"
    assert events[0].data == {
        "event_type": "text",
        "decision": "agent_handoff",
        "basis": "exact_type_match",
        "matched": None,
    }


def test_direct_dispatch_records_route_decision_tool_call_tool_result_and_closes_turn(store):
    project = _project_with_customer()
    router = MonitoredRouter(RuleBasedRouter(project), store, session_id="s1")
    admin_token = Token(sub="admin", scopes=["*:*"])
    event = _event(
        project,
        type="create_customer",
        payload={"id": "c1", "name": "Ada"},
        token=admin_token,
    )

    result = asyncio.run(router.route(event))

    assert not isinstance(result, AgentHandoff)
    assert result.name == "Ada"

    events = store.list_events(session_id="s1")
    kinds = [e.kind for e in events]
    assert kinds == ["route_decision", "tool_call", "tool_result"]
    assert events[0].data["decision"] == "direct_dispatch"
    assert events[0].data["matched"] == "create_customer"
    assert events[1].data == {"name": "create_customer", "input": {"id": "c1", "name": "Ada"}}
    assert events[2].data["result"]["name"] == "Ada"

    turn = store.get_turn(events[0].turn_id)
    assert turn.status == "completed"
    assert turn.ended_at is not None


def test_direct_dispatch_failure_records_error_and_closes_turn_then_reraises(store):
    project = _project_with_customer()
    router = MonitoredRouter(RuleBasedRouter(project), store, session_id="s1")
    viewer_token = Token(sub="view", scopes=["*:read"])
    event = _event(
        project,
        type="create_customer",
        payload={"id": "c1", "name": "Ada"},
        token=viewer_token,
    )

    with pytest.raises(PermissionError):
        asyncio.run(router.route(event))

    events = store.list_events(session_id="s1")
    kinds = [e.kind for e in events]
    assert kinds == ["route_decision", "tool_call", "tool_result"]
    assert "error" in events[2].data

    turn = store.get_turn(events[0].turn_id)
    assert turn.status == "error"
    assert turn.errors


def test_build_router_returns_monitored_router_when_store_and_session_id_given():
    project = _project_with_customer()
    with SQLiteSessionStore(":memory:") as store:
        project.monitoring_store = store
        router = build_router(project, session_id="s1")
        assert isinstance(router, MonitoredRouter)


def test_build_router_returns_plain_router_without_monitoring():
    project = _project_with_customer()
    router = build_router(project, session_id="s1")
    assert isinstance(router, RuleBasedRouter)
    assert not isinstance(router, MonitoredRouter)


def test_build_router_returns_plain_router_without_session_id():
    project = _project_with_customer()
    with SQLiteSessionStore(":memory:") as store:
        project.monitoring_store = store
        router = build_router(project)
        assert isinstance(router, RuleBasedRouter)
        assert not isinstance(router, MonitoredRouter)
