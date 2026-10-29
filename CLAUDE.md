# Crystalline

Framework where deterministic execution meets agentic reasoning. Full
architecture and design rationale: [docs/architecture.md](docs/architecture.md)
— read it before working on any component, it's the source of truth for
how the pieces fit together.

## Status

All ten architecture components are implemented except
`crystalline.crystallization` (not started). `crystalline.cli` is also
implemented — it's not one of the ten, built early as a stand-in UI/router
layer. This file is the practical reference for working in the code:
exact locations and non-obvious gotchas not covered in the architecture
doc.

**Naming overlaps worth knowing about (different namespaces, not code
collisions):** `crystalline.agents.Skill` (SDK skill directories — markdown
capability packages the model reads) vs. `crystalline.skills.Skill` (a
`Tool` subclass our code invokes) are unrelated concepts with the same
name; nothing bridges them. Same for `crystalline.monitoring.SessionStore`
vs. `claude_agent_sdk`'s own `SessionStore`/`InMemorySessionStore` (the
SDK's session-resumption feature).

## Component reference

- `crystalline.schema` — `crystalline/schema/{base,registry}.py`.
  `CrystallineModel` (Pydantic base, rejects unknown fields),
  `SchemaRegistry` (name -> model, raises on collision unless
  `replace=True`).

- `crystalline.storage` — `crystalline/storage/{base,memory,sqlite}.py`.
  `Storage` ABC + `InMemoryStorage`/`SQLiteStorage`. `update()`'s id
  param is named `record_id`, not `id`, so `id` can appear in `**changes`
  and get rejected as an immutable-field error instead of colliding with
  the positional arg. `HasId` (exported from `crystalline.storage`) is a
  structural protocol used with `cast` wherever `.id` needs reading off a
  generically-typed `T` — `T` itself stays bound to plain `BaseModel`,
  not `HasId`, so `Storage` keeps working with any Pydantic model.

- `crystalline.security` — `crystalline/security/*.py`. `Token`/`Actor`,
  `SecurityPolicy`, `User`. Tokens propagate ambiently via `bind_token`/
  `current_token` (`contextvars`), never as an explicit handler
  parameter. **`PROTECTED_TYPES = {"User", "Role"}` in `scopes.py`:** a
  partial wildcard scope (`*:read`, `*:delete`, ...) never covers either
  — only literal `*:*` or an explicit `User:...`/`Role:...` grant does.
  Add any future framework-reserved pseudo-type with its own admin tools
  here too, or the default `editor` role can read/delete other users'
  `password_hash` through generic CRUD.

- `crystalline.tools` — `crystalline/tools/*.py`. `Tool.invoke(data)` is
  the one true call path (checks `enabled`/`scope` before calling
  `handler`) — never call a tool's raw `handler` directly from new code.
  `crud.py` generates storage CRUD into one shared `"storage"` MCP
  server; `admin.py` hand-curates `User`/role/scope tools into a separate
  `"admin"` server (`list_users`/`get_user` never return `password_hash`).
  `Project.sync_tools()` (re)generates both; `load_project` calls it
  automatically.

- `crystalline.skills` — `crystalline/skills/{skill,registry}.py`.
  `Skill` is a dataclass subclass of `crystalline.tools.Tool` (`group`
  defaults to `"skills"`); `SkillRegistry` is a `ToolRegistry` subclass.
  No auto-generation — `Project.skills` starts empty, populated by
  application code. See **Extensions loading** below for how
  skills/tools get discovered from a project's `extensions:` folder.

- `crystalline.agents` — `crystalline/agents/{base,claude_code}.py`.
  `Agent` ABC (tool/skill/property CRUD + connect/send/receive/run).
  `ClaudeCodeAgent._build_options` groups handler-having tools into one
  SDK MCP server per distinct `tool.metadata["group"]` value (default
  `"crystalline"`) — this is how `wire_tools` keeps a project's
  "storage"/"admin"/"skills" tools as separate MCP servers.
  `describe_message(message) -> list[TextChunk | ToolCallChunk]`
  (`TextChunk`/`ToolCallChunk` are frozen dataclasses alongside
  `Tool`/`Skill`) lets a backend-agnostic consumer (the CLI) render a raw
  message without importing that backend's SDK types — a list, since one
  message can carry several blocks (interleaved text/tool-call).
  `receive()` itself still yields raw, backend-native messages (needed
  for full fidelity by `crystalline.monitoring`'s Claude-specific
  recorder, e.g. `ResultMessage` cost/usage). `MonitoredAgent` delegates
  `describe_message` straight to its inner agent, like its other
  passthrough methods.

- `crystalline.project` — `crystalline/project/*.py`. `Project` holds
  `name`/`version`/`description`/`schema`/`storage`/`security`/`tools`/
  `skills`/`agent_config`/`extensions_dir`/`monitoring_store`/
  `properties`. `load_project`/`save_project` (JSON/YAML) are a thin
  layer on top — the `Project` object is the source of truth, not the
  file. `load_project` automatically runs `sync_tools()` and
  `apply_extensions()`; `/reload` re-runs both.
  - Schema types are declared as data (field name -> type-expression
    string: `str`, `list[str]`, `X | None`, or another type registered
    earlier in the same file — that's how nesting works, e.g.
    `Order.items: list[OrderItem]`). No forward references yet.
    Compiled by `crystalline.project.fields` via `pydantic.create_model`.
  - `storage`/`agent`/`monitoring` config sections (`{type: ..., ...}`)
    each have a `build_x`/`describe_x`/`register_x_backend` adapter
    (`crystalline.project.storage`/`.agent`/`.monitoring_config`). A
    relative `path` resolves against the project *file's* directory, not
    the CWD. `monitoring:` has no always-on default (unlike `storage:`)
    — omitting it means `Project.monitoring_store` is `None`.
    `register_storage_backend` optionally takes `storage_cls`/`describe`
    so a custom backend can round-trip through `describe_storage` (for
    `save_project`), not just be built.
  - `build_agent(project, *, session_id=None)` constructs the real
    `Agent` (tools/system-prompt wired via `agent_wiring`), wrapped in a
    `MonitoredAgent` if `monitoring_store` is set — it never itself
    starts/ends the session. `build_router(project, *, session_id=None)`
    is the `Router` equivalent (plain `RuleBasedRouter`, or
    `MonitoredRouter` when monitoring is configured).

- `crystalline.events` — `crystalline/events/{event,router}.py`. `Event`
  (frozen dataclass: `type`/`payload`/`project_name`/`session_id`/
  `token`/`id`/`created_at`). `TEXT_EVENT_TYPE = "text"` always falls
  back to `AgentHandoff`, checked before any tool/skill name match.
  `Router` ABC + `RuleBasedRouter` (exact `event.type` match against
  `project.tools`/`project.skills`, falling back to
  `AgentHandoff(event, turn_id=...)`).

- `crystalline.monitoring` — `crystalline/monitoring/*.py`.
  `Session`/`Turn`/`SessionEvent` (Pydantic), `SessionStore` ABC (sync,
  not async) + `SQLiteSessionStore`. The Claude-specific instrumentation
  (`MonitoredAgent`/`MonitoredRouter`) lives in
  `crystalline/project/monitoring_wiring.py`, not here. **That module and
  `crystalline.events.router` are genuinely bidirectionally circular at
  the package level** — resolved via `TYPE_CHECKING`-deferred imports
  plus local imports inside the few functions that actually construct
  `AgentHandoff`/`RuleBasedRouter`. Read `monitoring_wiring.py`'s
  docstring before changing either side's imports; a plain top-level
  import on either side reintroduces a real `ImportError`.

- `crystalline.cli` — `crystalline/cli/*.py`. See **CLI practical notes**
  below.

## Extensions loading (tools/skills)

A project file's `extensions: path/` is resolved as plain data by
`load_project` (no code execution at load time). `apply_extensions
(project)` is the explicit step that discovers `tool_*.py`/`skill_*.py`
files and imports them, calling each file's `build_tool(project)` /
`build_skill(project)`. Idempotent (`add_tool(..., replace=True)`), which
is what makes `/reload` safe to call repeatedly.

**Gotcha:** `_load_module` (`crystalline/project/extensions.py`) must
register the module in `sys.modules` *before* `exec_module`, not after —
otherwise a file with two models where one references the other by name
(common under `from __future__ import annotations`) fails with
`PydanticUserError: ... not fully defined` the first time the model is
instantiated (not at import time), since Pydantic resolves forward
references via `sys.modules[model.__module__]`.

## CLI practical notes

- Slash commands (`crystalline/cli/commands.py`): `/quit`, `/project`,
  `/reload`, `/commands`, `/whoami`, `/tools`, `/skills`, `/scopes`,
  `/users <action>`, `/roles <action>`, `/history`. A handler may be sync
  or async — `run_repl` awaits it if awaitable. These are direct
  `Tool.invoke()` calls, not routed through `crystalline.events.Router`.
- Free text goes through the real router (`_dispatch_text` in
  `crystalline/cli/repl.py`): wrapped in a `TEXT_EVENT_TYPE` `Event`,
  routed via `build_router(ctx.project, session_id=...)` built fresh on
  every line. On `AgentHandoff` with a `turn_id`, it calls
  `ctx.agent.continue_turn(turn_id)` (duck-typed via `getattr`) before
  streaming the reply, so the whole exchange lands under the turn the
  router already opened.
- All list-shaped output renders via one shared
  `crystalline.cli.console.render_result` — don't add a bespoke renderer
  for a new command without a good reason.
- Rich markup convention (not enforced by any check): static UI text may
  use `[tag]` markup; anything dynamic must be escaped
  (`rich.markup.escape`) or routed through `Markdown`/`Table`, which
  don't interpret `[...]` as markup.
- Status bar styling (`crystalline/cli/repl.py`, `STATUS_BAR_STYLE`)
  needs `noreverse` set explicitly on every class — prompt_toolkit's own
  default `"bottom-toolbar": "reverse"` rule's `reverse` attribute
  otherwise keeps applying underneath your fg/bg and silently swaps them
  back at render time. `"bottom-toolbar"` and `"bottom-toolbar.text"` are
  separate style classes (Window fill vs. text) and both need the
  override. Use named ANSI colors (`ansiblack`), not 24-bit hex — hex
  renders inconsistently depending on a terminal's detected color depth.
- A synthetic pty (`os.openpty()`, no real terminal attached) silently
  suppresses `bottom_toolbar` unless something answers
  cursor-position-report (`\x1b[6n`) queries — a prompt_toolkit
  limitation, not a bug; real terminals always answer CPR. Verifying
  actual rendered colors (not just that something renders) needs `pyte`
  — install it ad hoc, it's not a project dependency.
- Ctrl+C is caught both inside `run_repl`'s loop (alongside `EOFError`)
  and, as a fallback, around `asyncio.run(run_repl(...))` in `main.py`
  (exits with code 130).

## Example project

`examples/demo_shop/` exercises the whole stack: `sqlite` storage
(`demo_shop.db`), `agent: {type: claude_code, model: claude-sonnet-5}`,
`monitoring: {type: sqlite, path: monitoring.db}`, seeded users
(`admin`/`admin123` admin, `alice`/`alice123` editor, `bob`/`bob123`
viewer), and `extensions: extensions/` (`place_order` skill,
`total_revenue` tool). `seed_data.py` populates 10 customers/5
products/5 orders separately — idempotent, run by hand, not loaded by
`load_project`.

**Never use it for ad hoc/live testing — hard rule, not a "prefer to
avoid."** It's the user's own live demo. Don't load its `project.yaml`,
read/write/delete `demo_shop.db`, or touch the project file for any kind
of manual verification — build a scratch project under `/tmp` instead.
Only touch `examples/demo_shop/` when explicitly asked to change it.

## Working conventions

- **One sub-package per component**, under `crystalline/<component>/`.
  A sub-package should only ever depend on `crystalline.schema` plus
  whatever the architecture doc's dependency table says — never reach
  into a sibling component's internals. If a task seems to require that,
  it probably belongs in `crystalline.project` (the wiring layer)
  instead.
- **Config objects are the API; file formats are a layer on top.** Every
  component that takes configuration (tools, skills, schema types, the
  project itself) supports plain programmatic add/get/update/remove.
  JSON/YAML loaders serialize to/from that object — they are not a
  separate source of truth.
- **Pydantic (v2)** for anything that crosses a boundary: tool
  inputs/outputs, event payloads, project config. Plain dataclasses are
  fine for in-process runtime objects that don't need
  validation/serialization (e.g. `crystalline.agents.Tool`/`Skill`,
  `crystalline.events.Event`).
- **Security is enforced at the tool-invocation boundary**, not assumed
  from upstream. Every `crystalline.tools.Tool` checks the caller's
  token/scope itself via `Tool.invoke()` — don't call a tool's raw
  `handler` directly from new code, and don't rely on the router or a
  skill having already checked.
- **Router stays rule-based for now.** Explicit intent/pattern → tool or
  skill mapping, falling back to an agent. Don't reach for an LLM
  classifier for routing unless asked — a deliberate starting choice, not
  an oversight.
- **Monitoring storage is behind an interface.** Don't hardcode a
  specific database into `crystalline.monitoring`'s public API; the
  concrete backend is an adapter.
- When a design question comes up that the architecture doc flags as
  open, resolve it in the doc (update it) as part of that component's
  implementation, rather than deciding it silently in code.

## Dev environment

- Python venv at `.venv` (Python 3.13). Activate with
  `source .venv/bin/activate`.
- Package installed editable: `pip install -e .`.
- Tests live under `tests/<component>/`, mirroring `crystalline/<component>/`,
  so each component can be tested in isolation. Every `tests/<component>/`
  directory (and `tests/` itself) has an `__init__.py`, making them real
  packages — without that, pytest's default import mode resolves modules
  by bare filename, and two unrelated `test_registry.py` files (say, in
  `tests/schema/` and `tests/tools/`) collide at collection time. Keep
  the `__init__.py` files when adding a new test component.

## Attribution

Follow the attribution conventions provided in-session for commits and
PRs; don't hardcode attribution text here.
