from crystalline.cli.commands import CLIContext, default_commands
from crystalline.project import Project
from crystalline.security import Token, bind_token


def test_quit_is_registered_and_stops_the_repl():
    command = default_commands.get("quit")
    assert command is not None
    ctx = CLIContext(project=Project("demo", "0.1.0"), agent=object(), commands=default_commands)
    assert command.handler(ctx, []) is False


def test_project_command_prints_description(capsys):
    command = default_commands.get("project")
    assert command is not None
    project = Project("demo-shop", "0.1.0", description="a shop")
    ctx = CLIContext(project=project, agent=object(), commands=default_commands)

    assert command.handler(ctx, []) is True

    out = capsys.readouterr().out
    assert "demo-shop" in out
    assert "a shop" in out


def test_unknown_command_returns_none():
    assert default_commands.get("nope") is None


def test_commands_command_lists_all_commands(capsys):
    command = default_commands.get("commands")
    assert command is not None
    ctx = CLIContext(
        project=Project("demo", "0.1.0"), agent=object(), commands=default_commands
    )

    assert command.handler(ctx, []) is True

    out = capsys.readouterr().out
    assert "/quit" in out
    assert "Exit the CLI." in out
    assert "/project" in out
    assert "/commands" in out
    assert "/whoami" in out


def test_whoami_with_bound_token(capsys):
    command = default_commands.get("whoami")
    assert command is not None
    ctx = CLIContext(project=Project("demo", "0.1.0"), agent=object(), commands=default_commands)
    token = Token(sub="ada", roles=["editor"], scopes=["Customer:read"])

    with bind_token(token):
        assert command.handler(ctx, []) is True

    out = capsys.readouterr().out
    assert "sub" in out
    assert "ada" in out
    assert "editor" in out
    assert "Customer:read" in out


def test_whoami_without_bound_token(capsys):
    command = default_commands.get("whoami")
    assert command is not None
    ctx = CLIContext(project=Project("demo", "0.1.0"), agent=object(), commands=default_commands)

    assert command.handler(ctx, []) is True

    assert "Not authenticated." in capsys.readouterr().out


def test_history_empty_by_default(capsys):
    command = default_commands.get("history")
    assert command is not None
    ctx = CLIContext(project=Project("demo", "0.1.0"), agent=object(), commands=default_commands)

    assert command.handler(ctx, []) is True

    assert "(empty)" in capsys.readouterr().out


def test_history_lists_entries_in_order(capsys):
    command = default_commands.get("history")
    assert command is not None
    ctx = CLIContext(
        project=Project("demo", "0.1.0"),
        agent=object(),
        commands=default_commands,
        history=["hello", "/whoami"],
    )

    assert command.handler(ctx, []) is True

    out = capsys.readouterr().out
    assert "hello" in out
    assert "/whoami" in out


class _FakeAgent:
    def __init__(self, name: str = "fake") -> None:
        self.name = name
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False


_PROJECT_YAML = (
    "name: demo\nversion: '0.1.0'\nschema: {}\nproperties: {}\n"
)


def test_reload_without_project_path_reports_error(capsys):
    import asyncio

    command = default_commands.get("reload")
    assert command is not None
    ctx = CLIContext(
        project=Project("demo", "0.1.0"), agent=_FakeAgent(), commands=default_commands
    )

    result = asyncio.run(command.handler(ctx, []))

    assert result is True
    assert "No project file path available" in capsys.readouterr().out


def test_reload_swaps_in_a_freshly_loaded_project(tmp_path, capsys, monkeypatch):
    import asyncio

    from crystalline.cli import commands as commands_module

    path = tmp_path / "project.yaml"
    path.write_text(_PROJECT_YAML)

    # build_agent's "claude_code" backend spawns a real subprocess on
    # connect() — stub it out so this stays a fast, hermetic unit test.
    monkeypatch.setattr(commands_module, "build_agent", lambda project, **kwargs: _FakeAgent("new"))

    command = default_commands.get("reload")
    assert command is not None
    old_agent = _FakeAgent("old")
    old_project = Project("demo", "0.1.0")
    ctx = CLIContext(
        project=old_project,
        agent=old_agent,
        commands=default_commands,
        project_path=str(path),
    )

    result = asyncio.run(command.handler(ctx, []))

    assert result is True
    assert ctx.project is not old_project
    assert ctx.project.name == "demo"
    assert ctx.agent is not old_agent
    assert old_agent.connected is False
    assert "Project reloaded." in capsys.readouterr().out


def test_reload_passes_the_same_session_id_to_build_agent(tmp_path, monkeypatch):
    import asyncio

    from crystalline.cli import commands as commands_module

    path = tmp_path / "project.yaml"
    path.write_text(_PROJECT_YAML)

    calls = []

    def fake_build_agent(project, **kwargs):
        calls.append(kwargs)
        return _FakeAgent("new")

    monkeypatch.setattr(commands_module, "build_agent", fake_build_agent)

    command = default_commands.get("reload")
    assert command is not None
    ctx = CLIContext(
        project=Project("demo", "0.1.0"),
        agent=_FakeAgent("old"),
        commands=default_commands,
        project_path=str(path),
        session_id="s1",
    )

    asyncio.run(command.handler(ctx, []))

    assert calls[-1].get("session_id") == "s1"


def test_reload_failure_leaves_old_project_and_agent_in_place(tmp_path, capsys):
    import asyncio

    path = tmp_path / "project.yaml"
    path.write_text("name: demo\nversion: '0.1.0'\nschema:\n  User:\n    id: str\n")

    command = default_commands.get("reload")
    assert command is not None
    old_agent = _FakeAgent("old")
    old_project = Project("demo", "0.1.0")
    ctx = CLIContext(
        project=old_project,
        agent=old_agent,
        commands=default_commands,
        project_path=str(path),
    )

    result = asyncio.run(command.handler(ctx, []))

    assert result is True
    assert ctx.project is old_project
    assert ctx.agent is old_agent
    assert "Reload failed" in capsys.readouterr().out


class _FailingDisconnectAgent(_FakeAgent):
    async def disconnect(self) -> None:
        raise RuntimeError("transport already closed")


def test_reload_succeeds_even_if_old_agent_disconnect_fails(tmp_path, capsys, monkeypatch):
    import asyncio

    from crystalline.cli import commands as commands_module

    monkeypatch.setattr(commands_module, "build_agent", lambda project, **kwargs: _FakeAgent("new"))

    path = tmp_path / "project.yaml"
    path.write_text(_PROJECT_YAML)

    command = default_commands.get("reload")
    assert command is not None
    old_agent = _FailingDisconnectAgent("old")
    old_project = Project("demo", "0.1.0")
    ctx = CLIContext(
        project=old_project,
        agent=old_agent,
        commands=default_commands,
        project_path=str(path),
    )

    result = asyncio.run(command.handler(ctx, []))

    assert result is True
    # The new project/agent are already live and must not be rolled back
    # just because tearing down the discarded old agent failed.
    assert ctx.project is not old_project
    assert ctx.agent is not old_agent
    out = capsys.readouterr().out
    assert "disconnect cleanly" in out
    assert "Project reloaded." in out


def test_reload_rebinds_token_reflecting_updated_roles(tmp_path, monkeypatch):
    import asyncio

    from crystalline.cli import commands as commands_module
    from crystalline.security import Token, bind_token, current_token

    monkeypatch.setattr(commands_module, "build_agent", lambda project, **kwargs: _FakeAgent("new"))

    path = tmp_path / "project.yaml"
    path.write_text(
        "name: demo\nversion: '0.1.0'\nschema: {}\n"
        "users:\n  - id: alice\n    password: secret\n    roles: [viewer]\n"
        "properties: {}\n"
    )

    command = default_commands.get("reload")
    assert command is not None
    ctx = CLIContext(
        project=Project("demo", "0.1.0"),
        agent=_FakeAgent("old"),
        commands=default_commands,
        project_path=str(path),
    )
    old_token = Token(sub="alice", roles=["viewer"], scopes=["*:read"])

    # An admin promotes alice to admin in the project file before reloading.
    path.write_text(
        "name: demo\nversion: '0.1.0'\nschema: {}\n"
        "users:\n  - id: alice\n    password: secret\n    roles: [admin]\n"
        "properties: {}\n"
    )

    async def run() -> object:
        with bind_token(old_token):
            await command.handler(ctx, [])
            return current_token()

    new_token = asyncio.run(run())

    assert new_token is not None
    assert new_token.roles == ["admin"]
    assert "*:*" in new_token.scopes


def test_reload_fails_if_bound_user_no_longer_exists(tmp_path, capsys, monkeypatch):
    import asyncio

    from crystalline.cli import commands as commands_module
    from crystalline.security import Token, bind_token, current_token

    monkeypatch.setattr(commands_module, "build_agent", lambda project, **kwargs: _FakeAgent("new"))

    path = tmp_path / "project.yaml"
    path.write_text(_PROJECT_YAML)

    command = default_commands.get("reload")
    assert command is not None
    old_agent = _FakeAgent("old")
    old_project = Project("demo", "0.1.0")
    ctx = CLIContext(
        project=old_project,
        agent=old_agent,
        commands=default_commands,
        project_path=str(path),
    )
    old_token = Token(sub="ghost", roles=["viewer"], scopes=["*:read"])

    async def run() -> tuple[bool, object]:
        with bind_token(old_token):
            result = await command.handler(ctx, [])
            return result, current_token()

    result, token_after = asyncio.run(run())

    assert result is True
    assert ctx.project is old_project
    assert ctx.agent is old_agent
    assert token_after == old_token
    assert "Reload failed" in capsys.readouterr().out
