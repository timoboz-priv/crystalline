import asyncio

import pytest
from pydantic import BaseModel

from crystalline.security import Token, bind_token
from crystalline.tools import Tool, ToolRegistry


class Input(BaseModel):
    value: int


async def _handler(data: Input) -> int:
    return data.value


def test_add_get_remove():
    registry = ToolRegistry()
    tool = Tool(name="echo", input_model=Input, handler=_handler)
    registry.add_tool(tool)

    assert registry.get_tool("echo") is tool
    assert len(registry) == 1
    assert "echo" in registry
    assert list(registry) == [tool]

    assert registry.remove_tool("echo") is tool
    assert registry.get_tool("echo") is None


def test_add_duplicate_raises_without_replace():
    registry = ToolRegistry()
    registry.add_tool(Tool(name="echo", input_model=Input, handler=_handler))
    with pytest.raises(ValueError):
        registry.add_tool(Tool(name="echo", input_model=Input, handler=_handler))


def test_add_duplicate_allowed_with_replace():
    registry = ToolRegistry()
    registry.add_tool(Tool(name="echo", input_model=Input, handler=_handler))
    replacement = Tool(name="echo", input_model=Input, handler=_handler, description="v2")
    registry.add_tool(replacement, replace=True)
    assert registry.get_tool("echo") is replacement


def test_update_tool():
    registry = ToolRegistry()
    registry.add_tool(Tool(name="echo", input_model=Input, handler=_handler))
    registry.update_tool("echo", enabled=False)
    assert registry.get_tool("echo").enabled is False


def test_update_missing_raises():
    registry = ToolRegistry()
    with pytest.raises(KeyError):
        registry.update_tool("nope", enabled=False)


def test_register_decorator():
    registry = ToolRegistry()

    @registry.register("echo", input_model=Input, scope="X:read")
    async def echo(data: Input) -> int:
        return data.value

    tool = registry.get_tool("echo")
    assert tool is not None
    assert tool.scope == "X:read"

    async def run():
        with bind_token(Token(sub="ada", scopes=["X:read"])):
            return await tool.invoke(Input(value=3))

    assert asyncio.run(run()) == 3
