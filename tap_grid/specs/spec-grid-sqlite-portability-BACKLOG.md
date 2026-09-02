# Draft SQLite Portability & Compact Deployment Specification

Note: this is a **research / theoretical** backlog spec. It captures an adjacent-possible
capability surfaced while auditing TAP's database coupling — it is *not* approved work, and
nothing here should be built until a deployment shape actually demands it. Its job is to
preserve the thinking and to make the portability cost legible so future design decisions can
keep the door open cheaply rather than slam it shut by accident. All requirements below are
`Backlog`.

## Philosophy

TAP today assumes a server with a PostgreSQL process alongside it. That assumption is load-bearing
for the cloud-collector / always-on instance TAP was first built for, but an audit of the actual
database coupling (2026-06-05) found the *core* of TAP — the Entity/Edge spine, dimensions, the
service layer, and the Gryphon query engine — is essentially database-neutral, because almost
everything flows through the Django ORM rather than hand-written SQL.

That neutrality points at a **compact deployment shape** TAP could grow into: a single process over
a single file. The motivating use case is **personal deployments** — TAP/the grid managing content
and information for a single user, or at most a small community such as a family. Such instances are
low-impact, low-utilization, and have no need for a separate always-on database process. Collapsing
the database to a file (SQLite) is the enabling decision that unlocks two deployment shapes the
current Docker+PostgreSQL assumption forecloses:

1. **Scale-to-zero cloud** — fire the instance up on demand, serve, and let it go idle with no
   running processes (and therefore no 24/7 meter) in between. PostgreSQL forecloses this: the
   cheapest honest option is an always-on managed instance or a serverless tier with a non-zero
   floor. A file-backed instance is stateless-process-over-one-artifact, which is exactly what
   serverless platforms want.
2. **Standalone desktop / embedded application** — TAP packaged as a native app, where SQLite is
   the obvious and conventional store and there is no separate database to install or run.

This spec records *why that is possible*, *what the real coupling points are*, and *what would have
to flex* — so that the capability remains a cheap option rather than an expensive rewrite.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Database-Neutral Core | The grid spine, service layer, and Gryphon run identically on PostgreSQL and SQLite, with the ORM absorbing dialect differences. |
| 2. | Legible Coupling | Every PostgreSQL-specific dependency is named, located, and given a portable fallback path, so the cost of portability is known rather than discovered. |
| 3. | Stateless-Process Runtime | The runtime can cold-boot, serve, and exit with no always-on companion process — the database is a file, background work runs inline, and migrations run at provision time, not every boot. |
| 4. | Proven Parity | Gryphon behaviour on SQLite is *demonstrated equal* to PostgreSQL via the existing Gridkin / `test_gryphon` corpus, not merely assumed from a code read. |
| 5. | Door-Open Discipline | Future design decisions weigh whether they introduce new PostgreSQL-only coupling *or* esoteric client-side rendering that would break the minimal cross-platform webview, and prefer the portable construct when the cost is comparable. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-sqlite-portability-audit | [Coupling Audit Findings](#coupling-audit-findings) | Backlog | The 2026-06-05 audit: what is already portable and what is not |
| req-grid-sqlite-conditional-index | [Backend-Conditional Indexes](#backend-conditional-indexes) | Backlog | The GIN index on `Entity.dimensions` is the one hard migration blocker |
| req-grid-sqlite-readonly-shim | [Read-Only Session Fallback](#read-only-session-fallback) | Backlog | `search_readonly` uses a PostgreSQL-only session option |
| req-grid-sqlite-json-contains-guard | [JSON Containment Footgun](#json-containment-footgun) | Backlog | JSONField `__contains` is unsupported on SQLite; keep it out of portable paths |
| req-grid-sqlite-regex-function | [SQLite REGEXP Registration](#sqlite-regexp-registration) | Backlog | Gryphon's regex operator needs a registered REGEXP function on SQLite |
| req-grid-coldstart-stateless-runtime | [Stateless-Process Runtime](#stateless-process-runtime) | Backlog | Worker, migrate-on-boot, secrets, and entrypoint assume always-on |
| req-grid-coldstart-deployment-shapes | [Compact Deployment Shapes](#compact-deployment-shapes) | Backlog | Scale-to-zero cloud and standalone desktop as named targets |
| req-grid-coldstart-webview-portability | [Cross-Platform Webview Rendering Discipline](#cross-platform-webview-rendering-discipline) | Backlog | Keep the client surface portable across native webviews so the minimal pywebview shell stays viable |
| req-grid-sqlite-traversal-cte-seam | [Recursive-CTE Accelerator Seam](#recursive-cte-accelerator-seam) | Backlog | If traversals need CTEs to scale, SQLite supports them too — portable |
| req-grid-sqlite-parity-validation | [SQLite Parity Validation](#sqlite-parity-validation) | Backlog | Run the graph corpus against SQLite to prove behavioural parity |

## Explanation

#### The Core Finding

The audit traced the SQL-generation path with particular attention to Gryphon, the most likely
place for PostgreSQL-specific SQL to hide. The result: **Gryphon builds Django querysets, not raw
SQL.** Multi-hop graph traversal is expressed as reverse-FK JOINs (`_compute_hop_paths`), predicates
as `Q` objects, aggregation as `Count()`, anti-joins as `Exists()`/`OuterRef()`. There are no
recursive CTEs, no `->>`/`jsonb`/`::cast` operators, no hand-written SQL strings. The
SQL-capture / `explain_gryphon_raw` seam merely *observes* statements via
`connection.execute_wrapper`, so it is backend-agnostic too.

Because the engine rides the ORM, the dialect differences that matter most (JSON access, parameter
binding, join planning) are Django's problem, not TAP's. JSON nested-key lookups
(`entity__dimensions__<key>`) compile to `json_extract()` on SQLite. UUIDv7 primary keys are
generated Python-side (`uuid.uuid7`), not via `gen_random_uuid()`. `select_for_update` degrades to a
no-op on SQLite, and TAP's write correctness already rests on the application-level OCC `version`
counter rather than on row locks.

The conclusion is that the database swap itself is the *easy 80%*. The remaining work splits into a
handful of small, well-located PostgreSQL couplings (below) and a distinct concern — the *always-on*
runtime assumptions — that the database swap alone does not address.

#### Why SQLite Specifically Is the Unlock

The point is not that SQLite is convenient; it is that SQLite is what makes scale-to-zero honest.
The recurring cost of an idle instance is the always-on database process. Collapse the database to a
file and the instance becomes a stateless process over one artifact: boot on a request, serve, exit.
On the cloud that is the serverless / scale-to-zero model with the file on a volume (or replicated
to object storage). On the desktop it is simply the file. Same artifact, two deployment shapes.

#### What Does Not Transfer For Free

Three PostgreSQL couplings and one class of runtime assumption. None is large; the value of this spec
is that they are *named* so they don't get rediscovered the hard way. See the per-requirement
sections.

#### The Core Transfers; The Collectors Do Not

The grid spine, dimensions/scoping, and Gryphon are domain-agnostic — they do not care whether the
nodes are AWS resources or a family's documents and photos. What changes for a personal deployment is
the *ingestion* surface: personal-data collectors instead of boto3/GitHub collectors. That is
additive, not a rewrite, and it composes with the satellite/outpost direction — a compact personal
instance could itself be an outpost or host a few of them.

### Coupling Audit Findings
----
RID: `req-grid-sqlite-portability-audit`

Status: `Backlog`

Records the 2026-06-05 audit of TAP's PostgreSQL coupling, so the portability cost is a known
quantity rather than a future discovery.

#### Status Details
Research finding. Captured from a code audit; not a behaviour change. Should be re-validated if the
service layer, Gryphon, or the model layer takes on new raw-SQL or PostgreSQL-specific surface.

#### Implementation
**Already portable (rides the Django ORM):**
- Gryphon executor (`tap_grid/gryphon/executor.py`) — 100% queryset-based; FK-join traversal, `Q`
  predicates, `Count()` aggregation, `Exists()`/`OuterRef()` anti-joins. No raw SQL, no CTEs.
- Gryphon SQL capture (`tap_grid/gryphon/capture.py`) — passive observation via
  `connection.execute_wrapper`; backend-agnostic.
- JSON nested-key lookups (`entity__dimensions__<key>`, `data__<key>`) — compile to `json_extract()`
  on SQLite.
- UUIDv7 primary keys — generated Python-side (`uuid.uuid7`), stored as portable field types.
- `select_for_update` in the OCC paths (`services.py`, `grift/importer.py`) — no-op on SQLite;
  correctness rests on the app-level `version` counter regardless.
- All model field types in `tap_grid/models.py` — standard Django fields only.

**Not portable without a fallback (the short list):**
- GIN index on `Entity.dimensions` → `req-grid-sqlite-conditional-index`.
- `search_readonly` PostgreSQL session option → `req-grid-sqlite-readonly-shim`.
- JSONField `__contains` containment lookup → `req-grid-sqlite-json-contains-guard`.
- Gryphon regex operator → `req-grid-sqlite-regex-function`.

**Out of scope of the DB swap (separate concern):** always-on runtime assumptions →
`req-grid-coldstart-stateless-runtime`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-sqlite-portability-audit-1 | Findings Recorded | Backlog | The portable surfaces and the non-portable short list are documented with file references. | |
| req-grid-sqlite-portability-audit-2 | Re-Validation Trigger Named | Backlog | New raw-SQL or PostgreSQL-specific surface in the service/Gryphon/model layers triggers a re-audit. | |

### Backend-Conditional Indexes
----
RID: `req-grid-sqlite-conditional-index`

Status: `Backlog`

The GIN index on `Entity.dimensions` (`tap_grid/models.py`, migration `0005`, via
`django.contrib.postgres.indexes.GinIndex`) is PostgreSQL-only and is the one coupling that *stops a
migration from applying* on SQLite. It must become backend-conditional, with a plain B-tree index (or
no index) as the SQLite fallback.

#### Implementation
- Make the GIN index declaration conditional on a PostgreSQL backend, or move it into a
  PostgreSQL-only migration branch.
- On SQLite, dimension nested-key queries still function unindexed (acceptable at personal-deployment
  utilization); a generic `Index` may be used if a measured query needs it.
- `django.contrib.postgres` in `INSTALLED_APPS` is required only for the GIN import; revisit whether
  it can be gated alongside the index.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-sqlite-conditional-index-1 | Migrations Apply On SQLite | Backlog | A clean migrate against a SQLite backend completes without a PostgreSQL-only index error. | |
| req-grid-sqlite-conditional-index-2 | GIN Retained On PostgreSQL | Backlog | The PostgreSQL deployment keeps the GIN index unchanged. | |

### Read-Only Session Fallback
----
RID: `req-grid-sqlite-readonly-shim`

Status: `Backlog`

The `search_readonly` database alias (`tap/settings.py`) enforces read-only execution by passing the
PostgreSQL session option `-c default_transaction_read_only=on`. SQLite has no session-level
equivalent. The DB-enforced read-only seam for Gryphon execution (`req-grid-search-readonly.sec`) must
degrade gracefully on non-PostgreSQL backends.

#### Implementation
- On SQLite, the libpq `options` key is meaningless and must not be passed.
- Fallbacks, in rough order of strength: open the database file read-only at the OS/connection level;
  enforce read-only at the application layer; or accept that on a single-user embedded instance the
  DB-level guarantee is replaced by the absence of concurrent writers.
- Whatever the fallback, the *security intent* of `req-grid-search-readonly.sec` must be restated for
  the SQLite case so it is a deliberate choice, not a silent gap.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-sqlite-readonly-shim-1 | No PostgreSQL Option On SQLite | Backlog | The SQLite connection does not receive the PostgreSQL `options` session string. | |
| req-grid-sqlite-readonly-shim-2 | Read-Only Intent Preserved Or Stated | Backlog | The read-only search guarantee is either preserved by another mechanism or explicitly documented as relaxed for the embedded case. | |

### JSON Containment Footgun
----
RID: `req-grid-sqlite-json-contains-guard`

Status: `Backlog`

Django's JSONField `__contains` containment lookup raises `NotSupportedError` on SQLite. It is not in
TAP's load-bearing production scoping path today (dimension scoping uses nested-key lookups), but the
pattern exists (e.g. `dimensions__contains={...}` in plugin tests) and is an easy reach. Portable
code paths must avoid JSONField `__contains` / `__contained_by` / `__has_key*` containment lookups.

#### Implementation
- Prefer nested-key lookups (`dimensions__<key>=<value>`) over containment (`dimensions__contains`)
  in any code expected to run on SQLite.
- If containment semantics are genuinely needed in a portable path, express them as a composition of
  nested-key lookups or guard them behind a backend check.
- Existing containment uses (notably plugin tests) are non-blocking for PostgreSQL but would need
  revisiting before those suites could run on SQLite.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-sqlite-json-contains-guard-1 | Portable Paths Avoid Containment | Backlog | Code paths intended to run on SQLite use nested-key lookups, not JSONField containment lookups. | |

### SQLite REGEXP Registration
----
RID: `req-grid-sqlite-regex-function`

Status: `Backlog`

Gryphon's `regex` operator compiles to Django's `__regex` lookup (`tap_grid/gryphon/executor.py`),
which emits SQL `REGEXP` on SQLite — and SQLite has no built-in `REGEXP` function. A REGEXP function
must be registered on the SQLite connection for the operator to work. (Gryphon's `contains` operator
is fine — it is a string `LIKE`, not JSON containment.)

#### Implementation
- Register a `REGEXP` function on the SQLite connection (e.g. via a connection-init hook backed by
  Python's `re`), gated to the SQLite backend.
- Behaviour must match the PostgreSQL `~` semantics closely enough that the Gryphon regex corpus
  passes identically (validated under `req-grid-sqlite-parity-validation`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-sqlite-regex-function-1 | REGEXP Available On SQLite | Backlog | Gryphon's regex operator executes on SQLite without a missing-function error. | |
| req-grid-sqlite-regex-function-2 | Regex Corpus Parity | Backlog | The Gryphon regex test cases produce the same results on SQLite as on PostgreSQL. | |

### Stateless-Process Runtime
----
RID: `req-grid-coldstart-stateless-runtime`

Status: `Backlog`

The database swap is necessary but not sufficient for the cold-start shape. Cold-boot requires the
*runtime* to be process-light too. Several current pieces assume a supervisor that stays up: the
Steady Queue worker, the entrypoint's migrate-on-boot, the plugin-seed step, and the on-disk secrets
model. These are the seams that decide whether a cold start is sub-second or several seconds, and they
are independent of the DB portability work.

#### Implementation
- **Background tasks** — TAP already uses Django Tasks sparingly. A compact instance should run them
  inline / synchronously and skip the always-on worker entirely.
- **Migrations** — run once at package/provision time against the file, not on every boot.
- **Plugin seed** — a cold-boot instance needs a fast, pre-seeded state rather than an
  import-on-startup step.
- **Secrets** — the `TAP_SECRETS_ROOT` on-disk model is collector-oriented; a personal deployment's
  secret model differs (per-user, possibly none, possibly OS keychain) and should be treated as a
  separate design.
- **Entrypoint** — the current entrypoint assumes a long-running `runserver`; a packaged/serverless
  shape needs a different bootstrap.

#### Development
Treat this as a distinct workstream from the DB swap. It is possible to run TAP on SQLite long before
the runtime is genuinely cold-start-ready; conflating the two would overscope both.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-coldstart-stateless-runtime-1 | No Mandatory Companion Process | Backlog | A compact instance can serve a request without an always-on worker or database process. | |
| req-grid-coldstart-stateless-runtime-2 | Boot Cost Characterized | Backlog | The cold-boot cost (migrate, seed, import) is measured and the always-on assumptions are itemized. | |

### Compact Deployment Shapes
----
RID: `req-grid-coldstart-deployment-shapes`

Status: `Backlog`

Names the two target deployment shapes the SQLite + stateless-runtime work unlocks, so future
decisions have a concrete picture to weigh against.

#### Implementation
- **Scale-to-zero cloud** — instance fires up on demand, serves, and goes fully idle with no running
  processes; SQLite file on a volume or replicated to object storage. Motivated by extremely cheap
  hosting for low-utilization personal instances.
- **Standalone desktop / embedded** — TAP packaged as a native application with the SQLite file as
  its store and no separate database to run. Server-rendered templates + Cytoscape package cleanly
  into a webview-style shell. The **preferred shell is pywebview** — it keeps TAP pure-Python (no
  Node, no Rust, no bundled browser): Django runs in-process and a native OS webview renders the UI.
  Keeping pywebview viable imposes a client-side rendering discipline — see
  `req-grid-coldstart-webview-portability`. (Survey of alternatives: Electron bundles its own
  Chromium for identical rendering everywhere but is heavy (~150MB); Tauri is lean but, like
  pywebview, uses the OS-native webview; a Swift+WKWebView shell is the fully-native but Mac/iOS-only
  end. The "service you visit" alternative — a background server + menu-bar icon + the user's own
  browser, the Plex/Home-Assistant shape — needs near-zero packaging and is the right shape if a
  personal instance is conceptually a service rather than a document you open.)
- Both shapes target single-user or small-community (e.g. family) utilization. Multi-tenancy remains
  out of scope per the standing Core TAP Rule.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-coldstart-deployment-shapes-1 | Shapes Documented | Backlog | The scale-to-zero and desktop/embedded shapes are described with their assumptions and constraints. | |

### Cross-Platform Webview Rendering Discipline
----
RID: `req-grid-coldstart-webview-portability`

Status: `Backlog`

The desktop shape targets **pywebview** — the minimal native-shell option that keeps TAP pure-Python
(no Node, no Rust, no bundled browser engine). pywebview renders in each OS's *native* webview:
WKWebView (macOS), WebView2 (Windows, Chromium-based), WebKitGTK (Linux). The only shell that bundles
its own Chromium for byte-identical rendering everywhere is **Electron**, and it is the heavyweight
escape hatch this work is deliberately trying *not* to need. Keeping pywebview viable therefore
imposes a standing discipline: the client-side surface must render correctly across all three native
webviews without esoteric, engine-specific behaviour.

The point of recording this in a backlog spec is that the constraint is *cheap to honour
continuously and expensive to recover* — client-side debt that assumes Chromium creeps in invisibly
and is only discovered when the desktop shape is attempted. TAP has so far avoided it; this
requirement exists to make sure it does not creep in without the future implications being weighed.

#### Implementation
- **Preserve the conservative client posture.** TAP's UI is server-rendered Django templates +
  Cytoscape (canvas/WebGL2), with no esoteric client-side JS. That posture is precisely the property
  that keeps the minimal pure-Python shell on the table — treat it as load-bearing, not incidental.
- **WebKit is the de-facto compatibility floor.** Two of the three native engines (WKWebView,
  WebKitGTK) are WebKit; WebView2 is Chromium and is the permissive one. So "does it work on
  Safari / WebKit" is the practical proxy for cross-webview portability — the lagging engine sets the
  bar, not the most capable one.
- **Weigh new client-side capability before adoption.** Avoid Chromium-only web APIs, bleeding-edge
  CSS, and JS features not supported on WebKit. Prefer server-rendered HTML and mature,
  widely-supported client libraries over novel browser features.
- **Treat a genuine Chromium-only need as an explicit shell-escalation signal.** If a client-side
  capability truly requires Chromium semantics, that forces the shell up to Electron (bundled
  Chromium, heaviest footprint) and abandons the pure-Python pywebview goal. That is a legitimate
  tradeoff — but it must be made deliberately and recorded, never stumbled into via a convenience
  dependency.
- **Verify the viz on the native webviews.** Cytoscape's canvas/WebGL2 rendering is expected to work
  on WebKit, but it should be confirmed on WKWebView and WebKitGTK before the desktop shape is
  committed (client-surface analogue of `req-grid-sqlite-parity-validation`).

#### Development
This is a *discipline*, not a feature. Its entire value is being applied at the moment someone reaches
for an esoteric client-side capability — the gate is "have we considered the cross-webview / pywebview
implications?", not a blanket ban on client-side richness.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-coldstart-webview-portability-1 | WebKit Floor Honoured | Backlog | New client-side surface renders on WebKit (the WKWebView / WebKitGTK floor), not only on Chromium. | |
| req-grid-coldstart-webview-portability-2 | Esoteric-JS Is A Recorded Decision | Backlog | Adopting a Chromium-only / bleeding-edge client-side capability is a deliberate, recorded shell-escalation decision, not an incidental one. | |
| req-grid-coldstart-webview-portability-3 | Viz Verified Cross-Webview | Backlog | The Cytoscape visualization is verified on the native webviews (WKWebView, WebKitGTK) before the desktop shape ships. | |

### Recursive-CTE Accelerator Seam
----
RID: `req-grid-sqlite-traversal-cte-seam`

Status: `Backlog`

If/when traversals grow past what ORM-join expansion handles gracefully, a recursive-CTE accelerator
is a reasonable future seam — and crucially, it does *not* reintroduce a PostgreSQL dependency:
SQLite has supported `WITH RECURSIVE` since 3.8.3. The portable design keeps the ORM-join path as the
default and treats CTEs as an optional accelerator behind a capability flag.

#### Implementation
- Do **not** build the CTE path speculatively. This requirement exists to record that the door stays
  open on both backends, not to authorize work.
- When a real traversal goes cold, design the accelerator as standard SQL recursive CTEs (portable to
  both PostgreSQL and SQLite) selected behind a capability flag, with the ORM path as fallback.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-sqlite-traversal-cte-seam-1 | Accelerator Stays Portable | Backlog | Any future traversal accelerator uses standard recursive CTEs that run on both backends, with the ORM path as fallback. | |

### SQLite Parity Validation
----
RID: `req-grid-sqlite-parity-validation`

Status: `Backlog`

Behavioural parity must be *demonstrated*, not assumed from a code read. TAP already has a robust
graph validation surface — Gridkin scenarios in `plugins/gryphon_playground/` and
`tap_grid/tests/test_gryphon.py`. Running that corpus against a SQLite backend is the evidence that
the engine behaves identically.

#### Implementation
- Stand up a SQLite test configuration and run the Gryphon corpus + Gridkin scenarios against it.
- Any divergence is a Gryphon-portability bug to fix and lock with a scenario — never a case to route
  around (this inherits the standing "a Gryphon failure is NOT OKAY" rule).
- Parity results feed back into `req-grid-sqlite-portability-audit` as confirmation or new findings.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-sqlite-parity-validation-1 | Corpus Runs On SQLite | Backlog | The Gryphon/Gridkin corpus executes against a SQLite backend. | |
| req-grid-sqlite-parity-validation-2 | Results Match PostgreSQL | Backlog | Corpus results on SQLite match the PostgreSQL baseline; divergences are tracked as portability bugs. | |

## Clarifying Questions For Future Work

These are recorded so the research framing does not pretend the open questions are settled.

1. Is the first concrete target scale-to-zero cloud, standalone desktop, or both — and does that
   ordering change which runtime seams get addressed first?
2. For the embedded/single-user case, is DB-level read-only enforcement worth preserving at all, or is
   "no concurrent writers" a sufficient replacement for `req-grid-search-readonly.sec`?
3. What is the secret model for a personal deployment (none / OS keychain / per-user file), and does
   it belong in this spec or its own?
4. Does the desktop shape want server-rendered templates in a webview, or does it motivate a
   different frontend packaging entirely?
5. At what utilization (if ever) does the unindexed-dimensions query cost on SQLite actually bite,
   and what is the trigger to add a portable index?
6. How does a compact instance relate to the satellite/outpost vision — is a personal instance an
   outpost, a host for outposts, or both?
7. Is a personal instance conceptually a *document you open* (favouring the pywebview window) or a
   *service you visit* (favouring the menu-bar-server + browser shape)? That framing drives the shell
   choice more than any framework comparison does.
8. Does Cytoscape (and any future viz dependency) render correctly on WKWebView and WebKitGTK, or does
   the viz surface end up being the thing that forces a Chromium-bundled (Electron) shell?

## Status Vocabulary

| Status States |  |
| --- | --- |
| Backlog | Recorded research / theoretical work; not approved for development |
| Proposed |  |
| Approved for Development | Requirement is accepted and ready to be implemented |
| In Development |  |
| Implemented |  |
| Verified |  |
| Refactoring |  |
| Deprecating |  |
| Deprecated | Not part of the current architecture and should not be implemented |

## RID Format

`req-<application>-<specification>-<feature>-<sub-feature>`

## Requirements Format

`RID: \`...\``
`Status: \`...\``

| Sub-Sections | (as needed) |
| --- | --- |
| Status Details |  |
| Implementation |  |
| Development |  |
| Acceptance Criteria |  |
| Future |  |
