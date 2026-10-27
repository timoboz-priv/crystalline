import asyncio

import pytest

from crystalline.events import TEXT_EVENT_TYPE, AgentHandoff, Event, RuleBasedRouter
from crystalline.project import Project
from crystalline.project.fields import build_model_from_field_spec
from crystalline.security import Token
from crystalline.skills import Skill
from crystalline.tools import Tool


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


def test_text_event_always_falls_back_to_agent_handoff():
    project = _project_with_customer()
    router = RuleBasedRouter(project)
    event = _event(project, type=TEXT_EVENT_TYPE, payload="hello there")

    result = asyncio.run(router.route(event))

    assert isinstance(result, AgentHandoff)
    assert result.event is event


def test_unmatched_event_type_falls_back_to_agent_handoff():
    project = _project_with_customer()
    router = RuleBasedRouter(project)
    event = _event(project, type="no_such_tool_or_skill", payload={})

    result = asyncio.run(router.route(event))

    assert isinstance(result, AgentHandoff)


def test_event_type_matching_a_tool_name_invokes_it_directly():
    project = _project_with_customer()
    router = RuleBasedRouter(project)
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


def test_event_type_matching_a_skill_name_invokes_it_directly():
    project = _project_with_customer()

    async def handler(data):
        return f"greetings, {data.id}"

    Customer = project.schema.get("Customer")
    project.skills.add_tool(
        Skill(name="greet_customer", input_model=Customer, handler=handler)
    )
    router = RuleBasedRouter(project)
    event = _event(project, type="greet_customer", payload={"id": "c1", "name": "Ada"})

    result = asyncio.run(router.route(event))

    assert result == "greetings, c1"


def test_direct_dispatch_enforces_tool_scope():
    project = _project_with_customer()
    router = RuleBasedRouter(project)
    viewer_token = Token(sub="view", scopes=["*:read"])
    event = _event(
        project,
        type="create_customer",
        payload={"id": "c1", "name": "Ada"},
        token=viewer_token,
    )

    with pytest.raises(PermissionError):
        asyncio.run(router.route(event))


def test_direct_dispatch_with_no_token_fails_scoped_tool():
    project = _project_with_customer()
    router = RuleBasedRouter(project)
    event = _event(project, type="create_customer", payload={"id": "c1", "name": "Ada"})

    with pytest.raises(PermissionError):
        asyncio.run(router.route(event))


def test_text_type_is_reserved_even_if_a_tool_is_named_text():
    project = _project_with_customer()

    async def handler(data):
        return "should never run"

    project.tools.add_tool(
        Tool(
            name=TEXT_EVENT_TYPE,
            input_model=project.schema.get("Customer"),
            handler=handler,
        )
    )
    router = RuleBasedRouter(project)
    event = _event(project, type=TEXT_EVENT_TYPE, payload="hello")

    result = asyncio.run(router.route(event))

    assert isinstance(result, AgentHandoff)


def test_mismatched_project_name_raises():
    project = _project_with_customer()
    router = RuleBasedRouter(project)
    event = _event(project, project_name="some-other-project")

    with pytest.raises(ValueError, match="some-other-project"):
        asyncio.run(router.route(event))
