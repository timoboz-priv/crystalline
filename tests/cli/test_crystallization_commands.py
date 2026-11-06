import asyncio
from pathlib import Path

from crystalline.cli.commands import CLIContext, default_commands
from crystalline.crystallization import CrystallizationProposal, FileChange, SchemaChange
from crystalline.monitoring import Session, SQLiteSessionStore, Turn
from crystalline.project import Project, save_project


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

    async def fake_prompt_choice(message: str, choices: dict[str, str]) -> str:
        return "r"

    monkeypatch.setattr(commands_module, "_prompt_choice", fake_prompt_choice)

    project = _project_with_monitoring(tmp_path)
    ctx = CLIContext(
        project=project, agent=object(), commands=default_commands, session_id="s1"
    )
    command = default_commands.get("crystallize")
    assert asyncio.run(command.handler(ctx, ["session"])) is True
    out = capsys.readouterr().out
    assert "Discarded." in out
    assert not Path(project.extensions_dir, "skill_dashboard.py").exists()


def test_crystallize_shows_condensed_summary_before_prompting(tmp_path, capsys, monkeypatch):
    from crystalline.cli import commands as commands_module

    _patch_run_crystallization(monkeypatch, commands_module)

    async def fake_prompt_choice(message: str, choices: dict[str, str]) -> str:
        return "r"

    monkeypatch.setattr(commands_module, "_prompt_choice", fake_prompt_choice)

    project = _project_with_monitoring(tmp_path)
    ctx = CLIContext(
        project=project, agent=object(), commands=default_commands, session_id="s1"
    )
    command = default_commands.get("crystallize")
    assert asyncio.run(command.handler(ctx, ["session"])) is True
    out = capsys.readouterr().out
    # The condensed row (kind inferred from filename, action, size) shows up
    # before the full unified diff would (full diff isn't shown at all here,
    # since the fake choice is "r" without ever picking "expand").
    assert "skill_dashboard.py" in out
    assert "skill" in out
    assert "create" in out
    assert "+1" in out
    assert "@@" not in out  # no full unified diff hunk header


def test_crystallize_expand_then_collapse_then_reject(tmp_path, capsys, monkeypatch):
    from crystalline.cli import commands as commands_module

    _patch_run_crystallization(monkeypatch, commands_module)

    choices_seen: list[str] = []
    responses = iter(["e", "c", "r"])

    async def fake_prompt_choice(message: str, choices: dict[str, str]) -> str:
        choices_seen.append(frozenset(choices))
        return next(responses)

    monkeypatch.setattr(commands_module, "_prompt_choice", fake_prompt_choice)

    project = _project_with_monitoring(tmp_path)
    ctx = CLIContext(
        project=project, agent=object(), commands=default_commands, session_id="s1"
    )
    command = default_commands.get("crystallize")
    assert asyncio.run(command.handler(ctx, ["session"])) is True
    out = capsys.readouterr().out
    assert "Discarded." in out
    assert "@@" in out  # the full diff was shown once, while expanded
    assert choices_seen[0] == frozenset({"a", "r", "e"})  # starts collapsed
    assert choices_seen[1] == frozenset({"a", "r", "c"})  # expand -> collapse offered
    assert choices_seen[2] == frozenset({"a", "r", "e"})  # collapse -> expand offered again


def test_crystallize_escapes_rich_markup_in_llm_generated_text(tmp_path, capsys, monkeypatch):
    # proposal.title/.rationale and a FileChange's path are all free text
    # that ultimately comes from the codegen agent's response — bracket
    # syntax in there must render literally, not be interpreted as rich
    # markup (which would otherwise let it swallow/style arbitrary parts
    # of the panel, same convention CLAUDE.md spells out for any other
    # dynamic text reaching the console).
    from crystalline.cli import commands as commands_module

    proposal = CrystallizationProposal(
        plugin="session",
        title="[red]Dashboard[/red]",
        rationale="[blue]Chains tool calls[/blue]",
        changes=[
            FileChange(path="skill_[bold]x[/bold].py", action="create", content="x = 1\n")
        ],
    )

    async def fake_run_crystallization(*args, **kwargs):
        return proposal

    monkeypatch.setattr(commands_module, "run_crystallization", fake_run_crystallization)

    responses = iter(["e", "r"])

    async def fake_prompt_choice(message: str, choices: dict[str, str]) -> str:
        return next(responses)

    monkeypatch.setattr(commands_module, "_prompt_choice", fake_prompt_choice)

    project = _project_with_monitoring(tmp_path)
    ctx = CLIContext(
        project=project, agent=object(), commands=default_commands, session_id="s1"
    )
    command = default_commands.get("crystallize")
    assert asyncio.run(command.handler(ctx, ["session"])) is True
    out = capsys.readouterr().out
    assert "[red]Dashboard[/red]" in out
    assert "[blue]Chains tool calls[/blue]" in out
    assert "skill_[bold]x[/bold].py" in out


def test_crystallize_approving_the_proposal_writes_the_file(tmp_path, capsys, monkeypatch):
    from crystalline.cli import commands as commands_module

    _patch_run_crystallization(monkeypatch, commands_module)

    async def fake_prompt_choice(message: str, choices: dict[str, str]) -> str:
        return "a"

    monkeypatch.setattr(commands_module, "_prompt_choice", fake_prompt_choice)

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


_PROPOSAL_WITH_SCHEMA_CHANGE = CrystallizationProposal(
    plugin="session",
    title="Order summary skill",
    rationale="Needs a new OrderSummary type.",
    changes=[FileChange(path="skill_dashboard.py", action="create", content="x = 1\n")],
    schema_changes=[
        SchemaChange(
            type_name="OrderSummary",
            action="create",
            field_spec={"order_id": "str", "total": "float"},
        )
    ],
)


def test_crystallize_shows_schema_change_in_condensed_summary(tmp_path, capsys, monkeypatch):
    from crystalline.cli import commands as commands_module

    async def fake_run_crystallization(*args, **kwargs):
        return _PROPOSAL_WITH_SCHEMA_CHANGE

    monkeypatch.setattr(commands_module, "run_crystallization", fake_run_crystallization)

    async def fake_prompt_choice(message: str, choices: dict[str, str]) -> str:
        return "r"

    monkeypatch.setattr(commands_module, "_prompt_choice", fake_prompt_choice)

    project = _project_with_monitoring(tmp_path)
    ctx = CLIContext(
        project=project, agent=object(), commands=default_commands, session_id="s1"
    )
    command = default_commands.get("crystallize")
    assert asyncio.run(command.handler(ctx, ["session"])) is True
    out = capsys.readouterr().out
    assert "OrderSummary" in out
    assert "schema" in out
    assert "+2" in out


def test_crystallize_approving_schema_change_without_project_path_reports_error(
    tmp_path, capsys, monkeypatch
):
    from crystalline.cli import commands as commands_module

    async def fake_run_crystallization(*args, **kwargs):
        return _PROPOSAL_WITH_SCHEMA_CHANGE

    monkeypatch.setattr(commands_module, "run_crystallization", fake_run_crystallization)

    async def fake_prompt_choice(message: str, choices: dict[str, str]) -> str:
        return "a"

    monkeypatch.setattr(commands_module, "_prompt_choice", fake_prompt_choice)

    project = _project_with_monitoring(tmp_path)
    # No project_path set: applying a schema change has nowhere to persist
    # to, so this should be reported as an error, not crash the REPL, and
    # nothing (not even the accompanying file change) should be written.
    ctx = CLIContext(
        project=project, agent=object(), commands=default_commands, session_id="s1"
    )
    command = default_commands.get("crystallize")
    assert asyncio.run(command.handler(ctx, ["session"])) is True
    out = capsys.readouterr().out
    assert "Error" in out
    assert project.schema.get("OrderSummary") is None
    assert not Path(project.extensions_dir, "skill_dashboard.py").exists()


def test_crystallize_approving_schema_change_with_project_path_persists(
    tmp_path, capsys, monkeypatch
):
    from crystalline.cli import commands as commands_module

    async def fake_run_crystallization(*args, **kwargs):
        return _PROPOSAL_WITH_SCHEMA_CHANGE

    monkeypatch.setattr(commands_module, "run_crystallization", fake_run_crystallization)

    async def fake_prompt_choice(message: str, choices: dict[str, str]) -> str:
        return "a"

    monkeypatch.setattr(commands_module, "_prompt_choice", fake_prompt_choice)

    project = _project_with_monitoring(tmp_path)
    project_path = tmp_path / "project.yaml"
    save_project(project, project_path)

    ctx = CLIContext(
        project=project,
        agent=object(),
        commands=default_commands,
        project_path=str(project_path),
        session_id="s1",
    )
    command = default_commands.get("crystallize")
    # The post-approval /reload attempt will fail gracefully (reported,
    # not raised) since there's no real agent backend wired up here — the
    # point of this test is that the schema change itself landed on disk
    # before that reload ever ran.
    assert asyncio.run(command.handler(ctx, ["session"])) is True
    out = capsys.readouterr().out
    assert "Proposal applied" in out
    assert Path(project.extensions_dir, "skill_dashboard.py").read_text() == "x = 1\n"
    assert project.schema.get("OrderSummary") is not None
    assert "OrderSummary" in project_path.read_text()
