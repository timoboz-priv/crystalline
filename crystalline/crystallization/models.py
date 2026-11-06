"""Data shapes a `crystalline.crystallization` plugin produces.

A proposal is a set of file changes under a project's `extensions_dir` —
see `crystalline.project.extensions` for the `tool_*.py`/`skill_*.py`
convention these target — plus, optionally, a set of schema-type changes.
Crystallization doesn't invent a new artifact kind for either: a file
change is the same kind of file a human would hand-write, and a schema
change is the same `{field_name: type_expr}` shape a human would add to
a project file's `schema:` section (see `crystalline.project.fields`) —
just proposed by a plugin instead of typed by hand. Pydantic (not a
dataclass), since a `CrystallizationProposal` crosses the CLI boundary: a
plugin builds it, the CLI renders/stores it, and only after explicit
human approval does `crystalline.project.
crystallization_wiring.apply_crystallization` write it out.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import model_validator

from crystalline.schema import CrystallineModel


class FileChange(CrystallineModel):
    path: str
    """Relative to the project's `extensions_dir` — never an absolute
    path or one escaping that directory (enforced by
    `crystallization_wiring.apply_crystallization`, not here)."""
    action: Literal["create", "modify", "delete"]
    content: str | None = None
    """Required for `create`/`modify`; must be `None` for `delete`."""

    @model_validator(mode="after")
    def _content_matches_action(self) -> FileChange:
        if self.action == "delete" and self.content is not None:
            raise ValueError("content must be None for a delete FileChange")
        if self.action != "delete" and self.content is None:
            raise ValueError(f"content is required for a {self.action!r} FileChange")
        return self


class SchemaChange(CrystallineModel):
    type_name: str
    """The name the type would be registered under in `project.schema` —
    same namespace as a project file's `schema:` section keys."""
    action: Literal["create", "modify", "delete"]
    field_spec: dict[str, Any] | None = None
    """Same `{field_name: type_expr_or_entry}` shape
    `crystalline.project.fields.build_model_from_field_spec` compiles —
    required for `create`/`modify`; must be `None` for `delete`. Give the
    type an `id: str` field only if it should be an independently stored
    entity (and get its own CRUD tools); omit it for a nested value
    object, same distinction `crystalline.tools.crud` already draws."""

    @model_validator(mode="after")
    def _field_spec_matches_action(self) -> SchemaChange:
        if self.action == "delete" and self.field_spec is not None:
            raise ValueError("field_spec must be None for a delete SchemaChange")
        if self.action != "delete" and self.field_spec is None:
            raise ValueError(f"field_spec is required for a {self.action!r} SchemaChange")
        return self


class CrystallizationProposal(CrystallineModel):
    plugin: str
    title: str
    rationale: str
    changes: list[FileChange] = []
    schema_changes: list[SchemaChange] = []
