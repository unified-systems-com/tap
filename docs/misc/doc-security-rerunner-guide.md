# TAP Security Rerunner Guide

This guide is for future Codex Security runs and other security tooling instances
that need to come online quickly against TAP, The Analogy Platform.

TAP is a Python/Django and PostgreSQL-backed graph system for modeling systems,
operations, compliance, and security. Treat the local instance as production for
security testing purposes, even when the runtime profile is a dev profile.

## Core Security Invariant

TAP's central authorization rule is:

> Passing request authentication never implies permission.

Every graph read requires `grid.read`. Every graph write requires `grid.write`
or a narrower capability. This includes direct service reads, Gryphon, Search,
API read endpoints, page rendering, panel rendering, and helper paths that
resolve graph-backed objects for display.

Denied authorization decisions should log through:

- `tap_auth.policy` with site token `[e5d9]`
- `tap_auth.middleware` with site token `[a6b7]` for web denials

If a no-cap user receives graph data and no denial log appears, assume the route
skipped the authorization policy entirely.

## Structural Controls Now In Place (read this before hunting the old classes)

The 2026-06-30 finding classes were all "graph ORM below the service layer with no
capability gate." That class is now caught structurally, in depth. Know these
controls so you (a) do not re-report closed classes as open and (b) focus effort
on the deliberately-open edges instead of the covered core.

Runtime guards (fail closed, `unguarded_operation`), both in `tap_grid/`:

- **ORM read backstop** (`tap_grid/read_guard.py`, `req-tap-auth-orm-read-backstop`).
  Every materialization of a TAP-managed queryset re-checks `grid.read` at the ORM
  itself. Layer 1 = `BaseModelQuerySet._fetch_all` (get/first/iterate/list/values
  over any `BaseModel` incl. `Edge`); Layer 2 = a `connection.execute_wrapper`
  catching count/exists/aggregate/raw/cursor + the non-`BaseModel` `EntityType`
  catalog. A capless (or wrong-cap) `CallerContext` reading graph rows raises even
  if the route forgot to gate. Escape hatch: `unguarded_read()`. **Deliberate open
  edge:** `Entity` (`tap_entity`) reads are NOT backstopped (separate manager,
  pervasive below the boundary; the Entity API carries its own gate). A view/route
  that reads `Entity.objects...` directly and returns spine metadata to a capless
  actor is still a real finding — the runtime net does not catch it.
- **ORM write backstop** (`tap_grid/write_guard.py`, `req-tap-auth-write-batch-routing`).
  A node/edge mutation is permitted only inside a *service-layer write scope*, opened
  by the sanctioned write API (`write_batch` / `create_node` / `create_edge` /
  `delete_*` / `purge_node` / `patch_node`, via the write-class `@requires_capability`
  decorator). A direct `instance.save()` / `Model.objects.create()` / `entity.delete()`
  from a view, panel, editor descriptor, collector, or command raises. Escape hatch:
  `unguarded_write()` (admin/infra + tests). **Deliberate open edge:** queryset-level
  bulk writes (`Model.objects.filter(...).update()/.delete()`) bypass the instance
  `save`/`delete` hooks, so the *runtime* guard does not see them — they are covered
  by the static lint below instead.

Build-time lints (baseline-ratchet to zero, `# TAP-*-COV: <reason>` inline hatch):

- **authz-coverage** (`tap/authz_coverage.py`, Rule A): every service-layer read/write
  sink must sit inside a `@requires_capability`/`authorized()` function.
- **direct-write** (`tap/direct_write_coverage.py`, Rule B write half): statically
  flags `<Model>.objects.create/update/...`, `<Model>.objects.filter(...).delete()/
  .update()`, and `<Model>(...).save()` on graph models outside the sanctioned service
  modules — catching the queryset-level writes the runtime guard cannot.

How to reason about a candidate finding against these controls:

1. Does the sink go through a `BaseModel`/`Edge` queryset with a bound capless context?
   If yes, the read backstop already fails it closed — verify by live HTTP that it
   actually returns `403`, and if it returns `200` you have found a **gap in the net**
   (an exemption abused, a ctx-None path, or `Entity`/queryset-bulk edge), which is a
   *higher-value* finding than the original class.
2. Is `CallerContext` actually bound on the path? The guards allow when NO context is
   bound (the infra zone: migrations/shell). A request path that reaches graph rows
   with no context bound is itself the finding — middleware should always bind one
   (`user=None` for anonymous). Look for background/async/thread paths that lose it.
3. Is the sink `Entity.objects` or a raw SQL string not covered by Layer 2's regex?
   Those are the open edges; test them directly.

## Read First

Start with these files before broad scanning:

1. `AGENTS.md`
2. `architecture.md`
3. `plan/road-products.md`
4. `tap_auth/specs/spec-tap-auth-v0.md`
5. `tap_web/specs/spec-web-page.md`
6. `tap_web/specs/spec-web-panel.md`
7. `tap_web/specs/spec-web-rendering.md`
8. `tap_web/specs/spec-web-panel-security.md`
9. `specs/spec-security-posture.md`
10. `tap_grid/read_guard.py` and `tap_grid/write_guard.py` (the runtime backstops)
11. `tap/authz_coverage.py` and `tap/direct_write_coverage.py` (the build-time lints)
12. The relevant `tap_api/routers/` code and tests

Specs are canonical. If current route behavior disagrees with a spec, treat the
spec as the intended security contract and the behavior as suspect.

## Runtime Rules

Use the Python inside the container for Django/runtime validation:

```bash
scripts/dc exec web uv run python ...
```

The local web process is commonly published as:

```text
0.0.0.0:8030 -> container port 8000
```

For authorization validation, prefer real HTTP from inside the container to the
host-published port:

```python
BASE = "http://host.docker.internal:8030"
HEADERS = {"Host": "localhost:8030"}
```

Do not rely only on Django's test client or `force_login()` when proving route
authz. Create real users, log in through `/auth/login/`, keep the session
cookies, and hit the app over HTTP.

## Capability Matrix

Create and test at least these actors:

- anonymous client
- authenticated human user with no TAP capability groups
- `tap_viewer` user with `grid.read`
- `tap_admin` user
- optional program user for non-human actor constraints

Expected pattern:

- anonymous web pages usually redirect to `/auth/login/`
- anonymous APIs usually return `401`
- capless graph reads should return `403` and emit authz-denial logs
- `tap_viewer` can read graph-backed surfaces
- `tap_viewer` cannot write
- `tap_admin` can read and write where the request is otherwise valid

## High-Value Surfaces

Prioritize these before spending time on lower-signal files:

- `tap_web/views.py`
- `tap_web/page.py`
- `tap_web/panels/*`
- `tap_web/templates/*`
- `tap_api/routers/*`
- `tap_auth/policy.py`
- `tap_auth/middleware.py`
- `tap_grid/search`
- Gryphon executor and API router
- service-layer graph read/write chokepoints
- plugin panel context builders and templates
- `tap_cares` collector/action execution paths

Search for direct graph ORM reads in web/API paths:

```bash
rg -n "Page\\.objects|Panel\\.objects|Entity\\.objects|EntityType\\.objects|Edge\\.objects|model_cls\\.objects" tap_* plugins
```

Any route that touches graph state before an explicit `grid.read` authorization
decision deserves review.

Search for direct graph ORM **writes** outside the service layer (the write-side
twin — these must route through `write_batch`/`create_node`/`create_edge`/
`delete_*`/`patch_node`, not direct ORM). The static lint already fails new ones,
but framework dispatch and instance writes can still slip; confirm by hand:

```bash
rg -n "\\.objects\\.(create|get_or_create|bulk_create|bulk_update|update)\\b|\\.save\\(|\\.delete\\(" tap_web tap_api plugins tap_cares
```

For each hit, confirm it either (a) calls a service function, or (b) sits inside a
write-class `@requires_capability` scope. A write reached from a view/panel/
descriptor/collector handler by direct ORM is a finding even if the runtime guard
would trip — because the *authorization gate* (not just the write scope) may be
missing, which is the actual escalation.

## Known Finding Classes To Retest

Recent validated classes included:

1. Generic panel fragments: `/panel/<slug>--<uuid>/` resolved and rendered
   `Panel` data without `grid.read`.
2. ViewerPanel object selection: a ViewerPanel could use `entity_id` and
   `entity_type` query parameters to render another object behind the unguarded
   panel endpoint.
3. Page/nav enumeration: dynamic page routes and `/__nav-index.json` exposed
   page metadata, layout slots, and panel URL identifiers without `grid.read`.
4. Entity type catalog: `/api/v1/entity-types/` returned graph metadata to
   authenticated no-cap users.

All four are now closed at the data layer by the read backstop (verify they return
`403`, not just trust it). Expand to nearby route families and to these adjacent
classes that the runtime net does NOT fully cover:

5. **Write-side twin (`grid.write`/`delete`/`purge`).** The same "below the service
   layer" pattern on the write side: a mutation endpoint, panel `handle_save`,
   editor descriptor, or `tap_cares` collector/action that writes graph state by
   direct ORM without a write-class gate. Found live this session in
   `table_panel.handle_save` and the LOTR editor descriptor. Test that a capless (or
   read-only `tap_viewer`) actor cannot drive a write through any framework dispatch
   path, and that the write actually routes through the service layer (carries FLIP +
   provenance), not just that it "worked."
6. **Authorize-after-lookup (existence oracles).** A route that does
   `get_object_or_404(...)` *before* authorizing leaks existence via `404` vs `403`
   timing/status even when the read is otherwise gated. The fix pattern applied this
   session is authorize-BEFORE-lookup in `tap_api/routers/entities.py` and `edges.py`.
   Look for any handler that resolves the target before its `policy.authorize(...)`.
7. **Empty-payload / no-op mutation endpoints that read.** A PATCH/POST endpoint that
   fetches and returns the target with an empty body is a read dressed as a write; if
   it gates only `grid.write` an actor with write-but-not-read (or the reverse) gets an
   unintended read/leak. Check that mutation endpoints authorize the capability that
   matches what they actually expose.
8. **`Entity` spine reads and raw SQL.** The read backstop deliberately excludes
   `Entity.objects` and any raw SQL not matched by Layer 2's table regex. A view
   returning spine metadata via `Entity.objects` to a capless actor is uncaught by the
   net — test directly.
9. **Context-loss paths.** Background tasks, async views, threads, or signal handlers
   that reach graph rows after `CallerContext` is lost hit the infra-zone allow. Any
   such path serving user-triggered data is a finding.

Retest 1–4 first after fixes, then work 5–9.

## Logging Checks

For every denied request, check both status and logs.

Good guarded denial evidence looks like:

```text
tap_auth.policy ... [e5d9] authz denied: reason=capability_denied capability=grid.read ...
tap_auth.middleware ... [a6b7] web authz denied ...
```

If a no-cap request returns `200`, no authz denial log may appear because the
policy was never called. Record that as part of the finding.

## POST, CSRF, XSS, CORS, And Headers

Always run a small live HTTP sanity pass:

- POST without CSRF token returns `403`
- POST with bogus CSRF token returns `403`
- cross-origin POST returns `403`
- valid same-origin CSRF token is the only write that lands
- stored `<script>` and `<img onerror>` payloads render escaped
- no template applies `|safe` to a JSON payload (they use Django's `json_script`); any remaining `|safe` is clearly escaped HTML
- responses do not unexpectedly emit `Access-Control-Allow-Origin`
- `X-Frame-Options` is `DENY`
- `X-Content-Type-Options` is `nosniff`
- `Referrer-Policy` is `same-origin`
- `Cross-Origin-Opener-Policy` is `same-origin`

The dev profile may fail `manage.py check --deploy`. Before reporting that as an
exploitable deployment issue, verify whether the deploy boot path fails closed.
`tap_auth.boot._check_deploy_posture` is the relevant source.

## Useful Commands

Targeted auth/web/API tests:

```bash
scripts/dc exec web uv run python -m pytest \
  tap_auth/tests/test_policy.py \
  tap_auth/tests/test_enforcement.py \
  tap_auth/tests/test_login_wall.py \
  tap_api/tests/test_gryphon.py \
  tap_api/tests/test_searches.py \
  tap_api/tests/test_entity_types.py \
  tap_web/tests/test_views.py \
  tap_web/tests/test_reserved_prefixes.py \
  tap/tests/test_authz_coverage.py \
  tap/tests/test_direct_write_coverage.py \
  tap_grid/tests/test_read_guard.py \
  tap_grid/tests/test_write_guard.py -q
```

Deploy posture:

```bash
scripts/dc exec web uv run python manage.py check --deploy
```

Logs:

```bash
scripts/dc logs --since 2m web
```

Broad source search:

```bash
rg -n "objects\\.|authorize\\(|requires_capability|csrf_exempt|mark_safe|\\|safe|innerHTML|insertAdjacentHTML" tap_* plugins
```

## Efficient Scan Order

1. Read the architecture, active roadmap step, and auth/web/API specs.
2. Build the threat model around anonymous, capless, viewer, and admin actors.
3. Enumerate routes and graph-read sinks.
4. Live-test high-value routes over real HTTP.
5. Compare no-cap behavior against guarded graph APIs.
6. Check denial logs.
7. Check POST, CSRF, XSS, CORS, and browser-security headers.
8. Broaden into plugin-specific surfaces once core boundaries are understood.

TAP's highest-signal bug class is usually a presentation/helper route that reads
graph state outside the capability policy. Prove or disprove those first.

## Reporting Expectations

For each finding, include:

- exact route or callable
- required capability
- actual no-cap status
- expected guarded status
- source root-control line
- sink line
- live HTTP proof
- access-control logging behavior
- remediation
- no-cap regression test

For coverage, be explicit about deferred work. A partial scan with precise
receipts is better than an exhaustive-looking report that silently skipped
surfaces.
