---
title: Per-App Auth Standards
date: 2026-06-23
status: draft-for-review
audience:
  - llm
  - developer
related_specs:
  - tap_auth/specs/spec-tap-auth-v0.md
  - specs/archive/spec-tap-auth-assurance-v0.md  # DEPRECATED/retired 2026-07-08 — surface-centric model rejected
  - specs/spec-security-posture.md
  - specs/spec-tap-flaw-v0.md
related_docs:
  - docs/misc/doc-auth-codepath-inventory.md
---

# Per-App Auth Standards

## Purpose & status

This doc captures **how authorization is handled inside each TAP app**, given that each app
has a different *operational construction* and was built in a different era (some before
Gryphon, before the service layer, before authZ existed at all). The thesis: auth wants a
**common core** (one capability model, one service layer, one structural backstop) plus a
**per-app standard** fitted to how each app binds an actor and reaches graph state. Trying to
apply one identical approach across all apps is what produced whack-a-mole.

**Status: draft for review; core partially landed.** Each app section is self-contained so it can
be reviewed independently. The **core** tightening pass has landed (`req-tap-auth-policy` stateless
backstop + the `{grid.delete}` split + empty-batch + `is_actor_active`, plus the Rule-A coverage
lint; commits `66ff0f2`/`88dd555`); the per-app passes (tap_cares, tap_web, tap_boot, plugins) are
still ahead. Decisions that are genuinely open are collected in [Open Decisions](#open-decisions).

> **Post-backout note (read first).** The contextvar **decision ledger was removed** — the backstop
> is now a direct `policy.can(actor, needed_cap)` re-check (`req-tap-auth-policy-8`). Any mention
> below of a "ledger", `record_authorization`, "ledger isolation", or "ledger lifecycle" describes
> the *superseded pre-backout* analysis. The forward-looking standards in this doc have been updated
> to the stateless model; the ledger-leak, empty-batch, and cover-cap classes are now closed **by
> construction**. Build-time gate coverage comes from the authz-coverage lint (`req-tap-auth-policy-9`,
> Rule A live). **Do not reintroduce ledger machinery** in the per-app passes.

This is **capability-centric, not surface-centric.** The heavier per-surface assurance model
(a la Cedar/surface-identity) was deliberately rejected for this scale — every real issue
below is a *forgotten or bypassed capability gate*, and none is solved by surface identity.

## Provenance & a note on reliability

Derived from two passes: the static [auth codepath inventory](doc-auth-codepath-inventory.md)
(a useful map) and an independent per-app verification pass that read each app's real code.
The inventory was treated as a *map, not an oracle*: its most concrete trust-gating claim
("parse-invalid Python-2 exception syntax blocks trusting the suite") was a **confirmed false
positive** — `except A, B:` is valid Python 3.14 via PEP 758, which the project requires. So
each claim here was verified against source; the file:line anchors are corroborated.

One **meta-finding** runs through several apps: the autouse `conftest` fixture
(`default_caller_context`) binds a privileged ambient actor for *every* DB test, which structurally
hides the **ambient-actor class** (tap_cares/tap_boot broken in prod, green in CI) — the test
harness is blind to exactly the class we keep shipping. (The fixture used to *also* pre-authorize a
ledger, masking a now-removed ledger-leak class; that pre-auth went with the backout — the
ambient-actor masking remains and is the load-bearing one for the tap_cares pass.) Fixing
test-realism is itself a standard (see tap_cares / tap_boot enforcement and
[Open Decisions](#open-decisions)).

---

## The Common Core

`tap_auth` **defines** it; `tap_grid` **owns** the two chokepoints that consume it; every
other app **inherits** it unchanged. Five invariants:

1. **Named actor.** A `CallerContext` carries the acting user or program-actor. No
   anonymous / `User=None` at a protected boundary. Passing authentication is never permission.
2. **Capability gate.** `policy.authorize(ctx, cap)` evaluates actor → Django group →
   permission → capability (**not** `has_perm`, so `is_superuser` is not a service bypass) and
   raises typed `AuthzError` on denial (no decision ledger — see the post-backout note).
   Vocabulary is fixed: `grid.read/write/delete/import_grift/admin/purge`,
   `cares.run_collectors`, `auth.manage_*`, `config.manage`, `plugins.manage`.
3. **Service layer is the only sanctioned graph path.** Reads via the
   `@requires_capability('grid.read')`-decorated Search/Gryphon executors; writes via
   `write_batch` / `assert_write_authorized`. Direct ORM on `Entity`/`Edge`/graph-managed
   `BaseModel` is a bypass except for migrations / intentional low-level.
4. **Structural backstop (stateless).** `@requires_capability` / `authorized()` authorize before
   the body; `assert_write/read_authorized` **fail closed** with `UnguardedOperation` (a loud
   500-class Flaw) via a direct `policy.can(actor, needed_cap)` re-check if commit/return is
   reached with an actor that lacks the capability the op requires (or no actor).
5. **Edge translation.** `AuthzError` → 403; `UnguardedOperation` stays a loud 500.

> **The load-bearing structural fact:** the backstop has reach **only over operations that
> enter the service layer.** Anything that touches graph state via direct ORM (web panels,
> plugin panels, scheduler cursor fields, boot EntityType registration) is *outside the
> contract and ungated by structure*. This is why the highest-leverage fixes move the gate to
> a **host chokepoint**, rather than trusting each caller to route through the service layer.

A correctness gap in the core is inherited platform-wide, so the core's enforcement bar is the
highest in the system. **Tighten the core first.**

---

## App: tap_grid + tap_auth (the core / standard-setter)

**Operational construction.** `tap_auth` owns the ledger primitives, both backstops, and the
cover-cap sets; `tap_grid` owns the two service chokepoints (`write_batch`,
Search/Gryphon read dispatch). Two enforcement styles coexist: (1) *structural* —
`@requires_capability`/`authorized()` open an isolated ledger scope and the chokepoint asserts
a decision exists; (2) *edge-gate* — API/web views call **bare** `policy.authorize(ctx, 'grid.read')`
with no scope push, then read via direct ORM, never touching the structural backstop.

**Why it's loose (era).** `tap_grid/services.py` is the **oldest** surface — it predates
`tap_auth` entirely (its write pipeline still has a "Step 2: Security/authz stub (reserved)"
comment). The gate, ledger, and backstops were bolted on as decorators + two chokepoint
asserts over a pre-authZ pipeline. The leak, the empty-batch hole, and the undecorated reads
are that retrofit seam.

**Vulnerability classes:**

- **Ambient-ledger leak.** Edge gates `record_authorization` into the ambient contextvar;
  `CallerContextMiddleware` resets `CallerContext` per request but **never** resets the ledger
  (`reset_authorization_ledger` is never called in prod). A leaked `grid.read` satisfies the
  backstop for a later op that itself authorized nothing; on a reused worker thread it bleeds
  into the next request. — `tap_auth/policy.py:52-77`, `tap_auth/middleware.py:47-55`,
  `tap_api/routers/{entities.py:34,43, edges.py:35,48, searches.py:44}`, `tap_web/views.py:226,275`.
- **Empty-batch authorization void.** `write_batch([])` → `needs_write`/`needs_delete` both
  False → `assert_write_authorized` no-ops, yet `_ensure_batch` still creates an `Entity`+`Batch`.
  — `tap_grid/services.py:690-696,718-725`, `tap_auth/enforcement.py:164-182`.
- **Cover-cap over-grant.** `WRITE_CAPABILITIES`/`DELETE_CAPABILITIES` include broad covers
  (`grid.import_grift`, `grid.admin`), so the **delete** backstop is satisfiable without
  `grid.delete`. The bootloader bundle excludes `grid.delete`/`grid.purge` "so a boot bug can't
  nuke the grid" — yet reaches the delete backstop via the cover. — `tap_auth/capabilities.py:88-89,125-135`,
  `tap_auth/enforcement.py:179-182`.
- **Undecorated convenience reads.** `resolve_entity`/`get_node`/`get_edge`/`get_object` read
  rows with no `grid.read` gate and no backstop, and are advertised as read functions. —
  `tap_grid/services.py:1528,1547,1579,1601,1734-1743`.
- **Activation-state drift.** `_evaluate` denies on `not is_active OR deactivated_at not None`;
  `get_builtin_actor` filters `is_active=True` only; `_ensure_program_actor` repairs `is_active`
  but never clears `deactivated_at` → a synced built-in can be a permanently-denied "healthy"
  zombie. — `tap_auth/policy.py:128`, `tap_auth/actors.py:35`, `tap_auth/sync.py:205-214`.

**The standard:**

1. **Stateless backstop (no ledger).** Every backstop check is a direct `policy.can(actor,
   needed_cap)` re-check; it never depends on whether `authorize()` ran. A bare edge `authorize()`
   is a UI/early-denial check the backstop neither needs nor consults.
2. **No ambient authorization state.** There is no per-request/-op authorization scope to push,
   pop, reset, or leak — the prior ledger and its scope machinery are removed (`req-tap-auth-policy-8`).
3. **One gated read chokepoint.** Every TAP-managed read goes through a
   `@requires_capability('grid.read')` function that reaches `assert_read_authorized`;
   undecorated read helpers and direct-ORM edge reads are eliminated or gated.
4. **Backstop encodes least privilege.** `write_batch([])` never commits state without a
   recorded decision; the DELETE backstop requires `grid.delete` specifically, PURGE
   `grid.purge` — broad covers do **not** satisfy `needs_delete`.
5. **One definition of active.** `is_active=True AND deactivated_at IS NULL`, single-sourced
   across `_evaluate`, `get_builtin_actor`, and `_ensure_program_actor` (which clears
   `deactivated_at` on re-activation).

**Class-eliminating moves:**

- **Delete the ledger → stateless backstop** (DONE, `req-tap-auth-policy-8`): removing the
  contextvar ledger killed the leak class *and* the thread-reuse class by construction — no ambient
  authorization state remains to leak. (Supersedes the earlier "boundary-scope the ledger" move.)
- **Split cover semantics from backstop semantics** (low): DELETE backstop = `{grid.delete}`,
  PURGE = `{grid.purge}`; the grift importer authorizes `grid.delete` explicitly in its own
  scope. Makes "boot cannot tombstone" literally true.
- **One gated read facade** (low–med): decorate/funnel `resolve_entity`/`get_node`/`get_edge`/
  `get_object` through `grid.read` so "reads go through the gate" is true by construction.
- **Centralize `is_actor_active`** (low): one predicate consumed by evaluate/resolve/repair.
- **Seal empty-batch** (low): short-circuit before `_ensure_batch`, or require `grid.write`
  regardless of op count.

**Enforcement:** cross-request ledger-leak regression test; empty-batch test (no `Batch` row
without a decision); cover-cap delete test (`grid.import_grift`-only actor denied a delete;
bootloader cannot tombstone); active-actor drift test (set `deactivated_at`, sync, assert
usable); a CI grep that fails on new bare `policy.authorize(` outside an allowlisted edge-denial
set or a `@requires_capability`/`authorized()` scope.

---

## App: tap_web (human request/response + the panel contract)

**The shape (George, 2026-06-24): tap_web is a pure pass-through for user context
and capabilities.** It mints no actor of its own and swaps to no service identity;
it retains the middleware-bound request user and hands that context to the grid
operation, which confirms the user may perform it. Page-shell loads, panel/page
lookups, and render-reads therefore execute **as the user**, against the user's
capabilities — not a privileged renderer. This is the property that makes
future fine-grained page/data access possible: when the read already runs as the
user, gating *which* pages and *which* rows a user may see is a capability/scope
question at the same chokepoint, not a re-plumb. The same pass-through shape is
expected to hold for **tap_api** and **tap_viz** (the HTTP edge and the
visualization surface are likewise pass-throughs for user context + capabilities).
The one sanctioned exception is a deliberate, gated swap to a bounded program
actor for a *named background job* (e.g. a panel POST that triggers a collector
routes through `run_collection`, which authorizes the user for
`cares.run_collectors` and *then* runs the collection as `tap_cares.collector` —
see the tap_cares section); the trigger is the user's, the execution identity is
the job's, and the two are never collapsed.

**Operational construction.** Synchronous Django views rendering pages, panel HTMX fragments,
and synthetic in-memory pages. The request actor is always bound by `CallerContextMiddleware`;
the only question is whether a path consults the gate. Four entry kinds: page-shell views,
panel-render views, object views (the **only** ones that `policy.authorize('grid.read')`), and
the synthetic builder. Two read chokepoints (`execute_search`, `execute_gryphon_raw`) are
gated — panels that route through them are gated *by accident*; panels that read by direct ORM
are not.

**Why it's loose (era).** The oldest, loosest UI surface: the page model, panel framework, and
most built-in panels predate the service layer, Gryphon, and authZ. `object_view`/`object_edit_view`
are the one place the new model was retrofitted (and the only views with denial tests);
everything else still reflects the pre-authZ world where rendering never asked "may this actor
read the grid?"

**Vulnerability classes:**

- **Panel render-read via direct ORM** (the central panel-contract hole). A `get_view_context`
  reads `BaseModel`/`Entity`/`Edge` directly and renders to any caller the view admits,
  no `grid.read`. Because the panel framework is the cross-app extensible surface, every
  conforming panel inherits the hole. — `tap_web/panels/{viewer_panel:119, editor_panel:77,123,158,
  flip_panel:55,67, batch_list:36, batch_viewer:80,103}`.
- **Page-shell / loader reads ungated.** `landing_view`/`page_view`/`parameterized_page_view`
  + `page.py`/`panel.py` helpers + `Panel.objects.get` in `panel_view`/`panel_edit_view` serve
  the shell, panel list, and config (which can embed Gryphon strings + entity_id bindings) pre-gate.
  — `tap_web/page.py:24,42,74`, `tap_web/panel.py:33`, `tap_web/views.py:29,43,52,88,136`.
- **Config/action-write outside `write_batch`** (silent, *not* fail-closed). `handle_save`
  does raw `panel.save()` / `Edge.objects.create/.delete`, never reaching `assert_write_authorized`
  — worse than an `UnguardedOperation`: a silent, unauthorized, unattributed write that succeeds.
  — `tap_web/panels/table_panel/__init__.py:336,339,345`, `plugins/lotr/editors/character.py:70`.
- **Denial swallowed by render-error handling.** Broad `except Exception` flattens `AuthzError`
  and `UnguardedOperation` into a 200 fragment. — `tap_web/synthetic.py:230,303`,
  `tap_web/panels/table_panel:246`, `tap_viz/panels/graph_panel:201,257`, `tap_web/views.py:650`
  (note: `panel_view`/`object_view` re-raise `AuthzError` but still swallow `UnguardedOperation`).
- **Synthetic/nested panels lack a per-render read rule.** `render_synthetic_page` has no gate;
  it relies on callers having authorized. — `tap_web/synthetic.py:266,313`.

**The standard:**

1. Every view that renders graph data establishes `grid.read` for the request actor **before
   any ORM touch** — via a gated chokepoint or an explicit `policy.authorize` at the top
   (`object_view` is the reference; `page_view`/`panel_view`/`landing_view` adopt it).
2. **Panel render-read** half of the contract: `get_view_context` obtains rows through a gated
   read path, never direct ORM. Binds tap_web, tap_viz, and plugin panels identically.
3. **Panel config/action-write** half: `handle_save`/`EditorDescriptor.handle_save` mutate
   **only** through the service layer (`patch_node`/`write_batch`). Raw `.save()`/`Edge.objects`
   in a save hook is forbidden.
4. A denial is never flattened: render-time `except` lets `AuthzError` (→403) and
   `UnguardedOperation` (→500) propagate; only genuine render errors become a 200 fragment.
5. No protected boundary runs with `User=None`.
6. The synthetic builder self-guards (`render_synthetic_page` authorizes `grid.read` at its own
   boundary).

**Class-eliminating moves:**

- **One sanctioned panel render-read helper** (med) that wraps the gated executors; migrate
  viewer/editor/flip/batch panels onto it. Converts "gated by accident" → "gated by construction".
- **Authorize `grid.read` at the page-shell + panel_view head** (low), promoting `object_view`'s
  pattern to a uniform rule.
- **`render_synthetic_page` authorizes at its own boundary** (low).
- **Reframe the editor/panel save hooks** (med): base `handle_save` takes cleaned data and calls
  `patch_node`; typed editors override only field-mapping — a plugin author *cannot* write raw ORM.
- **One shared render-read error guard** (low) replacing the ad-hoc `except Exception` blocks.

**Enforcement:** denial tests for page_view/panel_view/each direct-ORM panel (anon + no-cap →
403, missing slug → 403 no-leak); write-bypass test (no-write actor POST → 403, no mutation);
a registry conformance test over `panel_type_registry` (every panel's `get_view_context` 403s
for a no-cap actor); a lint flagging direct `.objects.`/`.save()`/`Edge.objects` inside any
`get_view_context`/`handle_save`/`handle_post`.

**Relation to core:** inherits everything; **adds** the three-faceted *panel auth contract*
(render-read / config-write / action-write) and the tap_web-specific rule that denials must
never be flattened (its "render must always produce something" ethos fights the fail-closed
backstop).

---

## App: tap_cares (background / program-actor land)

**Status — standard 1-3 LANDED (session/boot, 2026-06-24).** The task body, the
on-commit callback, `submit_grift`, and the human-trigger gate are done via the
**generic `tap_auth.acting_as(actor)`** context manager (NOT the per-app
`collector_runtime_context()` speculated below — see the class-eliminating moves).
`run_collector` binds `COLLECTOR` once at task entry; `run_collection` carries
`@requires_capability("cares.run_collectors")` (the human-trigger chokepoint —
every surface, incl. the boot mgmt commands now binding `acting_as(BOOTLOADER)`,
routes through it); `submit_grift` dropped its `actor=` param. The
production-realism fixture + human-trigger denial test ship in
`tap_cares/tests/test_no_request_actor.py`. **Standard 5 now LANDED too** (2026-06-24):
`register_collector` is read-only at `ready()` (in-memory + a stashed node descriptor)
and the on-grid upsert moved into `reconcile_collector_nodes()` — one `write_batch`
under the caller-bound bootloader (the `reconcile_collectors` command, run from the
spawn sequence after `sync_auth`). The cares authz-coverage cluster is now **zero**.
Paired hardening: the INTERNAL_ONLY write bypass now asserts a **program** actor
(`assert_program_actor` in `tap_auth.enforcement`, checked at the `write_batch`
chokepoint) — a human can no longer write an INTERNAL_ONLY node by any path.

**Operational construction.** Entry points run with **no** `request.user`, so the
request-binding middleware never fires. Four entry kinds that do **not** share an actor source:
async task body (`run_collector`), app-ready registration, scheduler tick (the one path that
*already* self-heals via `_scheduler_ctx`), and human/boot trigger → service → async handoff
(`run_collection`). The actor must be **minted at the boundary** (Kubernetes-ServiceAccount
model): the runtime has its own identity (`tap_collector`/`tap_scheduler`); the human/schedule
is recorded as provenance, not as principal.

**Why it's loose (era).** The collector/task runtime predates the named-actor boundary. The
retrofit was uneven: `run_collection` and `_scheduler_ctx` were rewritten for the new world
(they resolve `get_builtin_actor` explicitly); but `tasks.py`, `registry.py`, and `submit_grift`
were left on the old ambient-inheriting assumption. Tests pass only because conftest binds a
privileged ambient actor the production worker never has — *the era root cause and the
test-realism gap are the same fact viewed twice.*

**Vulnerability classes:**

- **Ambient-actor reliance in a non-request context.** Grid writes from a task/on_commit/
  app-ready pass no `caller_context`; in prod the contextvar is `None` → `policy.authorize(None, ...)`
  raises `MissingActor` (an `AuthzError` at the decorator, *not* `UnguardedOperation`). **Net
  effect: every collector run is broken in production** — `run_collector`'s first write raises
  before any collection — yet green in CI. — `tap_cares/tasks.py:80,151,167,196,214,258,280`,
  `tap_cares/services.py:268-272`, `tap_cares/registry.py:157,194`, `tap_cares/collectors/base.py:234-293`.
- **Human-trigger conflated with runtime-actor.** `run_collection` has no gate on the *caller*;
  the panel POST runs it off `request.POST` and swaps to the privileged `tap_collector` actor —
  so any authenticated user who reaches the POST can start runs without `cares.run_collectors`.
  — `tap_cares/services.py:152`, `plugins/administrivia/tap_cares/panels/collector_detail:281`.
- **Scheduler cursor fields via direct ORM.** `set_schedule_enabled`/`_claim_and_create_fire`
  write `enabled_at`/`last_schedule_fired` via `Schedule.objects.update()` — bypassing the
  service layer, capability gate, and history (partly intentional; scheduler-owned cursor).
  — `tap_cares/scheduler.py:240,258-262`.

**The standard:**

1. Every grid mutation from a task body, on_commit callback, or app-ready binds an **explicit
   named program actor** (`COLLECTOR`/`SCHEDULER`/bootstrap) via `get_builtin_actor` — never
   inherits ambient.
2. `run_collector` establishes its `COLLECTOR` context **once at task entry**; downstream calls
   inherit it. `submit_grift` uses the bound actor, never `actor=None`.
3. **Two decisions on the human-trigger path**: `authorize(request.user, 'cares.run_collectors')`
   at the panel/command boundary *before* the run, separate from and never replaced by the
   runtime `tap_collector` swap.
4. Scheduler cursor fields are the **only** sanctioned direct-ORM writes — inside their paired
   service patch, documented; every other write goes through the service layer with a bound actor.
5. Registration binds a named registration actor and must **not** swallow `MissingActor`/`AuthzError`
   as "DB not ready."

**Class-eliminating moves:**

- **A task-boundary context helper** (med): ✅ landed as the **generic
  `tap_auth.acting_as(actor)`** — the no-request analogue of the request middleware,
  parameterized by the *resolved* actor so every subsystem shares it
  (`acting_as(get_builtin_actor(COLLECTOR))` for the collector runtime,
  `acting_as(get_builtin_actor(BOOTLOADER))` for boot, `acting_as(delegated)` for a
  future AI runner). Deliberately NOT a per-app `collector_runtime_context()`. Kills
  the entire ambient-actor class at one chokepoint per boundary.
- **`run_collection` as the human-trigger chokepoint** (low): a `triggering_actor` authorized
  for `cares.run_collectors` before the swap; every trigger surface routes through it.
- **`submit_grift` off the `actor=None` default** (low, naturally satisfied by the helper).
- **Honest registration failure** (low): bind the bootstrap actor; narrow the catch-all to
  DB-not-ready.

**Enforcement (highest-value first):** a **production-realism fixture** that runs a cares
write-path with the ambient context cleared (`set_caller_context(None)`, ledger not
pre-authorized) and asserts it still succeeds by binding its own actor — *this closes the
conftest gap that hides the whole class.* Plus: a human-trigger test (no-cap POST → 403, no job);
a grep/lint flagging any cares grid-write call without an explicit `caller_context` outside the
helper; a direct-ORM allowlist ratchet pinning the two scheduler cursor writes.

**Relation to core:** inherits everything; **adds** the actor *source* (the core's default
source — request middleware — is structurally absent), minting a named program actor at every
boundary; and adds the second decision the core implies but this app never made (authorize the
human trigger separately from the program actor).

---

## App: tap_boot / bootstrap (tap_bootloader, ordering, registration-at-import)

**Operational construction.** The one surface with no request, no session, and (briefly, on a
fresh DB) no actors at all — it **manufactures** the "a named actor always exists" precondition
the rest of the platform assumes. Three sub-eras of actor availability: app-ready/import (no
ambient context, actors may not exist yet), the bootstrap pre-phase (resolve/grant
`tap_bootloader` — today done by `spawn-session.sh`, the code-defined phase is *future*), and
named-actor boot (everything runs as `tap_bootloader`). Ordering — auth before population — is
the load-bearing invariant.

**Why it's loose (era).** Boot straddles the moment the platform's invariants come true.
`EntityType` registration is pre-authZ direct ORM; the collector dual-existence upsert was added
after the service layer but runs at `ready()` where no actor exists; the whole ordered standup
lives in `spawn-session.sh` step-numbering, not code. The dedicated `tap_boot` app + `manage.py
boot` phase sequencer are entirely *Proposed*.

**Vulnerability classes:**

- **Graph write at app-ready with no actor.** `_ensure_collector_node` calls
  `_create_node_internal`/`_patch_node_internal` at `ready()`; in prod → `MissingActor`,
  **masked** by a broad `except Exception: return` ("DB not ready"); in tests → masked the
  other way by the autouse fixture. So a fresh standup can report success with an empty/stale
  Collector inventory. — `tap_cares/registry.py:104,144`, plugin `apps.py` `register_collector`
  call sites, `conftest.py:85`.
- **Type-registry write via direct ORM at import.** `EntityType.objects.get_or_create/
  update_or_create` at `ready()` — no actor, no gate, no attribution; defended only by an
  informal "registry metadata, not graph data" boundary that is exactly `grid.admin` territory.
  — `tap_grid/apps.py:22`, `tap_plugins/base.py:185,196`.
- **Ordering invariant enforced only by bash.** Auth-before-population lives in
  `spawn-session.sh` step numbers; nothing asserts it in CI, and the registration-at-import
  writes already run *before* `sync_auth`. — `scripts/spawn-session.sh:514,526,542,591`.
- **Boot-actor cover-cap reach.** `BOOTLOADER_BUNDLE` correctly omits `grid.delete`/`grid.purge`,
  but holds `grid.import_grift`+`grid.admin` (both cover-caps), so boot can reach the delete
  backstop via an import sweep — "a boot bug can't nuke the grid" is narrower than it reads.
  — `tap_auth/capabilities.py:88-89,125`, `tap_plugins/management/commands/import_plugin_grift.py:279`.

**The standard:**

1. Every graph-managed write on a boot/registration surface binds an **explicit** `tap_bootloader`
   via `get_builtin_actor(BOOTLOADER)`; never relies on ambient.
2. **`ready()` is read-only** w.r.t. graph node/edge state. The collector upsert (and any other
   `ready()` graph write) moves into the explicit boot command that runs *after* auth sync.
3. `EntityType`/type-registry writes are `grid.admin` territory: route through a gated actor-bound
   helper, **or** formally declare them below-service-boundary registry metadata with a *named*
   exemption — not silent ungated direct ORM.
4. **Ordering is code, not bash.** "bootstrap → identity → auth → population"; a population write
   before the actor+grants exist fails closed (the existing `MissingActor` is correct) and is
   **not** swallowed.
5. A boot-time catch-all must not swallow `MissingActor`/`InactiveActor`/`CapabilityDenied`/
   especially `UnguardedOperation`.
6. The boot actor stays least-privilege; its cover-cap reach to the delete backstop is a *named,
   deliberately-accepted residual* (seed sweep) — and the actor never directly holds
   `grid.delete`/`grid.purge`.

**Class-eliminating moves:**

- **Move the Collector upsert out of `ready()`** ✅ LANDED (2026-06-24): `register_collector` is
  read-only (in-memory `register()` + a stashed descriptor); `reconcile_collector_nodes()` does the
  on-grid upsert in one `write_batch` under the caller-bound bootloader (the `reconcile_collectors`
  command, run from the spawn sequence after `sync_auth`); the DB-not-ready catch-all is gone
  (reconcile runs when the DB is ready, so failures are loud). The full `tap_boot` app/profile still
  absorbs this command later.
- **A `boot_actor_context()` write chokepoint** (med): the only sanctioned way to mutate graph
  state during boot — makes "forgot to bind the boot actor" structurally impossible.
- **Code-defined phases** (high, *future* — the `tap_boot` capstone): "auth before population"
  becomes a code invariant, not a script convention.
- **Reclassify `EntityType` registration** (low–med): gated helper or named exemption.

**Enforcement:** a production-shape test (no ambient actor) asserting registration either isn't
invoked at import or fails closed loudly; a lint forbidding graph-managed writes inside any
`apps.py` `ready()` (enforces `req-tap-plugin-load-v0-ready-readonly`); a boot-actor authority test
(`tap_bootloader` cannot `policy.can(grid.delete/grid.purge)` directly); a CI ordering assertion.

**Relation to core:** inherits the model for sub-era 3 (named-actor boot); **adds** the
explicit boot-actor binding, the read-only-at-import rule, and the code-defined phase ordering —
boot is the layer that *manufactures* the "a named actor always exists" precondition everyone
else takes as given.

---

## App: tap_api (the HTTP edge — the reference)

**Operational construction.** A single Django-Ninja `NinjaAPI`, five thin routers + discovered
plugin routers, all mounted `auth=session_auth` (anon → 401 at the edge; only `api_root` is
`auth=None`). AuthZ is **delegated downstream** to `@requires_capability` + the backstops; the
edge's job is "authenticate, resolve a named actor, hand off, translate denials." One quirk:
two divergent actor-flow patterns — `entities.py`/`edges.py` build a local `_caller_ctx(request)`;
`searches.py`/`gryphon.py`/plugins rely on the ambient contextvar.

**Why it's loose (era).** Youngest, cleanest app; looseness is *transitional*, not legacy.
Two routers predate the ambient-contextvar convention (they hand-build `_caller_ctx`);
`entity_types.py` predates authZ as a concept (pure read listing, got `session_auth` at mount
but never a capability gate).

**Vulnerability classes:**

- **Authenticated-but-ungated read.** `list_entity_types` is session-authed but calls no gate —
  any no-cap user gets the full type catalog. An *unmade decision* (public discovery vs gap)
  masquerading as behavior. — `tap_api/routers/entity_types.py:12-14`.
- **Existence-sensitive preflight.** `get_object_or_404` before the authorizing service call →
  404-vs-403 existence leak (mutation still fails closed). `searches.py:44-45` is the correct
  counter-example. — `tap_api/routers/{entities.py:48-52,57-58,66-67, edges.py:53-55,71-72}`.
- **Divergent actor-flow.** Two copies of `_caller_ctx` vs sole ambient reliance — correctness
  spread across a middleware, two local helpers, and downstream decorators (regression-shaped,
  no live hole). — `tap_api/routers/{entities.py:19-22, edges.py:19-22, searches.py:44, gryphon.py:24-34}`.
- **Plugin routers inherit the contract implicitly.** Mounted `session_auth`, but no structural
  proof a plugin endpoint that touches the graph actually authorizes. — `tap_api/api.py:110-122`.

**The standard:**

1. **Edge authenticates, service authorizes.** Every router mounted `auth=session_auth` at
   add_router time; no router does direct-ORM graph access — it calls a `@requires_capability`
   service function.
2. **Authorize before existence-sensitive lookup** (the `searches.py` pattern) so a denied
   caller gets 403, not 404-vs-403.
3. **One actor binding.** Consume the ambient `get_caller_context()`; the duplicated
   `_caller_ctx` helpers go away.
4. **Explicit public-surface classification.** Every endpoint is exactly one of
   {anon-public (`api_root` only), capability-gated, deliberately-authenticated-public}, and
   category (c) is a *named, commented* decision. `list_entity_types` must be resolved.
5. Denial translation is central and lossless (`AuthzError`→403 single handler;
   `UnguardedOperation` stays 500; no router swallows a denial).

**Class-eliminating moves:** collapse the two `_caller_ctx` helpers onto ambient
`get_caller_context()` (low); an **authorize-then-resolve** idiom for every id-addressed view
(low — kills the existence-leak class app-wide); resolve `list_entity_types`' classification
(low); eventually migrate off the deprecated bare-`Entity` helpers onto the typed pipeline /
Search dispatch so the backstop covers the edge with no per-router authorize.

**Enforcement:** a **parametrized router-matrix test** — enumerate every mounted route, assert
each is in exactly one declared bucket (a new ungated router fails); an existence-leak test
(no-cap PATCH/DELETE on existing vs missing id → same 403); a mount-time invariant test (every
router `session_auth`, only `api_root` is `auth=None`).

**Relation to core:** the core's *purest consumer* — adds only the session-auth-at-mount
mechanism that mints the actor, the existence-preflight discipline (a concern that exists only
because HTTP exposes 404-vs-403), and explicit public-surface classification. The right place
to set the canonical thin-router pattern other request edges copy.

---

## App: plugins (extension code — conformance by construction)

**Operational construction.** Not a runtime — extension classes the host loads and invokes
(tap_web for panels, tap_cares for collectors). A plugin ships a **duck-typed** PanelType
(no base class; `ScopedRegistry.register` does no validation); the host dispatches
`get_view_context`/`handle_post` by `hasattr`. **`panel_view` performs no `authorize()`** — the
host relies entirely on the panel body reaching a gated service helper, so a panel that does
only direct ORM is gated by *nothing*. Collector POST actions call `run_collection` (which swaps
to the privileged `COLLECTOR` actor) with no human-capability check.

**Why it's loose (era).** Panels were a presentation/extension layer built before the gate and
the read chokepoint were law; the deliberately-minimal duck-typed contract that made authoring
cheap is exactly what lets a panel reach raw ORM and swallow exceptions with nothing structural
stopping it. The codebase straddles two eras (older direct-ORM panels; newer service-routed ones
that still wrap the gated call in a broad except).

**Vulnerability classes:**

- **Graph read via direct ORM** (no `authorize()`, no backstop reach). The worst instance walks
  `apps.get_models()` and queries *every* `BaseModel` — a wholesale spine scan. —
  `plugins/github_core/panels/*` (incl. `cross_grid_references:47,102-110`),
  `plugins/administrivia/tap_cares/panels/*`.
- **Privileged side-effect with no human check.** `handle_post` → `run_collection`; the
  actor-swap bounds the collector's blast radius but checks nothing about the initiator. —
  `plugins/administrivia/tap_cares/panels/{collector_table:154, collector_detail:281}`.
- **`UnguardedOperation` swallowed.** Host `except Exception` (`views.py:116`) catches it; plugin
  panels add ~18 of their own broad/`bare except` sites that swallow even earlier (one bare
  `except:` can also eat `AuthzError`). — `plugins/fedramp_20x_ksi/panels/*`,
  `plugins/samsite/panels/ksi_scoreboard:200,216`, `plugins/github_core/.../cross_grid_references:118`.
- **Unconstrained registration.** Any object accepted as a panel type; no interface contract,
  so conformance is by plugin discipline — the wrong trust model for third-party code. —
  `tap_grid/registry.py:55,151`, `tap_web/views.py:503-512`.

**The standard:**

1. Every plugin panel read of graph data goes through a **host-provided gated read helper**;
   direct `Model.objects.*` against graph-managed models in a panel is prohibited — the **host**
   owns the `grid.read` authorization, not the plugin.
2. `panel_view` establishes a `grid.read` scope **before** invoking any plugin hook — a
   direct-ORM panel is still gated by the host.
3. Every privileged side-effecting action authorizes the **human** for the matching capability
   at the host boundary before the plugin handler runs (the program-actor swap is *additional*,
   not a substitute).
4. A plugin panel must not swallow `AuthzError`/`UnguardedOperation` — preferably the gated call
   is owned by the host *outside* the plugin's try-scope.
5. A registered panel type must conform to a **host-owned PanelType contract** (base class /
   validated protocol); the registry refuses non-conformers.

**Class-eliminating moves:**

- **Single host read-gate at `panel_view`** (low, ~3 lines): `with authorized(get_caller_context(),
  'grid.read', operation='panel_view'):`. Gates *every* panel render — tap_web and all plugins,
  current and future — independent of the panel body. **Highest blast-radius-per-line in the
  whole pass.**
- **A PanelType base class** (med) providing the only sanctioned accessors + owning the try/except;
  registry rejects non-subclasses. Conformance by construction.
- **Host-side human-gate for POST actions** (low–med): declared `post_capability`; the host
  authorizes before dispatch.
- **Replace the `apps.get_models()` spine scan** with a gryphon traversal through the base accessor.

**Enforcement:** a host-gate test (a direct-ORM-only fixture panel rendered by a no-cap actor →
403); an AST/grep ratchet over `plugins/**/panels/**` forbidding `<Model>.objects.` on
graph-managed models outside the base accessors; a registry conformance test (non-PanelType
registration fails); a swallow test (`panel_view` re-raises `UnguardedOperation`); a POST
human-gate test (no-cap Run → 403, no job).

**Relation to core:** inherits everything; **adds** a *conformance harness* — because plugin
code is untrusted and the backstop only protects operations that enter the service layer, the
host must (1) gate at the panel chokepoint so authorization doesn't depend on the plugin, (2)
provide a base class that makes the gated path the only reachable one, (3) own propagation so a
plugin can't swallow denials. The core defines how auth works; the plugins standard defines how
the host *forces* untrusted extensions through it.

---

## App interaction seams

- **Everything → service layer** (the universal seam). The backstop reaches only what enters the
  service layer; direct-ORM paths are outside the contract. → Move gates to **host chokepoints**.
- **Request edge → service** (tap_api, tap_web). Authenticate at the edge, bind the named actor
  **once** into the ambient contextvar, authorize before existence-sensitive lookups, delegate
  the real decision, translate `AuthzError`→403 / `UnguardedOperation`→500.
- **Plugins → host** (the untrusted seam). The host owns the `grid.read` scope, the human-capability
  check, the try/except, and the only sanctioned accessors. Conformance **by construction**, not
  plugin discipline.
- **Cares/boot → service** (the no-request seam). The actor is **minted** at the boundary, never
  inherited. The fragility is that conftest binds a privileged ambient actor, so the *test*
  contract (actor present) diverges from the *prod* contract (actor absent).
- **Boot → auth** (the ordering seam). Boot manufactures "a named actor always exists"; today the
  contract lives only in `spawn-session.sh` step numbers and is already violated by
  registration-at-import writes.

## Sequencing

1. **Core first** (tap_grid + tap_auth) — non-negotiable; every per-app standard is only as
   strong as the core. Stateless backstop (ledger removed), `{grid.delete}`-only delete backstop,
   single `is_actor_active`, empty-batch seal. Mostly low-cost.
2. **tap_web** — loosest, broadest exposure, and host for plugins. The single host-side
   `grid.read` scope at `panel_view` + the PanelType base class close tap_web's central class
   **and most of plugins'** at once.
3. **plugins** — largely *rides* tap_web's chokepoint + base class. Residual: the
   `cross_grid_references` spine-scan migration and the collector-POST human gate.
4. **tap_cares** — a silent prod outage of ingestion (green in tests). Contained to one
   subsystem; the fix is the task-boundary context helper + the `run_collection` human-gate.
5. **tap_boot** — capstone, mostly future. Cheap wins (move the upsert out of `ready()`, narrow
   the catch-all, name the cover-cap residual) ride the cares work; the phase sequencer is the
   durable owner of "auth before population."
6. **tap_api** — opportunistic anytime after the core; low urgency (no live bypass), high
   pedagogical value (sets the canonical thin-router pattern).

## Open decisions

These need a deliberate call (George's per-app thinking pass):

1. **`list_entity_types`** — deliberately public schema discovery (document it) or gate on
   `grid.read` (or a future `auth.read_schema`)?
2. **`EntityType`/type-registry writes** — route through a gated `grid.admin` service helper, or
   durably declare as below-service-boundary registry metadata with a *named* exemption?
3. **Boot-actor cover-cap residual** — accept "boot can sweep-tombstone via import" as a named
   risk, or give the importer its own explicit `grid.delete` scope so the bundle's exclusion is
   literally honored? *(Recommendation: honor it — the core "split cover semantics" move makes it
   nearly free.)*
4. **Scheduler cursor fields** — bless `enabled_at`/`last_schedule_fired` as a permanent
   direct-ORM carve-out (with a ratchet test), or invest in a service-layer path? *(Recommendation:
   bless + ratchet.)*
5. **Conftest test-realism** — flip the autouse default to *no ambient actor* (forces each test to
   mint its own, matching prod) or add targeted production-shape fixtures only on the
   cares/boot/ledger paths? *(Recommendation: targeted fixtures now, full flip later.)*
6. **Human-trigger gate location** — inside `run_collection` (one chokepoint) vs at each
   panel/command boundary? *(Recommendation: chokepoint.)*
7. **PanelType base class** — mandatory now (breaks out-of-tree plugins immediately) or a
   deprecation window with a baseline-ratchet? *(Recommendation: ratchet.)*
8. **`tap_boot` app + code-defined phase sequencer** now (capstone) vs keep ordering in
   `spawn-session.sh` + a CI ordering-assertion as interim? *(Recommendation: interim.)*
