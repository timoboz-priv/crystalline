"""`SessionReplayPlugin` (`name = "session"`): the first crystallization
plugin — "the agent goes over the session and does it the agentic way".

Looks at the turns/events of one monitored session, the project's
*current* tools/skills/extension files (so it can reuse instead of
reinventing), and asks a one-shot codegen agent to write (or modify) one
`skill_*.py`/`tool_*.py` extension file that deterministically
reproduces whatever agentic tool-chaining happened — or to say there's
nothing worth crystallizing, including "already fully covered by an
existing tool/skill".
"""

from __future__ import annotations

import re
from pathlib import Path

from crystalline.monitoring import SessionEvent, Turn

from .models import CrystallizationProposal, FileChange
from .plugin import CrystallizationContext, CrystallizationPlugin

_MAX_RETRIES = 1

_FILE_BLOCK_RE = re.compile(
    r"FILE:\s*(?P<path>[^\n]+)\n"
    r"ACTION:\s*(?P<action>create|modify|delete)\s*\n"
    r"(?:```python\n(?P<code>.*?)\n```\n?)?",
    re.DOTALL,
)


class _MalformedResponse(Exception):
    pass


def _tool_catalog(project) -> str:
    lines = []
    for tool in (*project.tools, *project.skills):
        schema = tool.input_model.model_json_schema().get("properties", {})
        fields = ", ".join(schema) or "(no fields)"
        lines.append(f"- {tool.name} [{tool.group}]: {tool.description} (input: {fields})")
    return "\n".join(lines) or "(none registered)"


def _existing_extension_files(project) -> dict[str, str]:
    if project.extensions_dir is None:
        return {}
    directory = Path(project.extensions_dir)
    if not directory.is_dir():
        return {}
    return {
        path.name: path.read_text()
        for path in sorted(directory.glob("*.py"))
    }


def _truncated(value: object, limit: int = 300) -> object:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _session_transcript(turns: list[Turn], events: list[SessionEvent]) -> str:
    turn_order = {turn.id: index for index, turn in enumerate(turns)}
    ordered_events = sorted(
        events, key=lambda e: (turn_order.get(e.turn_id, 0), e.created_at)
    )
    lines = [
        f"[{event.kind}] {_truncated(event.data)}" for event in ordered_events
    ]
    return "\n".join(lines) or "(no events recorded in this session yet)"


def _build_prompt(ctx: CrystallizationContext, *, retry_error: str | None = None) -> str:
    existing_files = _existing_extension_files(ctx.project)
    files_listing = "\n".join(f"--- {name} ---\n{content}" for name, content in existing_files.items())
    prompt = f"""You are crystallization: turning one monitored CLI session's agentic
tool-chaining into a deterministic `crystalline` extension file.

Project: {ctx.project.name}. Registered schema types: {", ".join(ctx.project.schema)}.

Existing tools/skills (reuse these — don't recreate what already exists):
{_tool_catalog(ctx.project)}

Existing extension files under {ctx.project.extensions_dir!r} (modify one of
these instead of creating a near-duplicate, when it already covers part of
the pattern below):
{files_listing or "(none)"}

Session transcript (route decisions, user messages, tool calls/results,
assistant text, in order):
{_session_transcript(ctx.turns, ctx.events)}

Task: if this session shows a repeated or multi-step tool-chaining pattern
worth crystallizing, write ONE new or modified extension file for it — a
`skill_*.py` with a `build_skill(project) -> Skill` function (see
`crystalline.skills.Skill`), or a `tool_*.py` with `build_tool(project) ->
Tool`, following the exact style of the existing files shown above: call
other tools via `project.tools.get_tool(name).invoke(input_model(...))`,
never a raw handler. If something already in the catalog above fully
covers this pattern, or the session has nothing worth automating, propose
nothing.

Respond in EXACTLY this format, nothing else:

If nothing to propose:
NOTHING: <one-line reason>

Otherwise:
TITLE: <short title>
FILE: <filename, e.g. skill_dashboard.py>
ACTION: <create|modify|delete>
```python
<full file content, omit the python fence and this block entirely if ACTION is delete>
```
(repeat FILE/ACTION/code for additional files if needed)
RATIONALE:
<why this crystallizes the session, and what (if anything) it reuses>
"""
    if retry_error is not None:
        prompt += f"\n\nYour previous response had a problem: {retry_error}\nTry again, following the format exactly."
    return prompt


def _parse_response(plugin_name: str, text: str) -> CrystallizationProposal | None:
    stripped = text.strip()
    if stripped.upper().startswith("NOTHING"):
        return None

    title_match = re.search(r"TITLE:\s*(?P<title>[^\n]+)", text)
    rationale_match = re.search(r"RATIONALE:\s*(?P<rationale>.*)\Z", text, re.DOTALL)
    if title_match is None or rationale_match is None:
        raise _MalformedResponse("missing TITLE: or RATIONALE: section")

    changes: list[FileChange] = []
    for match in _FILE_BLOCK_RE.finditer(text):
        path = match.group("path").strip()
        action = match.group("action")
        code = match.group("code")
        if action == "delete":
            changes.append(FileChange(path=path, action=action, content=None))
            continue
        if code is None:
            raise _MalformedResponse(f"FILE {path} (ACTION {action}) is missing a ```python block")
        try:
            compile(code, path, "exec")
        except SyntaxError as exc:
            raise _MalformedResponse(f"FILE {path} has a Python syntax error: {exc}") from exc
        changes.append(FileChange(path=path, action=action, content=code))

    if not changes:
        raise _MalformedResponse("no FILE blocks found, and response did not start with NOTHING:")

    return CrystallizationProposal(
        plugin=plugin_name,
        title=title_match.group("title").strip(),
        rationale=rationale_match.group("rationale").strip(),
        changes=changes,
    )


class SessionReplayPlugin(CrystallizationPlugin):
    @property
    def name(self) -> str:
        return "session"

    async def propose(self, ctx: CrystallizationContext) -> CrystallizationProposal | None:
        retry_error: str | None = None
        for attempt in range(_MAX_RETRIES + 1):
            prompt = _build_prompt(ctx, retry_error=retry_error)
            response = await ctx.agent.run(prompt)
            try:
                return _parse_response(self.name, response)
            except _MalformedResponse as exc:
                if attempt == _MAX_RETRIES:
                    raise ValueError(
                        f"SessionReplayPlugin could not parse a valid proposal "
                        f"after {_MAX_RETRIES + 1} attempt(s): {exc}"
                    ) from exc
                retry_error = str(exc)
        return None  # unreachable
