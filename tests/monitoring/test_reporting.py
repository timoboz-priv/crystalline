from crystalline.monitoring import Turn
from crystalline.monitoring.reporting import session_cost_total, turn_rows


def _turn(**kwargs) -> Turn:
    defaults = {"id": "t1", "session_id": "s1", "status": "completed"}
    defaults.update(kwargs)
    return Turn(**defaults)


def test_session_cost_total_sums_known_costs():
    turns = [_turn(id="t1", total_cost_usd=0.01), _turn(id="t2", total_cost_usd=0.02)]
    assert session_cost_total(turns) == 0.03


def test_session_cost_total_treats_none_as_zero():
    turns = [_turn(id="t1", total_cost_usd=None), _turn(id="t2", total_cost_usd=0.02)]
    assert session_cost_total(turns) == 0.02


def test_session_cost_total_empty_list():
    assert session_cost_total([]) == 0.0


def test_turn_rows_includes_one_row_per_turn_plus_total():
    turns = [
        _turn(id="t1", total_cost_usd=0.01, duration_ms=100, usage={"input_tokens": 5}),
        _turn(id="t2", total_cost_usd=0.02, duration_ms=200, usage={"output_tokens": 7}),
    ]
    rows = turn_rows(turns)
    assert len(rows) == 3
    assert rows[0]["turn"] == "t1"[:8]
    assert rows[0]["tokens"] == 5
    assert rows[-1]["turn"] == "TOTAL"
    assert rows[-1]["cost_usd"] == 0.03
    assert rows[-1]["duration_ms"] == 300
    assert rows[-1]["tokens"] == 12


def test_turn_rows_handles_no_usage():
    turns = [_turn(id="t1", total_cost_usd=None, usage=None)]
    rows = turn_rows(turns)
    assert rows[0]["tokens"] is None
