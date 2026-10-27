# Crystalline

Framework where deterministic execution meets agentic reasoning. Full
architecture and design rationale: [docs/architecture.md](docs/architecture.md)
— read it before working on any component, it's the source of truth for
how the pieces fit together and what's decided vs. still open.

## Current state

We're building this component by component, in the order listed in
"Build order" in the architecture doc. Check the "Status" table there
before assuming something exists.

- `crystalline.agents` — **implemented**. `Agent` abstract base
  (tool/skill/property CRUD + connect/send/receive/run lifecycle) and
  `ClaudeCodeAgent`, the first concrete implementation, backed by
  `claude-agent-sdk`. `ClaudeCodeAgent._build_options` now groups
  handler-having tools into one SDK MCP server per distinct
  `tool.metadata["group"]` value (default `"crystalline"`), not a single
  hardcoded server — that's how `crystalline.project.wire_tools` keeps a
  project's "storage" and "admin" tool groups as separate MCP servers.
  Still flagged for a revisit once `crystalline.skills` exists (the
  `Tool`/`crystalline.tools.Tool` open question is now resolved).
- `crystalline.schema` — **implemented**. `CrystallineModel` (Pydantic
  base, rejects unknown fields) and `SchemaRegistry` (name -> model
  registry; raises on name collisions unless `replace=True`, unlike the
  simpler dict-overwrite CRUD in `crystalline.agents`).
- `crystalline.project` — **first pass implemented**. `Project` holds
  name/version/description, `schema` (`SchemaRegistry`), `storage`
  (`Storage`), `security` (`SecurityPolicy`), `tools`/`skills`
  (`ToolRegistry`/`SkillRegistry`), `agent_config` (plain dict, not a live
  `Agent` — that carries async connection state that doesn't belong on a
  static config object), `extensions_dir` (resolved path, see below),
  `monitoring_store` (a live `crystalline.monitoring.SessionStore`, or
  `None` if unconfigured — unlike `agent_config` it's fine to hold as a
  static object, since a store has no async connection state), and
  a `properties` escape hatch. `load_project`/
  `save_project` (JSON/YAML) are a thin layer on top — the `Project`
  object is the source of truth, not the file.
  - **Schema** types are declared as data (field name -> type-expression
    string), compiled to real Pydantic models by `crystalline.project.
    fields`, not Python classes. A type can reference another type
    registered earlier in the file by name (that's how nesting works,
    e.g. `demo-shop`'s `Order.items: list[OrderItem]`) — no forward
    references yet.
  - **Storage** (`{type: ..., ...}`, e.g. `{type: sqlite, path: ...}`) is
    built by `crystalline.project.storage`; a relative `path` resolves
    against the project *file's* directory, not the CWD.
  - **Security** (`{roles: {...}, secret_key: ...}`) and **users**
    (`{id, password, roles}` seed list, hashed on first load, left alone
    after) are both optional.
  - **Agent** (`{type: claude_code, model: ...}`) is normalized by
    `crystalline.project.agent`; `build_agent(project, *, session_id=None)`
    constructs the real `Agent` (via `agent_wiring.wire_tools`/
    `system_prompt_for` for tools/skills/system-prompt wiring) — used by
    `crystalline/cli/main.py` instead of constructing `ClaudeCodeAgent`
    directly. If `project.monitoring_store` is set, `build_agent` wraps
    the result in a `crystalline.project.monitoring_wiring.MonitoredAgent`
    recording into that `session_id` — `build_agent` itself never starts
    or ends the session; see the `crystalline.monitoring` entry below for
    who does. `crystalline.project.build_router(project, *,
    session_id=None)` is the equivalent for `crystalline.events.Router`:
    plain `RuleBasedRouter(project)`, or a `MonitoredRouter` wrapping it
    when both `monitoring_store` and `session_id` are given.
  - **Monitoring** (`{type: sqlite, path: ...}`) is normalized by
    `crystalline.project.monitoring_config`; unlike `storage`, there's no
    always-on default — no `monitoring:` section means
    `Project.monitoring_store` is `None` and a project simply isn't
    monitored.
  - **`tools`/`skills`**: CRUD/admin tools are *generated*, not
    config — `Project.sync_tools()` (re)populates `project.tools` from
    the current schema/storage/security, and `load_project` calls it
    automatically. Hand-written tools/skills are declared via a single
    `extensions:` directory (resolved like `storage.path`) — see the
    `crystalline.tools`/`crystalline.skills` entries below for the full
    loading story (`crystalline.project.extensions`).
  - `examples/demo_shop/project.yaml` uses all of it: `sqlite` storage
    against `demo_shop.db`, `agent: {type: claude_code, model:
    claude-sonnet-5}`, seeded `admin`/`admin123` (admin),
    `alice`/`alice123` (editor), `bob`/`bob123` (viewer) users,
    `extensions: extensions/`.
    `examples/demo_shop/seed_data.py` populates the business data (10
    customers, 5 products, 5 orders) separately — idempotent, run it by
    hand, not loaded by `load_project`.
- `crystalline.storage` — **implemented**. Abstract `Storage`: generic
  create/get/update/delete/list for any `pydantic.BaseModel` with an `id`
  field — no dependency on `crystalline.schema`, works with any Pydantic
  model. `InMemoryStorage` and `SQLiteStorage` (one table per type, `id` +
  JSON blob) both satisfy the same contract, tested together in
  `tests/storage/test_storage.py`. `update()`'s id parameter is named
  `record_id` (not `id`) deliberately, so `id` can appear in `**changes`
  and get rejected as an immutable-field error instead of colliding with
  the positional argument. `crystalline.tools.crud` now auto-generates
  CRUD tools over a project's `Storage` for every schema type with an
  `id` field, in one shared `"storage"` MCP server (not one per type).
- `crystalline.security` — **implemented**. `Token` (frozen Pydantic
  model, modeled on RFC 8693 actor tokens: `sub` is the fixed original
  principal, `act` is a chainable delegation record) with `has_scope`/
  `has_role`, `act_as()` for delegation (can only narrow scopes, never
  grant new ones), and `to_jwt`/`from_jwt` (via `pyjwt`) for crossing a
  process boundary — the live object via `contextvars` is the in-process
  default, JWT is a serialization layer on top, not the primary vehicle.
  `bind_token`/`current_token` propagate a token ambiently (no explicit
  parameter — MCP tool handlers have no slot for one and shouldn't, since
  that would let a model supply its own). `check_scope`/`requires_scope`
  check it at a call boundary. `User` (id/roles/password_hash/disabled) is
  framework-reserved: every `Project` auto-registers it in its schema as
  `"User"`; `SecurityPolicy` holds roles (name -> scope patterns, built-in
  `admin`/`editor`/`viewer` always present unless overridden by name) and
  the JWT signing secret. **Important, non-obvious:** `scope_matches` in
  `crystalline/security/scopes.py` hardcodes an exception for
  `PROTECTED_TYPES = {"User", "Role"}` — a partial wildcard (`*:read`,
  `*:delete`, ...) never covers either, only literal `*:*` or an explicit
  `User:...`/`Role:...` grant does. Without it the default `editor` role
  could read/delete other users' `password_hash`, or redefine roles,
  through `crystalline.tools`'s generic CRUD and admin tools — this was
  actually caught live while building `crystalline.tools`, not designed
  upfront, so if you add another framework-reserved pseudo-type with its
  own admin tools, add it to `PROTECTED_TYPES` too.
- `crystalline.tools` — **implemented**. `Tool` (name, Pydantic
  `input_model`/`output_model`, async `handler(data) -> Any`, optional
  `scope`, `group`) + `ToolRegistry` (same collision-protected CRUD as
  `SchemaRegistry`). `Tool.invoke(data)` is the one true call path — it
  checks `enabled` and `scope` before calling `handler` — so both the
  MCP-facing adapter and CLI commands call through `invoke()` rather than
  the raw handler, and neither can bypass the scope check.
  `crystalline.tools.crud.generate_storage_tools` builds
  `create_x`/`get_x`/`update_x`/`delete_x`/`list_x` for every schema type
  that has an `id` field and isn't reserved (skips both `User` and
  id-less nested value types like `OrderItem`), all in one `"storage"`
  MCP server — deliberately one global server, not one per type.
  `crystalline.tools.admin.generate_admin_tools` hand-curates
  `User`/role/scope management tools in a separate `"admin"` server;
  `list_users`/`get_user` never return `password_hash`, and
  `create_user`/`update_user` take a plaintext `password` to hash.
  `Project.sync_tools()` (re)generates both sets; `load_project` calls it
  automatically.
- `crystalline.skills` — **implemented**. `Skill` is a dataclass
  *subclass* of `crystalline.tools.Tool` (same fields, same `invoke()`
  path) with `group`'s default overridden to `"skills"` — not a parallel
  implementation. `SkillRegistry` is a `ToolRegistry` subclass (same
  CRUD, unchanged) whose `register()` builds a `Skill`. No auto-
  generation (unlike `tools`, nothing to derive a workflow from) —
  `Project.skills` starts empty and application code populates it after
  the project's tools exist. `agent_wiring.wire_tools` wires
  `project.skills` exactly like `project.tools` (no special-casing
  needed, since `Skill` already *is* a `Tool`), into its own `"skills"`
  MCP server group. A skill's own `scope` (if set) is a fail-fast gate;
  the "union of its steps' scopes" happens for free because each
  internal `tool.invoke()` call inside its handler still checks its own
  scope on the ambient token — don't add separate bookkeeping for that.
  **Config-driven folder discovery, no CLI flags**: a project file
  declares one `extensions: path/to/dir` (relative to the project file
  like `storage.path`). Convention: one tool/skill per file, named
  `tool_*.py`/`skill_*.py`, each needing a `build_tool(project) -> Tool`/
  `build_skill(project) -> Skill` function. `load_project` resolves that
  path (`crystalline.project.extensions.resolve_extensions_dir`) onto
  `Project.extensions_dir` as plain data — it does **not** scan/import
  anything, since parsing a project file shouldn't run arbitrary code as
  a side effect. `apply_extensions(project)` is the explicit step that
  discovers `tool_*.py`/`skill_*.py` files and imports them, using
  `add_tool(..., replace=True)` so re-running it is idempotent;
  `crystalline/cli/main.py` calls it automatically right after
  `load_project`, and the `/reload` command calls it again. There are
  deliberately no `--tools`/`--skills` CLI flags — an earlier version had
  individual-file config plus flags as an ad hoc alternative path in;
  dropping the flags means a project's tools/skills are fully determined
  by its config file, which `/reload` can re-derive from scratch.
  **Non-obvious bug already hit once:** `crystalline.project.extensions.
  _load_module` must register the module in `sys.modules` *before*
  `exec_module`, not after/never — otherwise a tool/skill file with two
  models where one references the other by name (common under `from
  __future__ import annotations`) fails with `PydanticUserError: ... not
  fully defined` the first time the model is actually instantiated, not
  at import time, since Pydantic resolves forward references via
  `sys.modules[model.__module__]`. Caught by actually invoking the
  example skill live, not by the import succeeding silently — a reminder
  that "it imported fine" isn't the same as "it works."
  `examples/demo_shop/extensions/skill_place_order.py`'s `place_order` is
  the worked example: chains `get_product` + `create_order`, computing
  subtotals/total itself instead of leaving that arithmetic to an agent's
  free text. `examples/demo_shop/extensions/tool_total_revenue.py`'s
  `total_revenue` is the equivalent for a hand-written tool (a read-only
  aggregate CRUD generation can't produce). `examples/demo_shop/
  project.yaml` declares `extensions: extensions/`, so loading it through
  the CLI picks up both with no flags needed.
- `crystalline.events` — **implemented**. Holds both `Event` and
  `Router` — they started as separate `crystalline.events`/
  `crystalline.router` packages, merged once it was clear a router has
  nothing to route without the event type it routes (the split added an
  import hop with no real boundary behind it). `Event`
  (`crystalline/events/event.py`) is a frozen *dataclass*, not a Pydantic
  model — like `crystalline.agents.Tool`/`Skill`, it's an in-process
  runtime object that doesn't itself cross a process boundary or need
  validation. Fields: `type`, `payload`, `project_name` (a bare string,
  not a live `Project` — *this module* depends on `security` only, never
  `crystalline.project`), `session_id`, optional `token`, plus
  auto-generated `id`/`created_at`. `TEXT_EVENT_TYPE = "text"` is
  reserved for free-form text input; `Router` always treats it as an
  agent handoff. `Router` (`crystalline/events/router.py` — the one
  module in this package that *does* depend on `crystalline.project`, for
  `Project`) is a one-method ABC — `async def route(self, event) ->
  RouteResult`, where `RouteResult` is either a direct tool/skill result
  or an `AgentHandoff(event)` sentinel — so a smarter router can replace
  `RuleBasedRouter` later without touching callers. `RuleBasedRouter(project)`
  checks `event.type == TEXT_EVENT_TYPE` *first* (always `AgentHandoff`,
  unconditionally, so a project can never shadow it with a same-named
  tool/skill), then looks `event.type` up by name against
  `project.tools`/`project.skills`; a match is validated against that
  tool's `input_model` and invoked with `event.token` bound via
  `bind_token` for the call (so `Tool.invoke`'s scope check applies
  exactly as it would from any other call path); no match also falls
  back to `AgentHandoff`. Raises `ValueError` if `event.project_name`
  doesn't match the router's own project. The router itself never drives
  an agent conversation — returning `AgentHandoff` just hands that back
  to whoever produced the event.
- `crystalline.monitoring` — **implemented**, **three-tier**
  `Session`/`Turn`/`SessionEvent` (revised from an earlier flat
  `Session` + `SessionRecord` design after surveying Langfuse/OpenAI/OTel
  — see `docs/architecture.md` for the comparison; all of them put
  status/cost/usage/duration on a *middle* tier, never the session, which
  the old flat design had no object for). `SessionStore`
  (`crystalline/monitoring/store.py`) is a **sync** ABC — matching
  `crystalline.storage.Storage`'s convention (this is a storage layer,
  like that one), not the async convention of `tools`/`agents`/
  `events.Router` — with `start_session`/`end_session`/`get_session`/
  `list_sessions(project_name=, since=, until=)`, `start_turn`/
  `end_turn`/`get_turn`/`list_turns(session_id)`, and
  `append_event`/`list_events(turn_id=, session_id=)`.
  `SQLiteSessionStore` is the one concrete backend, with its own
  three-table (`sessions`/`turns`/`session_events`) schema built directly
  on `sqlite3` — deliberately **not** reusing `crystalline.storage.
  SQLiteStorage`'s id+JSON-blob design, since ordered appends and a
  time-range query don't fit that generic-CRUD contract well.
  `Session`/`Turn`/`SessionEvent` (`crystalline/monitoring/session.py`)
  are Pydantic models (unlike `crystalline.events.Event`, these *are*
  persisted, so they follow "Pydantic for anything crossing a boundary").
  `Session` (`id`/`project_name`/`principal`/`started_at`/`ended_at`/
  `metadata`) rolls up nothing itself. `Turn` is one user-prompt-to-
  final-response round trip — `status` (`in_progress`/`completed`/
  `error`), `duration_ms`, `total_cost_usd`, `usage`, `result`, `errors`
  all live here now, not as a same-level `turn_result` event sibling to
  `tool_call`. `SessionEvent` (one flexible `{session_id, turn_id, kind,
  data: dict, parent_event_id, id, created_at}` shape, not a rigid
  subclass per kind) is named `SessionEvent`, not `Event` — matching
  Langfuse/OTel terminology exactly would collide with
  `crystalline.events.Event`, and unlike the `Skill`/`SessionStore`
  naming overlaps (ours vs. an unrelated third-party concept), this would
  be two of *our own* packages reusing the identical name.
  `parent_event_id` is nullable and unused by the default recorder today
  — borrowed from Langfuse's nestable observations, free to add now for
  a future producer that wants to nest e.g. a tool result under its call.
  `EVENT_KIND_*` constants (`user_message`/`assistant_text`/`tool_call`/
  `tool_result`/`message` catch-all) are what the Claude instrumentation
  below produces, not a closed enum.
  **Non-obvious naming overlap, not a code collision:** `claude_agent_sdk`
  exports its own, unrelated `SessionStore`/`InMemorySessionStore` for the
  SDK's own session-resumption feature — same situation as
  `crystalline.agents.Skill` vs `crystalline.skills.Skill`, don't confuse
  the two.
  **Claude instrumentation** lives in `crystalline/project/
  monitoring_wiring.py`, not inside `crystalline.monitoring` itself —
  it needs that package plus `crystalline.agents`/`claude_agent_sdk`
  message types *and* `crystalline.events` (for `RuleBasedRouter`/
  `AgentHandoff`) all at once, which is a wiring concern (same reasoning
  as `events`'s `Router` needing `crystalline.project`, just with one more
  dependency). Two wrapper classes, revised from an earlier single-wrapper
  design once it was clear a direct tool/skill dispatch (handled entirely
  by the router, no `Agent` involved) was otherwise invisible to
  monitoring — **the originating event must always land in the session,
  no matter how it's handled or what type it is**:
  - **`MonitoredRouter`** wraps a `RuleBasedRouter` and owns `Turn`
    creation. `route(event)` *always* opens a turn and appends a
    `route_decision` event first — `{event_type, decision:
    "agent_handoff"|"direct_dispatch", basis, matched}` (`basis` is
    currently always `"exact_type_match"`, a hook for a future smarter
    router to report its own reasoning) — before anything else happens.
    For a direct dispatch it also records `tool_call`/`tool_result` and
    closes the turn itself (`status="completed"`/`"error"`, exception
    always re-raised, never swallowed); for an agent handoff it leaves the
    turn `in_progress` and returns `AgentHandoff(event, turn_id=turn_id)`
    — the `turn_id` field `AgentHandoff` gained specifically for this (a
    plain, non-monitoring `RuleBasedRouter` leaves it `None`).
    Structurally implements `route(event)` without formally subclassing
    `crystalline.events.Router`, since doing so would require importing
    `crystalline.events` at module load time — and `crystalline.events.
    router` already does an absolute `from crystalline.project import
    Project`, so that would make the two packages genuinely *bidirectionally*
    circular, not just import-order-fragile. `Event`/`RuleBasedRouter`/
    `RouteResult` are deferred to `TYPE_CHECKING` (safe at runtime —
    `from __future__ import annotations` already makes every annotation in
    the file a string); `AgentHandoff`/`RuleBasedRouter` are imported
    locally, inside the one function body each is actually used in.
  - **`MonitoredAgent(Agent)`** wraps any `Agent` and is itself a drop-in
    `Agent`; tool/skill/property CRUD delegates explicitly to the inner
    agent (`__getattr__` wouldn't work here — `Agent` already defines
    those methods concretely, so a fallback never fires and they'd
    silently run against the wrapper's own, uninitialized state).
    `connect()`/`disconnect()` have **no session side effects anymore** —
    session lifecycle moved to the CLI (see below), since a session now
    spans more than one connect/disconnect cycle (every `/reload` rebuilds
    the agent). `continue_turn(turn_id)` attaches to a turn already opened
    elsewhere (a `MonitoredRouter`, typically) so the *next* `send()`
    appends to it instead of starting a new one — the attachment is
    consumed after that one `send()`, so a later, unrelated `send()` goes
    back to self-managing its own turn (this fallback is what keeps
    standalone use of `MonitoredAgent`, with no router in front of it,
    working exactly as the original single-tier design did). `receive()`
    feeds each yielded message through two swappable functions —
    `MessageRecorder` (default `claude_message_recorder`) for per-step
    events, and `TurnOutcomeExtractor` (default `claude_turn_outcome`,
    recognizing `ResultMessage` and calling `end_turn(...)` instead of
    emitting a plain event) — while passing every message through
    unchanged; `run()` is reimplemented via the wrapper's own
    `connect`/`send`/`receive` (not the inner agent's `run()`) so
    recording happens regardless of entry point. A still-open turn is
    force-closed with `status="error"` if a new `send()` arrives before
    the previous turn's `ResultMessage` showed up, or if `disconnect()`
    happens mid-turn — a turn can never be left permanently `in_progress`
    by an interrupted conversation.
  - **Session lifecycle is the CLI's job**, via `start_monitoring_session`/
    `end_monitoring_session` (both no-ops if `monitoring_store` is `None`,
    so call sites don't need to guard themselves). One `session_id`,
    generated once per CLI invocation, flows into *both*
    `build_agent(project, session_id=...)` and
    `build_router(project, session_id=...)`, and persists across every
    `/reload` within that invocation — `/reload` passes `ctx.session_id`
    (unchanged) to the rebuilt `build_agent` call and must **not** call
    `start_monitoring_session` again, since the session already exists and
    `SessionStore.start_session` raises on a duplicate id.
  **Wired into the CLI** via a project file's `monitoring:` section
  (`crystalline.project.monitoring_config`, same `{type: sqlite, path:
  ...}` shape as `storage:`, but no always-on default — no section means
  `Project.monitoring_store` is `None` and nothing is recorded).
  `crystalline/cli/main.py` generates `session_id` once, calls
  `start_monitoring_session(project, session_id, principal=user.id)`,
  passes `session_id` to both `build_agent` and `run_repl`, and calls
  `end_monitoring_session` in a `finally` (so it still runs on
  `KeyboardInterrupt`).
- `crystalline.cli` — **implemented**, not one of the ten architecture
  components. Console script `crystalline --project <path> --user <id>
  --password <pw>` (prompts, hiding the password via `getpass`, for
  whichever is omitted) authenticates against the project's storage,
  mints a token, binds it for the REPL's lifetime, calls
  `wire_tools(agent, project)`, then opens the REPL. Free text is wrapped
  in a `TEXT_EVENT_TYPE` `Event` (`crystalline/cli/repl.py`'s
  `_dispatch_text`) and routed through `build_router(ctx.project,
  session_id=session_id)` — built fresh on every line (so it always
  reflects the current project, including right after `/reload`), and a
  `MonitoredRouter` whenever monitoring is configured. If routing comes
  back as an `AgentHandoff` with a `turn_id`, `_dispatch_text` calls
  `ctx.agent.continue_turn(turn_id)` (duck-typed via `getattr` — a plain
  `ClaudeCodeAgent` has no such method, and nothing breaks when it's
  absent) before streaming the reply, so the whole exchange lands under
  the turn the router already opened. Since `"text"` is always an
  `AgentHandoff`, this looks identical to the old direct `agent.send()`
  call for ordinary conversation; the CLI doesn't yet send any other
  event type (direct tool-name events are a path available to
  other/future UI layers). The bound token *is* enforced throughout,
  since every generated tool call (agent/MCP, `/users`/`/roles` CLI
  command, or a direct-dispatch router event) goes through `Tool.invoke`'s
  scope check. Slash commands (`/quit`, `/project`, `/reload`, `/commands`,
  `/whoami`, `/tools`, `/skills`, `/scopes`, `/users <action>`,
  `/roles <action>`, `/history`) are a small registry in
  `crystalline/cli/commands.py`; `CommandHandler` may be sync or async
  (`run_repl` awaits it if awaitable) specifically so `/users`/`/roles`/
  `/reload` can call through `Tool.invoke`/rebuild the project — slash
  commands remain direct `Tool.invoke()` calls, not routed through
  `crystalline.events.Router`. `/reload`
  re-runs `load_project`/`apply_extensions`/`build_agent` against
  `CLIContext.project_path` and swaps the live `Project`/`Agent` into
  `ctx`, connecting the new agent before disconnecting the old one and
  leaving the old ones in place if reloading raises — which is why
  `run_repl`'s loop reads `ctx.project`/`ctx.agent` throughout instead of
  capturing local variables. Rendering is `rich`-based
  (`crystalline/cli/console.py`): themed `Console`, a banner `Panel`,
  assistant replies through `Markdown` (so tables/bold text in a reply
  actually render), a "Thinking…" spinner, and live `⏺ tool_name(args)`
  lines when the model calls a tool (`ToolUseBlock`, previously ignored).
  **Convention, not enforced by any check:** our own UI text may use
  rich's `[tag]` markup; anything dynamic must be escaped
  (`rich.markup.escape`) or routed through `Markdown`/`Table`, which
  don't interpret `[...]` as markup — watch for this on any new
  `console.print` call. All "list"-shaped output (list of dicts -> table,
  dict -> 2-column field/value table, list of scalars -> single-column
  table, scalar -> plain text) goes through one shared `render_result()`
  for consistency across `/tools`, `/commands`, `/whoami`, and every
  `/users`/`/roles` sub-action — don't add a bespoke renderer for a new
  command without a good reason.
  **Input/layout** (`crystalline/cli/repl.py`) branches on
  `sys.stdin.isatty()`: a real terminal gets a `prompt_toolkit.
  PromptSession` with a `bottom_toolbar` status line
  (`console.status_segments`, rendered via `_status_toolbar`) pinned to
  the input box and a persistent `FileHistory` at `~/.crystalline/history`
  (Up/Down recall, shared across projects); piped/non-interactive stdin
  (including this test suite) falls back to plain `input()` with the
  equivalent info printed via `print_divider`/`print_status_line` instead,
  since prompt_toolkit needs a real tty. **The toolbar's `STATUS_BAR_STYLE`
  uses one flat `bg:ansiblack` across every segment** — project
  name/version in bold bright white (`fg:ansiwhite bold`), everything
  else in dim gray (`fg:ansigray dim`); `print_status_line` (non-tty
  fallback, via the `statusbar_project`/`muted` rich theme styles)
  matches. The background never varies, only foreground color/weight.
  Three separate things are required for the background to actually
  render flat-black in a real terminal, each only caught by live
  terminal feedback (not by a scripted pty test, which showed the
  *intended* codes without catching real rendering behavior):
  1. `"bottom-toolbar"` and `"bottom-toolbar.text"` are *separate*
     prompt_toolkit style classes (Window fill vs. text content) — both
     need the override or the library default leaks through on one.
  2. 24-bit hex colors (`bg:#000000`) render inconsistently depending on
     a terminal's detected color depth; named ANSI colors (`ansiblack`)
     and the `default` keyword are universal.
  3. **`noreverse` must be set explicitly on every class.** prompt_toolkit's
     `merge_styles` combines *attributes* per class, not whole rules — the
     library's own default `"bottom-toolbar": "reverse"` rule's `reverse`
     attribute kept applying underneath our fg/bg even after (1) and (2),
     silently swapping them back at render time. That's why the bar
     showed as a solid colored band with inverted text instead of black
     — the "background" being shown was actually the terminal's own
     ambient background color. If you ever touch this style again and
     the bar looks wrong in a real terminal despite the style dict
     looking right, check for a missing `noreverse` first.
  The rendered text starts with two spaces, lining up with where typed
  input starts after the `"❯ "` prompt; `print_status_line` (the
  non-interactive fallback) matches with the same indent.
  **If you test the interactive path with a synthetic pty**
  (`os.openpty()`, no real terminal attached), `bottom_toolbar` silently
  renders nothing unless something answers cursor-position-report
  (`\x1b[6n`) queries — a prompt_toolkit limitation, not a bug; confirmed
  by reproducing it with a bare prompt_toolkit script outside this
  codebase, then fixing it by having the test harness answer CPR like a
  real terminal does. Real terminals always answer CPR, so this only
  affects scripted/headless testing, never actual users. (Verifying the
  actual rendered colors, not just that something renders, needs
  `pyte` — install it ad hoc for a verification session, it's not a
  project dependency.)
  `CLIContext.history: list[str]` records every submitted line (commands
  and free text, appended before dispatch, so `/history` run first still
  shows itself) regardless of which input path is active. Ctrl+C at the
  prompt is caught both inside the REPL loop (alongside `EOFError`, exits
  the REPL like Ctrl+D) and, as a fallback, around
  `asyncio.run(run_repl(...))` in `main.py` (exits with code 130) —
  found while debugging an unrelated report, not designed upfront.
- **Never use `examples/demo_shop/` for ad hoc/live testing — hard rule,
  not a "prefer to avoid."** The user plays with it themselves as the
  project's working demo. Don't load its `project.yaml`, don't read/
  write/delete `demo_shop.db`, don't touch the project file, for any kind
  of manual verification. Build a scratch project under `/tmp` (or
  similar) instead for anything that needs a real project/storage/CLI to
  exercise. This was learned the hard way: earlier test runs against the
  shared `demo_shop.db` (including `rm -f` cleanups between iterations)
  looked exactly like a "new user doesn't persist after restart" bug —
  it wasn't a code bug (the storage/commit path was verified correct in
  isolation), it was test runs clobbering the user's own live session
  against the same file. Only touch `examples/demo_shop/` when
  explicitly asked to change it (e.g. "pre-populate it with data").
- Everything else in the architecture doc is design/not started yet.

## Working conventions

- **One sub-package per component**, under `crystalline/<component>/`.
  A sub-package should only ever depend on `crystalline.schema` (once it
  exists) plus whatever the architecture doc's dependency table says —
  never reach into a sibling component's internals. If a task seems to
  require that, stop and check whether it belongs in `crystalline.project`
  (the wiring layer) instead.
- **Config objects are the API; file formats are a layer on top.** Every
  component that takes configuration (tools, skills, schema types, the
  project itself) must support plain programmatic add/get/update/remove,
  the same pattern already used in `crystalline.agents.Agent`. JSON/YAML
  loaders serialize to/from that object — they are not a separate source
  of truth.
- **Pydantic (v2)** is the schema layer once `crystalline.schema` exists.
  Use it for anything that crosses a boundary: tool inputs/outputs, event
  payloads, project config. Plain dataclasses are fine for in-process
  runtime objects that don't need validation/serialization (e.g. the
  existing `crystalline.agents.Tool`/`Skill`).
- **Security is enforced at the tool-invocation boundary**, not assumed
  from upstream. Every `crystalline.tools.Tool` checks the caller's
  token/scope itself, via `Tool.invoke()` (which calls
  `crystalline.security.check_scope`, reading the ambient token via
  `current_token()`) — don't call a tool's raw `handler` directly from
  new code (CLI commands, future router/skills) and don't rely on the
  router or a skill having already checked; always go through `invoke()`.
- **Router stays rule-based for now.** Explicit intent/pattern → tool or
  skill mapping, falling back to an agent. Don't reach for an LLM
  classifier for routing unless asked — the architecture doc records this
  as a deliberate starting choice, not an oversight.
- **Monitoring storage is behind an interface.** Don't hardcode a specific
  database into `crystalline.monitoring`'s public API; the concrete
  backend is an adapter.
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
