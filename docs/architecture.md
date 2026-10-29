# Crystalline Architecture

## Vision

Deterministic execution meets agentic reasoning. A Crystalline **project**
starts out leaning on agents for anything not yet automated. Every
interaction is recorded. A background process ("crystallization")
periodically looks for sessions where an agent did the same free-form thing
repeatedly and distills it into a deterministic **tool** or **skill** — so
the system gets cheaper, faster, and more auditable over time without
anyone hand-writing the automation.

The name is the thesis: agentic behavior is the liquid state; tools and
skills are the crystallized, deterministic state. The system should flow
between them as needed, and solidify over time.

## Design principles

1. **Each component is a standalone sub-package.** You should be able to
   `import crystalline.schema` (for example) in a project that has nothing
   to do with the rest of Crystalline and get something useful on its own.
2. **Schema is the only universal dependency.** Every other component may
   depend on `crystalline.schema`. Components should not depend on each
   other's internals beyond that — cross-component wiring happens through
   adapters owned by whichever side is more concrete (usually `project`).
3. **Config objects first, file formats second.** Every component that
   needs configuration exposes a plain Python object you can build and
   mutate programmatically (add/remove/get/update). JSON/YAML (de)serializers
   are a thin layer on top of that object, not the source of truth.
4. **Deterministic by default, agentic by exception.** The router always
   prefers a tool or skill match over handing an event to an agent. Agents
   are the fallback for what hasn't been crystallized yet, not the default
   path.
5. **Security is enforced at the boundary, not trusted from upstream.**
   Every tool invocation checks the caller's token/claims itself. Nothing
   upstream (router, skill, agent) is trusted to have already checked.

## Components

All of these are implemented except `crystalline.crystallization`. The
table is ordered by dependency (each row may depend on rows above it):

| Sub-package | Responsibility | Depends on |
|---|---|---|
| `crystalline.schema` | Pydantic data types shared across a project | — (foundation) |
| `crystalline.storage` | Generic CRUD persistence for any Pydantic model with an `id` field | standalone (not even `schema`) |
| `crystalline.security` | Users, roles, scopes; token minting, delegation, verification | `schema`, `storage` |
| `crystalline.tools` | Tools organized into APIs/MCP servers, typed on `schema` in/out | `schema`, `security`, `storage` |
| `crystalline.skills` | Workflows chaining tool calls (and optionally agentic steps) | `tools`, `schema`, `agents` (optional) |
| `crystalline.agents` | Model layer: calls agents equipped with tools | standalone (takes schema-typed tools via an adapter, not directly) |
| `crystalline.project` | Top-level config object: schema/storage/security/tools/skills/agent/monitoring for one project | all of the above |
| `crystalline.events` | `Event` + `Router`: decides whether an event is handled by a tool, a skill, or an agent | `security` (`Event`), `project` (`Router`, same package) |
| `crystalline.monitoring` | Storage-agnostic session/turn/event recording | `events` (label only — the Claude-specific instrumentation lives in `project`) |
| `crystalline.crystallization` | Mines monitored sessions, proposes/generates new tools/skills — **not yet built** | `monitoring`, `tools`, `skills`, `agents` |
| `crystalline.cli` | Interactive command-line UI (not one of the ten components above) | `project`, `agents`, `security`, `events` |

### Dependency direction

```
schema
  ├── security
  ├── tools  (+ security)
  └── skills (+ tools, + agents optionally)

agents (standalone; takes schema-typed tools via crystalline.project.agent_wiring)

project = schema + tools + skills + agents + security + monitoring, wired together
events  = security (Event.token) + project (Router, same package)
monitoring = events (label only; real instrumentation lives in project.monitoring_wiring)
cli     = project + agents + security + events
crystallization = monitoring + tools + skills + agents (not built)
```

`crystalline.project.monitoring_wiring` (the Claude-specific instrumentation:
`MonitoredAgent`/`MonitoredRouter`) and `crystalline.events.router` import
each other's packages — a genuine bidirectional circular import at the
package level, resolved with `TYPE_CHECKING`-deferred imports plus local
imports inside the handful of functions that actually construct
`AgentHandoff`/`RuleBasedRouter` (see `monitoring_wiring.py`'s docstring
before touching either side of this).

`crystalline.events` is the one package that doesn't fit "depends only on
what the table says" cleanly: `Event` itself depends only on `security`,
but `router.py` in the same package also depends on `project` — they live
together because a router has nothing to route without a project's
tools/skills to dispatch against.

Nothing below `project` in this graph should import `events`'s router
half, `monitoring`, or `crystallization`. If you find yourself wanting
that, the thing you're building probably belongs in `project` or a new
adapter module instead.

### `crystalline.schema`

Pydantic v2 — free validation, JSON Schema generation (useful for tool
input/output specs and MCP), and serialization, and the SDK ecosystem
(MCP, FastAPI, ...) already speaks Pydantic. `CrystallineModel` is the
project's base model (rejects unknown fields). `SchemaRegistry` maps a
type name to its model, so tools/skills/events can reference a type by
name instead of a direct Python import — this is what makes config-file-
driven wiring possible. Raises on name collisions unless `replace=True`.

### `crystalline.storage`

Abstract `Storage` (`crystalline/storage/base.py`): generic create/get/
update/delete/list for any `pydantic.BaseModel` with an `id` field. No
dependency on `crystalline.schema` at all — works with any Pydantic model.
Records are bucketed by `model.__name__`, so one `Storage` instance should
be scoped to one schema namespace (one project).

Two backends, same contract (`tests/storage/test_storage.py` parametrizes
both):
- `InMemoryStorage` — dict of dicts, gone on process exit.
- `SQLiteStorage` — one table per type, each record stored as `id` + a
  JSON blob (`model_dump_json`/`model_validate_json`), sidestepping
  column-mapping every field type at the cost of filtering in Python
  rather than SQL.

Conventions: `update()`'s id parameter is named `record_id`, not `id`, so
`id` can appear in `**changes` and get rejected as an immutable-field
error instead of colliding with the positional arg. `list(**filters)` is
exact-match only — no comparisons, sorting, or pagination.

`T = TypeVar("T", bound=BaseModel)` deliberately doesn't encode the "has
an `id`" requirement — that's a runtime-only contract
(`_require_id_field`), kept that way so `Storage` stays usable with *any*
Pydantic model rather than forcing a dedicated base class. The few places
that need `.id` off a generically-typed `T` use a narrow `HasId`
structural protocol plus `cast`, not a blanket `# type: ignore`.

### `crystalline.security`

Modeled on RFC 8693's actor-token pattern. `Token` (frozen Pydantic
model): `sub` is the fixed original principal; `act` is an optional,
chainable delegation record of who's acting right now. `token.act_as(actor,
scopes=...)` can only narrow scopes, never grant new ones — a sub-agent
can never end up with more power than its parent. `to_jwt`/`from_jwt`
(via `pyjwt`, HS256) exist for crossing a process boundary; the live
object is the in-process default.

Tokens propagate ambiently via `contextvars` (`bind_token`/`current_token`
in `crystalline/security/context.py`), not as an explicit parameter — MCP
tool handlers have no slot for one, and a token must never be something a
model can supply itself. `check_scope(token, "Customer:create")` (raises
`PermissionError`) and `@requires_scope(...)` are the two ways to enforce
a scope at a call boundary.

Scopes are `"{type}:{action}"` strings with `*` wildcards per segment
(`scope_matches`, `crystalline/security/scopes.py`). One hardcoded
exception: a *partial* wildcard (`"*:read"`, `"*:delete"`, ...) never
covers `PROTECTED_TYPES = {"User", "Role"}` — only a literal `"*:*"` or an
explicit `"User:..."`/`"Role:..."` grant does. Without it, the built-in
`editor` role could read/delete other users' `password_hash` or redefine
roles via `crystalline.tools`'s generic CRUD/admin tools. Add any future
framework-reserved pseudo-type here too.

`User` (id/roles/password_hash/disabled) is framework-reserved: every
`Project` auto-registers it under the schema name `"User"`.
`SecurityPolicy` holds roles (name -> scope patterns) with built-in
defaults always present unless overridden by name (`admin`: `*:*`;
`editor`: `*:create`/`*:read`/`*:update`/`*:delete`; `viewer`: `*:read`),
plus the JWT signing secret.

### `crystalline.tools`

`Tool` (`crystalline/tools/tool.py`): name, Pydantic `input_model`/
`output_model`, async `handler(data) -> Any`, optional `scope`, `group`
(which MCP server it belongs to). `ToolRegistry` is the name -> `Tool` CRUD
registry (collision-protected, like `SchemaRegistry`). **`Tool.invoke(data)`
is the one true call path** — it checks `enabled` and `scope` before
calling `handler`, so nothing (CLI commands, the router, a skill) should
call a handler directly.

- `crystalline.tools.crud.generate_storage_tools` builds `create_x`/
  `get_x`/`update_x`/`delete_x`/`list_x` for every schema type with an
  `id` field (skipping `User` and id-less nested value types), all in one
  shared `"storage"` MCP server, scoped `{Type}:create`/`read`/`update`/
  `delete`.
- `crystalline.tools.admin.generate_admin_tools` hand-curates `User`/
  role/scope management in a separate `"admin"` server: `list_users`/
  `get_user` never return `password_hash`; `create_user`/`update_user`
  take a plaintext `password` to hash.
- `Project.sync_tools()` (re)generates both sets; `load_project` calls it
  automatically.

Hand-written tools (anything generic CRUD can't produce, e.g. a custom
aggregate) are declared via the extensions-folder mechanism shared with
skills — see `crystalline.skills` below.

`crystalline.agents.Tool` (generic, raw dict-in/dict-out, agent-facing)
and `crystalline.tools.Tool` (project-level, Pydantic-typed,
security-scoped) are deliberately different shapes for different
audiences; `crystalline.project.agent_wiring.wire_tools(agent, project)`
is the adapter between them.

### `crystalline.skills`

`Skill` (`crystalline/skills/skill.py`) is a dataclass *subclass* of
`crystalline.tools.Tool` — same fields, same `invoke()` path, `group`'s
default overridden to `"skills"`. `SkillRegistry` is a `ToolRegistry`
subclass. No auto-generation (there's nothing to derive a workflow
from) — `Project.skills` starts empty; application code populates it
after the project's tools exist. A skill's own `scope` (if set) is a
fail-fast gate; its steps' own `tool.invoke()` calls still check their
own scope independently, so there's no separate "union of steps' scopes"
bookkeeping to maintain.

**Extensions folder** (`crystalline/project/extensions.py`): a project
file declares one `extensions: path/to/dir` (resolved like `storage.path`,
relative to the project file). Convention: one tool/skill per file,
`tool_*.py`/`skill_*.py`, each needing a `build_tool(project) -> Tool` /
`build_skill(project) -> Skill` function. `load_project` only resolves the
path onto `Project.extensions_dir` as data — it never imports anything
(parsing a project file shouldn't run arbitrary code). `apply_extensions
(project)` is the explicit step that discovers and imports those files,
using `add_tool(..., replace=True)` so re-running it (e.g. on `/reload`)
is idempotent. There are deliberately no `--tools`/`--skills` CLI flags —
a project's tools/skills are fully determined by its config file.

**Gotcha:** `_load_module` must register the module in `sys.modules`
*before* `exec_module`, not after — otherwise a file with two models
where one references the other by name (common under `from __future__
import annotations`) fails with `PydanticUserError: ... not fully
defined` the first time the model is instantiated (not at import time),
since Pydantic resolves forward references via
`sys.modules[model.__module__]`.

### `crystalline.agents`

`Agent` abstract base: tool/skill/property CRUD plus a `connect`/`send`/
`receive`/`run` lifecycle. `ClaudeCodeAgent` is the first concrete
implementation, backed by `claude-agent-sdk`. `_build_options` groups
handler-having tools into one SDK MCP server per distinct
`tool.metadata["group"]` value (default `"crystalline"`) — this is how
`crystalline.project.wire_tools` keeps a project's "storage"/"admin"/
"skills" tool groups as separate MCP servers instead of one
undifferentiated bag.

`receive()` yields raw, backend-native messages (needed for full
fidelity — e.g. `crystalline.monitoring`'s Claude-specific recorder reads
cost/usage off a `ResultMessage`, which has no generic equivalent).
`describe_message(message) -> list[TextChunk | ToolCallChunk]` is a
separate, per-backend method that interprets one raw message into a
normalized shape a backend-agnostic consumer (the CLI) can render without
importing that backend's own SDK types — a list, not one optional chunk,
since one message can carry several blocks (interleaved text/tool-call).
`ClaudeCodeAgent.describe_message` implements this against
`AssistantMessage`/`TextBlock`/`ToolUseBlock`.

### `crystalline.project`

`Project` is a config object, not a framework: `name`/`version`/
`description`, `schema` (`SchemaRegistry`), `storage` (`Storage`),
`security` (`SecurityPolicy`), `tools`/`skills` (`ToolRegistry`/
`SkillRegistry`), `agent_config` (plain dict, not a live `Agent` — an
`Agent` carries async connection state that doesn't belong on a static
config object), `extensions_dir`, `monitoring_store` (a live
`SessionStore`, or `None` if unconfigured — fine to hold directly, since a
store has no async connection state), and a `properties` escape hatch.

Each configurable piece follows the same `build_x(config) -> X` /
`describe_x(x) -> config` / `register_x_backend(name, factory)` adapter
pattern (`crystalline.project.storage`/`.agent`/`.monitoring_config`),
keeping `crystalline.storage`/`.agents`/`.monitoring` themselves free of
"backend name" concepts. `register_storage_backend` optionally takes
`storage_cls`/`describe` so a custom backend can also round-trip through
`describe_storage` (for `save_project`), not just be built.

Schema types are declared as data (field name -> type-expression string:
`str`, `list[str]`, `X | None`, or the name of another type registered
earlier in the same file), compiled to real Pydantic models via
`crystalline.project.fields` (`pydantic.create_model`) — no forward
references yet, so types must be ordered dependencies-first.

`build_agent(project, *, session_id=None)` constructs the real `Agent`,
wires its system prompt/tools (`agent_wiring`), and wraps it in a
`MonitoredAgent` if `monitoring_store` is set. `build_router(project, *,
session_id=None)` is the `Router` equivalent. `sync_tools()` (re)generates
CRUD/admin tools from the current schema/storage/security; `load_project`
calls it automatically, as it does `apply_extensions`.

`examples/demo_shop/` is the worked example exercising all of this — see
`CLAUDE.md` for its exact contents and the hard rule against touching it
for ad hoc testing.

### `crystalline.events`

`Event` (`crystalline/events/event.py`): frozen dataclass, not Pydantic —
like `crystalline.agents.Tool`/`Skill`, an in-process object that never
itself crosses a boundary (a payload's shape is validated against a
tool's `input_model` at dispatch time instead). Fields: `type`, `payload`,
`project_name` (a bare string — this module depends only on `security`,
never `project`), `session_id`, optional `token`, auto-generated
`id`/`created_at`. `TEXT_EVENT_TYPE = "text"` is reserved for free-form
text input; `Router` always treats it as an agent handoff, checked before
any tool/skill name match, so a project can never shadow it.

`Router` (`crystalline/events/router.py`, same package — a router has
nothing to route without the event type it routes) is a one-method ABC:
`async def route(event) -> RouteResult`, where `RouteResult` is either a
direct tool/skill result or an `AgentHandoff(event, turn_id=...)`
sentinel. `RuleBasedRouter(project)` checks `TEXT_EVENT_TYPE` first, then
looks `event.type` up against `project.tools`/`project.skills` by name —
a match is validated against the tool's `input_model` and invoked with
`event.token` bound via `bind_token`; no match falls back to
`AgentHandoff`. Raises `ValueError` on a project-name mismatch. The
router never drives the agent conversation itself — returning
`AgentHandoff` hands that back to whoever produced the event.

Router stays rule-based deliberately: explicit name matching, not an LLM
classifier, keeps the common path deterministic and debuggable. Kept
behind the `Router` ABC so a smarter router can be swapped in later
without changing callers.

### `crystalline.monitoring`

Ingests session activity into a storage-agnostic database. `SessionStore`
(`crystalline/monitoring/store.py`) is a **sync** ABC — matching
`crystalline.storage.Storage`'s convention, not the async convention of
`tools`/`agents`/`events.Router` — with `start_session`/`end_session`/
`get_session`/`list_sessions`, `start_turn`/`end_turn`/`get_turn`/
`list_turns`, `append_event`/`list_events`. `SQLiteSessionStore` is the
one concrete backend, with its own three-table schema built directly on
`sqlite3` (deliberately not reusing `SQLiteStorage`'s id+JSON-blob design
— ordered appends and time-range queries don't fit that contract well).

Three tiers (`crystalline/monitoring/session.py`, all Pydantic — unlike
`Event`, these do cross a storage boundary):
- **`Session`** — one CLI invocation (login to quit, spanning every
  `/reload`). Rolls up nothing itself.
- **`Turn`** — one user-initiated action, from event to resolution
  (direct dispatch, or a full agent conversation). Carries `status`/
  `duration_ms`/`total_cost_usd`/`usage`/`result`/`errors`.
- **`SessionEvent`** — one step within a turn: `{session_id, turn_id,
  kind, data: dict, parent_event_id, id, created_at}`. `EVENT_KIND_*`
  constants (`route_decision`/`user_message`/`assistant_text`/
  `tool_call`/`tool_result`/`message`) are what the Claude instrumentation
  below produces, not a closed enum.

**Claude instrumentation** lives in `crystalline/project/
monitoring_wiring.py` (needs `agents`+`monitoring`+`events` all at once —
a wiring concern), not inside `crystalline.monitoring` itself:
- **`MonitoredRouter`** wraps `RuleBasedRouter` and owns `Turn` creation —
  `route(event)` always opens a turn and records a `route_decision` event
  first, *before* anything else, so the originating event always lands in
  the session regardless of how it's handled. For a direct dispatch it
  records `tool_call`/`tool_result` and closes the turn itself; for an
  agent handoff it leaves the turn open and returns `AgentHandoff(event,
  turn_id=...)`.
- **`MonitoredAgent`** wraps any `Agent`. `continue_turn(turn_id)`
  attaches to a turn already opened by a `MonitoredRouter` so the next
  `send()` appends to it instead of starting a new one (consumed after
  that one `send()`). `receive()` feeds each message through a swappable
  `MessageRecorder` (default `claude_message_recorder`) and
  `TurnOutcomeExtractor` (default `claude_turn_outcome`, which recognizes
  `ResultMessage` and calls `end_turn`). A still-open turn is force-closed
  with `status="error"` if a new `send()` arrives before the previous
  turn's `ResultMessage`, or if `disconnect()` happens mid-turn.
- **Session lifecycle is the CLI's job** (`start_monitoring_session`/
  `end_monitoring_session`, both no-ops if `monitoring_store` is `None`).
  One `session_id`, generated once per CLI invocation, flows into both
  `build_agent`/`build_router` and persists across every `/reload`.

A project file's `monitoring:` section (`{type: sqlite, path: ...}`) has
no always-on default, unlike `storage:` — no section means
`Project.monitoring_store` is `None` and nothing is recorded.

### `crystalline.crystallization` — not yet built

Will periodically walk sessions captured by `monitoring`, look for
recurring patterns in agent-only (non-crystallized) handling, and propose
or generate new `tools`/`skills` to cover them, using `agents` to help
write the new tool/skill itself. The most speculative component, last in
dependency order since it needs everything else already working. Open
design questions, to resolve when building it: cron-style periodic job
vs. manual trigger; whether generated tools/skills are auto-merged or go
through human review before becoming part of a project (likely
human-in-the-loop initially).

### `crystalline.cli` — not one of the ten components

A concrete stand-in for the `events`/UI-layer and `router`
responsibilities, built early so there was something to drive the project
through. `crystalline --project <path> --user <id> --password <pw>`
authenticates, mints a token, binds it for the REPL's lifetime, and opens
a loop of free text / `/command`s.

Free text is wrapped in a `TEXT_EVENT_TYPE` `Event` and routed through
`build_router` (built fresh each line, so it reflects the current project
including right after `/reload`) — a tool/skill match short-circuits the
agent entirely; otherwise the `AgentHandoff` is streamed via
`agent.send()`/`receive()`, using `describe_message` to render without
importing `claude_agent_sdk` types directly. Slash commands
(`crystalline/cli/commands.py`) remain direct `Tool.invoke()` calls, not
routed through `Router`. See `CLAUDE.md` for the full command list and
rendering/input-handling details.

One thing still open here: CLI admin commands (`/users`, `/roles`) call
through `project.tools` directly with typed args parsed from `list[str]`.
A natural-language equivalent ("disable user ada") resolving to the same
tools would need the router to extract structured args from free text —
out of scope for the deliberately rule-based `RuleBasedRouter`, so this
stays a separate code path until that changes.

## Open questions

- **Crystallization trigger and review flow.** Cron-style periodic job
  vs. manual trigger; whether generated tools/skills are auto-merged or go
  through a human review/approval step before becoming part of a project.
  Decide when building that component — likely human-in-the-loop
  initially.

## Repository layout

```
crystalline/
  __init__.py
  schema/
  storage/
  security/
  tools/
  skills/
  agents/
  project/
  events/            # Event + Router
  monitoring/         # Session/Turn/SessionEvent, SessionStore, SQLiteSessionStore
  crystallization/    # not yet built
  cli/                # not one of the ten components
examples/
  demo_shop/          # worked example project (YAML), with seed_data.py and extensions/
  load_demo_shop.py
docs/
  architecture.md     # this file
pyproject.toml
CLAUDE.md
```

Tests live under `tests/<component>/`, mirroring the sub-package
structure, so each component's tests can be run in isolation
(`pytest tests/schema`) even though they share one `pyproject.toml`/venv.
