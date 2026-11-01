import pytest
from pydantic import ValidationError

from crystalline.crystallization import CrystallizationProposal, FileChange


def test_file_change_create_requires_content():
    with pytest.raises(ValidationError):
        FileChange(path="skill_x.py", action="create", content=None)


def test_file_change_delete_forbids_content():
    with pytest.raises(ValidationError):
        FileChange(path="skill_x.py", action="delete", content="whatever")


def test_file_change_delete_allows_no_content():
    change = FileChange(path="skill_x.py", action="delete")
    assert change.content is None


def test_proposal_defaults_to_no_changes():
    proposal = CrystallizationProposal(plugin="session", title="t", rationale="r")
    assert proposal.changes == []
