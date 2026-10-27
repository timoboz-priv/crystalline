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

Each component lives in its own sub-package under `crystalline/` and gets
its own section in this doc once implemented (see "Status" below).

| Sub-package | Responsibility | Depends on |
|---|---|---|
| `crystalline.schema` | Pydantic data types shared across a project | — (foundation) |
| `crystalline.storage` | Generic CRUD persistence for any Pydantic model with an `id` field. **Implemented** — see below | standalone (not even `schema`) |
| `crystalline.tools` | Tools organized into APIs/MCP servers, typed on `schema` in/out. **Implemented** — see below | `schema`, `security`, `storage` |
| `crystalline.skills` | Workflows chaining tool calls (and optionally agentic steps). **Implemented** — see below | `tools`, `schema`, `agents` (optional) |
| `crystalline.agents` | Model layer: calls agents equipped with tools + schema. **Implemented** — see below | `schema` (future), presently standalone |
| `crystalline.security` | Users, roles, scopes; token minting, delegation, and verification. **Implemented** — see below | `schema`, `storage` |
| `crystalline.project` | Top-level config object: which agent, tools, skills, schema, security policy make up a project | all of the above |
| `crystalline.events` | `Event` definition + the `Router` that decides whether one is handled by a tool, a skill, or an agent. **Implemented** — see below | `security` (`Event`), `project` + `security` (`Router`, in the same package — see below) |
| `crystalline.monitoring` | Ingests all session activity into a (storage-agnostic) database. **Implemented** — see below | `events` (the Claude instrumentation itself lives in `project`, not here — see below) |
| `crystalline.crystallization` | Periodically mines monitored sessions and proposes/generates new tools/skills | `monitoring`, `tools`, `skills`, `agents` |
| `crystalline.cli` | Interactive command-line UI: free text + slash commands. **Implemented** — see below | `project`, `agents`, `security`, `events` |

### Dependency direction

```
schema
  ├── security
  ├── tools  (+ security)
  └── skills (+ tools, + agents optionally)

agents (standalone today; will take schema-typed tools later)

project = schema + tools + skills + agents + security + monitoring, wired together
events  = security (Event.token is a security.Token) + project (Router, same package)
cli     = project + agents + security + events
monitoring = events  (fed by the router, tools/skills, and agents as they execute)
crystallization = monitoring + tools + skills + agents
```

`monitoring`'s own package stays dependency-light (`events` only, really
just a label — its code doesn't actually import `crystalline.events`
today); the Claude-specific *instrumentation* that feeds it
(`MonitoredAgent`/`MonitoredRouter`) lives in `crystalline.project`
instead, since it needs `monitoring` plus `agents`/`claude_agent_sdk`
*and* `events` (for `RuleBasedRouter`/`AgentHandoff`) all at once — the
same "wiring belongs in project" reasoning as `events`'s `Router` needing
`project`, just with one more dependency in the mix. This makes
`crystalline.project.monitoring_wiring` <-> `crystalline.events` a
genuine bidirectional circular import at the package level (not just an
ordering issue), resolved with `TYPE_CHECKING`-deferred types plus local
imports inside the few functions that actually construct
`AgentHandoff`/`RuleBasedRouter` — see that module's docstring.

`crystalline.events` is the one exception to "a sub-package only depends
on what the table says" being a strict layering — `Event` itself depends
on nothing but `security`, but `router.py` in the same package also
depends on `project`, since a router has nothing to route without a
project's tools/skills to dispatch against. They're one package because
a router is meaningless without the event type it routes, not because
the dependency is symmetric.

Nothing below `project` in this graph should import `events`'s router
half, `monitoring`, or `crystallization`. If you find yourself wanting that,
the thing you're building probably belongs in `project` or a new adapter
module, not in the lower-level package.

### `crystalline.project` — the top-level entity (implemented, first pass)

A `Project` is a config object, not a framework. It will eventually hold
references to a tool registry, a skill registry, one or more agent
configs, and a security policy, each with programmatic add/get/update/
remove (mirroring the pattern already used in `crystalline.agents.Agent`
for tools/skills/properties). First pass implements the part of that
which doesn't depend on unbuilt components:

- `name: str`, `version: str`, `description: str | None`
- `schema: SchemaRegistry` — a project's own registry instance
- `storage: Storage` — a project's own `crystalline.storage.Storage`
  instance (defaults to `InMemoryStorage()`), persisting the project's
  schema-typed records
- `agent_config: dict[str, Any]` — `{"type": ..., ...}`, defaults to
  `{"type": "claude_code"}`. Unlike `storage`, this is *not* a live
  `Agent` instance — an `Agent` carries async connection state that
  doesn't belong on a static config object. `crystalline.project.
  build_agent(project)` constructs the actual `Agent` it names (with
  tools and system prompt already wired via `agent_wiring`) only when
  something is about to start a session.
- `properties: dict[str, Any]` — the same get/set/remove escape hatch
  pattern as `crystalline.agents.Agent`, for stashing config that belongs
  to a not-yet-built component (tools, skills, security policy) until
  that component exists and gets a dedicated field.

A project file's `storage` section is just `{type: <backend>, ...}` —
`crystalline.project.storage` (`build_storage`/`describe_storage`) is the
adapter between that declarative shape and a real `Storage` instance; it
owns the backend-name registry (`register_storage_backend` to add more),
not `crystalline.storage` itself. A relative `path` property is resolved
against the project *file's* directory, not the process's working
directory, so `crystalline --project examples/demo_shop/project.yaml`
behaves the same regardless of where it's run from — see
`examples/demo_shop/project.yaml`, which wires a `sqlite` backend against
`demo_shop.db` next to the project file, seeded with three users
(`admin`/`admin123`, `alice`/`alice123` as editor, `bob`/`bob123` as
viewer) plus 10 customers / 5 products / 5 orders via
`examples/demo_shop/seed_data.py` (idempotent — re-run it any time to
backfill anything missing without disturbing existing records), plus a
`place_order` skill and a `total_revenue` tool in
`examples/demo_shop/extensions/` (`extensions: extensions/` in the
project file — loaded automatically, no CLI flag needed). This is the
user's own live demo project — don't load it, modify it, or touch
`demo_shop.db` for ad hoc/live testing; use a scratch project instead.
Its `agent` section is `{type: claude_code, model: claude-sonnet-5-5}`.

A project file's `agent` section mirrors `storage`'s shape exactly:
`{type: <backend>, ...}`, with `crystalline.project.agent`
(`build_agent_config`/`describe_agent_config`/`register_agent_backend`)
as the adapter and backend-name registry — `"claude_code"` maps to
`crystalline.agents.ClaudeCodeAgent`, everything besides `type` passed
through as constructor kwargs (e.g. `model`).

**Loading/saving** is file-based (JSON or YAML, dispatched on extension)
via `crystalline.project.load_project`/`save_project`. A config file
declares a project's schema types *declaratively* — field name to a small
type-expression string (`str`, `list[str]`, `X | None`, or the name of
another type registered earlier in the same file) — rather than pointing
at Python classes, since the whole point is that a project file is data,
not code. Referencing another in-project type by name is how nesting
works (e.g. `Order.items: list[OrderItem]`, with `OrderItem` defined
earlier in the file) — there's no separate "nested type" feature, it
falls out of type names resolving against the registry. The only current
limitation: a referenced type must already be registered, so types must
be ordered dependencies-first in the file (no forward references yet).
`crystalline.project.fields` compiles expressions to real Pydantic models
via `pydantic.create_model` (and back, for saving) —
see `crystalline/project/fields.py` for the exact grammar. A worked
example lives in `examples/demo_shop/`.

### `crystalline.schema` — data types

Suggestion from the brief: **Pydantic** (v2). Decision: yes — it gives us
validation, JSON Schema generation (useful for tool input/output specs and
for MCP), and serialization for free, and the SDK ecosystem (MCP, FastAPI,
etc.) already speaks Pydantic. Types are registered in a schema registry
by name so tools/skills/events can reference them without a direct Python
import where that matters (e.g. config-file-driven wiring).

### `crystalline.storage` — generic CRUD persistence (implemented)

An abstract `Storage` (`crystalline/storage/base.py`) doing generic
create/get/update/delete/list for any `pydantic.BaseModel` that has an
`id` field — not just `CrystallineModel`/schema-registry types, though
those qualify automatically since they're `BaseModel` subclasses. This is
deliberately the one component with **no dependency on `crystalline.schema`
at all**: it only needs Pydantic. Records are bucketed by `model.__name__`,
so one `Storage` instance should be scoped to one schema namespace (one
project) — two unrelated types sharing a name would collide.

Two backends ship today, both satisfying the same contract (see
`tests/storage/test_storage.py`, parametrized over both):

- `InMemoryStorage` — a dict of dicts, gone when the process exits.
- `SQLiteStorage` — one table per type, storing each record as
  `id` + a JSON blob (`model.model_dump_json()`/`model_validate_json()`).
  That sidesteps mapping every field type (nested models, lists, dicts)
  onto SQL columns; the cost is `list(**filters)` loads all rows of that
  type and filters in Python rather than pushing the filter into SQL.
  Fine for a first implementation — revisit if a project's data outgrows
  it. Takes a path (or `:memory:`).

Conventions, both deliberate simplifications for this first pass:
`update()`'s id parameter is named `record_id`, not `id`, specifically so
`id` can appear in `**changes` (and get rejected with a clear error —
a record's id is immutable) without colliding with the positional
parameter. `list(**filters)` only does exact-match equality on field
values — no comparisons, sorting, or pagination yet.

**Why this exists now, ahead of `tools`:** the plan is for
`crystalline.tools` to auto-generate one MCP server per registered schema
type, with tool functions (`create_x`/`get_x`/`update_x`/`delete_x`/
`list_x`) that are thin wrappers calling through a `Storage` instance.
Building `Storage` first, independent of `tools`, means it can be tested
and used standalone before that wiring exists.

### `crystalline.tools` — tools as APIs/MCP servers (implemented)

`Tool` (`crystalline/tools/tool.py`) is the project-level source of truth
for "what can be done": a name, a Pydantic `input_model` (and optional
`output_model`), an async `handler(data: BaseModel) -> Any`, an optional
required `scope`, and a `group` (which API/MCP server it belongs to).
`ToolRegistry` is the name -> `Tool` CRUD registry (same collision
protection as `SchemaRegistry`: raises on name collision unless
`replace=True`), with `register()` decorator sugar matching the pattern
used everywhere else in the codebase.

**`Tool.invoke(data)` is the one true call path** — it checks `enabled`
and `scope` (via `crystalline.security.check_scope`/`current_token()`)
before calling `handler`. Both the MCP-facing adapter and CLI admin
commands call through `invoke()`, specifically so the scope check can't
be bypassed by calling a handler directly from either.

This resolves the open question that used to live here: `crystalline.
agents.Tool` (generic, agent-facing, raw dict-in/dict-out MCP handler)
and `crystalline.tools.Tool` (project-level, Pydantic-typed, security-
scoped) are deliberately different shapes for different audiences.
`crystalline.project.agent_wiring.wire_tools(agent, project)` is the
adapter: for each `Tool`, it builds an `agents.Tool` whose handler
validates the raw MCP args against `input_model`, calls `tool.invoke`,
and serializes the result back to MCP's `{"content": [...]}` shape
(`crystalline.tools.to_jsonable` handles Pydantic models/lists/dicts).
`crystalline.agents.claude_code.ClaudeCodeAgent` groups handler-tools
into one SDK MCP server per distinct `tool.metadata["group"]` value, so a
project's "storage" and "admin" tools end up as two separate MCP servers
rather than one undifferentiated bag.

**Auto-generated tools**, both regenerable via `Project.sync_tools()`
(idempotent — safe to call again after the schema changes; `load_project`
calls it automatically):

- `crystalline.tools.crud.generate_storage_tools(schema, storage)` — for
  every registered type that both isn't reserved (`User`) and actually
  has an `id` field (so a nested value type like `OrderItem`, embedded in
  `Order` but never looked up on its own, correctly gets no tools —
  `Storage` itself requires an `id` to manage a type), generates
  `create_x`/`get_x`/`update_x`/`delete_x`/`list_x`, scoped
  `{Type}:create`/`read`/`update`/`delete` to match the role scope
  patterns in `crystalline.security`. **One global `"storage"` MCP
  server for every type**, not one server per type — a project's
  registered types are naturally "the storage API", and one server keeps
  the tool list manageable as the schema grows.
- `crystalline.tools.admin.generate_admin_tools(storage, security, schema)`
  — hand-curated (not generic-CRUD-generated) tools for `User` in one
  `"admin"` MCP server: `list_users`/`get_user` (never return
  `password_hash` — resolving the open question that used to be here),
  `create_user`/`update_user` (take a plaintext `password` to hash, not a
  hash), `delete_user`; plus `list_roles`/`get_role`/`create_role`/
  `update_role`/`delete_role` over `SecurityPolicy`, and an unscoped
  `list_scopes` enumerating every `{type}:{action}` the schema currently
  supports plus the wildcard scopes. Scoped against `User:*`/`Role:*` —
  `Role` was added to `crystalline.security.scopes.PROTECTED_TYPES`
  alongside `User` specifically so the default `editor` role's
  `*:create`/`*:read`/`*:update`/`*:delete` can't redefine roles either.

**Hand-written tools** (anything auto-generation doesn't cover — a custom
aggregate, an integration with something outside the project's own
storage, ...) are declared the same way skills are — see the shared
extensions-folder discovery mechanism described under `crystalline.skills`
below, which covers both tools and skills together since the loading code
is identical for both. `examples/demo_shop/extensions/tool_total_revenue.py`
is the worked example: `total_revenue`, a read-only aggregate over
`Order` that generic per-record CRUD has no way to produce.

### `crystalline.skills` — workflows (implemented)

A `Skill` (`crystalline/skills/skill.py`) is structurally identical to
`crystalline.tools.Tool` — it's a dataclass *subclass* of `Tool`
(same Pydantic input/output, same single optional `scope`, same
`invoke()` call path), overriding only `group`'s default to `"skills"`.
No parallel implementation, no declarative step list: a skill's handler
is a plain async function that happens to orchestrate other tools, calling
their own `.invoke()` directly. This resolves the open question this
section used to flag (`Skill` vs. a hypothetical separate shape) the same
way `Tool` resolved it for `crystalline.agents.Tool` — reuse, not a
parallel hierarchy. `SkillRegistry` is a `ToolRegistry` subclass (same
collision-protected CRUD, inherited unchanged) whose `register()`
decorator builds a `Skill` instead of a bare `Tool`.

"Their own claims requirement (typically the union of their steps')"
isn't a separate declared/enforced field — it falls out for free from the
security principle that every `Tool.invoke()` (including a tool called
*from inside* a skill's handler) checks the ambient token's scope itself,
regardless of what already happened upstream. A skill's own `scope` (if
set) is a fail-fast gate checked before the handler runs, not a
replacement for the checks its internal tool calls still do.

Unlike `tools`, there's nothing to auto-generate `skills` from — a
workflow is custom logic, always hand-written. `Project.skills` starts
empty and application code populates it (`project.skills.add_tool(...)`
or the `@project.skills.register(...)` decorator) after the project and
its tools exist; there's no `sync_skills()`. `crystalline.project.
agent_wiring.wire_tools` wires `project.skills` onto an `Agent` exactly
like `project.tools` (a `Skill` already *is* a `Tool`, so no special
casing), landing in its own `"skills"` MCP server group, and
`system_prompt_for` includes it in the reported tool groups too.

**Folder-based discovery** (`crystalline/project/extensions.py`): a
project file declares one directory:

```yaml
extensions: path/to/dir   # resolved relative to the project file
```

Convention: one tool or skill per file, named `tool_*.py` / `skill_*.py`.
A `tool_*.py` file needs a `build_tool(project) -> Tool` function; a
`skill_*.py` file needs `build_skill(project) -> Skill`. Each returns
exactly one object, so a project's extensions directory listing *is* the
list of its custom tools/skills — see `examples/demo_shop/extensions/`.
`load_project` resolves `extensions:` via `resolve_extensions_dir` and
stores it on `Project.extensions_dir` as plain data — it does **not**
scan or execute anything; `project_to_dict` saves it back out the same
way. Parsing a project file should never run arbitrary code as a side
effect, even though *running* a project (which the CLI is about to do,
driving an agent with full tool access against it) already extends far
more trust than "also run the Python files it points to."
`apply_extensions(project)` is the explicit step that discovers
`tool_*.py`/`skill_*.py` files in `extensions_dir` and imports them —
`crystalline/cli/main.py` calls it automatically right after
`load_project`, and again whenever `/reload` fires, so declaring
`extensions:` in the project file is the only way in: there's no
`--tools <path>`/`--skills <path>` CLI flag, because everything a running
project needs should derive from the project definition itself (`--user`/
`--password` are the deliberate exception, since a login identity is
outside the project). `apply_extensions` is safe to call more than once
on the same project — each file's tool/skill is replaced
(`add_tool(..., replace=True)`), not duplicated — which is what makes
`/reload` work without accumulating stale duplicates.

An earlier version pointed `tools:`/`skills:` at individual files with a
`register_tools(project)`/`register_skills(project)` convention, plus
`--tools`/`--skills` CLI flags as an ad hoc alternative path in. Folder
discovery replaced it: one file per capability instead of one file doing
arbitrary registration, and dropping the flags means there's exactly one
way a project acquires tools/skills, which `/reload` can re-run
deterministically.

The `/reload` CLI command (`crystalline/cli/commands.py`) re-runs
`load_project`/`apply_extensions`/`build_agent` against the same project
file path (`CLIContext.project_path`, threaded through from `--project`)
and swaps the live `Project`/`Agent` into the running `CLIContext` —
connecting the new agent before disconnecting the old one, and leaving
the old project/agent in place untouched if reloading raises. This is why
`crystalline/cli/repl.py`'s loop reads `ctx.project`/`ctx.agent`
throughout rather than capturing local variables: a command handler
mutating `ctx` mid-session needs the next loop iteration to see the
change immediately.

A `/skills` command (mirroring `/tools`) lists what's registered, and the
status bar/`describe_project` both show a skill count.
**Non-obvious bug, worth remembering if this loader is ever touched
again:** the dynamically-loaded module must be registered in
`sys.modules` *before* `exec_module` runs, not skipped — a skills (or
tools) file with two models where one references the other by name (e.g.
under `from __future__ import annotations`, very common style) fails with
`PydanticUserError: ... not fully defined` at the *first validation
call*, not at import time, if this is missed, since Pydantic resolves
forward references via `sys.modules[model.__module__]`. This was caught
by actually invoking the example skill live, not by the import succeeding
silently.

`examples/demo_shop/skills.py` is a worked example: `place_order` chains
`get_product` (to look up each line item's current price) and
`create_order` (to persist the computed result), doing the subtotal/total
arithmetic itself — exactly the kind of thing worth crystallizing into a
deterministic workflow instead of leaving an agent to improvise the
arithmetic in free text on every order. `examples/demo_shop/project.yaml`
declares both `tools: tools.py` and `skills: skills.py`, so loading it
through the CLI picks up `total_revenue` and `place_order` with no flags
needed.

### `crystalline.agents` — model layer (implemented)

Already built. `Agent` is the abstract base (tool/skill/property CRUD +
connect/send/receive/run lifecycle); `ClaudeCodeAgent` is the first
concrete implementation, backed by `claude-agent-sdk`. Future work here:
accept schema-typed tools from `crystalline.tools` directly instead of
requiring callers to hand-build `crystalline.agents.Tool` objects.

### `crystalline.events` + UI layer (implemented)

`Event` (`crystalline/events/event.py`) is the unit that flows through
the system: `type`, `payload`, `project_name`, `session_id`, an optional
`token`, plus an auto-generated `id`/`created_at`. A plain frozen
dataclass, not a Pydantic model — like `crystalline.agents.Tool`/`Skill`,
it's an in-process runtime object, not something that crosses a process
boundary or itself needs validation (a tool-bound `payload`'s own shape
is validated against that tool's `input_model` when the router dispatches
it, which is where Pydantic does its job instead). `project_name` is
deliberately a bare string, not a live `Project` reference — *this
module* depends on `security` (for `Token`) only, never
`crystalline.project`; resolving a name to an actual project is
`router.py`'s job, in the same package (see below).

`TEXT_EVENT_TYPE = "text"` is a reserved event type for free-form text
input (what a chat-style UI like the CLI sends for a plain message) —
`Router` always falls back to an agent handoff for it, checked *before*
any tool/skill name matching, so a project can never accidentally shadow
it by registering a same-named tool. UI layers (CLI, HTTP, chat,
whatever) are meant to be thin producers of events — they shouldn't
contain routing or business logic themselves; see the CLI's
`_dispatch_text` for the worked example (builds one `Event` per line of
free text, then just routes it).

**`Router`** (`crystalline/events/router.py`, same package as `Event` —
they started as separate `crystalline.events`/`crystalline.router`
packages, merged once it became clear a router has nothing to route
without the event type it routes, so the split added an import hop with
no real boundary behind it) is a one-method ABC — `async def
route(self, event: Event) -> RouteResult`, where `RouteResult` is either
a direct tool/skill invocation result or an `AgentHandoff(event)`
sentinel — specifically so a smarter (e.g. embedding- or LLM-based)
router can be swapped in later without changing callers; this resolves
the architecture doc's "small interface" open point. Unlike `event.py`,
`router.py` *does* depend on `crystalline.project` (for `Project`) — the
one asymmetry in this package, noted in the dependency table above.

`RuleBasedRouter` is the first (and currently only) implementation, true
to the decision below: explicit name matching, not an LLM classifier.
Constructed with one `Project`; `route(event)` checks `event.type ==
TEXT_EVENT_TYPE` first (always an `AgentHandoff`, unconditionally), then
looks `event.type` up against `project.tools`/`project.skills` by name —
a match is validated against that tool's `input_model` and invoked
directly (`event.token` bound via `bind_token` for the call, so
`Tool.invoke()`'s scope check applies exactly as it would from the CLI or
an agent's own MCP call); no match also falls back to `AgentHandoff`.
Raises `ValueError` if `event.project_name` doesn't match the router's
own project, as a sanity check against misrouted events. Driving the
actual agent conversation (e.g. streaming a reply) is left entirely to
whoever receives the `AgentHandoff` back — the router itself has no
opinion on how a UI layer renders an agent's response.

Decision: **start with explicit rule/pattern matching** (e.g. an intent
name or payload shape maps to a specific tool or skill), falling back to
an agent when nothing matches. No LLM-based classification yet — keep the
common path deterministic and debuggable. The matching strategy should sit
behind a small interface so a smarter (e.g. embedding- or LLM-based)
router can be swapped in later without changing callers.

**CLI integration.** `crystalline/cli/repl.py`'s free-text path no longer
calls `agent.send()` directly — it builds a generic `Event` (always
`type=TEXT_EVENT_TYPE`) and routes it through a `RuleBasedRouter` built
fresh from `ctx.project` on every line (so it always reflects the current
project, including right after `/reload`). Since a `"text"` event is
always an `AgentHandoff`, this is behaviorally identical to the old
direct call for ordinary conversation today — the CLI doesn't yet send
any other event type (that's a direct-tool-dispatch path available to
other/future UI layers, not something the CLI's own slash commands need,
since those already call `Tool.invoke()` directly). Slash commands
(`/users`, `/roles`, ...) are unaffected — they remain direct
`Tool.invoke()` calls, not routed through `crystalline.events.Router` at
all.

### `crystalline.security` (implemented)

Modeled on RFC 8693's actor-token pattern rather than invented from
scratch: a `Token` has `sub` (the original principal — a human user —
fixed through the whole call chain) and an optional, chainable `act`
record of who's actually acting right now (an agent, then maybe a
sub-agent), kept for audit/monitoring. Delegating via `token.act_as(actor,
scopes=...)` can only narrow the delegate's scopes to a subset of what the
parent already holds, never grant new ones — a sub-agent can never end up
with more power than its parent regardless of what it asks for.

`Token` is the primary, in-process vehicle — a frozen Pydantic model,
checked directly via `has_scope`/`has_role`. `to_jwt`/`from_jwt` (via
`pyjwt`, HS256) exist for when a token needs to cross a process boundary
or be persisted verifiably; same relationship as `crystalline.project`'s
config objects vs. their YAML/JSON files, so day-to-day code isn't paying
encode/decode cost for calls that stay in-process.

**Passing tokens down** uses ambient propagation
(`crystalline.security.context`: a `contextvars.ContextVar` plus
`bind_token`/`current_token`), not an explicit parameter — MCP tool
handlers are shaped `args: dict` matching a declared schema, with no slot
for one, and a token must never be something a model can supply itself.
Whoever mints or narrows a token wraps the call with `with bind_token(t):
...`; works across `asyncio` tasks and `asyncio.to_thread` (both copy the
current context).

**Checking** is `check_scope(token, "Customer:create")` (raises
`PermissionError`) or the `@requires_scope("Customer:create")` decorator
for wrapping an async tool handler — the shape `crystalline.tools` will
use once it auto-generates CRUD tool handlers over `Storage`.

**Scopes** are `"{type}:{action}"` strings with `*` wildcards per segment
(`scope_matches` in `crystalline/security/scopes.py`). One deliberate,
hardcoded exception: a *partial* wildcard (`"*:read"`, `"*:delete"`, ...)
never covers the reserved `"User"` type — only literal `"*:*"` (true
admin) or an explicit `"User:..."` grant does. Without this, the built-in
`editor` role (`*:create`/`*:read`/`*:update`/`*:delete`) would let any
editor read or delete other users' `password_hash` the moment generic
CRUD tools exist over every registered type. This lives in the generic
scope-matching function, not just in the default roles, because it must
hold for scopes a project defines itself too.

**Users and roles.** `User` (id, roles, password_hash, disabled) is
framework-provided and reserved: every `Project` auto-registers it in its
schema under the name `"User"` (a project file cannot redeclare that
name), and users are stored exactly like any other type — via the
project's own `Storage`. Roles are policy config, not business data: a
`SecurityPolicy` (name -> granted scope patterns) attached to the
project, with built-in defaults always present unless a project
overrides them by name:

- `admin`: `*:*`
- `editor`: `*:create`, `*:read`, `*:update`, `*:delete`
- `viewer`: `*:read`

A project file's `security:` section (`{roles: {...}, secret_key: ...}`)
and `users:` section (seed credentials: `{id, password, roles}`, hashed
with `bcrypt` and created in storage on first load, left alone on
subsequent loads) are both optional — see `examples/demo_shop/`. Note
`secret_key` round-trips in plaintext when a project is saved; fine for a
dev/demo file you control, not secret management for anything that
matters.

**CLI integration.** `crystalline --project <path> --user <id> --password
<pw>` (prompted — password hidden via `getpass` — if either is omitted)
calls `authenticate()` against the project's storage, mints a token via
`project.security.mint_token(user)`, and binds it with `bind_token` for
the lifetime of the REPL. `/whoami` prints the bound token's principal,
roles, and scopes. Enforcement happens at the tool-invocation boundary: a
tool checks the token's scope against its own requirement before running
(`check_scope`/`requires_scope`), regardless of what already happened
upstream (router, skill, agent, the CLI's own login check). Skills will
aggregate their steps' requirements but won't replace the per-tool check.

### `crystalline.monitoring` (implemented)

Ingests all project sessions (events in, decisions made, tool/skill/agent
invocations, outcomes) into a database. Decision realized: **storage-
agnostic interface first** — `SessionStore` (`crystalline/monitoring/
store.py`) is a sync ABC with one concrete backend so far,
`SQLiteSessionStore`. Sync, not async — matching `crystalline.storage.
Storage`'s convention (this is a storage layer, like that one), not the
async convention of `tools`/`agents`/`events.Router` (I/O-bound on an
external model, not on local persistence). Deliberately **not** built on
`crystalline.storage.Storage`: that contract is generic id-based CRUD
with exact-match filtering, and this needs ordered appends plus a
project/time-range query — different enough that reusing it would fight
the abstraction rather than share it; this also matches the dependency
table (`monitoring` depends on `events` only, not `storage`).
`SQLiteSessionStore` has its own three-table schema (`sessions`, `turns`,
`session_events`) built directly on `sqlite3`, not `SQLiteStorage`'s
id+JSON-blob design.

**Three tiers, not two** (revised after surveying how observability tools
built for this exact problem structure it — Langfuse's
Session/Trace/Observation, OpenAI's Conversation/Response/Item, both
putting status/cost/usage/duration on the *middle* tier, never the
session; OTel's GenAI semantic conventions go further and don't reify a
session object at all, just a `conversation.id` attribute correlating
spans). The original two-tier `Session` + flat `SessionRecord` design had
no way to group "everything that happened answering one prompt," which is
both the most useful grouping for display and the unit `crystallization`
will eventually mine patterns over. `crystalline/monitoring/session.py`:

- **`Session`** — one CLI invocation (login to quit), spanning every
  `/reload` within it. `id`, `project_name`, `principal`, `started_at`,
  `ended_at`, `metadata`. Rolls up nothing itself — totals are a query
  over its turns, never stored redundantly here.
- **`Turn`** — one user-initiated action, from the moment a UI layer
  builds a `crystalline.events.Event` and hands it to the router, through
  to however it's resolved (a direct tool/skill dispatch, or an agent
  handoff and everything that happens during that conversation). `id`,
  `session_id`, `status` (`in_progress`/`completed`/`error`),
  `started_at`, `ended_at`, `duration_ms`, `total_cost_usd`, `usage`,
  `result`, `errors`, `metadata`. This is the tier that carries
  cost/usage/duration, per the survey above — it's exactly what the old
  `turn_result` *event* kind used to hold, now promoted to a real object
  instead of a same-level sibling of `tool_call`/`assistant_text`.
- **`SessionEvent`** — one step within a turn: `session_id`, `turn_id`,
  `kind`, `data: dict`, `parent_event_id` (nullable, unused by the
  default recorder today but free to add now — borrowed from Langfuse's
  nestable observations, for a future producer that wants to nest a tool
  result under its call rather than beside it), `id`, `created_at`. Named
  `SessionEvent`, not `Event` — matching the survey's terminology exactly
  would collide with `crystalline.events.Event`, and unlike the
  `Skill`/`SessionStore` naming overlaps elsewhere (ours vs. an unrelated
  third-party concept), this would be two of *our own* packages reusing
  the identical name for related-but-different things. The *first* event
  in every turn, no exceptions, is a `route_decision` — see "Ownership,
  revised" below.

All three are Pydantic models, not dataclasses — unlike
`crystalline.events.Event` (an in-process dispatch envelope that's never
itself serialized), these *are* the things written to a `SessionStore`,
i.e. they cross a storage boundary, which is exactly what CLAUDE.md's
"Pydantic for anything that crosses a boundary" rule is about. One
flexible `SessionEvent` shape, not a rigid subclass per kind — "events
in, decisions made, tool/skill/agent invocations" (outcomes now live on
`Turn`) all fit as `{kind, data}`. `EVENT_KIND_*` constants
(`route_decision`, `user_message`, `assistant_text`, `tool_call`,
`tool_result`, plus a `message` catch-all for anything a recorder doesn't
explicitly parse) are
the kinds the Claude instrumentation below currently produces — not a
closed enum.

Note: `claude_agent_sdk` exports its own, unrelated `SessionStore`/
`InMemorySessionStore` (for the SDK's own session-resumption feature) — no
code collision, since they're in different namespaces, but don't confuse
the two. Same situation as `crystalline.agents.Skill` vs
`crystalline.skills.Skill`.

**Ownership, revised: the router opens turns, not the agent.** The first
cut of this (described in an earlier draft of this doc) had
`MonitoredAgent.send()` start every turn itself, with its own
`session_id` independent of the CLI's — which meant a direct tool/skill
dispatch (handled by `crystalline.events.Router` without ever touching an
`Agent`) was invisible to monitoring entirely. Revised so that **the
originating event always lands in the session, no matter how it's
handled or what type it is**:

- **`Session`** is owned by the CLI (`crystalline/cli/main.py`), not by
  `MonitoredAgent` — one `session_id`, generated once per CLI invocation,
  is passed to *both* `build_agent(project, session_id=...)` and
  `build_router(project, session_id=...)`, and spans every `/reload`
  within that invocation (a rebuilt `Project`/`Agent` still shares the
  same session). `start_monitoring_session`/`end_monitoring_session`
  (also in `monitoring_wiring.py`) are the only things that touch session
  lifecycle; both are no-ops if `project.monitoring_store` is `None`, so
  callers don't need to guard every call site themselves.
- **`Turn`** is owned by `MonitoredRouter` (`crystalline/project/
  monitoring_wiring.py`), wrapping a plain `RuleBasedRouter`. Its
  `route(event)` *always* opens a turn and records a `route_decision`
  event first — `{event_type, decision: "agent_handoff"|"direct_dispatch",
  basis, matched}` — before doing anything else. `basis` is currently
  always `"exact_type_match"` (all `RuleBasedRouter` does), but the field
  exists so a future smarter router has somewhere to report *why* it
  decided what it decided. For a direct dispatch, `MonitoredRouter` also
  records `tool_call`/`tool_result` and closes the turn itself
  (`status="completed"` or `"error"`, with the exception re-raised either
  way — monitoring never swallows an error). For an agent handoff, the
  turn is left `in_progress` and handed back via
  `AgentHandoff(event, turn_id=turn_id)` — the `turn_id` field `Router`
  gained specifically for this (a plain, non-monitoring `RuleBasedRouter`
  leaves it `None`).
- The CLI (`_dispatch_text` in `crystalline/cli/repl.py`) checks
  `result.turn_id` and, if the agent exposes a `continue_turn(turn_id)`
  method (duck-typed via `getattr`, not an `isinstance` check — a plain
  `ClaudeCodeAgent` simply doesn't have one and nothing breaks), calls it
  before streaming the reply. `MonitoredAgent.continue_turn` attaches to
  that turn so the next `send()` appends to it instead of starting a new
  one — the attachment is consumed after one `send()`, so a second,
  unrelated `send()` later in the same process goes back to self-managing
  its own turn (the original, router-less behavior, still fully supported
  for standalone/test use of `MonitoredAgent`).
- End to end, this makes a text turn look like: `route_decision` ->
  `user_message` -> (`assistant_text`/`tool_call`/`tool_result` as the
  model replies) -> turn closed via `claude_turn_outcome` on
  `ResultMessage`. A direct-dispatch turn looks like: `route_decision` ->
  `tool_call` -> `tool_result`, turn closed immediately — no
  `user_message`/`assistant_text` at all, since it never touched an
  agent. Both are full, equally-queryable turns in the same session,
  which is exactly what makes "how often did a rule handle this vs. the
  agent" answerable from the data instead of only inferable after the
  fact.
- `MonitoredRouter` doesn't formally subclass `crystalline.events.Router`
  — it structurally implements `route(event)` instead. Doing otherwise
  would make `crystalline.project.monitoring_wiring` import
  `crystalline.events` at module-load time, which is now a genuine
  **bidirectional** circular import (`crystalline.events.router` already
  does an absolute `from crystalline.project import Project`): `Event`/
  `RuleBasedRouter`/`RouteResult` are deferred to `TYPE_CHECKING` (safe at
  runtime — `from __future__ import annotations` makes every annotation
  in the file a string already); `AgentHandoff`/`RuleBasedRouter` are
  imported locally, inside the one function body each is actually
  constructed/called in.

**Project/CLI integration.** A project file's `monitoring:` section
mirrors `storage:`'s shape (`{type: sqlite, path: ...}`,
`crystalline.project.monitoring_config`) with one difference: there's no
always-on default (unlike `storage`, which defaults to in-memory) — no
`monitoring:` section means `Project.monitoring_store` is `None`,
`start_monitoring_session`/`end_monitoring_session`/`build_agent`/
`build_router` all treat that as "monitoring is off" silently, and
nothing is recorded. `crystalline/cli/main.py` generates `session_id`
once, calls `start_monitoring_session(project, session_id,
principal=user.id)`, passes `session_id` into both `build_agent` and
`run_repl`, and calls `end_monitoring_session` in a `finally` so it still
happens on `KeyboardInterrupt`. `/reload` (`crystalline/cli/commands.py`)
passes `ctx.session_id` (unchanged) to the rebuilt `build_agent` call —
it must *not* call `start_monitoring_session` again, since the session
already exists and `SessionStore.start_session` raises on a duplicate id.

### `crystalline.crystallization`

Periodically walks sessions captured by `monitoring`, looks for recurring
patterns in agent-only (non-crystallized) handling, and proposes or
generates new `tools`/`skills` to cover them — using `agents` to help
write the new tool/skill itself. This is the most speculative component
and the last one we should build; it depends on everything else already
existing and working.

### `crystalline.cli` — interactive command line (implemented, temporary)

A console script (`crystalline --project <path> --user <id> --password
<pw>`, prompting for either if omitted) that authenticates against the
project's `Storage`, mints a token, and opens a REPL: free text, or a
`/command`. This is **not** one of the ten architecture components — it's
a concrete stand-in for the `events` (UI layer) and `router`
responsibilities, built early because there was nothing else to drive the
project through yet. Two things to revisit once those components exist:

- Free text currently goes straight to a `ClaudeCodeAgent` built from the
  project (`crystalline/cli/main.py`). Once `router` exists, the CLI
  should produce `Event`s (carrying the bound token) and hand them to the
  router instead of calling an agent directly — a tool/skill match should
  short-circuit the agent entirely.
- `crystalline/cli/repl.py` imports `AssistantMessage`/`TextBlock` from
  `claude_agent_sdk` directly to print streamed replies, which only works
  because the CLI is hardwired to `ClaudeCodeAgent`. The generic `Agent.
  receive()` contract doesn't define a backend-agnostic message shape —
  if the CLI needs to work with a non-Claude-Code `Agent` later, this
  needs a normalized "text chunk" event that any `Agent` implementation
  can yield.
- CLI admin commands (`/users`, `/roles`) call through `project.tools`
  directly, synchronously with typed args parsed from `list[str]` — once
  `router` exists, natural-language equivalents ("disable user ada")
  should resolve to the exact same tools, not a separate code path.

Login failure (`PermissionError` from `crystalline.security.authenticate`)
prints the error and exits non-zero without opening the REPL. Passing
`--password` on the command line is visible in shell history and process
listings — acceptable for this dev/demo flow, not something to carry into
a real deployment. The token *is* enforced now: every generated storage
CRUD and admin tool call goes through `Tool.invoke`'s scope check,
whether triggered by the agent (MCP) or a `/users`/`/roles` CLI command.

Slash commands are a small registry (`crystalline/cli/commands.py`):
`/quit` (exit), `/project` (print the loaded project via
`crystalline.project.describe_project`), `/commands` (list all registered
commands), `/whoami` (print the bound token's principal, roles, and
scopes), `/tools` (list all registered tools, grouped), `/scopes` (list
every scope string via the `list_scopes` tool), and `/users`/`/roles`
(list/get/create/update/delete, dispatching on a sub-action: e.g.
`/users create ada secret editor`, `/roles create support Order:read`).
`CommandHandler` may be sync or async — `run_repl` awaits the result if
it's awaitable, which is what lets `/users`/`/roles` call through
`Tool.invoke` (async, so the scope check and the real handler both run).
Adding a command means registering a `(name, description) -> handler`
entry; a handler returns `False` to stop the REPL.

**Rendering** goes through `rich` (`crystalline/cli/console.py`): a
themed `Console`, a banner `Panel` at startup, assistant replies rendered
as `Markdown` (so a reply containing a table or bold text actually
renders as one, instead of literal `**`/`|---|` characters), a
"Thinking…" spinner while waiting for a reply, and a dim `⏺ tool_name(args)`
line printed live whenever the model makes a tool call (`ToolUseBlock` in
`receive()` — previously silently ignored, so tool activity was
invisible). One rule, enforced only by convention so far: our own static
UI text may use rich's `[tag]...[/tag]` markup; anything dynamic (tool
names/args, data) is either escaped (`rich.markup.escape`) or routed
through a renderer that doesn't interpret `[...]` as markup in the first
place (`Markdown`, `Table`) — forgetting this on a new print site lets a
crafted value break rendering.

**Every "list"-shaped command output renders the same way**, via
`crystalline.cli.console.render_result`: a list of dicts becomes a table
(one row per item — `/tools`, `/commands`, `list_users`); a dict becomes
a 2-column field/value table (`/whoami`, `list_roles`, single-record
results like `create_user`); a list of scalars becomes a single-column
table (`list_scopes`); a bare scalar (`bool`/`None`/a count) prints as
plain styled text. This was a deliberate consistency pass — the
alternative (bespoke rendering per command) was explicitly rejected.

**Layout and input** (`crystalline/cli/repl.py`) branch on
`sys.stdin.isatty()`:

- **Interactive terminal**: a `prompt_toolkit.PromptSession`. Its
  `bottom_toolbar` (`crystalline.cli.console.status_segments`: project
  name/version, logged-in user and roles, tool count, storage backend
  type, agent backend type) stays attached to the input box for as long
  as that `prompt_async` call is waiting — i.e. it's pinned to the bottom
  of the terminal the whole time the user is looking at the prompt, which
  is indistinguishable from "permanently there" in normal use. It does go
  away for the few seconds the agent is actively replying (replaced by
  the spinner/tool-call lines), then a fresh box+toolbar appear for the
  next turn. A genuinely always-on status bar *during* a reply too would
  need a full-screen `Application` layout instead of `PromptSession` — a
  materially bigger rewrite (rich's `Markdown`/`Table` output would need
  rendering to ANSI strings and bridging into the TUI's own buffers
  rather than printed directly) that was deliberately scoped out in
  favor of this simpler approach.
  The toolbar (`crystalline/cli/repl.py`'s `STATUS_BAR_STYLE`/
  `_status_toolbar`) uses one flat black background (`bg:ansiblack`)
  across every segment; the project name renders bold bright white
  (`fg:ansiwhite bold`), everything else (user/roles, tool count,
  storage/agent backend, separators) dim gray (`fg:ansigray dim`) — color
  and weight both vary per segment, but the background never does. The
  non-interactive rich fallback (`print_status_line`, via the
  `statusbar_project`/`muted` theme styles) matches the same scheme.
  Getting an actually-flat, correctly-black bar took three
  attempts, each only exposed by testing in a real terminal (a scripted
  pty with synthesized CPR responses showed the *intended* codes being
  emitted but can't catch a real terminal's own color-depth/rendering
  behavior):
  1. `"bottom-toolbar"` and `"bottom-toolbar.text"` are separate
     prompt_toolkit style classes — the toolbar `Window`'s fill uses the
     former, the text content the latter — so both need the override, or
     the one left alone keeps the library default (`"reverse"`).
  2. 24-bit hex colors (`bg:#000000`) render inconsistently across real
     terminals depending on detected color depth/truecolor support;
     named ANSI colors (`ansiblack`) and the `default` keyword (the
     terminal's own current foreground) map onto every terminal's
     standard palette and don't have that problem.
  3. Even with named colors, the bar still rendered as a solid colored
     band with inverted-looking text. Cause: `merge_styles` combines
     *attributes* per class across style layers, not whole rules —
     prompt_toolkit's own default `"bottom-toolbar": "reverse"` rule's
     `reverse` attribute kept applying underneath our fg/bg colors,
     silently swapping them back at render time (so the "background"
     shown was actually whatever the terminal's own ambient background
     color is — on a theme with a blue/navy-tinted default, that's a
     blue bar with inverted text, exactly the reported symptom). Fixed by
     adding `noreverse` to every class explicitly.
  The rendered text also starts two spaces in, to line up under where
  typed input starts after the `"❯ "` prompt; the non-interactive rich
  fallback (`print_status_line`) applies the same two-space indent for
  visual consistency between the two paths.
  History is a `prompt_toolkit.history.FileHistory` at
  `~/.crystalline/history`, shared across projects and sessions, giving
  Up/Down recall for free. Verifying any of this live requires a real pty
  that answers cursor-position-report (CPR) queries — a bare
  `os.openpty()` with nothing responding to CPR silently suppresses
  `bottom_toolbar` entirely (a prompt_toolkit limitation, not a bug in
  this code, confirmed by reproducing it with a minimal prompt_toolkit
  script outside crystalline entirely, then fixing it by having the test
  harness answer `\x1b[6n` like a real terminal does). A real terminal
  (Terminal.app, iTerm2, a real SSH session, ...) always answers CPR, so
  this only bites synthetic/scripted test harnesses, not actual users.
- **Piped/non-interactive stdin** (including this project's own test
  suite): a plain `input()` loop, with the project/version/user/tools/
  storage info printed via `print_divider`/`print_status_line` (rich,
  not prompt_toolkit) around each turn instead, since prompt_toolkit
  itself expects a real tty.

Separately, `CLIContext.history: list[str]` records every line submitted
this session (commands and free text alike, appended before dispatch —
so `/history` run as the very first command still shows itself, like a
shell's own `history` builtin) regardless of which input path is active;
`/history` renders it via the shared `render_result`.

Pressing Ctrl+C while waiting at the prompt is caught both inside
`run_repl`'s loop (alongside `EOFError`, so it exits the REPL cleanly the
same way Ctrl+D does) and, as a fallback, in `crystalline/cli/main.py`
around `asyncio.run(run_repl(...))`, exiting with code 130 instead of
dumping an uncaught `KeyboardInterrupt` traceback — found while debugging
an unrelated report, not designed upfront.

**Known footgun (not a code bug): don't run manual/live CLI tests against
`examples/demo_shop/`'s real `demo_shop.db` while someone else might be
using it.** It's a single shared SQLite file; a concurrent test run that
deletes/recreates it (e.g. `rm -f demo_shop.db` between test iterations)
can pull the file out from under another process that still has it open,
silently losing whatever that process writes afterward. This looks
exactly like a "created user doesn't persist after restart" bug but
isn't one — the storage/commit path itself was verified correct (clean
quit, Ctrl+C mid-session, and logging in as a freshly-created user were
all tested and persisted correctly in isolation). Use a scratch project
file for ad hoc testing instead of the shared demo one.

## Status

| Component | Status |
|---|---|
| `crystalline.agents` | Implemented (`Agent`, `Tool`, `Skill`, `ClaudeCodeAgent`). `ClaudeCodeAgent` now groups handler-tools into one SDK MCP server per `tool.metadata["group"]`. **TODO:** revisit once `crystalline.skills` exists (the `Tool`/`crystalline.tools.Tool` question is resolved; see that component's section). |
| `crystalline.schema` | Implemented (`CrystallineModel`, `SchemaRegistry`) |
| `crystalline.storage` | Implemented (`Storage` ABC, `InMemoryStorage`, `SQLiteStorage`) |
| `crystalline.tools` | Implemented (`Tool`, `ToolRegistry`, storage CRUD + user/role/scope admin tool generation, wired into `Project`/`ClaudeCodeAgent`) |
| `crystalline.skills` | Implemented (`Skill` as a `Tool` subclass, `SkillRegistry`, wired into `Project`/`agent_wiring`/CLI and `/skills` command) |
| `crystalline.security` | Implemented (`Token`/`Actor`, `SecurityPolicy`, `User`, auth, context propagation, scope checks) |
| `crystalline.project` | First pass implemented (`Project` with name/version/description/schema/storage/security/tools/skills/agent_config/extensions_dir/monitoring_store/properties; JSON/YAML load/save; `sync_tools()`; `build_agent`/`build_router`/`wire_tools`/`system_prompt_for`; `extensions.apply_extensions` for folder-discovered `tool_*.py`/`skill_*.py` files, reusable from the CLI's `/reload` command; `monitoring_wiring` — `MonitoredAgent`/`MonitoredRouter` auto-wrapping `build_agent`/`build_router`'s results and `start_monitoring_session`/`end_monitoring_session` owning session lifecycle — when `monitoring_store` is set). |
| `crystalline.events` | Implemented. `Event` frozen dataclass (`type`/`payload`/`project_name`/`session_id`/`token`/`id`/`created_at`; `TEXT_EVENT_TYPE` reserved constant) plus `Router` ABC + `RuleBasedRouter` in the same package (name-matches `event.type` against a project's tools/skills via `resolve()`, falling back to `AgentHandoff(event, turn_id=...)`; wired into the CLI's free-text path) — originally a separate `crystalline.router` package, merged in since a router has nothing to route without the event type it routes. |
| `crystalline.monitoring` | Implemented. Three-tier `Session`/`Turn`/`SessionEvent` Pydantic models; `SessionStore` ABC (sync) + `SQLiteSessionStore`. Claude instrumentation (`MonitoredAgent`, `MonitoredRouter`, `claude_message_recorder`, `claude_turn_outcome`, `start_monitoring_session`/`end_monitoring_session`) lives in `crystalline.project.monitoring_wiring` — `MonitoredRouter` opens every turn (recording a `route_decision` event first, always), `MonitoredAgent` continues it via `continue_turn()` on an agent handoff. Wired into the CLI via a project file's `monitoring:` section. |
| `crystalline.crystallization` | Not started |
| `crystalline.cli` | Implemented (not one of the ten components). `crystalline --project <path> --user <id> --password <pw>`, `/quit`, `/project`, `/reload`, `/commands`, `/whoami`, `/tools`, `/skills`, `/scopes`, `/users <action>`, `/roles <action>`, `/history`. Free text is wrapped in a `TEXT_EVENT_TYPE` `Event` and routed through a `RuleBasedRouter`, same path any other UI layer would use. `rich`-based rendering (banner, Markdown replies, tool-call lines, consistent table output); `prompt_toolkit`-based input on a real terminal (pinned box + status-line `bottom_toolbar`, persistent `~/.crystalline/history` with Up/Down recall), falling back to plain `input()` when stdin isn't a tty. |

## Build order

1. `schema` — everything else types against this
2. `security` — small, independent, needed before `tools` can enforce anything
3. `tools` — depends on `schema` + `security`
4. `agents` — adapt existing implementation to accept schema-typed tools
5. `skills` — depends on `tools`, `schema`, optionally `agents`
6. `project` — wires schema/tools/skills/agents/security into one config object, with JSON/YAML loaders
7. `events` — depends on `schema` + `security` (token shape)
8. `router` — depends on `project` + `events`
9. `monitoring` — storage-agnostic interface, fed from `events`/`router`
10. `crystallization` — last; depends on everything above

We'll go component by component in this order, nailing down the concrete
API and data model for each before moving to the next.

## Open questions / known tensions

These are flagged, not blocking — resolve each when we build the relevant
component:

- **`crystalline.agents.Tool` vs. `crystalline.tools.Tool` — resolved.**
  See `crystalline.tools`'s section: `crystalline.project.agent_wiring`
  is the adapter, `wire_tools(agent, project)`.
- **`crystalline.agents.Skill` vs. `crystalline.skills.Skill` — resolved,
  same way as `Tool` was, via the same adapter.** `crystalline.skills.
  Skill` is a `Tool` subclass, so `crystalline.project.agent_wiring.
  wire_tools` already handles it with no extra code — no new adapter was
  needed here. `crystalline.agents.Agent`'s own `Skill` dataclass (SDK
  skill directories, a different concept entirely — markdown capability
  packages the model reads, not something our code invokes) is untouched
  and still separate; nothing currently bridges a project's
  `crystalline.skills.Skill`s into that mechanism, and nothing needs to.
- **`User.password_hash` exposure via generic CRUD tools — resolved.**
  `User` is excluded from `crystalline.tools.crud`'s generic generation
  entirely; hand-curated tools in `crystalline.tools.admin` never read or
  return `password_hash` (`create_user`/`update_user` take a plaintext
  `password` to hash on the way in; `get_user`/`list_users` return an
  explicit safe subset).
- **Monitoring storage backend.** Interface first; concrete backend
  (SQLite, Postgres, something else) decided when we implement it.
- **Crystallization trigger and review flow.** Cron-style periodic job vs.
  manual trigger; whether generated tools/skills are auto-merged or go
  through a human review/approval step before becoming part of a project.
  Decide when we get there — likely human-in-the-loop initially.

## Repository layout

```
crystalline/
  __init__.py
  project/           # implemented (first pass)
  schema/            # implemented
  storage/           # implemented
  tools/             # implemented
  skills/            # implemented
  agents/            # implemented
  events/            # implemented (Event + Router)
  security/          # implemented
  monitoring/        # implemented (Session/Turn/SessionEvent, SessionStore, SQLiteSessionStore)
  crystallization/
  cli/               # implemented (not one of the ten components)
examples/
  demo_shop/         # worked example project (YAML), with seed_data.py and extensions/
  load_demo_shop.py
docs/
  architecture.md    # this file
pyproject.toml
CLAUDE.md
```

Tests live under `tests/<component>/`, mirroring the sub-package
structure, so each component's tests can be run in isolation
(`pytest tests/schema`) even though they share one `pyproject.toml`/venv
for now.
