"""`ToolRegistry`: name -> `Tool` registry for a project.

Same collision-protection stance as `crystalline.schema.SchemaRegistry`
(raise on name collision unless `replace=True`), since a tool's name is
the public surface an agent calls it by.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, overload

from pydantic import BaseModel

from .tool import Tool, ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def add_tool(self, tool: Tool, *, replace: bool = False) -> Tool:
        existing = self._tools.get(tool.name)
        if existing is not None and existing is not tool and not replace:
            raise ValueError(
                f"Tool {tool.name!r} is already registered; "
                "pass replace=True to overwrite"
            )
        self._tools[tool.name] = tool
        return tool

    @overload
    def register(
        self,
        name: str,
        *,
        input_model: type[BaseModel],
        description: str = "",
        output_model: type[BaseModel] | None = None,
        scope: str | None = None,
        group: str = "crystalline",
        enabled: bool = True,
    ) -> Callable[[ToolHandler], ToolHandler]: ...

    def register(
        self,
        name: str,
        *,
        input_model: type[BaseModel],
        description: str = "",
        output_model: type[BaseModel] | None = None,
        scope: str | None = None,
        group: str = "crystalline",
        enabled: bool = True,
    ) -> Callable[[ToolHandler], ToolHandler]:
        """Decorator sugar for defining and adding a `Tool`.

        @registry.register("add", input_model=AddInput, scope="Math:create")
        async def add(data: AddInput) -> int:
            return data.a + data.b
        """

        def decorator(handler: ToolHandler) -> ToolHandler:
            self.add_tool(
                Tool(
                    name=name,
                    input_model=input_model,
                    handler=handler,
                    description=description,
                    output_model=output_model,
                    scope=scope,
                    group=group,
                    enabled=enabled,
                )
            )
            return handler

        return decorator

    def get_tool(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def remove_tool(self, name: str) -> Tool | None:
        return self._tools.pop(name, None)

    def update_tool(self, name: str, **changes: Any) -> Tool:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool: {name!r}")
        for key, value in changes.items():
            setattr(tool, key, value)
        return tool

    @property
    def tools(self) -> list[Tool]:
        return list(self._tools.values())

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
