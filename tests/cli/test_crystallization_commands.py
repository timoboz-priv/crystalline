import asyncio
from pathlib import Path

from crystalline.cli.commands import CLIContext, default_commands
from crystalline.crystallization import CrystallizationProposal, FileChange
from crystalline.monitoring import Session, SQLiteSessionStore, Turn
from crystalline.project import Project


def _project_with_monitoring(tmp_path):
    extensions_dir = tmp_path / "extensions"
    extensions_dir.mkdir()
    store = SQLiteSessionStore(":memory:")
    store.start_session(Session(id="s1", project_name="demo"))
    store.start_turn(Turn(id="t1", session_id="s1", total_cost_usd=0.03))
    return Project("demo", "0.1.0", monitoring_store=store, extensions_dir=str(extensions_dir))


def test_cost_without_monitoring_configured(capsys):
    command = default_commands.get("cost")
    ctx = CLIContext(
        project=Project("demo", "0.1.0"), agent=object(), commands=default_commands,
        session_id="s1",
    )
    assert command.handler(ctx, []) is True
    out = capsys.readouterr().out
    assert "isn't configured" in out


def test_cost_renders_turn_rows(tmp_path, capsys):
    command = default_commands.get("cost")
    project = _project_with_monitoring(tmp_path)
    ctx = CLIContext(
        project=project, agent=object(), commands=default_commands, session_id="s1"
    )
    assert command.handler(ctx, []) is True
    out = capsys.readouterr().out
    assert "t1" in out


def test_crystallize_without_args_shows_usage(capsys):
    command = default_commands.get("crystallize")
    ctx = CLIContext(project=Project("demo", "0.1.0"), agent=object(), commands=default_commands)
    assert asyncio.run(command.handler(ctx, [])) is True
    out = capsys.readouterr().out
    assert "Usage: /crystallize" in out


def test_crystallize_surfaces_run_crystallization_errors(tmp_path, capsys, monkeypatch):
    from crystalline.cli import commands as commands_module

    async def fake_run_crystallization(*args, **kwargs):
        raise RuntimeError("monitoring not configured")

    monkeypatch.setattr(commands_module, "run_crystallization", fake_run_crystallization)

    command = default_commands.get("crystallize")
    ctx = CLIContext(
        project=_project_with_monitoring(tmp_path),
        agent=object(),
        commands=default_commands,
        session_id="s1",
    )
    assert asyncio.run(command.handler(ctx, ["session"])) is True
    out = capsys.readouterr().out
    assert "monitoring not configured" in out


def test_crystallize_none_proposal_reports_nothing_to_do(tmp_path, capsys, monkeypatch):
    from crystalline.cli import commands as commands_module

    async def fake_run_crystallization(*args, **kwargs):
        return None

    monkeypatch.setattr(commands_module, "run_crystallization", fake_run_crystallization)

    command = default_commands.get("crystallize")
    ctx = CLIContext(
        project=_project_with_monitoring(tmp_path),
        agent=object(),
        commands=default_commands,
        session_id="s1",
    )
    assert asyncio.run(command.handler(ctx, ["session"])) is True
    out = capsys.readouterr().out
    assert "Nothing to crystallize" in out


_PROPOSAL = CrystallizationProposal(
    plugin="session",
    title="Dashboard skill",
    rationale="Chains a few tool calls together.",
    changes=[FileChange(path="skill_dashboard.py", action="create", content="x = 1\n")],
)


def _patch_run_crystallization(monkeypatch, commands_module):
    async def fake_run_crystallization(*args, **kwargs):
        return _PROPOSAL

    monkeypatch.setattr(commands_module, "run_crystallization", fake_run_crystallization)


def test_crystallize_rejecting_the_proposal_writes_nothing(tmp_path, capsys, monkeypatch):
    from crystalline.cli import commands as commands_module

    _patch_run_crystallization(monkeypatch, commands_module)

    async def fake_confirm(message: str) -> bool:
        return False

    monkeypatch.setattr(commands_module, "_confirm", fake_confirm)

    project = _project_with_monitoring(tmp_path)
    ctx = CLIContext(
        project=project, agent=object(), commands=default_commands, session_id="s1"
    )
    command = default_commands.get("crystallize")
    assert asyncio.run(command.handler(ctx, ["session"])) is True
    out = capsys.readouterr().out
    assert "Discarded." in out
    assert not Path(project.extensions_dir, "skill_dashboard.py").exists()


def test_crystallize_approving_the_proposal_writes_the_file(tmp_path, capsys, monkeypatch):
    from crystalline.cli import commands as commands_module

    _patch_run_crystallization(monkeypatch, commands_module)

    async def fake_confirm(message: str) -> bool:
        return True

    monkeypatch.setattr(commands_module, "_confirm", fake_confirm)

    project = _project_with_monitoring(tmp_path)
    # No project_path set, so the post-approval /reload attempt fails
    # gracefully (reported, not raised) rather than needing a full
    # project file + working agent for this test.
    ctx = CLIContext(
        project=project, agent=object(), commands=default_commands, session_id="s1"
    )
    command = default_commands.get("crystallize")
    assert asyncio.run(command.handler(ctx, ["session"])) is True
    out = capsys.readouterr().out
    assert "Proposal applied" in out
    assert Path(project.extensions_dir, "skill_dashboard.py").read_text() == "x = 1\n"
