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

from datetime import datetime, timedelta, timezone

from crystalline.project import Project
from crystalline.schema import CrystallineModel
from crystalline.tools import Tool


class _TotalRevenueInput(CrystallineModel):
    days: int | None = None
    """Only count orders placed within the last `days` days; `None`
    (default) means all-time."""


def build_tool(project: Project) -> Tool:
    Order = project.schema.get("Order")
    if Order is None:
        raise RuntimeError("total_revenue tool requires the Order type")

    async def total_revenue(data: _TotalRevenueInput) -> float:
        orders = project.storage.list(Order)
        if data.days is None:
            return sum(order.total for order in orders)
        cutoff = datetime.now(timezone.utc) - timedelta(days=data.days)
        return sum(order.total for order in orders if order.placed_at >= cutoff)

    return Tool(
        name="total_revenue",
        description=(
            "Sum the total across orders placed so far. Pass `days` to restrict "
            "to orders placed within that many days (e.g. days=30); omit it for "
            "all-time revenue."
        ),
        input_model=_TotalRevenueInput,
        handler=total_revenue,
        scope="Order:read",
        group="custom",
    )
