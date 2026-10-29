import asyncio
from collections.abc import AsyncIterator

from typing import Any

from claude_agent_sdk import AssistantMessage, TextBlock

from crystalline.agents import Agent, TextChunk, ToolCallChunk
from crystalline.cli.repl import _status_toolbar, run_repl
from crystalline.project import Project


class FakeAgent(Agent):
    """Minimal `Agent` double: no network calls, records what it's sent."""

    def __init__(self) -> None:
        super().__init__("fake")
        self.connected = False
        self.sent: list[str] = []
        self._pending_reply = "ack"

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def send(self, prompt: str) -> None:
        self.sent.append(prompt)

    async def receive(self) -> AsyncIterator[AssistantMessage]:
        yield AssistantMessage(content=[TextBlock(text=self._pending_reply)], model="fake")

    def describe_message(self, message: Any) -> list[TextChunk | ToolCallChunk]:
        if not isinstance(message, AssistantMessage):
            return []
        return [
            TextChunk(text=block.text)
            for block in message.content
            if isinstance(block, TextBlock)
        ]

    async def run(self, prompt: str) -> str:
        await self.send(prompt)
        return self._pending_reply


def _fake_input(lines: list[str]):
    it = iter(lines)

    def fake_input(prompt: str = "") -> str:
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return fake_input


def test_free_text_is_sent_to_the_agent(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", _fake_input(["hello there", "/quit"]))
    agent = FakeAgent()
    project = Project("demo-shop", "0.1.0")

    asyncio.run(run_repl(project, agent))

    assert agent.sent == ["hello there"]
    assert agent.connected is False  # disconnected on exit
    assert "ack" in capsys.readouterr().out


def test_free_text_with_monitoring_records_one_turn_with_route_decision_first(
    monkeypatch, capsys
):
    # Plain FakeAgent (no continue_turn) — must not crash when build_router
    # hands back an AgentHandoff with a turn_id and the CLI tries (and
    # gracefully skips) attaching it via getattr.
    from crystalline.monitoring import Session, SQLiteSessionStore
    from crystalline.project import Project as ProjectCls

    monkeypatch.setattr("builtins.input", _fake_input(["hello there", "/quit"]))
    agent = FakeAgent()
    with SQLiteSessionStore(":memory:") as store:
        project = ProjectCls("demo-shop", "0.1.0", monitoring_store=store)
        store.start_session(Session(id="s1", project_name="demo-shop"))

        asyncio.run(run_repl(project, agent, session_id="s1"))

        assert agent.sent == ["hello there"]
        sessions = store.list_sessions(project_name="demo-shop")
        assert len(sessions) == 1
        turns = store.list_turns("s1")
        assert len(turns) == 1
        events = store.list_events(turn_id=turns[0].id)
        assert events[0].kind == "route_decision"
        assert events[0].data["decision"] == "agent_handoff"


def test_free_text_with_monitored_agent_continues_the_router_turn(monkeypatch, capsys):
    # A MonitoredAgent (has continue_turn) wrapping FakeAgent: the whole
    # exchange (route_decision, user_message, assistant_text) must land
    # under the *same* turn the router opened, not a second one.
    from crystalline.monitoring import Session, SQLiteSessionStore
    from crystalline.project import Project as ProjectCls
    from crystalline.project.monitoring_wiring import MonitoredAgent

    monkeypatch.setattr("builtins.input", _fake_input(["hello there", "/quit"]))
    inner = FakeAgent()
    with SQLiteSessionStore(":memory:") as store:
        store.start_session(Session(id="s1", project_name="demo-shop"))
        agent = MonitoredAgent(inner, store, session_id="s1")
        project = ProjectCls("demo-shop", "0.1.0", monitoring_store=store)

        asyncio.run(run_repl(project, agent, session_id="s1"))

        turns = store.list_turns("s1")
        assert len(turns) == 1
        events = store.list_events(turn_id=turns[0].id)
        kinds = [e.kind for e in events]
        assert kinds == ["route_decision", "user_message", "assistant_text"]


def test_project_slash_command_prints_project_info(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", _fake_input(["/project", "/quit"]))
    agent = FakeAgent()
    project = Project("demo-shop", "0.1.0", description="a shop")

    asyncio.run(run_repl(project, agent))

    assert agent.sent == []  # slash commands never reach the agent
    out = capsys.readouterr().out
    assert "demo-shop" in out
    assert "a shop" in out


def test_unknown_command_does_not_stop_the_repl(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", _fake_input(["/bogus", "/quit"]))
    agent = FakeAgent()
    project = Project("demo-shop", "0.1.0")

    asyncio.run(run_repl(project, agent))

    assert "Unknown command: /bogus" in capsys.readouterr().out


def test_bare_slash_does_not_crash_the_repl(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", _fake_input(["/", "/quit"]))
    agent = FakeAgent()
    project = Project("demo-shop", "0.1.0")

    asyncio.run(run_repl(project, agent))  # should not raise ValueError

    assert "Unknown command: /" in capsys.readouterr().out


def test_eof_stops_the_repl_gracefully(monkeypatch):
    monkeypatch.setattr("builtins.input", _fake_input([]))
    agent = FakeAgent()
    project = Project("demo-shop", "0.1.0")

    asyncio.run(run_repl(project, agent))  # should not hang or raise

    assert agent.connected is False


def test_history_command_lists_prior_session_entries(monkeypatch, capsys):
    monkeypatch.setattr(
        "builtins.input", _fake_input(["hello there", "/whoami", "/history", "/quit"])
    )
    agent = FakeAgent()
    project = Project("demo-shop", "0.1.0")

    asyncio.run(run_repl(project, agent))

    out = capsys.readouterr().out
    assert "hello there" in out
    assert "/whoami" in out


def test_history_includes_itself_as_the_latest_entry(monkeypatch, capsys):
    # a line is appended to history before being dispatched, so /history
    # run as the very first command still shows (at least) itself —
    # matching how a shell's own `history` builtin behaves.
    monkeypatch.setattr("builtins.input", _fake_input(["/history", "/quit"]))
    agent = FakeAgent()
    project = Project("demo-shop", "0.1.0")

    asyncio.run(run_repl(project, agent))

    out = capsys.readouterr().out
    assert "/history" in out
    assert "(empty)" not in out


def test_status_toolbar_starts_with_two_space_indent():
    project = Project("demo-shop", "0.1.0")
    toolbar = _status_toolbar(project)

    style, text = toolbar[0]
    assert style == "class:bottom-toolbar"
    assert text == "  "


def test_status_toolbar_highlights_project_segment():
    project = Project("demo-shop", "0.1.0")
    toolbar = _status_toolbar(project)

    style, text = toolbar[1]
    assert style == "class:statusbar.project"
    assert text == "demo-shop v0.1.0"
    assert all(style != "" for style, _ in toolbar)
    assert any(style == "class:statusbar.sep" for style, _ in toolbar)
    assert any(style == "class:bottom-toolbar" for style, _ in toolbar)


def test_status_toolbar_uses_flat_black_background_everywhere():
    from crystalline.cli.repl import STATUS_BAR_STYLE

    style_dict = dict(STATUS_BAR_STYLE.style_rules)
    class_names = (
        "bottom-toolbar",
        "bottom-toolbar.text",
        "statusbar.project",
        "statusbar.sep",
    )
    for class_name in class_names:
        assert "bg:ansiblack" in style_dict[class_name]
        # without this, prompt_toolkit's own default "bottom-toolbar:
        # reverse" rule still applies underneath ours (style merging is
        # per-attribute, not a wholesale rule replacement) and swaps our
        # fg/bg back at render time.
        assert "noreverse" in style_dict[class_name]


def test_status_toolbar_project_is_white_rest_is_gray():
    from crystalline.cli.repl import STATUS_BAR_STYLE

    style_dict = dict(STATUS_BAR_STYLE.style_rules)
    assert "fg:ansiwhite" in style_dict["statusbar.project"]
    assert "bold" in style_dict["statusbar.project"]
    for class_name in ("bottom-toolbar", "bottom-toolbar.text", "statusbar.sep"):
        assert "fg:ansigray" in style_dict[class_name]
        assert "dim" in style_dict[class_name]
