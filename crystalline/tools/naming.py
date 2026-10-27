"""PascalCase type names -> snake_case tool-name fragments."""

from __future__ import annotations

import re

_BOUNDARY_RE = re.compile(r"(?<!^)(?=[A-Z])")


def to_snake_case(name: str) -> str:
    """`"OrderItem"` -> `"order_item"`, `"Customer"` -> `"customer"`."""
    return _BOUNDARY_RE.sub("_", name).lower()
