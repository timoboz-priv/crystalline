"""Cost/usage reporting over a session's `Turn`s — pure functions, no
storage dependency, so both the CLI (`/cost`, the status bar) and tests
can call them directly on a `list[Turn]` already fetched from a
`SessionStore`.
"""

from __future__ import annotations

from typing import Any

from .session import Turn


def session_cost_total(turns: list[Turn]) -> float:
    """Sum of every turn's `total_cost_usd`, treating `None` (a turn with
    no LLM cost, e.g. a direct tool/skill dispatch) as zero."""
    return sum(turn.total_cost_usd or 0.0 for turn in turns)


def _token_total(usage: dict[str, Any] | None) -> int | None:
    """Sum of every integer value in a `usage` dict. Deliberately
    shape-agnostic: the exact key names `ResultMessage.usage` uses
    (input/output/cache tokens, ...) aren't part of this module's
    contract, only that they're integers worth adding up."""
    if not usage:
        return None
    total = sum(value for value in usage.values() if isinstance(value, int))
    return total or None


def turn_rows(turns: list[Turn]) -> list[dict[str, Any]]:
    """One row per turn plus a trailing totals row, ready for
    `crystalline.cli.console.render_result`."""
    rows: list[dict[str, Any]] = [
        {
            "turn": turn.id[:8],
            "status": turn.status,
            "duration_ms": turn.duration_ms,
            "cost_usd": turn.total_cost_usd,
            "tokens": _token_total(turn.usage),
            "kind": turn.metadata.get("kind", "-"),
        }
        for turn in turns
    ]
    rows.append(
        {
            "turn": "TOTAL",
            "status": f"{len(turns)} turn(s)",
            "duration_ms": sum(turn.duration_ms or 0 for turn in turns),
            "cost_usd": session_cost_total(turns),
            "tokens": sum(_token_total(turn.usage) or 0 for turn in turns),
            "kind": "-",
        }
    )
    return rows
