from crystalline.crystallization import (
    CrystallizationProposal,
    FileChange,
    SchemaChange,
    render_diff,
    summarize_changes,
)


def _proposal(*changes: FileChange) -> CrystallizationProposal:
    return CrystallizationProposal(
        plugin="session", title="t", rationale="r", changes=list(changes)
    )


def _schema_proposal(*schema_changes: SchemaChange) -> CrystallizationProposal:
    return CrystallizationProposal(
        plugin="session", title="t", rationale="r", schema_changes=list(schema_changes)
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


def test_summarize_changes_schema_create_reports_field_count():
    proposal = _schema_proposal(
        SchemaChange(type_name="OrderSummary", action="create", field_spec={"a": "str", "b": "int"})
    )
    [row] = summarize_changes(proposal, existing_files={})
    assert row["path"] == "OrderSummary"
    assert row["kind"] == "schema"
    assert row["action"] == "create"
    assert row["size"] == "+2"


def test_summarize_changes_schema_modify_reports_added_and_removed_field_counts():
    proposal = _schema_proposal(
        SchemaChange(type_name="OrderSummary", action="modify", field_spec={"a": "str", "c": "float"})
    )
    rows = summarize_changes(
        proposal, existing_files={}, existing_field_specs={"OrderSummary": {"a": "str", "b": "int"}}
    )
    [row] = rows
    assert row["size"] == "+1 -1"


def test_summarize_changes_schema_create_against_existing_type_reports_as_modify():
    # ACTION: create against a type name that already exists is applied
    # as a clobbering modify (`apply_crystallization` doesn't treat
    # create/modify differently) — the summary must reflect that, not
    # the declared action label, or a reviewer approving from the
    # condensed summary alone would miss removed fields.
    proposal = _schema_proposal(
        SchemaChange(type_name="OrderSummary", action="create", field_spec={"a": "str", "b": "int"})
    )
    [row] = summarize_changes(
        proposal,
        existing_files={},
        existing_field_specs={"OrderSummary": {"a": "str", "x": "int", "y": "int"}},
    )
    assert row["size"] == "+1 -2"


def test_summarize_changes_schema_delete_reports_removed_field_count():
    proposal = _schema_proposal(SchemaChange(type_name="OrderSummary", action="delete"))
    [row] = summarize_changes(
        proposal, existing_files={}, existing_field_specs={"OrderSummary": {"a": "str", "b": "int"}}
    )
    assert row["size"] == "-2"


def test_render_diff_schema_create_shows_only_additions():
    proposal = _schema_proposal(
        SchemaChange(type_name="OrderSummary", action="create", field_spec={"a": "str"})
    )
    [(path, diff_text)] = render_diff(proposal, existing_files={})
    assert path == "schema:OrderSummary"
    assert '+  "a": "str"' in diff_text


def test_render_diff_schema_delete_shows_only_removals():
    proposal = _schema_proposal(SchemaChange(type_name="OrderSummary", action="delete"))
    [(_, diff_text)] = render_diff(
        proposal, existing_files={}, existing_field_specs={"OrderSummary": {"a": "str"}}
    )
    assert '-  "a": "str"' in diff_text
    content_lines = [
        line for line in diff_text.splitlines() if not line.startswith(("+++", "---", "@@"))
    ]
    assert not any(line.startswith("+") for line in content_lines)


def test_render_diff_handles_file_and_schema_changes_in_order():
    proposal = CrystallizationProposal(
        plugin="session",
        title="t",
        rationale="r",
        changes=[FileChange(path="skill_x.py", action="create", content="a\n")],
        schema_changes=[SchemaChange(type_name="X", action="create", field_spec={"a": "str"})],
    )
    rendered = render_diff(proposal, existing_files={})
    assert [path for path, _ in rendered] == ["skill_x.py", "schema:X"]
