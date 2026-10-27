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


def describe_agent_config(config: dict[str, Any]) -> dict[str, Any]:
    """Inverse of `build_agent_config`, for saving a project back out."""
    return dict(config)


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
