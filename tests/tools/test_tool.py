import asyncio

import pytest
from pydantic import BaseModel

from crystalline.security import Token, bind_token
from crystalline.tools import Tool


class Input(BaseModel):
    value: int


def test_invoke_without_scope_runs_unconditionally():
    tool = Tool(name="noop", input_model=Input, handler=lambda data: _ret(data.value))
    assert asyncio.run(tool.invoke(Input(value=1))) == 1


async def _ret(value):
    return value


def test_invoke_disabled_raises():
    tool = Tool(
        name="noop", input_model=Input, handler=lambda data: _ret(data.value), enabled=False
    )
    with pytest.raises(PermissionError):
        asyncio.run(tool.invoke(Input(value=1)))


def test_invoke_checks_scope():
    tool = Tool(
        name="noop", input_model=Input, handler=lambda data: _ret(data.value), scope="X:read"
    )

    async def run_with_scope():
        with bind_token(Token(sub="ada", scopes=["X:read"])):
            return await tool.invoke(Input(value=5))

    assert asyncio.run(run_with_scope()) == 5


def test_invoke_blocks_missing_scope():
    tool = Tool(
        name="noop", input_model=Input, handler=lambda data: _ret(data.value), scope="X:delete"
    )

    async def run_without_scope():
        with bind_token(Token(sub="ada", scopes=["X:read"])):
            return await tool.invoke(Input(value=5))

    with pytest.raises(PermissionError):
        asyncio.run(run_without_scope())


def test_invoke_blocks_with_no_bound_token():
    tool = Tool(
        name="noop", input_model=Input, handler=lambda data: _ret(data.value), scope="X:read"
    )
    with pytest.raises(PermissionError):
        asyncio.run(tool.invoke(Input(value=5)))
