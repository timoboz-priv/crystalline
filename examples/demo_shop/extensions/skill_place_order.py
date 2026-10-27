"""An example skill for demo_shop: `place_order`.

Chains two existing tools — `get_product` (to look up each line item's
current price) and `create_order` (to persist the result) — doing the
subtotal/total arithmetic itself, so a caller only has to supply customer
+ product/count pairs instead of pre-computing subtotals by hand (and
risking the agent doing that arithmetic itself, inconsistently, in free
text).

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


class PlaceOrderItem(CrystallineModel):
    product_id: str
    count: int


class PlaceOrderInput(CrystallineModel):
    id: str
    customer_id: str
    items: list[PlaceOrderItem]


def build_skill(project: Project) -> Skill:
    get_product = project.tools.get_tool("get_product")
    create_order = project.tools.get_tool("create_order")
    if get_product is None or create_order is None:
        raise RuntimeError(
            "place_order skill requires get_product/create_order tools; "
            "call project.sync_tools() first"
        )

    async def place_order(data: PlaceOrderInput) -> Any:
        line_items: list[dict[str, Any]] = []
        total = 0.0
        for item in data.items:
            lookup = get_product.input_model(id=item.product_id)
            product = await get_product.invoke(lookup)
            if product is None:
                raise ValueError(f"No such product: {item.product_id!r}")
            subtotal = product.price * item.count
            total += subtotal
            line_items.append(
                {
                    "product_id": item.product_id,
                    "count": item.count,
                    "subtotal": subtotal,
                }
            )

        return await create_order.invoke(
            create_order.input_model(
                id=data.id,
                customer_id=data.customer_id,
                items=line_items,
                total=total,
            )
        )

    return Skill(
        name="place_order",
        description=(
            "Place an order: looks up each product's current price, computes "
            "subtotals and the total, and creates the order. Prefer this over "
            "calling create_order directly with hand-computed totals."
        ),
        input_model=PlaceOrderInput,
        handler=place_order,
        output_model=project.schema.get("Order"),
        scope="Order:create",
    )
