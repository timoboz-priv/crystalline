from crystalline.crystallization import CrystallizationProposal, FileChange, render_diff


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
