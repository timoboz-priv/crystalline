"""`SkillRegistry`: name -> `Skill` registry for a project.

Mirrors `crystalline.tools.ToolRegistry` exactly (same collision-protected
CRUD inherited unchanged) — the only difference is `register()`'s
decorator sugar builds a `Skill` instead of a bare `Tool`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import overload

from pydantic import BaseModel

from crystalline.tools import ToolRegistry
from crystalline.tools.tool import ToolHandler

from .skill import Skill


class SkillRegistry(ToolRegistry):
    @overload
    def register(
        self,
        name: str,
        *,
        input_model: type[BaseModel],
        description: str = "",
        output_model: type[BaseModel] | None = None,
        scope: str | None = None,
        group: str = "skills",
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
        group: str = "skills",
        enabled: bool = True,
    ) -> Callable[[ToolHandler], ToolHandler]:
        """Decorator sugar for defining and adding a `Skill`.

        @skills.register("place_order", input_model=PlaceOrderInput, scope="Order:create")
        async def place_order(data: PlaceOrderInput) -> Order:
            ...
        """

        def decorator(handler: ToolHandler) -> ToolHandler:
            self.add_tool(
                Skill(
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
