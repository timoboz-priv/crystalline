"""Load/save a `Project` to a JSON or YAML config file.

The config object (`Project`) is the source of truth; these are thin
(de)serializers on top of it, dispatching on file extension.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from crystalline.security import RESERVED_TYPE_NAMES

from .agent import build_agent_config, describe_agent_config
from .extensions import resolve_extensions_dir
from .fields import build_model_from_field_spec, field_spec_from_model
from .monitoring_config import build_monitoring_store, describe_monitoring_store
from .project import Project
from .security import build_security_policy, describe_security_policy, seed_users
from .storage import build_storage, describe_storage, resolve_storage_paths


def project_to_dict(project: Project, *, base_dir: Path | None = None) -> dict[str, Any]:
    return {
        "name": project.name,
        "version": project.version,
        "description": project.description,
        "schema": {
            type_name: field_spec_from_model(model, project.schema)
            for type_name, model in project.schema.types.items()
            if type_name not in RESERVED_TYPE_NAMES
        },
        "storage": describe_storage(project.storage, base_dir=base_dir),
        "security": describe_security_policy(project.security),
        "agent": describe_agent_config(project.agent_config),
        "extensions": project.extensions_dir,
        "monitoring": describe_monitoring_store(project.monitoring_store, base_dir=base_dir),
        "properties": project.properties,
    }


def project_from_dict(data: dict[str, Any], *, base_dir: Path | None = None) -> Project:
    """`base_dir` (the project file's directory, when loading from one)
    is used to resolve a relative storage `path`, a relative `monitoring`
    `path`, and a relative `extensions:` directory, against the file
    rather than the process's current working directory."""
    storage_config = data.get("storage")
    if storage_config is not None and base_dir is not None:
        storage_config = resolve_storage_paths(storage_config, base_dir)

    monitoring_config = data.get("monitoring")
    if monitoring_config is not None and base_dir is not None:
        monitoring_config = resolve_storage_paths(monitoring_config, base_dir)

    project = Project(
        name=data["name"],
        version=data["version"],
        description=data.get("description"),
        storage=build_storage(storage_config),
        security=build_security_policy(data.get("security")),
        agent_config=build_agent_config(data.get("agent")),
        extensions_dir=resolve_extensions_dir(data.get("extensions"), base_dir),
        monitoring_store=build_monitoring_store(monitoring_config),
    )
    for type_name, field_spec in (data.get("schema") or {}).items():
        if type_name in RESERVED_TYPE_NAMES:
            raise ValueError(
                f"{type_name!r} is a reserved, framework-provided type and cannot "
                "be redeclared in a project's schema section"
            )
        model = build_model_from_field_spec(type_name, field_spec, project.schema)
        project.schema.register(model, name=type_name)
    for key, value in (data.get("properties") or {}).items():
        project.set_property(key, value)

    seed_users(project.storage, data.get("users"))
    project.sync_tools()
    return project


def save_project(project: Project, path: str | Path) -> None:
    path = Path(path)
    data = project_to_dict(project, base_dir=path.resolve().parent)
    if path.suffix in (".yaml", ".yml"):
        path.write_text(yaml.safe_dump(data, sort_keys=False))
    elif path.suffix == ".json":
        path.write_text(json.dumps(data, indent=2))
    else:
        raise ValueError(f"Unsupported project file extension: {path.suffix!r}")


def load_project(path: str | Path) -> Project:
    path = Path(path)
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    elif path.suffix == ".json":
        data = json.loads(text)
    else:
        raise ValueError(f"Unsupported project file extension: {path.suffix!r}")
    return project_from_dict(data, base_dir=path.resolve().parent)
