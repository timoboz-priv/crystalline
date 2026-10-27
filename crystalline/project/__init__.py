from .project import Project
# `Project` must be bound here, before `.agent` (below), since `.agent`
# transitively imports `.monitoring_wiring`, which imports
# `crystalline.events` — and `crystalline.events.router` does an
# *absolute* `from crystalline.project import Project` (unlike this
# package's own submodules, which use the relative `.project` form and
# so reach `project.py` directly regardless of where `__init__.py` has
# gotten to). Moving this import first guarantees `Project` already
# exists on this package's namespace by the time that absolute import
# runs, avoiding a circular-import `ImportError`.
from .agent import (
    build_agent,
    build_agent_config,
    describe_agent_config,
    register_agent_backend,
)
from .agent_wiring import system_prompt_for, wire_tools
from .describe import describe_project
from .extensions import (
    apply_extensions,
    load_skill_file,
    load_tool_file,
    resolve_extensions_dir,
)
from .fields import (
    FieldSpecError,
    build_model_from_field_spec,
    field_spec_from_model,
    resolve_type,
    type_to_expr,
)
from .io import load_project, project_from_dict, project_to_dict, save_project
from .monitoring_config import (
    build_monitoring_store,
    describe_monitoring_store,
    register_monitoring_backend,
)
from .monitoring_wiring import (
    MonitoredAgent,
    MonitoredRouter,
    build_router,
    claude_message_recorder,
    claude_turn_outcome,
    end_monitoring_session,
    start_monitoring_session,
)
from .security import build_security_policy, describe_security_policy, seed_users
from .storage import build_storage, describe_storage, register_storage_backend

__all__ = [
    "Project",
    "describe_project",
    "load_project",
    "save_project",
    "project_to_dict",
    "project_from_dict",
    "build_model_from_field_spec",
    "field_spec_from_model",
    "resolve_type",
    "type_to_expr",
    "FieldSpecError",
    "build_storage",
    "describe_storage",
    "register_storage_backend",
    "build_security_policy",
    "describe_security_policy",
    "seed_users",
    "wire_tools",
    "system_prompt_for",
    "build_agent",
    "build_agent_config",
    "describe_agent_config",
    "register_agent_backend",
    "apply_extensions",
    "load_tool_file",
    "load_skill_file",
    "resolve_extensions_dir",
    "build_monitoring_store",
    "describe_monitoring_store",
    "register_monitoring_backend",
    "MonitoredAgent",
    "MonitoredRouter",
    "build_router",
    "claude_message_recorder",
    "claude_turn_outcome",
    "start_monitoring_session",
    "end_monitoring_session",
]
