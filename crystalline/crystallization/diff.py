"""Rendering a `CrystallizationProposal` as literal unified diffs, so a
human can review exactly what text would land on disk before approving
anything — no custom diff format, just `difflib` against whatever's
currently at each `FileChange.path`/`SchemaChange.type_name`'s current
state, handed in as plain data (`existing_files`/`existing_field_specs`)
rather than read from a live `Project` here — same reason `diff.py` never
imports `crystalline.project`: the project-reading part is the caller's
job (`crystalline.project.crystallization_wiring`), this module only
turns "before" + "after" text into a diff.
"""

from __future__ import annotations

import difflib
import json
from typing import Any

from .models import CrystallizationProposal

_KNOWN_KIND_PREFIXES = {"tool_": "tool", "skill_": "skill"}


def _kind_of(path: str) -> str:
    for prefix, kind in _KNOWN_KIND_PREFIXES.items():
        if path.startswith(prefix):
            return kind
    return "other"


def _field_spec_json(field_spec: dict[str, Any] | None) -> str:
    return "" if field_spec is None else json.dumps(field_spec, indent=2, sort_keys=True) + "\n"


def summarize_changes(
    proposal: CrystallizationProposal,
    existing_files: dict[str, str],
    existing_field_specs: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """One condensed row per `FileChange`/`SchemaChange` — path/type name,
    entity kind (`tool`/`skill`/`other`/`schema`), action, and a `+added
    -removed` line-count size — for a quick glance at a proposal's shape
    before expanding into `render_diff`'s full unified diffs.
    """
    existing_field_specs = existing_field_specs or {}
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
    for change in proposal.schema_changes:
        before_fields = set(existing_field_specs.get(change.type_name, {}))
        if change.action == "delete":
            size = f"-{len(before_fields)}"
        elif not before_fields:
            # A true create (nothing registered under this name yet) —
            # branching on `before_fields` rather than trusting
            # `change.action == "create"` matters because
            # `apply_crystallization` treats create/modify identically
            # (`register(..., replace=True)` either way): a `create`
            # against a name that already exists silently clobbers it,
            # and should be sized like the modify it actually is, not
            # reported as a pure addition.
            size = f"+{len(change.field_spec or {})}"
        else:
            after_fields = set(change.field_spec or {})
            size = f"+{len(after_fields - before_fields)} -{len(before_fields - after_fields)}"
        rows.append(
            {
                "path": change.type_name,
                "kind": "schema",
                "action": change.action,
                "size": size,
            }
        )
    return rows


def render_diff(
    proposal: CrystallizationProposal,
    existing_files: dict[str, str],
    existing_field_specs: dict[str, dict[str, Any]] | None = None,
) -> list[tuple[str, str]]:
    """One `(path, unified_diff_text)` per `FileChange`, then one per
    `SchemaChange`, in order. `existing_files` maps a `FileChange.path`
    to its current on-disk content; `existing_field_specs` maps a
    `SchemaChange.type_name` to its current `{field: type_expr}` spec.
    A path/name absent from either is treated as not existing yet (empty
    "before" text), the expected case for `create`. A schema change's
    diff is of its field spec rendered as JSON, not of any compiled
    Python — `crystalline.crystallization` never compiles field specs
    into types itself (see this package's `session_replay.py` docstring)."""
    existing_field_specs = existing_field_specs or {}
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
    for change in proposal.schema_changes:
        before = _field_spec_json(existing_field_specs.get(change.type_name))
        after = "" if change.action == "delete" else _field_spec_json(change.field_spec)
        diff_lines = difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/schema/{change.type_name}",
            tofile="/dev/null" if change.action == "delete" else f"b/schema/{change.type_name}",
        )
        rendered.append((f"schema:{change.type_name}", "".join(diff_lines)))
    return rendered
