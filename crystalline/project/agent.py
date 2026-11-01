"""Build/describe a project's agent configuration, and construct the
concrete `crystalline.agents.Agent` it names.

Mirrors `crystalline.project.storage`'s relationship to
`crystalline.storage`: a project file's `agent:` section is just
`{type: <backend>, ...}`, with everything besides `type` passed through
as keyword arguments to that backend's constructor (e.g. `model` for
`claude_code`). Unlike storage, the config isn't held as a live object on
`Project` — an `Agent` carries async connection state that doesn't belong
on a static config object, so `Project.agent_config` stays a plain dict
and `build_agent()` constructs a real `Agent` only when something (the
CLI, eventually the router) is actually about to start a session.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from crystalline.agents import Agent, ClaudeCodeAgent

from .agent_wiring import system_prompt_for, wire_tools
from .monitoring_wiring import MonitoredAgent

if TYPE_CHECKING:
    from .project import Project

AgentFactory = Callable[..., Agent]

DEFAULT_AGENT_TYPE = "claude_code"

_AGENT_BACKENDS: dict[str, AgentFactory] = {
    "claude_code": ClaudeCodeAgent,
}


def register_agent_backend(name: str, factory: AgentFactory) -> None:
    """Make `build_agent`/project files able to use `{"type": name, ...}`."""
    _AGENT_BACKENDS[name] = factory


def build_agent_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a project file's `agent:` section; defaults to Claude Code."""
    if config is None:
        return {"type": DEFAULT_AGENT_TYPE}
    return dict(config)


def resolve_agent_paths(config: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """Resolve a relative `cwd` property against `base_dir` (the project
    file's directory), same convention as `crystalline.project.storage.
    resolve_storage_paths`'s `path` — so a project's agent is confined to
    a directory relative to the project file, not to wherever the
    process launching the CLI happens to have its own cwd. Without this,
    a `ClaudeCodeAgent`'s filesystem-backed tools (Read/Write/Bash, ...)
    default to the *process's* cwd, which for a project meant to be run
    in "user mode" (not from within this repo) could be the whole
    framework source tree rather than just that project's own files."""
    config = dict(config)
    cwd = config.get("cwd")
    if isinstance(cwd, str) and not Path(cwd).is_absolute():
        config["cwd"] = str(base_dir / cwd)
    return config


def describe_agent_config(
    config: dict[str, Any], base_dir: Path | None = None
) -> dict[str, Any]:
    """Inverse of `build_agent_config`, for saving a project back out.

    `cwd` is always absolute (`resolve_agent_paths` resolved it that way
    on load) — when `base_dir` (the directory the project file is being
    saved *to*) is given and `cwd` sits under it, write it back out
    relative to `base_dir`, the same convention `load_project` reads it
    with (mirrors `crystalline.project.storage.describe_storage`)."""
    config = dict(config)
    cwd = config.get("cwd")
    if base_dir is not None and isinstance(cwd, str):
        absolute = Path(cwd)
        if absolute.is_absolute() and absolute.is_relative_to(base_dir):
            config["cwd"] = str(absolute.relative_to(base_dir))
    return config


def build_agent(
    project: Project, *, name: str | None = None, session_id: str | None = None
) -> Agent:
    """Construct the `Agent` named by `project.agent_config`, with its
    system prompt and tools already wired (`crystalline.project.
    agent_wiring`). If `project.monitoring_store` is set, the result is
    wrapped in a `MonitoredAgent` recording into it under `session_id` —
    the caller (the CLI) owns that session's lifecycle via
    `start_monitoring_session`/`end_monitoring_session`; `build_agent`
    itself never starts or ends one."""
    config = dict(project.agent_config)
    agent_type = config.pop("type", DEFAULT_AGENT_TYPE)
    factory = _AGENT_BACKENDS.get(agent_type)
    if factory is None:
        raise ValueError(f"Unknown agent type: {agent_type!r}")

    agent = factory(
        name=name or project.name,
        system_prompt=system_prompt_for(project),
        **config,
    )
    wire_tools(agent, project)
    if project.monitoring_store is not None:
        agent = MonitoredAgent(agent, project.monitoring_store, session_id=session_id)
    return agent
