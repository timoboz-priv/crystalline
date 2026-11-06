"""Shared `rich` console, theme, and rendering helpers for the CLI.

One rule, consistently applied: our own static UI chrome (banners,
labels, the prompt) is allowed to use rich's `[tag]...[/tag]` markup.
Anything dynamic — tool names/arguments, project/user data, model
output — is either escaped (`rich.markup.escape`) or routed through a
renderer (`Markdown`, `Table`) that doesn't interpret `[...]` as markup
in the first place. Forgetting this lets a crafted customer name or a
model reply break rendering.
"""

from __future__ import annotations

from typing import Any

from rich.align import Align
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from crystalline.project.storage import describe_storage
from crystalline.security import current_token

THEME = Theme(
    {
        "prompt": "bold cyan",
        "tool": "yellow",
        "error": "bold red",
        "success": "green",
        "muted": "dim",
        "title": "bold cyan",
        "statusbar_project": "bold white",
    }
)

console = Console(theme=THEME)

PROMPT_MARKUP = "[prompt]❯[/prompt] "

# figlet "CRYSTALLINE" (font: slant), trimmed of its trailing blank line.
LOGO = r"""   ____________  ________________    __    __    _____   ________
  / ____/ __ \ \/ / ___/_  __/   |  / /   / /   /  _/ | / / ____/
 / /   / /_/ /\  /\__ \ / / / /| | / /   / /    / //  |/ / __/
/ /___/ _, _/ / /___/ // / / ___ |/ /___/ /____/ // /|  / /___
\____/_/ |_| /_//____//_/ /_/  |_/_____/_____/___/_/ |_/_____/"""

# The logo/info-box are centered within this fixed frame, not the real
# terminal width — `console.print(..., width=BANNER_WIDTH)` overrides
# the available width for just that call, so a wide terminal doesn't
# drag the banner off to the right. Everything else (status line, the
# prompt hint, command output) keeps using the console's real width.
BANNER_WIDTH = 80


def print_logo() -> None:
    console.print(Align.center(Text(LOGO, style="title")), width=BANNER_WIDTH)


def print_info_box(project: Any) -> None:
    """Centered two-column info box: project/user/roles stacked on the
    left, agent/storage/tool+skill counts stacked as three rows on the
    right — same labels `status_segments` uses, just laid out as a box
    instead of a status-line."""
    token = current_token()

    left = Table.grid(padding=(0, 2))
    left.add_column()
    name_line = Text()
    name_line.append(project.name, style="bold white")
    name_line.append(f" v{project.version}", style="muted")
    left.add_row(name_line)
    if token is not None:
        left.add_row(Text(f"user: {token.sub}", style="muted"))
        if token.roles:
            left.add_row(Text(f"roles: {', '.join(token.roles)}", style="muted"))

    storage_type = describe_storage(project.storage)["type"]
    agent_type = project.agent_config.get("type", "?")
    n_tools = len(list(project.tools))
    n_skills = len(list(project.skills))
    right = Table.grid(padding=(0, 2))
    right.add_column()
    right.add_row(Text(f"agent: {agent_type}", style="muted"))
    right.add_row(Text(f"storage: {storage_type}", style="muted"))
    right.add_row(Text(f"{n_tools} tools, {n_skills} skills", style="muted"))

    layout = Table.grid(padding=(0, 4))
    layout.add_column()
    layout.add_column()
    layout.add_row(left, right)

    console.print(
        Align.center(Panel(layout, border_style="cyan", expand=False)),
        width=BANNER_WIDTH,
    )


def print_prompt_hint() -> None:
    console.print(
        "[muted]Type a message, or /commands for a list of slash commands.[/muted]"
    )


def print_banner(project: Any) -> None:
    """Startup sequence: the big ASCII logo, then the centered info box,
    then the left-aligned hint that sits above the first prompt line.
    Login name/roles are read straight off `current_token()`, same as
    `status_segments` — no need to pass them in."""
    print_logo()
    console.print()
    print_info_box(project)
    console.print()
    print_prompt_hint()


def status_segments(
    project: Any, *, session_cost_usd: float | None = None
) -> list[tuple[str, str]]:
    """`(role, text)` pairs describing the status line: role `"project"`
    for the highlighted lead segment, `"meta"` for everything else.
    Shared by both the rich (non-tty) and `prompt_toolkit` (tty) status
    lines, so they always show the same information. `session_cost_usd`
    is `None` (segment omitted) whenever the project has no monitoring
    configured, since there's nothing meaningful to show."""
    token = current_token()
    segments: list[tuple[str, str]] = [("project", f"{project.name} v{project.version}")]
    if token is not None:
        segments.append(("meta", f"user: {token.sub}"))
        if token.roles:
            segments.append(("meta", f"roles: {', '.join(token.roles)}"))
    segments.append(("meta", f"{len(list(project.tools))} tools"))
    segments.append(("meta", f"{len(list(project.skills))} skills"))
    segments.append(("meta", f"storage: {describe_storage(project.storage)['type']}"))
    segments.append(("meta", f"agent: {project.agent_config.get('type', '?')}"))
    if session_cost_usd is not None:
        segments.append(("meta", f"cost: ${session_cost_usd:.4f}"))
    return segments


def print_divider() -> None:
    console.rule(style="muted")


def print_status_line(project: Any, *, session_cost_usd: float | None = None) -> None:
    """A one-line footer: project name in bold white, everything else
    (user/roles, tool count, storage/agent backend) dim gray. Used for
    the non-interactive (piped/no-tty) REPL fallback — the interactive
    path renders `status_segments` as a `prompt_toolkit` bottom_toolbar
    instead (see `crystalline/cli/repl.py`'s `STATUS_BAR_STYLE`), with
    the same color scheme."""
    rendered = []
    for role, text in status_segments(project, session_cost_usd=session_cost_usd):
        text = escape(text)
        if role == "project":
            rendered.append(f"[statusbar_project]{text}[/statusbar_project]")
        else:
            rendered.append(text)
    # Two leading spaces so the text lines up with where typed input
    # starts after the "❯ " prompt (one glyph + one space).
    console.print("  " + " [muted]·[/muted] ".join(rendered), style="muted")


def print_error(message: str) -> None:
    console.print(f"[error]Error:[/error] {escape(message)}")


def print_tool_call(name: str, args: dict[str, Any]) -> None:
    rendered = ", ".join(f"{k}={_truncate(repr(v))}" for k, v in args.items())
    console.print(f"[tool]⏺[/tool] {escape(name)}({escape(rendered)})")


def render_reply(text: str) -> None:
    console.print(Markdown(text))


def _truncate(value: str, limit: int = 40) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _cell(value: Any) -> Text:
    # `Text` (not a bare `str`) so a stored value like "[bold red]x[/]"
    # renders as literal characters instead of being re-parsed as rich
    # markup — a plain string handed to `Table.add_row` goes through the
    # same markup parser as `console.print`.
    if value is None:
        return Text("-")
    if isinstance(value, list):
        return Text(", ".join(str(v) for v in value) if value else "-")
    return Text(str(value))


def _dict_list_table(items: list[dict[str, Any]]) -> Table:
    columns: list[str] = []
    for item in items:
        for key in item:
            if key not in columns:
                columns.append(key)
    table = Table(header_style="bold")
    for column in columns:
        table.add_column(column)
    for item in items:
        table.add_row(*(_cell(item.get(column)) for column in columns))
    return table


def _scalar_list_table(items: list[Any]) -> Table:
    table = Table(show_header=False, box=None)
    table.add_column("value")
    for item in items:
        table.add_row(_cell(item))
    return table


def _kv_table(data: dict[str, Any]) -> Table:
    table = Table(header_style="bold")
    table.add_column("Field")
    table.add_column("Value")
    for key, value in data.items():
        table.add_row(str(key), _cell(value))
    return table


def render_result(result: Any) -> None:
    """Render a tool's return value consistently: list of dicts -> a
    table (one row per item); dict -> a 2-column field/value table; list
    of scalars -> a single-column table; a bare scalar -> plain styled
    text. Every "list"-shaped command (`/tools`, `/commands`,
    `list_users`, `list_roles`, `list_scopes`, ...) ends up looking the
    same way.
    """
    if result is None:
        console.print("None", style="muted")
        return
    if isinstance(result, bool):
        console.print(str(result), style="success" if result else "error")
        return
    if isinstance(result, (int, float, str)):
        console.print(result, markup=False)
        return
    if isinstance(result, list):
        if not result:
            console.print("(empty)", style="muted")
        elif all(isinstance(item, dict) for item in result):
            console.print(_dict_list_table(result))
        else:
            console.print(_scalar_list_table(result))
        return
    if isinstance(result, dict):
        if not result:
            console.print("(empty)", style="muted")
        else:
            console.print(_kv_table(result))
        return
    console.print(result, markup=False)
