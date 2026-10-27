from datetime import timezone

from crystalline.monitoring import Session, SessionEvent, Turn


def test_session_defaults():
    session = Session(id="s1", project_name="demo")
    assert session.principal is None
    assert session.ended_at is None
    assert session.metadata == {}
    assert session.started_at.tzinfo is timezone.utc


def test_turn_defaults():
    turn = Turn(id="t1", session_id="s1")
    assert turn.status == "in_progress"
    assert turn.ended_at is None
    assert turn.duration_ms is None
    assert turn.total_cost_usd is None
    assert turn.usage is None
    assert turn.result is None
    assert turn.errors is None
    assert turn.metadata == {}
    assert turn.started_at.tzinfo is timezone.utc


def test_session_event_auto_generates_unique_id_and_timestamp():
    a = SessionEvent(session_id="s1", turn_id="t1", kind="user_message", data={"text": "hi"})
    b = SessionEvent(session_id="s1", turn_id="t1", kind="user_message", data={"text": "hi"})
    assert a.id != b.id
    assert a.created_at.tzinfo is timezone.utc


def test_session_event_defaults_to_empty_data_and_no_parent():
    event = SessionEvent(session_id="s1", turn_id="t1", kind="assistant_text")
    assert event.data == {}
    assert event.parent_event_id is None


def test_session_event_can_carry_a_parent_event_id():
    event = SessionEvent(
        session_id="s1", turn_id="t1", kind="tool_result", parent_event_id="e-call-1"
    )
    assert event.parent_event_id == "e-call-1"
