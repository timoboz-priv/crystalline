from datetime import datetime, timedelta, timezone

import pytest

from crystalline.monitoring import Session, SessionEvent, SQLiteSessionStore, Turn


@pytest.fixture
def store():
    with SQLiteSessionStore(":memory:") as store:
        yield store


@pytest.fixture
def session_in(store):
    store.start_session(Session(id="s1", project_name="demo", principal="ada"))
    return "s1"


# ---- sessions ----


def test_start_and_get_session(store):
    session = Session(id="s1", project_name="demo", principal="ada")
    store.start_session(session)

    fetched = store.get_session("s1")
    assert fetched is not None
    assert fetched.project_name == "demo"
    assert fetched.principal == "ada"
    assert fetched.ended_at is None


def test_get_session_missing_returns_none(store):
    assert store.get_session("nope") is None


def test_start_session_duplicate_id_raises(store):
    store.start_session(Session(id="s1", project_name="demo"))
    with pytest.raises(ValueError):
        store.start_session(Session(id="s1", project_name="demo"))


def test_end_session_sets_ended_at(store):
    store.start_session(Session(id="s1", project_name="demo"))
    ended_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    updated = store.end_session("s1", ended_at=ended_at)

    assert updated.ended_at == ended_at
    assert store.get_session("s1").ended_at == ended_at


def test_end_session_defaults_to_now(store):
    store.start_session(Session(id="s1", project_name="demo"))
    updated = store.end_session("s1")
    assert updated.ended_at is not None


def test_end_session_missing_raises(store):
    with pytest.raises(KeyError):
        store.end_session("nope")


def test_list_sessions_filters_by_project_name(store):
    store.start_session(Session(id="s1", project_name="demo"))
    store.start_session(Session(id="s2", project_name="other"))

    results = store.list_sessions(project_name="demo")

    assert [s.id for s in results] == ["s1"]


def test_list_sessions_filters_by_time_range(store):
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    recent = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store.start_session(Session(id="s1", project_name="demo", started_at=old))
    store.start_session(Session(id="s2", project_name="demo", started_at=recent))

    results = store.list_sessions(since=recent - timedelta(days=1))

    assert [s.id for s in results] == ["s2"]


def test_session_metadata_round_trips(store):
    store.start_session(
        Session(id="s1", project_name="demo", metadata={"agent": "claude_code"})
    )
    assert store.get_session("s1").metadata == {"agent": "claude_code"}


# ---- turns ----


def test_start_and_get_turn(store, session_in):
    turn = Turn(id="t1", session_id=session_in)
    store.start_turn(turn)

    fetched = store.get_turn("t1")
    assert fetched is not None
    assert fetched.session_id == session_in
    assert fetched.status == "in_progress"


def test_start_turn_unknown_session_raises(store):
    with pytest.raises(KeyError):
        store.start_turn(Turn(id="t1", session_id="nope"))


def test_start_turn_duplicate_id_raises(store, session_in):
    store.start_turn(Turn(id="t1", session_id=session_in))
    with pytest.raises(ValueError):
        store.start_turn(Turn(id="t1", session_id=session_in))


def test_end_turn_sets_outcome_fields(store, session_in):
    store.start_turn(Turn(id="t1", session_id=session_in))

    updated = store.end_turn(
        "t1",
        status="completed",
        duration_ms=120,
        total_cost_usd=0.01,
        usage={"input_tokens": 5},
        result="done",
        errors=None,
    )

    assert updated.status == "completed"
    assert updated.ended_at is not None
    assert updated.duration_ms == 120
    assert updated.total_cost_usd == 0.01
    assert updated.usage == {"input_tokens": 5}
    assert updated.result == "done"

    fetched = store.get_turn("t1")
    assert fetched.status == "completed"
    assert fetched.total_cost_usd == 0.01


def test_end_turn_missing_raises(store):
    with pytest.raises(KeyError):
        store.end_turn("nope", status="completed")


def test_get_turn_missing_returns_none(store):
    assert store.get_turn("nope") is None


def test_list_turns_ordered_oldest_first(store, session_in):
    t1 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2021, 1, 1, tzinfo=timezone.utc)
    store.start_turn(Turn(id="t2", session_id=session_in, started_at=t2))
    store.start_turn(Turn(id="t1", session_id=session_in, started_at=t1))

    results = store.list_turns(session_in)

    assert [t.id for t in results] == ["t1", "t2"]


def test_list_turns_for_unknown_session_is_empty(store):
    assert store.list_turns("nope") == []


# ---- events ----


def test_append_and_list_events_by_turn_preserves_order(store, session_in):
    store.start_turn(Turn(id="t1", session_id=session_in))
    store.append_event(
        SessionEvent(session_id=session_in, turn_id="t1", kind="user_message", data={"text": "a"})
    )
    store.append_event(
        SessionEvent(session_id=session_in, turn_id="t1", kind="assistant_text", data={"text": "b"})
    )

    events = store.list_events(turn_id="t1")

    assert [e.kind for e in events] == ["user_message", "assistant_text"]
    assert events[0].data == {"text": "a"}


def test_append_event_unknown_turn_raises(store, session_in):
    with pytest.raises(KeyError):
        store.append_event(
            SessionEvent(session_id=session_in, turn_id="nope", kind="user_message")
        )


def test_list_events_by_session_spans_multiple_turns(store, session_in):
    store.start_turn(Turn(id="t1", session_id=session_in))
    store.start_turn(Turn(id="t2", session_id=session_in))
    store.append_event(SessionEvent(session_id=session_in, turn_id="t1", kind="user_message"))
    store.append_event(SessionEvent(session_id=session_in, turn_id="t2", kind="user_message"))

    events = store.list_events(session_id=session_in)

    assert len(events) == 2
    assert {e.turn_id for e in events} == {"t1", "t2"}


def test_list_events_requires_exactly_one_filter(store):
    with pytest.raises(ValueError):
        store.list_events()
    with pytest.raises(ValueError):
        store.list_events(turn_id="t1", session_id="s1")


def test_event_parent_event_id_round_trips(store, session_in):
    store.start_turn(Turn(id="t1", session_id=session_in))
    call = store.append_event(
        SessionEvent(session_id=session_in, turn_id="t1", kind="tool_call", data={"name": "x"})
    )
    store.append_event(
        SessionEvent(
            session_id=session_in,
            turn_id="t1",
            kind="tool_result",
            parent_event_id=call.id,
        )
    )

    events = store.list_events(turn_id="t1")
    assert events[1].parent_event_id == call.id
