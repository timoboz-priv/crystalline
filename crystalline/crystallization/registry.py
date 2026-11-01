"""`CrystallizationRegistry`: name -> `CrystallizationPlugin`, the plug-in
point `/crystallize <mode>` dispatches through. Same shape as
`crystalline.cli.commands.CommandRegistry` — a plain dict registry, no
collision protection beyond "last registration wins", since plugins are
registered once at startup by `crystalline.project.
crystallization_wiring.build_crystallization_registry`, not by
untrusted input.
"""

from __future__ import annotations

from collections.abc import Iterator

from .plugin import CrystallizationPlugin


class CrystallizationRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, CrystallizationPlugin] = {}

    def register(self, plugin: CrystallizationPlugin) -> CrystallizationPlugin:
        self._plugins[plugin.name] = plugin
        return plugin

    def get(self, name: str) -> CrystallizationPlugin | None:
        return self._plugins.get(name)

    def __iter__(self) -> Iterator[CrystallizationPlugin]:
        return iter(self._plugins.values())

    def __len__(self) -> int:
        return len(self._plugins)
