"""An example skill for demo_shop: `dashboard_summary`.

Chains three existing read-only tools — `list_users` (admin), `list_product`
and `list_order` (storage) — to assemble the data behind a "show me a
dashboard" style request: the most recent `limit` users/products/orders plus
the revenue across just the returned orders. Rendering (tables, charts, a
markdown summary) stays an agentic/presentation concern on top of this —
this skill only does the deterministic part: which records to fetch and
how to aggregate them, so repeated dashboard requests don't re-derive that
from scratch in free text each time.

`list_users` returns sanitized dicts with no `created_at` (see
`crystalline.tools.admin`), so "most recent" users is just the tail of
whatever order the admin tool returns; products/orders are explicitly
sorted by `created_at`/`placed_at` since storage's generic `list` tools
don't guarantee insertion order.

Loaded automatically via this project's `project.yaml` (`extensions:
extensions/`) — see `crystalline.project.extensions.apply_extensions`.
Convention: one skill per file, named `skill_*.py`, with a
`build_skill(project) -> Skill` function.
"""

from __future__ import annotations

from typing import Any

from crystalline.project import Project
from crystalline.schema import CrystallineModel
from crystalline.skills import Skill


class DashboardSummaryInput(CrystallineModel):
    limit: int = 3
    """How many of each entity (users, products, orders) to include;
    defaults to the last 3 of each."""


class DashboardSummary(CrystallineModel):
    users: list[dict[str, Any]]
    products: list[dict[str, Any]]
    orders: list[dict[str, Any]]
    recent_orders_revenue: float
    """Sum of `total` across just the `orders` returned above — not all
    orders, only the most recent `limit` of them."""


def _build_skill(project: Project) -> Skill:
    list_users = project.tools.get_tool("list_users")
    list_product = project.tools.get_tool("list_product")
    list_order = project.tools.get_tool("list_order")
    if list_users is None or list_product is None or list_order is None:
        raise RuntimeError(
            "dashboard_summary skill requires list_users/list_product/"
            "list_order tools; call project.sync_tools() first"
        )

    async def dashboard_summary(data: DashboardSummaryInput) -> DashboardSummary:
        users = await list_users.invoke(list_users.input_model())
        products = await list_product.invoke(list_product.input_model())
        orders = await list_order.invoke(list_order.input_model())

        recent_users = list(users[-data.limit :])
        recent_products = sorted(
            products, key=lambda p: p.created_at, reverse=True
        )[: data.limit]
        recent_orders = sorted(
            orders, key=lambda o: o.placed_at, reverse=True
        )[: data.limit]

        revenue = sum(order.total for order in recent_orders)

        return DashboardSummary(
            users=recent_users,
            products=[p.model_dump(mode="json") for p in recent_products],
            orders=[o.model_dump(mode="json") for o in recent_orders],
            recent_orders_revenue=revenue,
        )

    return Skill(
        name="dashboard_summary",
        description=(
            "Fetch the most recent `limit` users, products, and orders "
            "(default 3 of each) plus the revenue across just those "
            "returned orders — the data behind a 'dashboard' style "
            "request. Rendering is left to the caller."
        ),
        input_model=DashboardSummaryInput,
        handler=dashboard_summary,
        output_model=DashboardSummary,
        scope=None,
    )