"""Adapting a project's tools (and schema) onto a `crystalline.agents.Agent`.

This is the resolution of the open question flagged in
`docs/architecture.md`: `crystalline.tools.Tool` (project-level, Pydantic
input/output, security-scoped) and `crystalline.agents.Tool` (generic,
agent-facing, raw dict-in/dict-out MCP handler) are different shapes for
different audiences. `crystalline.project` is where they meet, since it's
the only thing that knows about both.
"""

from __future__ import annotations

import json
from typing import Any

from crystalline.agents import Agent
from crystalline.agents import Tool as AgentTool
from crystalline.tools import Tool, to_jsonable

from .project import Project


def _to_agent_tool(tool: Tool) -> AgentTool:
    input_schema = tool.input_model.model_json_schema()

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        data = tool.input_model.model_validate(args)
        result = await tool.invoke(data)
        return {"content": [{"type": "text", "text": json.dumps(to_jsonable(result))}]}

    return AgentTool(
        name=tool.name,
        description=tool.description,
        input_schema=input_schema,
        handler=handler,
        enabled=tool.enabled,
        metadata={"group": tool.group},
    )


def wire_tools(agent: Agent, project: Project) -> None:
    """Add every tool in `project.tools` and `project.skills` to `agent`,
    adapted to the generic agent-facing `Tool` shape (a `Skill` already
    *is* a `Tool` subclass, so this needs no special-casing). Call after
    `project.sync_tools()` so generated CRUD/admin tools are included,
    and after any project-specific skills have been registered.
    """
    # `project.tools`/`project.skills` are each collision-protected within
    # their own registry, but `agent.add_tool` is a plain dict overwrite
    # with no protection of its own — so a skill named after an existing
    # tool (or vice versa) would otherwise silently replace the
    # agent-facing entry, including whatever `scope` it enforced.
    tool_names = {tool.name for tool in project.tools}
    colliding = sorted(skill.name for skill in project.skills if skill.name in tool_names)
    if colliding:
        raise ValueError(
            "Skill name(s) collide with existing tool name(s), refusing to "
            f"wire either onto the agent: {', '.join(colliding)}"
        )
    for tool in (*project.tools, *project.skills):
        agent.add_tool(_to_agent_tool(tool))


def system_prompt_for(project: Project) -> str:
    """A system prompt fragment describing a project's registered schema
    types and available tool/skill groups — the "wire schema into the
    agent" half of the equation, complementing the tool input schemas the
    model sees directly through MCP tool declarations."""
    type_names = ", ".join(project.schema) or "(none)"
    groups = sorted({tool.group for tool in (*project.tools, *project.skills)})
    groups = groups or ["(none)"]
    return (
        f"You are the assistant for the Crystalline project '{project.name}' "
        f"(v{project.version}). Registered schema types: {type_names}. "
        f"Available tool groups: {', '.join(groups)}."
    )
