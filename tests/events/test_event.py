import dataclasses
from datetime import datetime, timezone

import pytest

from crystalline.events import TEXT_EVENT_TYPE, Event
from crystalline.security import Token


def _make_event(**overrides) -> Event:
    defaults = dict(
        type=TEXT_EVENT_TYPE,
        payload="hello",
        project_name="demo",
        session_id="s1",
    )
    defaults.update(overrides)
    return Event(**defaults)


def test_event_defaults_token_to_none():
    event = _make_event()
    assert event.token is None


def test_event_auto_generates_a_unique_id():
    a, b = _make_event(), _make_event()
    assert a.id != b.id
    assert isinstance(a.id, str) and a.id


def test_event_auto_generates_a_timezone_aware_created_at():
    event = _make_event()
    assert isinstance(event.created_at, datetime)
    assert event.created_at.tzinfo is timezone.utc


def test_event_is_frozen():
    event = _make_event()
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.payload = "changed"


def test_event_carries_an_explicit_token():
    token = Token(sub="ada", roles=["admin"], scopes=["*:*"])
    event = _make_event(token=token)
    assert event.token is token


def test_text_event_type_constant():
    assert TEXT_EVENT_TYPE == "text"
