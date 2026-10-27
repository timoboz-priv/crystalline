"""A hand-written custom tool for demo_shop: `total_revenue`.

Demonstrates adding a tool that isn't just generic CRUD — a read-only
aggregate over existing data, something `crystalline.tools.crud` has no
way to generate since it only knows about per-record operations.

Loaded automatically via this project's `project.yaml` (`extensions:
extensions/`) — see `crystalline.project.extensions.apply_extensions`.
Convention: one tool per file, named `tool_*.py`, with a
`build_tool(project) -> Tool` function.
"""

from __future__ import annotations

from crystalline.project import Project
from crystalline.schema import CrystallineModel
from crystalline.tools import Tool


class _NoInput(CrystallineModel):
    pass


def build_tool(project: Project) -> Tool:
    Order = project.schema.get("Order")
    if Order is None:
        raise RuntimeError("total_revenue tool requires the Order type")

    async def total_revenue(_: _NoInput) -> float:
        return sum(order.total for order in project.storage.list(Order))

    return Tool(
        name="total_revenue",
        description="Sum the total across every order placed so far.",
        input_model=_NoInput,
        handler=total_revenue,
        scope="Order:read",
        group="custom",
    )
