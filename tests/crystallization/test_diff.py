from crystalline.crystallization import (
    CrystallizationProposal,
    FileChange,
    render_diff,
    summarize_changes,
)


def _proposal(*changes: FileChange) -> CrystallizationProposal:
    return CrystallizationProposal(
        plugin="session", title="t", rationale="r", changes=list(changes)
    )


def test_render_diff_create_shows_only_additions():
    proposal = _proposal(FileChange(path="skill_new.py", action="create", content="a\nb\n"))
    [(path, diff_text)] = render_diff(proposal, existing_files={})
    assert path == "skill_new.py"
    assert "+a" in diff_text
    assert "+b" in diff_text
    assert "-a" not in diff_text


def test_render_diff_modify_shows_before_and_after():
    proposal = _proposal(
        FileChange(path="skill_x.py", action="modify", content="new\n")
    )
    [(_, diff_text)] = render_diff(proposal, existing_files={"skill_x.py": "old\n"})
    assert "-old" in diff_text
    assert "+new" in diff_text


def test_render_diff_delete_shows_only_removals():
    proposal = _proposal(FileChange(path="skill_x.py", action="delete"))
    [(_, diff_text)] = render_diff(proposal, existing_files={"skill_x.py": "old\n"})
    assert "-old" in diff_text
    content_lines = [
        line for line in diff_text.splitlines() if not line.startswith(("+++", "---", "@@"))
    ]
    assert not any(line.startswith("+") for line in content_lines)


def test_render_diff_handles_multiple_changes_in_order():
    proposal = _proposal(
        FileChange(path="a.py", action="create", content="a\n"),
        FileChange(path="b.py", action="create", content="b\n"),
    )
    rendered = render_diff(proposal, existing_files={})
    assert [path for path, _ in rendered] == ["a.py", "b.py"]


def test_summarize_changes_infers_kind_from_filename_prefix():
    proposal = _proposal(
        FileChange(path="skill_dashboard.py", action="create", content="a\nb\n"),
        FileChange(path="tool_helper.py", action="create", content="a\n"),
        FileChange(path="other.py", action="create", content="a\n"),
    )
    rows = summarize_changes(proposal, existing_files={})
    assert [row["kind"] for row in rows] == ["skill", "tool", "other"]


def test_summarize_changes_create_reports_added_line_count():
    proposal = _proposal(FileChange(path="skill_new.py", action="create", content="a\nb\nc\n"))
    [row] = summarize_changes(proposal, existing_files={})
    assert row["action"] == "create"
    assert row["size"] == "+3"


def test_summarize_changes_delete_reports_removed_line_count():
    proposal = _proposal(FileChange(path="skill_x.py", action="delete"))
    [row] = summarize_changes(proposal, existing_files={"skill_x.py": "a\nb\n"})
    assert row["size"] == "-2"


def test_summarize_changes_modify_reports_added_and_removed_counts():
    proposal = _proposal(FileChange(path="skill_x.py", action="modify", content="a\nc\nd\n"))
    [row] = summarize_changes(proposal, existing_files={"skill_x.py": "a\nb\n"})
    assert row["size"] == "+2 -1"
