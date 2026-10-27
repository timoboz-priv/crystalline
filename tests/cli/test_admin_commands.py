import asyncio

from crystalline.cli.commands import CLIContext, default_commands
from crystalline.project import Project
from crystalline.project.fields import build_model_from_field_spec
from crystalline.security import Token, bind_token


def _project() -> Project:
    project = Project("demo", "0.1.0")
    Customer = build_model_from_field_spec(
        "Customer", {"id": "str", "name": "str"}, project.schema
    )
    project.schema.register(Customer, name="Customer")
    project.sync_tools()
    return project


def _ctx(project: Project) -> CLIContext:
    return CLIContext(project=project, agent=object(), commands=default_commands)


def _run_as_admin(coro):
    async def wrapped():
        with bind_token(Token(sub="admin", scopes=["*:*"])):
            return await coro

    return asyncio.run(wrapped())


def test_tools_command_lists_storage_and_admin_groups(capsys):
    ctx = _ctx(_project())
    command = default_commands.get("tools")

    assert command.handler(ctx, []) is True

    out = capsys.readouterr().out
    assert "storage" in out
    assert "admin" in out
    assert "create_customer" in out
    assert "create_user" in out


def test_tools_command_with_no_tools(capsys):
    ctx = _ctx(Project("empty", "0.1.0"))
    command = default_commands.get("tools")

    assert command.handler(ctx, []) is True
    assert "No tools registered." in capsys.readouterr().out


def test_skills_command_with_no_skills(capsys):
    ctx = _ctx(_project())
    command = default_commands.get("skills")

    assert command.handler(ctx, []) is True
    assert "No skills registered." in capsys.readouterr().out


def test_skills_command_lists_registered_skills(capsys):
    from crystalline.skills import Skill

    project = _project()

    async def handler(data):
        return data

    Customer = project.schema.get("Customer")
    project.skills.add_tool(
        Skill(
            name="greet_customer",
            description="Say hello to a customer.",
            input_model=Customer,
            handler=handler,
            scope="Customer:read",
        )
    )
    ctx = _ctx(project)
    command = default_commands.get("skills")

    assert command.handler(ctx, []) is True

    out = capsys.readouterr().out
    assert "skills" in out
    assert "greet_customer" in out
    assert "Customer:read" in out


def test_scopes_command(capsys):
    ctx = _ctx(_project())
    command = default_commands.get("scopes")

    assert _run_as_admin(command.handler(ctx, [])) is True

    out = capsys.readouterr().out
    assert "Customer:create" in out
    assert "*:*" in out


def test_users_create_list_get_delete(capsys):
    ctx = _ctx(_project())
    users = default_commands.get("users")

    assert _run_as_admin(users.handler(ctx, ["create", "alice", "secret", "editor"])) is True
    out = capsys.readouterr().out
    assert "alice" in out
    assert "editor" in out

    assert _run_as_admin(users.handler(ctx, ["list"])) is True
    assert "alice" in capsys.readouterr().out

    assert _run_as_admin(users.handler(ctx, ["get", "alice"])) is True
    assert "alice" in capsys.readouterr().out

    assert _run_as_admin(users.handler(ctx, ["delete", "alice"])) is True
    assert "true" in capsys.readouterr().out.lower()

    assert _run_as_admin(users.handler(ctx, ["get", "alice"])) is True
    assert "None" in capsys.readouterr().out


def test_users_set_password_and_roles_and_disable(capsys):
    ctx = _ctx(_project())
    users = default_commands.get("users")

    _run_as_admin(users.handler(ctx, ["create", "bob", "pw1"]))
    capsys.readouterr()

    assert _run_as_admin(users.handler(ctx, ["set-password", "bob", "pw2"])) is True
    assert _run_as_admin(users.handler(ctx, ["set-roles", "bob", "viewer"])) is True
    out = capsys.readouterr().out
    assert "viewer" in out

    assert _run_as_admin(users.handler(ctx, ["disable", "bob"])) is True
    assert "true" in capsys.readouterr().out.lower()

    assert _run_as_admin(users.handler(ctx, ["enable", "bob"])) is True
    assert "false" in capsys.readouterr().out.lower()


def test_users_usage_messages(capsys):
    ctx = _ctx(_project())
    users = default_commands.get("users")

    assert _run_as_admin(users.handler(ctx, [])) is True
    assert "Usage: /users" in capsys.readouterr().out

    assert _run_as_admin(users.handler(ctx, ["bogus"])) is True
    assert "Usage: /users" in capsys.readouterr().out

    assert _run_as_admin(users.handler(ctx, ["get"])) is True
    assert "Usage: /users get" in capsys.readouterr().out


def test_roles_create_get_update_delete(capsys):
    ctx = _ctx(_project())
    roles = default_commands.get("roles")

    assert _run_as_admin(roles.handler(ctx, ["create", "support", "Order:read"])) is True
    out = capsys.readouterr().out
    assert "Order:read" in out

    assert _run_as_admin(roles.handler(ctx, ["get", "support"])) is True
    assert "Order:read" in capsys.readouterr().out

    assert _run_as_admin(
        roles.handler(ctx, ["update", "support", "Order:read", "Order:update"])
    ) is True
    out = capsys.readouterr().out
    assert "Order:update" in out

    assert _run_as_admin(roles.handler(ctx, ["list"])) is True
    assert "support" in capsys.readouterr().out

    assert _run_as_admin(roles.handler(ctx, ["delete", "support"])) is True
    assert "true" in capsys.readouterr().out.lower()


def test_roles_usage_messages(capsys):
    ctx = _ctx(_project())
    roles = default_commands.get("roles")

    assert _run_as_admin(roles.handler(ctx, [])) is True
    assert "Usage: /roles" in capsys.readouterr().out

    assert _run_as_admin(roles.handler(ctx, ["bogus"])) is True
    assert "Usage: /roles" in capsys.readouterr().out


def test_non_admin_sees_permission_error_not_crash(capsys):
    ctx = _ctx(_project())
    users = default_commands.get("users")

    async def run():
        with bind_token(Token(sub="ed", scopes=["*:read"])):
            return await users.handler(ctx, ["create", "x", "pw"])

    assert asyncio.run(run()) is True  # REPL keeps going even on a tool error
    assert "Error:" in capsys.readouterr().out
