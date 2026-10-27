from crystalline.cli.console import print_status_line, render_result, status_segments
from crystalline.project import Project
from crystalline.security import Token, bind_token


def test_status_segments_highlights_project_first():
    project = Project("demo-shop", "0.1.0")
    segments = status_segments(project)

    role, text = segments[0]
    assert role == "project"
    assert text == "demo-shop v0.1.0"
    assert all(role == "meta" for role, _ in segments[1:])


def test_status_segments_include_storage_and_agent_type():
    project = Project("demo-shop", "0.1.0")
    texts = [text for _, text in status_segments(project)]
    assert "storage: memory" in texts
    assert "agent: claude_code" in texts


def test_status_segments_include_user_when_token_bound():
    project = Project("demo-shop", "0.1.0")
    token = Token(sub="ada", roles=["editor"])
    with bind_token(token):
        texts = [text for _, text in status_segments(project)]
    assert "user: ada" in texts
    assert "roles: editor" in texts


def test_status_segments_omit_user_without_bound_token():
    project = Project("demo-shop", "0.1.0")
    texts = [text for _, text in status_segments(project)]
    assert not any(t.startswith("user:") for t in texts)


def test_print_status_line_includes_all_segments(capsys):
    project = Project("demo-shop", "0.1.0")
    print_status_line(project)
    out = capsys.readouterr().out
    assert "demo-shop" in out
    assert "memory" in out
    assert "claude_code" in out


def test_render_result_scalar_with_bracket_markup_does_not_crash(capsys):
    # A stored field value shaped like rich markup must render as literal
    # text, not be re-parsed and raise rich.errors.MarkupError.
    render_result("[bold red]not markup[/bold red]")
    out = capsys.readouterr().out
    assert "[bold red]not markup[/bold red]" in out


def test_render_result_table_cell_with_bracket_markup_does_not_crash(capsys):
    render_result([{"name": "[/x]", "id": "c1"}])
    out = capsys.readouterr().out
    assert "[/x]" in out


def test_render_result_kv_table_with_bracket_markup_does_not_crash(capsys):
    render_result({"name": "[bold]x[/bold]"})
    out = capsys.readouterr().out
    assert "[bold]x[/bold]" in out
