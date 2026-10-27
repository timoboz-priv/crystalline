import asyncio

import pytest
from pydantic import BaseModel

from crystalline.security import Token, bind_token
from crystalline.skills import Skill
from crystalline.tools import Tool


class Input(BaseModel):
    value: int


async def _handler(data: Input) -> int:
    return data.value * 2


def test_skill_is_a_tool_subclass():
    skill = Skill(name="double", input_model=Input, handler=_handler)
    assert isinstance(skill, Tool)


def test_skill_defaults_to_skills_group():
    skill = Skill(name="double", input_model=Input, handler=_handler)
    assert skill.group == "skills"


def test_skill_group_can_be_overridden():
    skill = Skill(name="double", input_model=Input, handler=_handler, group="custom")
    assert skill.group == "custom"


def test_skill_invoke_works_like_tool():
    skill = Skill(name="double", input_model=Input, handler=_handler)
    assert asyncio.run(skill.invoke(Input(value=5))) == 10


def test_skill_invoke_enforces_scope():
    skill = Skill(name="double", input_model=Input, handler=_handler, scope="X:read")
    with pytest.raises(PermissionError):
        asyncio.run(skill.invoke(Input(value=5)))

    async def run_with_scope():
        with bind_token(Token(sub="ada", scopes=["X:read"])):
            return await skill.invoke(Input(value=5))

    assert asyncio.run(run_with_scope()) == 10
