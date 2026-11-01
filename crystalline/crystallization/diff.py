"""Rendering a `CrystallizationProposal` as literal unified diffs, so a
human can review exactly what text would land on disk before approving
anything — no custom diff format, just `difflib` against whatever's
currently at each `FileChange.path`.
"""

from __future__ import annotations

import difflib

from .models import CrystallizationProposal


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
