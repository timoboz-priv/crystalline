"""The interactive read-eval-print loop: free text goes to the agent,
lines starting with `/` are dispatched as slash commands.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
import uuid
from pathlib import Path

from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML, StyleAndTextTuples
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.markup import escape

from crystalline.agents import Agent
from crystalline.events import TEXT_EVENT_TYPE, AgentHandoff, Event
from crystalline.project import Project, build_router
from crystalline.security import current_token

from .commands import CLIContext, CommandRegistry, default_commands
from .console import (
    PROMPT_MARKUP,
    console,
    print_banner,
    print_divider,
    print_status_line,
    print_tool_call,
    render_reply,
    render_result,
    status_segments,
)

PROMPT_HTML = HTML("<ansicyan>❯</ansicyan> ")
HISTORY_PATH = Path.home() / ".crystalline" / "history"

# One flat black background across the whole bar. Named ANSI colors
# (`ansiblack`, `ansiwhite`, `ansigray`) render consistently across real
# terminals; 24-bit hex (`bg:#000000`) doesn't — it renders differently
# depending on a terminal's detected color depth/truecolor support. The
# project name is bold white (the highlighted segment); everything else
# is dim gray (de-emphasized metadata) — color/weight is the only thing
# that varies, never the background. Two non-obvious things are needed on
# every class, not just color, or this silently breaks in a real terminal
# (a scripted pty test won't catch either):
#   1. "bottom-toolbar.text" needs its own explicit override too, not just
#      "bottom-toolbar" — they're separate style classes (the Window's
#      fill uses the former, the text content the latter).
#   2. "noreverse" to explicitly cancel prompt_toolkit's own default rule
#      for "bottom-toolbar" (`"reverse"`) — style merging combines
#      attributes per class rather than replacing the whole rule, so
#      without this the inherited `reverse` attribute still applies on
#      top of our fg/bg, swapping them back at render time and showing
#      the terminal's ambient background color instead of black.
STATUS_BAR_STYLE = Style.from_dict(
    {
        "bottom-toolbar": "bg:ansiblack fg:ansigray dim noreverse",
        "bottom-toolbar.text": "bg:ansiblack fg:ansigray dim noreverse",
        "statusbar.project": "bg:ansiblack fg:ansiwhite bold noreverse",
        "statusbar.sep": "bg:ansiblack fg:ansigray dim noreverse",
    }
)


def _build_prompt_session() -> PromptSession:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    return PromptSession(history=FileHistory(str(HISTORY_PATH)), style=STATUS_BAR_STYLE)


def _status_toolbar(project: Project) -> StyleAndTextTuples:
    # Two leading spaces so the text lines up with where typed input
    # starts after the "❯ " prompt (one glyph + one space).
    toolbar: StyleAndTextTuples = [("class:bottom-toolbar", "  ")]
    for i, (role, text) in enumerate(status_segments(project)):
        if i > 0:
            toolbar.append(("class:statusbar.sep", " · "))
        if role == "project":
            style = "class:statusbar.project"
        else:
            style = "class:bottom-toolbar"
        toolbar.append((style, text))
    return toolbar


async def run_repl(
    project: Project,
    agent: Agent,
    *,
    commands: CommandRegistry = default_commands,
    project_path: str | None = None,
    session_id: str | None = None,
) -> None:
    session_id = session_id or uuid.uuid4().hex
    ctx = CLIContext(
        project=project,
        agent=agent,
        commands=commands,
        project_path=project_path,
        session_id=session_id,
    )
    token = current_token()
    print_banner(project, username=token.sub if token is not None else None)

    # A real interactive terminal gets prompt_toolkit: a persistent box
    # with history (saved to HISTORY_PATH, recalled with Up/Down) and a
    # status-line bottom_toolbar that stays attached to the prompt. Piped
    # or non-interactive stdin (including this project's own test suite)
    # falls back to a plain input() loop with the same information printed
    # as dividers/a status line instead — prompt_toolkit expects a tty.
    interactive = sys.stdin.isatty()
    session = _build_prompt_session() if interactive else None

    await ctx.agent.connect()
    try:
        while True:
            try:
                line = (await _read_line(session, ctx.project)).strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break

            if not interactive:
                print_divider()
                print_status_line(ctx.project)

            if not line:
                continue

            ctx.history.append(line)

            if line.startswith("/"):
                if not await _dispatch_command(ctx, line, commands):
                    break
                continue

            await _dispatch_text(ctx, line, session_id)
    finally:
        await ctx.agent.disconnect()


async def _read_line(session: PromptSession | None, project: Project) -> str:
    if session is not None:
        return await session.prompt_async(
            PROMPT_HTML, bottom_toolbar=lambda: _status_toolbar(project)
        )
    print_divider()
    console.print(PROMPT_MARKUP, end="")
    return await asyncio.to_thread(input)


async def _dispatch_command(
    ctx: CLIContext, line: str, commands: CommandRegistry
) -> bool:
    """Run the slash command in `line`. Returns False if the REPL should stop."""
    tokens = line[1:].split()
    if not tokens:
        console.print("[error]Unknown command:[/error] /")
        return True
    name, *rest = tokens
    command = commands.get(name)
    if command is None:
        console.print(f"[error]Unknown command:[/error] /{escape(name)}")
        return True
    result = command.handler(ctx, rest)
    if inspect.isawaitable(result):
        result = await result
    return result


async def _dispatch_text(ctx: CLIContext, line: str, session_id: str) -> None:
    """Build a generic text `Event` for free-form input and route it —
    the CLI is just a thin event producer, same as any other UI layer
    would be. A `"text"` event always falls back to an agent handoff (see
    `crystalline.events.RuleBasedRouter`), so this looks identical to the
    old direct `agent.send()` call for ordinary conversation; a project
    that registers a tool/skill literally named something else entirely
    is irrelevant here, since `"text"` can never match one.

    `build_router` returns a monitoring-aware `MonitoredRouter` whenever
    the project has monitoring configured — it opens a `Turn` for this
    event before routing it, so the turn exists (with its `route_decision`
    event already recorded) by the time we get a result back, whether
    that's an `AgentHandoff` or a direct tool/skill result.
    """
    event = Event(
        type=TEXT_EVENT_TYPE,
        payload=line,
        project_name=ctx.project.name,
        session_id=session_id,
        token=current_token(),
    )
    router = build_router(ctx.project, session_id=session_id)
    result = await router.route(event)
    if isinstance(result, AgentHandoff):
        # Hand the already-open turn to the agent (if it's monitoring-aware)
        # so send()/receive() append to it instead of starting a new one.
        if result.turn_id is not None:
            continue_turn = getattr(ctx.agent, "continue_turn", None)
            if continue_turn is not None:
                continue_turn(result.turn_id)
        await _stream_reply(ctx.agent, line)
    else:
        render_result(result)


async def _stream_reply(agent: Agent, prompt: str) -> None:
    await agent.send(prompt)
    buffer: list[str] = []
    with console.status("Thinking...", spinner="dots"):
        async for message in agent.receive():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        print_tool_call(block.name, block.input)
                    elif isinstance(block, TextBlock):
                        buffer.append(block.text)
    if buffer:
        render_reply("".join(buffer))
