"""Human-readable rendering of a `Project`, shared by the demo script and the CLI."""

from __future__ import annotations

from .project import Project
from .storage import describe_storage


def describe_project(project: Project) -> str:
    lines = [
        f"name:        {project.name}",
        f"version:     {project.version}",
        f"description: {project.description}",
        f"storage:     {describe_storage(project.storage)}",
        f"agent:       {project.agent_config}",
        f"security:    roles={project.security.roles}",
        f"tools:       {len(project.tools)} ({len(project.skills)} skills)",
        f"properties:  {project.properties}",
        "schema:",
    ]
    for type_name, model in project.schema.types.items():
        lines.append(f"  {type_name}")
        for field_name, info in model.model_fields.items():
            if info.is_required():
                required = "required"
            else:
                # get_default(call_default_factory=True) resolves fields
                # declared with a `default_factory` too, not just `default`.
                required = f"default={info.get_default(call_default_factory=True)!r}"
            lines.append(f"    - {field_name}: {info.annotation} ({required})")
    return "\n".join(lines)
