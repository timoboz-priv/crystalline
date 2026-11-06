"""`SessionReplayPlugin` (`name = "session"`): the first crystallization
plugin — "the agent goes over the session and does it the agentic way".

Looks at the turns/events of one monitored session, the project's
*current* tools/skills/extension files/schema types (so it can reuse
instead of reinventing), and asks a one-shot codegen agent to write (or
modify) one `skill_*.py`/`tool_*.py` extension file that deterministically
reproduces whatever agentic tool-chaining happened — optionally alongside
new/changed schema types that file's input/output needs — or to say
there's nothing worth crystallizing, including "already fully covered by
an existing tool/skill".

Schema-type changes are parsed into plain `SchemaChange` data here (name,
action, `{field_name: type_expr}` spec) without resolving/compiling the
field types — that compilation (`build_model_from_field_spec`) lives in
`crystalline.project.fields`, and this package must not import
`crystalline.project` at all (it's the dependency the project package's
own `crystallization_wiring` adapter module depends on, the other way
around — see `crystalline/crystallization/plugin.py`'s docstring). Real
validation of the field spec happens at apply time instead, same as a
hand-typed project file only finds out about a bad type expression when
it's loaded.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from crystalline.monitoring import SessionEvent, Turn
from crystalline.security import RESERVED_TYPE_NAMES

from .models import CrystallizationProposal, FileChange, SchemaChange
from .plugin import CrystallizationContext, CrystallizationPlugin

_MAX_RETRIES = 1

_FILE_BLOCK_RE = re.compile(
    r"FILE:\s*(?P<path>[^\n]+)\n"
    r"KIND:\s*(?P<kind>tool|skill)\s*\n"
    r"ACTION:\s*(?P<action>create|modify|delete)\s*\n"
    r"(?:```python\n(?P<code>.*?)\n```\n?)?",
    re.DOTALL,
)

_SCHEMA_BLOCK_RE = re.compile(
    r"SCHEMA:\s*(?P<name>[^\n]+)\n"
    r"ACTION:\s*(?P<action>create|modify|delete)\s*\n"
    r"(?:FIELDS:\s*\n```json\n(?P<fields>.*?)\n```\n?)?",
    re.DOTALL,
)

_INVOKE_RE = re.compile(r"\b(\w+)\.invoke\(")


class _MalformedResponse(Exception):
    pass


def _tool_catalog(project) -> str:
    lines = []
    for tool in (*project.tools, *project.skills):
        schema = tool.input_model.model_json_schema().get("properties", {})
        fields = ", ".join(schema) or "(no fields)"
        lines.append(f"- {tool.name} [{tool.group}]: {tool.description} (input: {fields})")
    return "\n".join(lines) or "(none registered)"


def _schema_catalog(project) -> str:
    # Field *names* only (via pydantic's own `model_json_schema`, not
    # `crystalline.project.fields.field_spec_from_model` — this package
    # can't import `crystalline.project`, see this module's docstring) —
    # enough for the agent to tell whether an existing type already
    # covers the shape it needs, without resolving every field's type.
    lines = []
    for name, model in project.schema.types.items():
        if name in RESERVED_TYPE_NAMES:
            continue
        fields = ", ".join(model.model_json_schema().get("properties", {})) or "(no fields)"
        lines.append(f"- {name}: {fields}")
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

Project: {ctx.project.name}.

Existing schema types (reuse these by name in a FIELDS spec below instead
of redeclaring one that already covers the shape you need):
{_schema_catalog(ctx.project)}

Existing tools/skills (reuse these — don't recreate what already exists):
{_tool_catalog(ctx.project)}

Existing extension files under {ctx.project.extensions_dir!r} (modify one of
these instead of creating a near-duplicate, when it already covers part of
the pattern below):
{files_listing or "(none)"}

Session transcript (route decisions, user messages, tool calls/results,
assistant text, in order):
{_session_transcript(ctx.turns, ctx.events)}

Task: first decide, per file, what this session's pattern actually needs —
don't default to a Tool:
- Nothing, if something already in the catalog above fully covers this
  pattern, or the session has nothing repeatable worth automating.
- A Tool (`tool_*.py`, `build_tool(project) -> Tool`) only if the new
  capability is ONE atomic operation (typically a single `Storage` call).
- A Skill (`skill_*.py`, `build_skill(project) -> Skill`, see
  `crystalline.skills.Skill`) if the handler orchestrates two or more other
  tool calls (via their own `.invoke()`) or agentic steps. Chaining several
  existing tools together — like this session's own tool-calling pattern —
  is a Skill, never a Tool wearing a tool's filename.
Follow the exact style of the existing files shown above: call other tools
via `project.tools.get_tool(name).invoke(input_model(...))`, never a raw
handler. The file's `tool_`/`skill_` prefix must match the KIND you declare
below, and must match what the handler actually does.

Also decide whether any file needs a schema type that doesn't already
exist, or needs an existing one changed — only propose this when the
tool/skill's input/output genuinely needs a structured shape that isn't
already covered above; don't invent a type for data that's only ever used
inline inside one handler. Give a type an `id: str` field only if it
should be an independently stored entity with its own CRUD tools, not for
a nested value object (e.g. a line-item type embedded in another type's
`list[...]` field never needs one).

Respond in EXACTLY this format, nothing else:

If nothing to propose:
NOTHING: <one-line reason>

Otherwise:
TITLE: <short title>
(zero or more, only when a file below needs a schema change)
SCHEMA: <TypeName>
ACTION: <create|modify|delete>
FIELDS:
```json
{{"field_name": "type_expr", "other_field": {{"type": "type_expr", "required": false, "default": null}}}}
```
(omit the FIELDS block entirely if ACTION is delete; repeat SCHEMA/ACTION/FIELDS for more types — a later block may reference an earlier one's TypeName by name)
FILE: <filename, e.g. skill_dashboard.py>
KIND: <tool|skill>
ACTION: <create|modify|delete>
```python
<full file content, omit the python fence and this block entirely if ACTION is delete>
```
(repeat FILE/KIND/ACTION/code for additional files if needed)
RATIONALE:
<2-3 sentences max: why this crystallizes the session, why this KIND is the
right one, and what (if anything) it reuses. No headers, no bullet lists.>
"""
    if retry_error is not None:
        prompt += f"\n\nYour previous response had a problem: {retry_error}\nTry again, following the format exactly."
    return prompt


def _parse_schema_changes(text: str) -> list[SchemaChange]:
    changes: list[SchemaChange] = []
    for match in _SCHEMA_BLOCK_RE.finditer(text):
        type_name = match.group("name").strip()
        action = match.group("action")
        fields_text = match.group("fields")
        if type_name in RESERVED_TYPE_NAMES:
            raise _MalformedResponse(
                f"SCHEMA {type_name} is a reserved, framework-provided type name"
            )
        if action == "delete":
            changes.append(SchemaChange(type_name=type_name, action=action, field_spec=None))
            continue
        if fields_text is None:
            raise _MalformedResponse(
                f"SCHEMA {type_name} (ACTION {action}) is missing a FIELDS ```json block"
            )
        try:
            field_spec = json.loads(fields_text)
        except json.JSONDecodeError as exc:
            raise _MalformedResponse(
                f"SCHEMA {type_name} has invalid JSON in its FIELDS block: {exc}"
            ) from exc
        if not isinstance(field_spec, dict) or not field_spec:
            raise _MalformedResponse(
                f"SCHEMA {type_name}'s FIELDS block must be a non-empty JSON object"
            )
        changes.append(SchemaChange(type_name=type_name, action=action, field_spec=field_spec))
    return changes


def _parse_response(plugin_name: str, text: str) -> CrystallizationProposal | None:
    stripped = text.strip()
    if stripped.upper().startswith("NOTHING"):
        return None

    title_match = re.search(r"TITLE:\s*(?P<title>[^\n]+)", text)
    rationale_match = re.search(r"RATIONALE:\s*(?P<rationale>.*)\Z", text, re.DOTALL)
    if title_match is None or rationale_match is None:
        raise _MalformedResponse("missing TITLE: or RATIONALE: section")

    schema_changes = _parse_schema_changes(text)

    changes: list[FileChange] = []
    for match in _FILE_BLOCK_RE.finditer(text):
        path = match.group("path").strip()
        kind = match.group("kind")
        action = match.group("action")
        code = match.group("code")
        if not path.startswith(f"{kind}_"):
            raise _MalformedResponse(
                f"FILE {path} declared KIND: {kind}, but its filename must start "
                f"with {kind + '_'!r} to match"
            )
        if action == "delete":
            changes.append(FileChange(path=path, action=action, content=None))
            continue
        if code is None:
            raise _MalformedResponse(f"FILE {path} (ACTION {action}) is missing a ```python block")
        try:
            compile(code, path, "exec")
        except SyntaxError as exc:
            raise _MalformedResponse(f"FILE {path} has a Python syntax error: {exc}") from exc
        invoked_tools = set(_INVOKE_RE.findall(code)) - {"self"}
        if kind == "tool" and len(invoked_tools) >= 2:
            raise _MalformedResponse(
                f"FILE {path} is declared KIND: tool, but its handler calls .invoke() "
                f"on {len(invoked_tools)} different tools ({', '.join(sorted(invoked_tools))}) "
                "— orchestrating multiple tool calls makes this a Skill "
                "(skill_*.py, build_skill), not a Tool"
            )
        changes.append(FileChange(path=path, action=action, content=code))

    if not changes:
        raise _MalformedResponse("no FILE blocks found, and response did not start with NOTHING:")

    return CrystallizationProposal(
        plugin=plugin_name,
        title=title_match.group("title").strip(),
        rationale=rationale_match.group("rationale").strip(),
        changes=changes,
        schema_changes=schema_changes,
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
