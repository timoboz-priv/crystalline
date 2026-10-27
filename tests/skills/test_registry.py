import asyncio

import pytest
from pydantic import BaseModel

from crystalline.skills import Skill, SkillRegistry


class Input(BaseModel):
    value: int


async def _handler(data: Input) -> int:
    return data.value


def test_add_get_remove():
    registry = SkillRegistry()
    skill = Skill(name="echo", input_model=Input, handler=_handler)
    registry.add_tool(skill)

    assert registry.get_tool("echo") is skill
    assert len(registry) == 1
    assert list(registry) == [skill]

    assert registry.remove_tool("echo") is skill
    assert registry.get_tool("echo") is None


def test_add_duplicate_raises_without_replace():
    registry = SkillRegistry()
    registry.add_tool(Skill(name="echo", input_model=Input, handler=_handler))
    with pytest.raises(ValueError):
        registry.add_tool(Skill(name="echo", input_model=Input, handler=_handler))


def test_register_decorator_builds_a_skill_not_a_bare_tool():
    registry = SkillRegistry()

    @registry.register("echo", input_model=Input)
    async def echo(data: Input) -> int:
        return data.value

    skill = registry.get_tool("echo")
    assert isinstance(skill, Skill)
    assert skill.group == "skills"
    assert asyncio.run(skill.invoke(Input(value=3))) == 3


def test_register_decorator_custom_group_and_scope():
    registry = SkillRegistry()

    @registry.register("echo", input_model=Input, group="custom", scope="X:read")
    async def echo(data: Input) -> int:
        return data.value

    skill = registry.get_tool("echo")
    assert skill.group == "custom"
    assert skill.scope == "X:read"
