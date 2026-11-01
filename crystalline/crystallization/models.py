"""Data shapes a `crystalline.crystallization` plugin produces.

A proposal is a set of file changes under a project's `extensions_dir` —
see `crystalline.project.extensions` for the `tool_*.py`/`skill_*.py`
convention these target. Crystallization doesn't invent a new artifact
kind; it generates the same kind of file a human would hand-write.
Pydantic (not a dataclass), since a `CrystallizationProposal` crosses the
CLI boundary: a plugin builds it, the CLI renders/stores it, and only
after explicit human approval does `crystalline.project.
crystallization_wiring.apply_crystallization` write it to disk.
"""

from __future__ import annotations

from typing import Literal

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


class CrystallizationProposal(CrystallineModel):
    plugin: str
    title: str
    rationale: str
    changes: list[FileChange] = []
