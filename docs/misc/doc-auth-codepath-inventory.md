---
title: Auth Codepath Inventory
date: 2026-06-23
status: review-inventory
audience:
  - llm
  - developer
related_specs:
  - tap_auth/specs/spec-tap-auth-v0.md
  - specs/archive/spec-tap-auth-assurance-v0.md  # DEPRECATED/retired 2026-07-08 — surface-centric model rejected
  - tap_web/specs/spec-web-pages-v0.md
  - tap_web/specs/spec-web-panels-v0.md
  - tap_cares/specs/spec-tap-cares-v0.md
---

# Auth Codepath Inventory

This is a review-only static inventory captured on 2026-06-23. No tests were
run and no implementation files were changed. The goal is to map the actual
AuthN/AuthZ wiring before adding more formal assurance machinery, with special
attention to the page/panel system, TAP Cares execution paths, graph reads and
writes, and the `is_active` / `deactivated_at` lifecycle split.

The short version: TAP now has useful capability gates, but the current system
is not yet surface-centric. The highest-risk loose zones are panels/pages,
program actor propagation in TAP Cares, activation-state drift, and broad
exception handlers that can flatten authorization failures into normal UI
errors.

## Inventory Legend

- **Actor gate** means a codepath must have a real `CallerContext` user or an
  explicit actor; anonymous actor flows are denied by policy.
- **Capability gate** means a path checks a named permission such as
  `grid.read`, `grid.write`, or `grid.import_grift`.
- **Surface gate** means the system knows which UI/API/task/plugin surface is
  asking. This is the desired next layer, but it is not present in the current
  runtime decision shape.
- **Direct ORM read/write** means code reaches model managers directly rather
  than going through Gryphon/search/read-service/write-service abstractions.
  Some direct ORM use is legitimate subsystem plumbing, but user-facing direct
  ORM reads and writes need explicit classification.

## Main Findings

### 1. The current AuthZ model gates capabilities, not surfaces

`tap_auth.policy.authorize()` rejects unknown capabilities, missing actors,
inactive/deactivated actors, and users lacking a direct group permission. That
is a solid base capability gate.

The current decision ledger, however, records only capability strings. For
example, `grid.write` can be marked as satisfied, but the ledger does not know
whether that write came from an API route, a page editor, a collector task, a
plugin panel action, or a synthetic nested panel. That means the lower-level
write backstop can confirm "some write capability was authorized", but not
"this exact surface was allowed to perform this exact operation".

Relevant code:

- `tap_auth/policy.py` - `authorize()`, `can()`, and the capability-only
  decision ledger.
- `tap_auth/enforcement.py` - `@requires_capability()` and
  `assert_write_authorized()`.
- `tap_grid/services.py` - write functions decorated with `grid.write`;
  `write_batch()` calls the write backstop before mutation.

Why it matters: this is the core reason a surface inventory is the right next
step. Without surface identity, nested pages, plugin panels, manual collector
runs, and background tasks all collapse into broad capabilities.

### 2. Pages and panels are the weird zone

The web layer has several different kinds of access mixed together:

- Page lookup and page composition.
- Panel fragment rendering.
- Panel edit configuration.
- Object view and object edit.
- Synthetic pages that render in-memory panels.
- Plugin-owned panel code that can perform arbitrary direct reads or writes.

Some paths explicitly authorize before object resolution. For example,
`object_view()` and `object_edit_view()` call `policy.authorize(...,
"grid.read")` before resolving the entity.

Other paths do direct ORM work before any explicit authorization. Examples:

- `tap_web.views.page_view()` and `parameterized_page_view()` resolve pages via
  `tap_web.page.get_page_by_slug()` without a local auth check.
- `tap_web.views.panel_view()` loads `Panel` by entity UUID before dispatching
  to the panel type.
- `tap_web.views.panel_edit_view()` loads `Panel` before the GET editor context
  or POST save path.
- `tap_web.page.get_page_by_slug()`, `get_page_panels()`, and
  `get_landing_page()` use direct ORM reads.
- `tap_web.panel.get_panel_search()` reads `USES_SEARCH` edges and `Search`
  rows directly.

Broad exception handlers also matter here. Several panel/page rendering paths
catch `Exception` and turn failures into inline panel errors. That is useful for
UX resilience, but dangerous for auth because `AuthzError` and
`UnguardedOperation` can become normal-looking render failures instead of
blocking the request loudly.

Examples:

- `tap_web.views._render_grid_placeholder()` catches all exceptions around
  `execute_search()`.
- `tap_web.synthetic._render_graph_panel_context()` catches all exceptions
  around `execute_search()`.
- `tap_web.synthetic._render_synthetic_panel()` catches all template/render
  exceptions and returns inline error HTML.
- `tap_web.panels.table_panel.TablePanel.get_view_context()` catches all
  exceptions around search execution.
- `tap_viz.panels.graph_panel.GraphPanel.get_view_context()` catches all
  exceptions and returns an error context.

Why it matters: page/panel code is exactly where surface identity needs to be
unambiguous. A panel render failure is not equivalent to an authorization
failure, and nested synthetic surfaces should not inherit power accidentally.

### 3. Some panel edit paths bypass the service layer

The clearest direct write bypass found in this pass is the table panel save
path. `tap_web/panels/table_panel/__init__.py` updates the `Panel` directly,
deletes `USES_SEARCH` edges directly, and creates a new `Edge` directly. That is
configuration writing for a user-facing panel editor, but it does not appear to
flow through the graph service layer or AuthZ write backstop.

The editor panel also deserves attention:

- `tap_web/panels/editor_panel/__init__.py` resolves target objects via direct
  ORM.
- Its POST path delegates saving to the descriptor. That may be safe for some
  descriptors, but the panel code itself is not an obvious AuthZ checkpoint.

Viewer/table/graph panels commonly do direct ORM reads to assemble context.
Those might be acceptable as internal composition reads once formally
classified, but they should not remain implicit.

Why it matters: panels are plugin-extensible and user-facing. They need a
simple rule for "panel render read", "panel config write", and "panel action
write", plus an enforcement point that cannot be bypassed by a custom panel
type.

### 4. API routes mostly gate reads, but some writes resolve objects first

The API layer mounts core routers under `session_auth`, and the global API
exception handlers translate `AuthzError` to HTTP 403.

Several read routes manually authorize `grid.read` before ORM access. That is
good. There are still write endpoints that resolve objects before hitting a
decorated service function:

- `tap_api/routers/entities.py` resolves `Entity` via `get_object_or_404()`
  before `update_entity()` or `delete_entity()`.
- `tap_api/routers/edges.py` resolves endpoint `Entity` rows before
  `create_edge()`, and resolves `Edge` before `delete_edge()`.

The mutation eventually reaches a decorated service function, but the preflight
lookup can leak existence or create inconsistent error behavior before AuthZ
has had a chance to deny.

Also note `tap_api/routers/entity_types.py`: `list_entity_types()` returns all
entity types without an explicit policy check. This may be intended as public
schema discovery, but it should be classified that way.

Why it matters: API routes are easier to reason about than pages/panels, so
they are good candidates for the first surface inventory. Write routes should
authorize before existence-sensitive lookups unless a spec explicitly says the
metadata is public.

### 5. TAP Cares program actor propagation looks incomplete

`tap_cares.services.run_collection()` creates the collection job with the
built-in `tap_collector` actor. That part is directionally right: the human
requester can authorize the request, then the collector runtime can act as the
collector program actor.

Several downstream task/registration paths call decorated service functions
without an explicit `caller_context`:

- `tap_cares/services.py` - `_enqueue_and_record_task_id()` calls
  `_patch_node_internal()` with no caller context.
- `tap_cares/tasks.py` - `run_collector()` patches job status several times
  with `_patch_node_internal()` and no caller context.
- `tap_cares/tasks.py` - `_link_produced_batches()` calls `create_edge()` with
  no caller context.
- `tap_cares/collectors/base.py` - `CollectorBase.submit_grift()` defaults
  `actor=None` and passes that into `grift_import()`.
- `tap_cares/registry.py` - collector registration upserts `Collector` nodes
  through decorated internal service helpers with no caller context.

Because the decorated service helpers resolve actor context through
`CallerContext`, these calls appear to depend on ambient context being present.
Background tasks, app-ready registration, and transaction callbacks are exactly
the places where ambient request context should not be assumed.

Why it matters: this is likely to fail closed now, which is good from a safety
perspective, but it also indicates that boot/runtime program actor behavior is
not yet explicitly modeled. The future surface matrix should include boot,
collector registry, collector task execution, scheduler task execution, and
manual operator-triggered collector run as distinct surfaces.

### 6. Manual collector run needs human authorization before runtime actor switch

The administrivia collector panel can trigger `run_collection()` from a POST:

- `plugins/administrivia/tap_cares/panels/collector_table/__init__.py`

That function switches to the built-in collector actor for the execution
records. That is reasonable for job execution, but the panel action itself
still needs a human/user-facing authorization gate before the actor switch.

Why it matters: "collector runtime may write collection results" and "this user
may manually start a collector" are different permissions. The surface matrix
should keep them separate.

### 7. Activation and deactivation are two variables with one denial outcome

`User.is_active` and `User.deactivated_at` both cause policy denial:

- `is_active=False` denies with `inactive_actor`.
- `deactivated_at is not None` also denies with `inactive_actor`.

The model comments describe `is_active` as the Django login/enabled toggle and
`deactivated_*` as audit metadata layered on top. There is no obvious service
API found in this pass that atomically deactivates/reactivates a user and keeps
the fields in sync.

Built-in actor handling may expose the drift:

- `tap_auth/actors.py:get_builtin_actor()` filters by `tap_builtin_key` and
  `is_active=True`, but not by `deactivated_at__isnull=True`.
- `tap_auth/management/commands/sync_builtin_auth.py` repairs built-ins to
  `is_active=True`, but the reviewed field list did not include clearing
  `deactivated_at`.

If a built-in actor has `deactivated_at` set but remains `is_active=True`,
lookup can return it while policy will still deny it as inactive. That is a
good example of why a single lifecycle variable or authoritative lifecycle
service may be cleaner.

Why it matters: "broken auth is failed auth" is good, but a drift-prone state
model will produce confusing failures and make test coverage harder to reason
about.

### 8. Direct graph reads need classification, not blanket panic

Direct ORM graph reads are widespread. Some are probably legitimate internal
composition reads. Others are user-facing and should be gated or routed through
Gryphon/search/read-service paths.

Examples that need classification:

- `tap_web.page` page composition helpers.
- `tap_web.panel.get_panel_search()`.
- `tap_web.panels.viewer_panel` direct object lookup.
- `tap_web.panels.editor_panel` direct object lookup.
- `tap_web.panels.batch_list`, `batch_viewer`, `batch_summary`, `flip_panel`,
  and `entity_resolution`.
- `tap_viz.panels.graph_panel` search/projection/layout helper reads.
- Plugin panels such as GitHub recent activity and TAP Cares schedule/collector
  tables.
- TAP Cares scheduler and task internals.

Why it matters: the right answer is probably not "ban every direct ORM read".
The right answer is to label each one: public discovery, user-facing read,
panel composition read, system-internal orchestration read, boot/registration
read, low-level test, or migration. Then the enforcement strategy can match the
category.

### 9. Python 3.14 exception syntax is valid, but may confuse older tooling

Correction: an earlier version of this inventory framed the parenthesis-free
multi-exception handlers below as parse-invalid Python 2-style syntax. That was
wrong for the project's Python runtime. Python 3.14 supports this form via PEP
758, so these are not an import blocker and should not be treated as a reason
to distrust the reported passing tests.

Static search found multiple parenthesis-free multi-exception handlers, such
as:

- `tap_grid/apps.py` - `except OperationalError, ProgrammingError:`
- `tap_plugins/base.py` - `except OperationalError, ProgrammingError:`
- `tap_cares/registry.py` - `except OperationalError, ProgrammingError:`
- `tap_grid/grift/importer.py` - several `except ValueError, ...:` handlers.
- `tap_web/panels/editor_panel/__init__.py` - `except KeyError, Exception:`
- `tap_web/panels/table_panel/__init__.py` - `except TypeError, ValueError:`
- Several plugin modules under `plugins/github_core`, `plugins/sigstore_core`,
  and `plugins/samsite`.

This is not an AuthZ design issue and not an assurance blocker for a Python
3.14+ project. The remaining concern is tooling/readability compatibility:
older Python grammar checks can falsely flag it, and the form visually resembles
the old Python 2 footgun. Adding parentheses may still be a cheap style cleanup,
but it should be prioritized as readability/tooling hygiene, not correctness.

Why it matters: the correction is itself a useful caution. Findings from static
inventory should be verified against the project's actual runtime and codepaths
before they drive structural cleanup work.

## Codepath Map

### Auth core

- `tap_auth.models.User`
  - Extends Django `AbstractUser`.
  - Adds TAP fields for user kind, built-in identity, provenance, and
    deactivation audit metadata.
  - `tap_builtin_key` immutability is enforced in model `save()`, but direct
    `QuerySet.update()` can bypass it by design/test acknowledgement.

- `tap_auth.policy`
  - Main capability decision function.
  - Requires a known capability, a non-null user, an active/non-deactivated
    user, and group permission membership.
  - `can()` returns a boolean but does not record an authorization decision.

- `tap_auth.enforcement`
  - Decorator wrapper around policy authorization.
  - Provides write/read backstop helpers.
  - Current write backstop validates capability presence, not surface identity.

- `tap_auth.middleware`
  - Binds ambient `CallerContext` for web requests.
  - Anonymous requests get `user=None`, which policy denies for gated paths.
  - Converts `AuthzError` to 403. `UnguardedOperation` remains loud as a 500.

### Grid service/read/write layer

- `tap_grid.services`
  - Public mutations are generally decorated with `grid.write`.
  - `write_batch()` calls `assert_write_authorized()`.
  - Internal helpers are also decorated, so they are not currently a bypass.
  - Public read helpers such as `resolve_entity()`, `get_node()`,
    `get_edge()`, and `get_object()` did not show local decorators in this
    pass, despite being convenient user-facing read entry points.
  - Legacy helper `create_edge()` uses the service path, then may update the
    backing entity name directly if the optional `name` argument is provided.

- `tap_grid.search`
  - `execute_search()` is decorated with `grid.read`.
  - Search modes are behind that entry point when callers use it.

- `tap_grid.gryphon.executor`
  - `execute_gryphon_raw()` and `explain_gryphon_raw()` are decorated with
    `grid.read`.
  - Internal implementation functions are separate.

- `tap_grid.grift.importer`
  - `grift_import()` authorizes `grid.import_grift`.
  - Purge mode additionally requires `grid.purge`.
  - If actor is omitted, it tries ambient caller context.

### Web pages and panels

- `tap_web.views`
  - `page_view()` and `parameterized_page_view()` resolve page state without a
    local authorization call.
  - `object_view()` and `object_edit_view()` explicitly authorize `grid.read`
    before object resolution.
  - `panel_view()` loads the panel before dispatching panel code.
  - `panel_edit_view()` loads the panel before edit GET/POST logic.
  - `_render_grid_placeholder()` can catch auth failures as normal errors.
  - `nav_index_view()` intentionally exposes discoverable pages without auth;
    this should be marked as public discovery in the spec/matrix.

- `tap_web.page`
  - Page, landing page, and page-panel composition helpers use direct ORM.
  - These are good candidates for "internal page composition read" if that
    category is accepted.

- `tap_web.synthetic`
  - Synthetic page rendering can execute search and render nested panels.
  - Broad exception handling can flatten authorization failures.
  - Nested synthetic panels need an explicit inheritance/delegation rule.

- Core panel types
  - Viewer panel: direct object lookup.
  - Editor panel: direct object lookup; descriptor-owned save behavior.
  - Table panel: search-backed reads, but direct config writes to panel/edges.
  - Graph panel: direct projection/layout/search helper reads, then guarded
    search execution.

### API

- `tap_api.api`
  - Core and plugin routers are mounted with session auth.
  - `AuthzError` becomes 403.

- `tap_api.routers.entities`
  - Read routes manually authorize `grid.read`.
  - Some write routes resolve entities before the decorated mutation path.

- `tap_api.routers.edges`
  - Read routes manually authorize `grid.read`.
  - Some write routes resolve endpoint/edge rows before the decorated mutation
    path.

- `tap_api.routers.searches`
  - Explicit read authorization before search lookup, then decorated search
    execution.

- `tap_api.routers.gryphon`
  - Calls decorated Gryphon execution.

- `tap_api.routers.entity_types`
  - Entity type listing appears unauthenticated/unauthorized and should be
    classified as public schema discovery or gated.

### TAP Cares

- `tap_cares.scheduler`
  - Uses scheduler built-in actor when no caller is provided.
  - Writes generally pass caller context.
  - Direct ORM reads are common and likely system-internal.
  - `set_schedule_enabled()` performs a direct `Schedule.objects.update()` after
    a service patch because the field is scheduler-owned and outside normal
    CRUD schema; this should be a named internal exception if retained.

- `tap_cares.services`
  - `run_collection()` uses built-in collector actor for job creation.
  - `_enqueue_and_record_task_id()` appears to patch without explicit caller
    context.

- `tap_cares.tasks`
  - Collector task status patches and produced-batch edge creation appear to
    call decorated service functions without caller context.
  - Direct ORM reads are common inside task execution.

- `tap_cares.collectors.base`
  - `submit_grift()` defaults actor to `None`; background collectors should not
    depend on ambient request context.

- `tap_cares.registry`
  - Collector node registration appears to call decorated write helpers without
    caller context during app-ready style registration.
  - This path also needs boot ordering treatment.

### Plugin panels sampled

- `plugins/administrivia/tap_cares/panels/collector_table`
  - Direct collector/job reads.
  - POST can trigger `run_collection()`. Needs human action authorization
    before collector runtime actor takes over.

- `plugins/administrivia/tap_cares/panels/schedule_table`
  - Direct schedule/job reads for operational display.

- `plugins/github_core/panels/*`
  - Direct ORM reads for repository/workflow/activity views.
  - Several modules also have parse-invalid exception syntax.

- `plugins/samsite/panels/*`
  - Some paths use `resolve_entity()` and `execute_search()` /
    `execute_gryphon_raw()`, which are closer to the intended read surface.
  - Broad exception handling still deserves review where it can hide auth
    failures.

## Recommended Next Steps

1. Create the first surface inventory from actual routes and dispatchers:
   API route, web page, object view, object edit, panel render, panel edit,
   panel action, synthetic nested panel, plugin panel, collector registry,
   collector task, scheduler task, boot sync, GRIFT import, and management
   command.

2. Decide the actor model for TAP Cares background work. Program actor identity
   should be explicit at task/registration/GRIFT submission boundaries rather
   than ambient.

3. Collapse or strictly service-wrap user lifecycle state. A single lifecycle
   enum is likely cleaner than `is_active` plus `deactivated_at`, but if both
   remain, all transitions need one authoritative service and tests for drift.

4. Separate human authorization from runtime authorization. For example, "user
   may click Run Collector" and "tap_collector may write job/results" should be
   two related but distinct decisions.

5. Tighten broad exception handling around auth-sensitive calls. Rendering
   errors can remain soft; `AuthzError` and `UnguardedOperation` should stay
   loud unless a spec explicitly says otherwise.

6. Classify direct ORM reads/writes rather than banning them blindly. The useful
   categories appear to be public discovery, user-facing read, panel composition
   read, system-internal orchestration read, boot/registration read,
   migration/low-level test, and service-layer internals.

7. Treat parenthesis-free multi-exception handlers as optional style/tooling
   cleanup only. They are valid for the Python 3.14 runtime, but may trip older
   linters/parsers or human readers.

8. Add tests from the codepath map, not from abstract policy alone. The
   highest-value tests are likely:
   panel render denied as 403, panel search AuthzError not swallowed, table
   panel save cannot bypass write AuthZ, collector task has explicit program
   actor, manual collector run requires human capability, built-in actor
   deactivation drift fails predictably, and API write routes authorize before
   existence-sensitive lookup.
