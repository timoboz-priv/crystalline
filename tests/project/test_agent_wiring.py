import asyncio

import pytest

from crystalline.agents import Agent as AgentBase
from crystalline.project import Project, system_prompt_for, wire_tools
from crystalline.project.fields import build_model_from_field_spec
from crystalline.security import Token, bind_token
from crystalline.skills import Skill


class FakeAgent(AgentBase):
    def __init__(self) -> None:
        super().__init__("fake")

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


def _project_with_customer() -> Project:
    project = Project("demo", "0.1.0")
    Customer = build_model_from_field_spec(
        "Customer", {"id": "str", "name": "str"}, project.schema
    )
    project.schema.register(Customer, name="Customer")
    project.sync_tools()
    return project


def test_wire_tools_adds_agent_facing_tools():
    project = _project_with_customer()
    agent = FakeAgent()

    wire_tools(agent, project)

    names = {t.name for t in agent.tools}
    assert "create_customer" in names
    assert "create_user" in names  # admin group also wired


def test_wired_tool_groups_are_preserved_in_metadata():
    project = _project_with_customer()
    agent = FakeAgent()
    wire_tools(agent, project)

    create_customer = agent.get_tool("create_customer")
    create_user = agent.get_tool("create_user")
    assert create_customer.metadata["group"] == "storage"
    assert create_user.metadata["group"] == "admin"


def test_wired_tool_handler_validates_and_invokes():
    project = _project_with_customer()
    agent = FakeAgent()
    wire_tools(agent, project)

    create_customer = agent.get_tool("create_customer")
    admin_token = Token(sub="admin", scopes=["*:*"])

    async def run():
        with bind_token(admin_token):
            return await create_customer.handler({"id": "c1", "name": "Ada"})

    result = asyncio.run(run())
    assert result["content"][0]["type"] == "text"
    assert "Ada" in result["content"][0]["text"]


def test_wired_tool_handler_enforces_scope():
    project = _project_with_customer()
    agent = FakeAgent()
    wire_tools(agent, project)

    create_customer = agent.get_tool("create_customer")
    viewer_token = Token(sub="view", scopes=["*:read"])

    async def run():
        with bind_token(viewer_token):
            return await create_customer.handler({"id": "c1", "name": "Ada"})

    try:
        asyncio.run(run())
        raise AssertionError("expected PermissionError")
    except PermissionError:
        pass


def test_system_prompt_mentions_types_and_groups():
    project = _project_with_customer()
    prompt = system_prompt_for(project)
    assert "Customer" in prompt
    assert "storage" in prompt
    assert "admin" in prompt


def test_wire_tools_also_wires_skills():
    project = _project_with_customer()

    async def handler(data):
        return data.id

    Customer = project.schema.get("Customer")
    skill = Skill(
        name="greet_customer",
        input_model=Customer,
        handler=handler,
        scope="Customer:read",
    )
    project.skills.add_tool(skill)

    agent = FakeAgent()
    wire_tools(agent, project)

    wired = agent.get_tool("greet_customer")
    assert wired is not None
    assert wired.metadata["group"] == "skills"


def test_wire_tools_rejects_skill_name_colliding_with_a_tool():
    # A skill with no scope that silently overwrote the agent-facing entry
    # for an existing, scoped tool (e.g. create_customer) would let the
    # scope check that tool enforced be skipped entirely.
    project = _project_with_customer()

    async def handler(data):
        return data.id

    Customer = project.schema.get("Customer")
    project.skills.add_tool(
        Skill(name="create_customer", input_model=Customer, handler=handler)
    )

    agent = FakeAgent()
    with pytest.raises(ValueError, match="create_customer"):
        wire_tools(agent, project)


def test_system_prompt_mentions_skills_group():
    project = _project_with_customer()

    async def handler(data):
        return data

    project.skills.add_tool(
        Skill(name="noop", input_model=project.schema.get("Customer"), handler=handler)
    )

    prompt = system_prompt_for(project)
    assert "skills" in prompt
