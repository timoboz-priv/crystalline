"""Rendering a `CrystallizationProposal` as literal unified diffs, so a
human can review exactly what text would land on disk before approving
anything — no custom diff format, just `difflib` against whatever's
currently at each `FileChange.path`.
"""

from __future__ import annotations

import difflib
from typing import Any

from .models import CrystallizationProposal

_KNOWN_KIND_PREFIXES = {"tool_": "tool", "skill_": "skill"}


def _kind_of(path: str) -> str:
    for prefix, kind in _KNOWN_KIND_PREFIXES.items():
        if path.startswith(prefix):
            return kind
    return "other"


def summarize_changes(
    proposal: CrystallizationProposal, existing_files: dict[str, str]
) -> list[dict[str, Any]]:
    """One condensed row per `FileChange` — path, entity kind (`tool`/
    `skill`/`other`, from the filename prefix), action, and a `+added
    -removed` line-count size — for a quick glance at a proposal's shape
    before expanding into `render_diff`'s full unified diffs.
    """
    rows: list[dict[str, Any]] = []
    for change in proposal.changes:
        before_lines = existing_files.get(change.path, "").splitlines()
        if change.action == "delete":
            size = f"-{len(before_lines)}"
        elif change.action == "create":
            size = f"+{len((change.content or '').splitlines())}"
        else:
            after_lines = (change.content or "").splitlines()
            matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines)
            added = removed = 0
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag in ("replace", "insert"):
                    added += j2 - j1
                if tag in ("replace", "delete"):
                    removed += i2 - i1
            size = f"+{added} -{removed}"
        rows.append(
            {
                "path": change.path,
                "kind": _kind_of(change.path),
                "action": change.action,
                "size": size,
            }
        )
    return rows


def render_diff(
    proposal: CrystallizationProposal, existing_files: dict[str, str]
) -> list[tuple[str, str]]:
    """One `(path, unified_diff_text)` per `FileChange` in `proposal`,
    in order. `existing_files` maps a `FileChange.path` to its current
    on-disk content; a path absent from it is treated as not existing
    yet (empty "before" text), which is the expected case for `create`.
    """
    rendered: list[tuple[str, str]] = []
    for change in proposal.changes:
        before = existing_files.get(change.path, "")
        after = "" if change.action == "delete" else (change.content or "")
        diff_lines = difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{change.path}",
            tofile="/dev/null" if change.action == "delete" else f"b/{change.path}",
        )
        rendered.append((change.path, "".join(diff_lines)))
    return rendered
