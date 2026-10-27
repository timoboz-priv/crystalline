"""Slash commands for the Crystalline CLI."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from rich.panel import Panel

from crystalline.agents import Agent
from crystalline.project import (
    Project,
    apply_extensions,
    build_agent,
    describe_project,
    load_project,
)
from crystalline.security import User, current_token, rebind_token

from .console import console, print_error, render_result

CommandHandler = Callable[["CLIContext", list[str]], "bool | Awaitable[bool]"]
"""A command handler returns False to stop the REPL, True to keep going.
May be a regular function or an async one — the REPL awaits the result
if it's awaitable."""


@dataclass
class CLIContext:
    project: Project
    agent: Agent
    commands: CommandRegistry
    history: list[str] = field(default_factory=list)
    """Every line submitted this session (commands and free text alike),
    in order — appended to by `run_repl`, read by `/history`."""
    project_path: str | None = None
    """Path `/reload` re-reads the project from. `None` means the REPL
    wasn't started from a project file, so reloading isn't possible."""
    session_id: str | None = None
    """The one `crystalline.monitoring` session id for this whole CLI
    invocation — set once by `run_repl`, reused by `/reload` so a rebuilt
    agent/router keep recording into the *same* session rather than
    starting a new one every reload."""


@dataclass
class Command:
    name: str
    description: str
    handler: CommandHandler


class CommandRegistry:
    """Name -> `Command` registry for CLI slash commands."""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(
        self, name: str, description: str = ""
    ) -> Callable[[CommandHandler], CommandHandler]:
        def decorator(handler: CommandHandler) -> CommandHandler:
            self._commands[name] = Command(
                name=name, description=description, handler=handler
            )
            return handler

        return decorator

    def get(self, name: str) -> Command | None:
        return self._commands.get(name)

    def __iter__(self):
        return iter(self._commands.values())


default_commands = CommandRegistry()


@default_commands.register("quit", "Exit the CLI.")
def _quit(ctx: CLIContext, args: list[str]) -> bool:
    return False


@default_commands.register("project", "Print the current project's properties.")
def _project(ctx: CLIContext, args: list[str]) -> bool:
    panel = Panel(describe_project(ctx.project), title="Project", border_style="cyan")
    console.print(panel)
    return True


@default_commands.register(
    "reload",
    "Reload the project (schema/storage/security/tools/skills/agent) from its config file.",
)
async def _reload(ctx: CLIContext, args: list[str]) -> bool:
    if ctx.project_path is None:
        print_error("No project file path available to reload from.")
        return True

    old_token = current_token()
    try:
        new_project = load_project(ctx.project_path)
        apply_extensions(new_project)

        # Re-derive the bound token from the *reloaded* security policy/
        # storage, not just carry the pre-reload one forward — otherwise a
        # role/scope edit a reload is meant to pick up wouldn't actually
        # take effect until the user logs out and back in.
        new_token = None
        if old_token is not None:
            user = new_project.storage.get(User, old_token.sub)
            if user is None or user.disabled:
                raise PermissionError(
                    f"User {old_token.sub!r} no longer exists or is disabled "
                    "in the reloaded project"
                )
            new_token = new_project.security.mint_token(user)

        new_agent = build_agent(new_project, session_id=ctx.session_id)
        await new_agent.connect()
    except Exception as exc:
        print_error(f"Reload failed: {exc}")
        return True

    # The new project/agent are already live at this point — a failure
    # tearing down the discarded old agent shouldn't undo the reload or
    # crash the REPL, just get reported as a (non-fatal) cleanup issue.
    try:
        await ctx.agent.disconnect()
    except Exception as exc:
        print_error(f"Old agent failed to disconnect cleanly: {exc}")

    ctx.project = new_project
    ctx.agent = new_agent
    if new_token is not None:
        rebind_token(new_token)
    console.print("Project reloaded.", style="success")
    return True


@default_commands.register("commands", "List all slash commands.")
def _commands(ctx: CLIContext, args: list[str]) -> bool:
    rows = [
        {"command": f"/{c.name}", "description": c.description}
        for c in sorted(ctx.commands, key=lambda c: c.name)
    ]
    render_result(rows)
    return True


@default_commands.register("whoami", "Print the current principal, roles, and scopes.")
def _whoami(ctx: CLIContext, args: list[str]) -> bool:
    token = current_token()
    if token is None:
        console.print("Not authenticated.", style="muted")
    else:
        render_result({"sub": token.sub, "roles": token.roles, "scopes": token.scopes})
    return True


@default_commands.register("history", "Print this session's prompt/command history.")
def _history(ctx: CLIContext, args: list[str]) -> bool:
    if not ctx.history:
        console.print("(empty)", style="muted")
        return True
    rows = [{"#": i, "entry": entry} for i, entry in enumerate(ctx.history, start=1)]
    render_result(rows)
    return True


@default_commands.register("tools", "List all registered tools.")
def _tools(ctx: CLIContext, args: list[str]) -> bool:
    tools = sorted(ctx.project.tools, key=lambda t: (t.group, t.name))
    if not tools:
        console.print("No tools registered.", style="muted")
        return True
    rows = [
        {
            "group": t.group,
            "name": t.name,
            "description": t.description,
            "scope": t.scope,
        }
        for t in tools
    ]
    render_result(rows)
    return True


@default_commands.register("skills", "List all registered skills.")
def _skills(ctx: CLIContext, args: list[str]) -> bool:
    skills = sorted(ctx.project.skills, key=lambda s: (s.group, s.name))
    if not skills:
        console.print("No skills registered.", style="muted")
        return True
    rows = [
        {
            "group": s.group,
            "name": s.name,
            "description": s.description,
            "scope": s.scope,
        }
        for s in skills
    ]
    render_result(rows)
    return True


async def _invoke_tool(ctx: CLIContext, tool_name: str, **kwargs: Any) -> bool:
    tool = ctx.project.tools.get_tool(tool_name)
    if tool is None:
        print_error(f"Tool {tool_name!r} is not available.")
        return True
    try:
        data = tool.input_model(**kwargs)
        result = await tool.invoke(data)
    except ValidationError as exc:
        print_error(f"Invalid arguments: {exc}")
        return True
    except (PermissionError, KeyError, ValueError) as exc:
        print_error(str(exc))
        return True
    render_result(result)
    return True


@default_commands.register("scopes", "List every scope string the system understands.")
async def _scopes(ctx: CLIContext, args: list[str]) -> bool:
    return await _invoke_tool(ctx, "list_scopes")


_USERS_USAGE = (
    "Usage: /users <list|get|create|set-roles|set-password|enable|disable|delete> "
    "[args...]"
)
_USERS_DESCRIPTION = (
    "Manage users: list/get/create/set-roles/set-password/enable/disable/delete."
)


@default_commands.register("users", _USERS_DESCRIPTION)
async def _users(ctx: CLIContext, args: list[str]) -> bool:
    if not args:
        console.print(_USERS_USAGE, style="muted")
        return True
    action, *rest = args

    if action == "list":
        return await _invoke_tool(ctx, "list_users")

    if action == "get":
        if not rest:
            console.print("Usage: /users get <id>", style="muted")
            return True
        return await _invoke_tool(ctx, "get_user", id=rest[0])

    if action == "create":
        if len(rest) < 2:
            usage = "Usage: /users create <id> <password> [role ...]"
            console.print(usage, style="muted")
            return True
        user_id, password, *roles = rest
        return await _invoke_tool(
            ctx, "create_user", id=user_id, password=password, roles=roles
        )

    if action == "set-roles":
        if not rest:
            console.print("Usage: /users set-roles <id> [role ...]", style="muted")
            return True
        user_id, *roles = rest
        return await _invoke_tool(ctx, "update_user", id=user_id, roles=roles)

    if action == "set-password":
        if len(rest) != 2:
            console.print("Usage: /users set-password <id> <password>", style="muted")
            return True
        user_id, password = rest
        return await _invoke_tool(ctx, "update_user", id=user_id, password=password)

    if action in ("enable", "disable"):
        if not rest:
            console.print(f"Usage: /users {action} <id>", style="muted")
            return True
        return await _invoke_tool(
            ctx, "update_user", id=rest[0], disabled=(action == "disable")
        )

    if action == "delete":
        if not rest:
            console.print("Usage: /users delete <id>", style="muted")
            return True
        return await _invoke_tool(ctx, "delete_user", id=rest[0])

    console.print(_USERS_USAGE, style="muted")
    return True


_ROLES_USAGE = "Usage: /roles <list|get|create|update|delete> [args...]"


@default_commands.register("roles", "Manage roles: list/get/create/update/delete.")
async def _roles(ctx: CLIContext, args: list[str]) -> bool:
    if not args:
        console.print(_ROLES_USAGE, style="muted")
        return True
    action, *rest = args

    if action == "list":
        return await _invoke_tool(ctx, "list_roles")

    if action == "get":
        if not rest:
            console.print("Usage: /roles get <name>", style="muted")
            return True
        return await _invoke_tool(ctx, "get_role", name=rest[0])

    if action in ("create", "update"):
        if not rest:
            console.print(f"Usage: /roles {action} <name> [scope ...]", style="muted")
            return True
        name, *scopes = rest
        tool_name = "create_role" if action == "create" else "update_role"
        return await _invoke_tool(ctx, tool_name, name=name, scopes=scopes)

    if action == "delete":
        if not rest:
            console.print("Usage: /roles delete <name>", style="muted")
            return True
        return await _invoke_tool(ctx, "delete_role", name=rest[0])

    console.print(_ROLES_USAGE, style="muted")
    return True
