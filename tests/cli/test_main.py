import importlib

# `crystalline.cli.__init__` re-exports the `main` function under the same
# name as this submodule, which shadows the submodule as a package
# attribute — so `import crystalline.cli.main` can't be trusted to hand
# back the module. Fetch it straight from `sys.modules` instead.
main_module = importlib.import_module("crystalline.cli.main")
main = main_module.main

PROJECT_YAML = """\
name: test-project
version: "0.1.0"
schema: {{}}
storage:
  type: memory
users:
  - id: alice
    password: {password}
    roles: [admin]
properties: {{}}
"""


def _write_project(tmp_path, password="secret"):
    path = tmp_path / "project.yaml"
    path.write_text(PROJECT_YAML.format(password=password))
    return path


def test_main_authenticates_and_launches_repl(tmp_path, monkeypatch):
    path = _write_project(tmp_path)
    calls = []

    async def fake_run_repl(project, agent, **kwargs):
        calls.append((project, agent))

    monkeypatch.setattr(main_module, "run_repl", fake_run_repl)

    exit_code = main(["--project", str(path), "--user", "alice", "--password", "secret"])

    assert exit_code == 0
    assert len(calls) == 1
    project, agent = calls[0]
    assert project.name == "test-project"
    assert agent.name == "test-project"


def test_main_passes_project_path_to_repl_for_reload(tmp_path, monkeypatch):
    path = _write_project(tmp_path)
    calls = []

    async def fake_run_repl(project, agent, **kwargs):
        calls.append(kwargs.get("project_path"))

    monkeypatch.setattr(main_module, "run_repl", fake_run_repl)

    exit_code = main(["--project", str(path), "--user", "alice", "--password", "secret"])

    assert exit_code == 0
    assert calls == [str(path)]


def test_main_rejects_wrong_password(tmp_path, monkeypatch, capsys):
    path = _write_project(tmp_path)
    calls = []

    async def fake_run_repl(project, agent, **kwargs):
        calls.append((project, agent))

    monkeypatch.setattr(main_module, "run_repl", fake_run_repl)

    exit_code = main(["--project", str(path), "--user", "alice", "--password", "wrong"])

    assert exit_code == 1
    assert calls == []
    assert "Invalid username or password" in capsys.readouterr().out


def test_main_prompts_for_missing_credentials(tmp_path, monkeypatch):
    path = _write_project(tmp_path)
    calls = []

    async def fake_run_repl(project, agent, **kwargs):
        calls.append((project, agent))

    monkeypatch.setattr(main_module, "run_repl", fake_run_repl)
    monkeypatch.setattr("builtins.input", lambda prompt="": "alice")
    monkeypatch.setattr(main_module.getpass, "getpass", lambda prompt="": "secret")

    exit_code = main(["--project", str(path)])

    assert exit_code == 0
    assert len(calls) == 1


def _write_project_with_extensions(tmp_path, password="secret"):
    extensions_dir = tmp_path / "extensions"
    extensions_dir.mkdir()
    path = tmp_path / "project.yaml"
    path.write_text(PROJECT_YAML.format(password=password) + "extensions: extensions\n")
    return path, extensions_dir


def test_main_loads_extensions_before_launching_repl(tmp_path, monkeypatch):
    project_path, extensions_dir = _write_project_with_extensions(tmp_path)
    (extensions_dir / "skill_echo.py").write_text(
        "from pydantic import BaseModel\n"
        "from crystalline.skills import Skill\n"
        "\n"
        "class Input(BaseModel):\n"
        "    value: int\n"
        "\n"
        "async def handler(data):\n"
        "    return data.value\n"
        "\n"
        "def build_skill(project):\n"
        "    return Skill(name='echo', input_model=Input, handler=handler)\n"
    )
    calls = []

    async def fake_run_repl(project, agent, **kwargs):
        calls.append(project)

    monkeypatch.setattr(main_module, "run_repl", fake_run_repl)

    exit_code = main(
        ["--project", str(project_path), "--user", "alice", "--password", "secret"]
    )

    assert exit_code == 0
    assert calls[0].skills.get_tool("echo") is not None


def test_main_loads_extensions_with_cross_model_forward_refs(tmp_path, monkeypatch):
    # Regression test: a skill_*.py (like
    # examples/demo_shop/extensions/skill_place_order.py) whose input
    # model references another model defined earlier in the same file,
    # under `from __future__ import annotations`. Pydantic resolves that
    # forward reference via sys.modules[model.__module__] — if the
    # dynamically-loaded module was never registered in sys.modules
    # before exec, this raises PydanticUserError at the first attempt to
    # instantiate/validate the model, not at import time.
    project_path, extensions_dir = _write_project_with_extensions(tmp_path)
    (extensions_dir / "skill_sum_items.py").write_text(
        "from __future__ import annotations\n"
        "from pydantic import BaseModel\n"
        "from crystalline.skills import Skill\n"
        "\n"
        "class Item(BaseModel):\n"
        "    value: int\n"
        "\n"
        "class Input(BaseModel):\n"
        "    items: list[Item]\n"
        "\n"
        "async def handler(data):\n"
        "    return sum(item.value for item in data.items)\n"
        "\n"
        "def build_skill(project):\n"
        "    return Skill(name='sum_items', input_model=Input, handler=handler)\n"
    )
    calls = []

    async def fake_run_repl(project, agent, **kwargs):
        calls.append(project)

    monkeypatch.setattr(main_module, "run_repl", fake_run_repl)

    exit_code = main(
        ["--project", str(project_path), "--user", "alice", "--password", "secret"]
    )

    assert exit_code == 0
    skill = calls[0].skills.get_tool("sum_items")
    assert skill is not None
    # This is exactly the call that raised PydanticUserError before the fix.
    instance = skill.input_model(items=[{"value": 1}, {"value": 2}])
    assert instance.items[0].value == 1


def test_main_extensions_missing_build_function_reports_error(tmp_path, monkeypatch, capsys):
    project_path, extensions_dir = _write_project_with_extensions(tmp_path)
    (extensions_dir / "skill_bad.py").write_text("x = 1\n")

    calls = []

    async def fake_run_repl(project, agent, **kwargs):
        calls.append(project)

    monkeypatch.setattr(main_module, "run_repl", fake_run_repl)

    exit_code = main(
        ["--project", str(project_path), "--user", "alice", "--password", "secret"]
    )

    assert exit_code == 1
    assert calls == []
    assert "build_skill" in capsys.readouterr().out


def test_main_extensions_missing_directory_reports_error(tmp_path, monkeypatch, capsys):
    path = tmp_path / "project.yaml"
    path.write_text(PROJECT_YAML.format(password="secret") + "extensions: nope\n")

    exit_code = main(
        ["--project", str(path), "--user", "alice", "--password", "secret"]
    )

    assert exit_code == 1
    assert "Failed to load tools/skills" in capsys.readouterr().out


def test_main_token_is_bound_during_repl(tmp_path, monkeypatch):
    from crystalline.security import current_token

    path = _write_project(tmp_path)
    seen = {}

    async def fake_run_repl(project, agent, **kwargs):
        token = current_token()
        seen["sub"] = token.sub if token else None
        seen["roles"] = token.roles if token else None

    monkeypatch.setattr(main_module, "run_repl", fake_run_repl)

    main(["--project", str(path), "--user", "alice", "--password", "secret"])

    assert seen["sub"] == "alice"
    assert seen["roles"] == ["admin"]
    assert current_token() is None  # unbound again after the REPL exits


def _write_monitored_project(tmp_path, password="secret"):
    path = tmp_path / "project.yaml"
    path.write_text(
        PROJECT_YAML.format(password=password)
        + f"monitoring:\n  type: sqlite\n  path: {tmp_path / 'monitoring.db'}\n"
    )
    return path


def test_main_starts_one_monitoring_session_shared_by_agent_and_repl(tmp_path, monkeypatch):
    path = _write_monitored_project(tmp_path)
    seen = {}

    async def fake_run_repl(project, agent, **kwargs):
        seen["repl_session_id"] = kwargs.get("session_id")
        seen["agent_session_id"] = agent.session_id
        seen["session_during_repl"] = project.monitoring_store.get_session(
            kwargs.get("session_id")
        )

    monkeypatch.setattr(main_module, "run_repl", fake_run_repl)

    exit_code = main(["--project", str(path), "--user", "alice", "--password", "secret"])

    assert exit_code == 0
    assert seen["repl_session_id"] == seen["agent_session_id"]
    assert seen["session_during_repl"] is not None
    assert seen["session_during_repl"].principal == "alice"
    assert seen["session_during_repl"].ended_at is None  # still open during the REPL


def test_main_ends_the_monitoring_session_after_repl_exits(tmp_path, monkeypatch):
    path = _write_monitored_project(tmp_path)
    captured = {}

    async def fake_run_repl(project, agent, **kwargs):
        captured["project"] = project
        captured["session_id"] = kwargs.get("session_id")

    monkeypatch.setattr(main_module, "run_repl", fake_run_repl)

    main(["--project", str(path), "--user", "alice", "--password", "secret"])

    session = captured["project"].monitoring_store.get_session(captured["session_id"])
    assert session.ended_at is not None


def test_main_ends_the_monitoring_session_even_on_keyboard_interrupt(tmp_path, monkeypatch):
    path = _write_monitored_project(tmp_path)
    captured = {}

    async def fake_run_repl(project, agent, **kwargs):
        captured["project"] = project
        captured["session_id"] = kwargs.get("session_id")
        raise KeyboardInterrupt

    monkeypatch.setattr(main_module, "run_repl", fake_run_repl)

    exit_code = main(["--project", str(path), "--user", "alice", "--password", "secret"])

    assert exit_code == 130
    session = captured["project"].monitoring_store.get_session(captured["session_id"])
    assert session.ended_at is not None
