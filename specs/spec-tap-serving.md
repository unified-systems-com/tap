# TAP Serving

## Philosophy

This spec owns the boundary between the deployed artifact and the network: **what process accepts a
request, how many of them there are, what they are allowed to hold, and how static assets reach a
browser.** It is deliberately separate from `spec-product-install.md`, which owns *how an operator
reaches a running instance*. Install is a conversation; serving is a property of the artifact,
identical whether the operator is a customer, a maintainer, or CI.

It exists because that property was never specified, and the default filled in for it. The published
`ghcr.io/unified-systems-com/tap-web` image serves with the Django development server
(`docker/entrypoint.sh:225`); `WSGI_APPLICATION` is declared at `tap/settings.py:299` and served by
nothing; `collectstatic` runs nowhere; and `DEBUG` defaults to `true` (`tap/settings.py:49`). None of
this was decided — it is the shape a project has before anyone writes the serving spec.

Two convictions shape every requirement below.

**The dev/prod delta is a short, named list — never a `DEBUG` branch.** Today static serving is
*implicitly* coupled to `DEBUG`, because Django's `staticfiles` app serves assets from `runserver`
only in debug mode. That coupling is why `DEBUG=false` cannot simply be set on the current image: it
does not harden the product, it unstyles it. A single boolean standing in for "everything that
differs between my laptop and production" is the mechanism that produced this spec's existence, and
reusing it would rebuild the trap one layer up.

**The first real deployment is dated, and it is not hypothetical.** `git-serious-tap#86` — launch
git-serious from a GitHub Codespace, zero-install, no org, no local Docker — is the target for the
`git-serious-friends` milestone. That target is what makes this spec urgent rather than tidy, and it
is what decides which requirements below are critical path. A Codespace is a real deployment
boundary: a generated HTTPS hostname, a proxy the artifact does not control, and a visitor who is not
us. Requirements that would otherwise read as "later" — proxy trust, hostname configuration, secure
cookies, a health probe that passes behind a deployment hostname — are load-bearing on that date.

**We run in development what we ship to customers.** The failures this spec guards against — static
not collected, `DEBUG`-dependent behavior, connection exhaustion, header handling — are invisible to
a developer running the dev server, and appear for the first time in front of the person we least
want to show them to. Parity is not tidiness; it is the only mechanism that makes these bugs
reachable before release.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Real Server | The artifact serves its WSGI application under a production server, not the development server. |
| 2. | Parity By Default | Development and production run the same serving stack, differing only by an explicitly enumerated set of named levers. |
| 3. | Derived Connection Budget | The database connection ceiling is derived from the process model rather than authored independently of it. |
| 4. | Static Without Debug | Static assets are served correctly with `DEBUG` off, and remain live-editable in a development worktree. |
| 5. | Fail Closed On Configuration | Configuration that is unsafe when defaulted has no default; the artifact refuses to start rather than starting insecurely. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-serving-server | [The Production Server](#the-production-server) | Proposed | gunicorn, sync workers, serving `tap.wsgi.application`; replaces `runserver` in every environment |
| req-tap-serving-server-crypto | [The Server Introduces No Crypto Provider](#the-server-introduces-no-crypto-provider) | Proposed | Standing constraint on this and any future server swap; the deciding factor against granian |
| req-tap-serving-connection-budget | [The Connection Budget Is Derived](#the-connection-budget-is-derived) | Proposed | `max_connections` derived from worker count + alias count; one authored number, not two |
| req-tap-serving-conn-max-age | [Persistent Connections Require Bounded Holders](#persistent-connections-require-bounded-holders) | Proposed | `TAP_DB_CONN_MAX_AGE`; the precondition is stated, not assumed |
| req-tap-serving-static | [Static Assets Without Debug](#static-assets-without-debug) | Proposed | WhiteNoise; collected static; finders + autorefresh in dev |
| req-tap-serving-static-plugins | [Plugin Assets Are Collected After Plugin Install](#plugin-assets-are-collected-after-plugin-install) | Proposed | **Unresolved fork.** Plugins install at boot, not build; build-time collection cannot see them |
| req-tap-serving-static-unhashed | [Static Filenames Are Not Hashed](#static-filenames-are-not-hashed) | Proposed | Inconsistent module versioning, and a runtime-resolved import no build step can follow |
| req-tap-serving-debug-scope | [`DEBUG` Governs Error Presentation Only](#debug-governs-error-presentation-only) | Proposed | No behavior outside error rendering may branch on `DEBUG` |
| req-tap-serving-delta | [The Dev/Prod Delta Is Enumerated](#the-devprod-delta-is-enumerated) | Proposed | The delta is a table in this spec; adding to it is a spec change |
| req-tap-serving-fail-closed | [Unsafe Configuration Has No Default](#unsafe-configuration-has-no-default) | Proposed | `SECRET_KEY`, DB credentials; a wrong default is worse than a missing one |
| req-tap-serving-readiness | [Readiness Is Server-Independent](#readiness-is-server-independent) | Proposed | What "ready" means, and the relationship to the steady_queue supervisor |
| req-tap-serving-grants | [A Table Cannot Exist Without Its Grant](#a-table-cannot-exist-without-its-grant) | Proposed | tap#431; migration and grant reconciliation must be inseparable |
| req-tap-serving-process-failure | [Process Failure Is Visible](#process-failure-is-visible) | Proposed | Two process trees, one container; either dying must turn readiness red |
| req-tap-serving-proxy | [Deployment Behind A Proxy](#deployment-behind-a-proxy) | Proposed | TLS termination, trusted proxy headers, secure cookies; tap#272, tap#277 |
| req-tap-serving-durability | [Durability Tuning Is Confined To Disposable Databases](#durability-tuning-is-confined-to-disposable-databases) | Proposed | The shipped compose disables `fsync`; that must not reach a durable deployment |
| req-tap-serving-codespace | [The One-Click Codespace Is The First Deployment](#the-one-click-codespace-is-the-first-deployment) | Proposed | git-serious-tap#86; sets which requirements are critical path and which can wait |

### The Production Server
----
RID: `req-tap-serving-server`

Status: `Proposed`

The artifact serves `tap.wsgi.application` under **gunicorn with sync workers**, in development and
production alike. The Django development server is not a deployment target; upstream states plainly
that it is neither security-audited nor performance-tested, and it is what the product ships today.

**Why sync workers specifically, and not merely "a real server".** The worker model is load-bearing
for [`req-tap-serving-connection-budget`](#the-connection-budget-is-derived). A sync worker is a
forked process handling one request at a time, so it holds exactly one database connection per
configured alias. That makes the connection ceiling a arithmetic consequence of the worker count
rather than an estimate. Async and gevent worker classes break this property — the documented failure
is connections accumulating faster than they are recycled until the server's limit is reached, which
is precisely the incident this spec was written after.

**Alternatives considered and rejected:**

| Option | Disposition |
| --- | --- |
| gunicorn, sync workers | **Chosen.** Pure Python, no new crypto provider, exact connection arithmetic, the boring default with the deepest operational record. |
| granian | Rejected. Rust; would pull `ring` / `aws-lc-rs` into the cryptographic boundary — see [`req-tap-serving-server-crypto`](#the-server-introduces-no-crypto-provider) — to buy throughput for which there is no demand signal. |
| uvicorn / ASGI | Rejected for now. Buys async concurrency the codebase does not use. Revisit only when a requirement actually needs it (websockets, streaming); doing so re-opens the connection arithmetic. |
| gunicorn with gevent / async workers | Rejected. Forfeits the one-connection-per-worker property this spec depends on. |

#### Implementation

Replaces `docker/entrypoint.sh:225` (`exec uv run python manage.py runserver_nocache 0.0.0.0:8000`).
Worker count is explicit configuration, not a computed default, because it is an input to
[`req-tap-serving-connection-budget`](#the-connection-budget-is-derived).

`tap_grid/management/commands/runserver_nocache.py` **retires** under this requirement. It exists to
put `no-store` on static responses so a browser stops running stale JS; WhiteNoise's development mode
sets `max-age=0` for the same reason, so the command's job is absorbed rather than ported. Its
docstring already asserts the outcome this spec defines — *"production never runs this; it serves
static through a real web server with proper caching"* — a declaration that has never been true.

#### Development

Coupling to `runserver` was verified to be shallow before this was written. The only dependents are
`docker/entrypoint.sh:225`; the spawn readiness poll at `scripts/spawn-session.sh:988-1019`, which
asks only whether HTTP answers on the port and is therefore already server-agnostic; and a warm-up
comment at `.github/workflows/api-fuzz.yml:115`. Nothing structural blocks the swap.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-server-1 | WSGI Application Served | Proposed | The running artifact serves `tap.wsgi.application` under gunicorn; no environment invokes `runserver` or `runserver_nocache`. | |
| req-tap-serving-server-2 | Sync Worker Class | Proposed | The configured worker class is the sync worker; an async or gevent worker class fails the check that guards the connection budget. | Pairs with `req-tap-serving-connection-budget-2` |
| req-tap-serving-server-3 | Worker Count Is Explicit | Proposed | Worker count is set by named configuration and readable at runtime; it is not left to a library default. | Input to the budget derivation |
| req-tap-serving-server-4 | No-Cache Command Retired | Proposed | `runserver_nocache` is removed, and editing a static asset in a development worktree still serves the new bytes on refresh. | |

#### Future

- Front-proxy posture (TLS termination, `SECURE_PROXY_SSL_HEADER`, real client IP) is deliberately
  out of scope until there is a deployment with a proxy in front of it. Named here so its absence is
  a decision rather than an oversight.
- Graceful-restart semantics and their interaction with the steady_queue supervisor's shutdown path
  (see tap#229, which reports the entrypoint's `EXIT` trap cannot fire) belong to a later pass.

### The Server Introduces No Crypto Provider
----
RID: `req-tap-serving-server-crypto`

Status: `Proposed`

The serving stack — the server, its worker class, and the static middleware — introduces **no
cryptographic provider** into the deployed artifact. Any future change to the serving stack is
evaluated against this before performance.

Per `spec-fips.md` and `req-fips-crypto-bom`, the audit question is "account for every crypto
provider," not "grep for MD5": a Rust binary linking `ring` or `aws-lc-rs` carries its own crypto,
ignores `OPENSSL_CONF`, and silently runs non-FIPS. This is not hypothetical — it is exactly the
zizmor plugin's declared posture (`uses-nonvalidated`, providers `boringssl` and `rust-aws-lc-rs`),
which is tolerable there only because that plugin runs its binary `--offline` and the providers never
execute a security operation. A web server terminating requests has no such escape.

gunicorn and WhiteNoise are pure Python and add no provider. `whitenoise[brotli]` is **not** used:
the Brotli C extension is a compiled dependency admitted for gzip-versus-brotli compression margin on
assets of our size, which does not justify the boundary conversation.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-server-crypto-1 | Serving Stack Adds No Provider | Proposed | The crypto-BOM gate classifies the serving dependencies as introducing no cryptographic provider. | Fails closed on an unclassified provider |
| req-tap-serving-server-crypto-2 | Brotli Extra Excluded | Proposed | The WhiteNoise dependency is declared without the `brotli` extra. | |

### The Connection Budget Is Derived
----
RID: `req-tap-serving-connection-budget`

Status: `Proposed`

PostgreSQL's `max_connections` is **derived** from the process model, not authored beside it. The
unit of derivation is a **connection-holding thread**, not a process:

```
max_connections >= (sum of concurrent request/task threads across every process) x (DB aliases)
                   + management-command and administrative sessions
                   + restart-overlap headroom
```

There are two aliases today: `default` and `search_readonly` (`tap/settings.py:376`), the
least-privilege role the Gryphon read path authenticates as.

**Counting the background side correctly matters, and the obvious count is wrong.** It is tempting to
say "one connection per worker process," which is true of gunicorn sync workers and false of
everything else in the artifact. `settings.STEADY_QUEUE` (`tap/settings.py:665`) configures a
`scheduler` worker with `threads=1` and a `default` worker with `threads=3`, plus a dispatcher
polling on its own. Each of those threads is an independent connection holder, and collectors run on
the `default` queue — so the background side alone can hold several times what a per-process count
predicts, precisely while a collection run is in flight and the web side is also busy.

Two further consumers are easy to forget and were part of the observed exhaustion: `manage.py`
invocations (boot, imports, ad-hoc shells) open their own connections, and a **rolling restart
overlaps** old and new workers, so peak demand briefly exceeds steady-state demand.

This is the derive-a-fact-once rule applied to capacity. Worker counts and the connection ceiling
authored independently are two copies of one fact, and the second copy goes stale silently — capacity
looks configured right up to the moment it is not. A ceiling left at PostgreSQL's default of 100 is
not a budget; it is the absence of one wearing a budget's clothes.

Bounded gunicorn workers fix the **web** side of this. They do not establish the budget.

#### Status Details

Proposed rather than Approved because two terms need values chosen against a real deployment: the
headroom constant, and whether the derivation is computed at startup from live configuration or
asserted as a check against it. The *shape* is settled; the constants are not.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-connection-budget-1 | Ceiling Derived From Threads | Proposed | `max_connections` is computed in one place from the configured gunicorn worker count, the steady_queue worker/thread configuration, and the alias count — not set as an independent literal. | Derive-a-fact-once |
| req-tap-serving-connection-budget-2 | Budget Holds Under Combined Load | Proposed | Under sustained page navigation **concurrent with a collection run**, `count(*) FROM pg_stat_activity WHERE backend_type='client backend'` stays below the derived ceiling and does not grow monotonically. | The 2026-09-15 signature; collection concurrency is the part a web-only test misses |
| req-tap-serving-connection-budget-3 | Queue Threads Counted | Proposed | The derivation reads steady_queue's per-worker `threads` values; changing `threads=3` to another value changes the computed ceiling. | Guards the per-process undercount |
| req-tap-serving-connection-budget-4 | Restart Overlap Survives | Proposed | A rolling restart under load does not exhaust connections while old and new workers coexist. | |

### Persistent Connections Require Bounded Holders
----
RID: `req-tap-serving-conn-max-age`

Status: `Proposed`

Persistent database connections are permitted **only** where the number of processes holding them is
bounded and fixed. The lifetime is configured by `TAP_DB_CONN_MAX_AGE`, applied to every alias, and
its default is `0` — connections closed at request end.

The precondition is the point. `CONN_MAX_AGE` applies independently *within each worker process*, so
its safety depends entirely on how many holders can exist. Under gunicorn sync workers that number is
the worker count, and a positive lifetime is correct. Under the Django development server it is
unbounded: `runserver` is thread-per-request with no thread cap, each new thread can pin one
connection per alias, threads churn and connections do not.

**The incident.** On 2026-09-15 the `demo-dev` session stack stopped serving after 16 hours. Nothing
had crashed — both containers were up and the database was healthy. There were 100 established
connections on port 5432 against a `max_connections` of 100, **all 100 from a single peer**: the web
container itself, across 8 Python processes (`runserver` parent and reloader child, steady_queue
supervisor and 4 workers), roughly 12 each. Every request and steady_queue's own heartbeat timer
failed with `FATAL: sorry, too many clients already`. The cause was `conn_max_age=600`
(`tap/settings.py:313`) — a persistent-connection optimization whose precondition had never held,
because nothing in the settings recorded that it had one.

Raising `max_connections` is not a remedy; it moves the wall. `--nothreading` is not a remedy; it
serializes every request and makes HTMX-driven panel pages unusable.

#### Implementation

Read in `tap/settings.py` for both the `default` and `search_readonly` aliases. The value is set by
the **serving profile** — by which server is running — and explicitly **not** derived from `DEBUG`;
see [`req-tap-serving-debug-scope`](#debug-governs-error-presentation-only). The setting carries a
comment stating the bounded-holder precondition, so the next reader inherits the reason and not just
the number.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-conn-max-age-1 | Configurable, Default Zero | Proposed | `TAP_DB_CONN_MAX_AGE` governs `conn_max_age` for every alias and defaults to `0`. | |
| req-tap-serving-conn-max-age-2 | Not Derived From DEBUG | Proposed | No code path sets connection lifetime from `DEBUG`. | |
| req-tap-serving-conn-max-age-3 | Precondition Recorded | Proposed | The setting's comment states that a positive lifetime requires a bounded number of connection-holding processes. | Prevents silent reintroduction |

### Static Assets Without Debug
----
RID: `req-tap-serving-static`

Status: `Proposed`

Static assets are served by **WhiteNoise**, in both environments, independent of `DEBUG`.

- **Production:** assets are collected once (see
  [`req-tap-serving-static-plugins`](#plugin-assets-are-collected-after-plugin-install) for *when*)
  and WhiteNoise serves the collected `STATIC_ROOT` (`tap/settings.py:604`) with compression and
  cache headers.
- **Development:** WhiteNoise runs with finders enabled and autorefresh on, serving straight from the
  source directories. A CSS or JS edit in a mounted plugin worktree is visible on refresh with **no**
  `collectstatic` step, and responses carry `max-age=0` so the browser never runs stale modules.

Today neither half exists. `collectstatic` runs nowhere — not in `docker/entrypoint.sh`, not in the
`Dockerfile` — `STATIC_ROOT` is declared and never populated, and there is no WhiteNoise dependency.
Assets reach the browser solely because Django's `staticfiles` app serves them from `runserver` when
`DEBUG` is true. That coupling is what makes the product structurally dependent on debug mode to
render itself, and removing it is the precondition for
[`req-tap-serving-fail-closed`](#unsafe-configuration-has-no-default).

Preserving the development inner loop is a first-class constraint, not a concession: several session
worktrees edit plugin templates, CSS and JS continuously, and a serving change that inserts a build
step into that cycle would be worked around rather than adopted.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-static-1 | Styled With DEBUG Off | Proposed | With `DEBUG=false`, every page renders with its CSS and JS loaded, including plugin-shipped assets. | The test that has never been run |
| req-tap-serving-static-2 | Live Edit Preserved | Proposed | Editing a plugin static asset in a mounted worktree is served on the next refresh with no `collectstatic` and no container restart. | Inner-loop guard |
| req-tap-serving-static-3 | No Stale Modules In Dev | Proposed | Development static responses carry `max-age=0`. | Absorbs `runserver_nocache`'s job |

### Plugin Assets Are Collected After Plugin Install
----
RID: `req-tap-serving-static-plugins`

Status: `Proposed`

Static collection must happen at a point where **the full plugin set is present**. Collecting at
image build does not satisfy this, and assuming it does would ship a product whose plugin pages are
unstyled in exactly the configuration a customer runs.

**Why build-time collection cannot work as-is.** Plugins are not baked into the image. The entrypoint
resolves a boot profile and installs that profile's plugins at container start
(`docker/entrypoint.sh:139-140`, via `tap.preboot`), which is what allows one image to serve
git-serious, zizmor or a customer's own plugin set. A `collectstatic` executed during `docker build`
therefore sees core assets only — `tap_web`, `tap_viz` — and none of the plugin assets that every
product page depends on. The gap is invisible in development, where finders serve from source.

**This is an unresolved fork**, and it is the reason this requirement is separate rather than a
clause of [`req-tap-serving-static`](#static-assets-without-debug):

| Option | Consequence |
| --- | --- |
| **Collect at boot**, after pre-boot plugin install and before the server starts | One image serves any plugin set — preserves the profile model. Adds work to every container start and needs a writable `STATIC_ROOT`, which interacts with a read-only root filesystem if that is ever adopted. |
| **Build per-product images** with the plugin set baked in | Collection returns to build time, start-up stays fast, the artifact is fully immutable. Abandons one-image-many-profiles and multiplies the images to publish, sign and scan. |

The current epic assumed **both models at once** — a build-time collect against a boot-time plugin
install. That cannot hold, and choosing between them is a product-shape decision, not a serving
detail: it determines whether the published artifact is generic or per-product.

#### Status Details

Blocked on that choice. No implementation should proceed on
[`req-tap-serving-static`](#static-assets-without-debug)'s production half until it is made, because
the two options produce different Dockerfiles, different entrypoints and different publish pipelines.
Resolving the question is the task; building is not.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-static-plugins-1 | Collection Sees Every Plugin | Proposed | In the shipped configuration, collected static contains the assets of every plugin in the booted profile. | |
| req-tap-serving-static-plugins-2 | Plugin Page Styled In Production | Proposed | With `DEBUG=false`, a plugin-owned page renders with its own plugin's CSS and JS, not merely core assets. | The specific failure build-time collection produces |
| req-tap-serving-static-plugins-3 | Model Recorded | Proposed | The chosen model is stated in this requirement with its rationale, and the rejected option is recorded. | |

### Static Filenames Are Not Hashed
----
RID: `req-tap-serving-static-unhashed`

Status: `Proposed`

The staticfiles backend compresses but **does not hash** filenames. `ManifestStaticFilesStorage` and
WhiteNoise's `CompressedManifestStaticFilesStorage` are not adopted until the constraints below are
resolved.

**What hashing actually does here — the failure is silent versioning, not a 404.** Django's hashed
storage writes *both* the original and the hashed name, and WhiteNoise keeps the originals by default
(`WHITENOISE_KEEP_ONLY_HASHED_FILES` defaults to `False`). So an unhashed request still resolves.
The consequence is subtler and worse for debugging:

`tap_viz`'s runtime is native ES modules importing each other by relative URL — for example
`tap_viz/static/tap_viz/js/runtime/projection.js:21`:

```js
import {loadLayoutModule} from "./layout-loader.js";
```

Django's manifest storages rewrite references in **CSS** (`@import`, `url()`) and source-map
comments; JavaScript `import` specifiers are covered only by an **experimental**, opt-in capability
requiring a storage subclass, off by default. Left off, the entry module reached through `{% static %}`
gets a hashed URL and is **cached forever** (WhiteNoise detects hashed names and sets immutable
caching), while every module it imports is served unhashed under `WHITENOISE_MAX_AGE` — 60 seconds by
default. The module graph is then versioned inconsistently: a permanently-cached entry point pulling
short-cached dependencies, with no mechanism ensuring a browser holds one coherent generation of the
runtime. That is the exact stale-module class `runserver_nocache` was written to escape, reintroduced
in production only.

It also arms a plausible future footgun: setting `WHITENOISE_KEEP_ONLY_HASHED_FILES=True` to halve
image size — a natural optimization with no obvious connection to this code — turns every one of
those imports into a 404.

**And the experimental rewriter would not be sufficient either.** This is the harder constraint:
`tap_viz/static/tap_viz/js/runtime/layout-loader.js` resolves a layout module's URL **at runtime from
grid data**. The projection definition stores the path in each elevation's `tap_layouts[i].js_file`;
`resolveLayoutUrl` turns it into a `/static/` URL and `loadLayoutModule` passes it to a dynamic
`import(url)`. No build-time rewriting can follow that, because the value does not exist at build
time — it is a property of the data, not of the source tree.

So the prohibition is a consequence of the projection system's design, not a preference about
cache-busting. The real problem to solve later is coherent module versioning; **import maps** are the
ecosystem's answer to the static half, and would still need a story for the data-resolved case. This
requirement exists so the manifest storage is not adopted as an apparently free upgrade.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-static-unhashed-1 | Non-Hashing Backend | Proposed | The configured staticfiles backend compresses without hashing filenames. | |
| req-tap-serving-static-unhashed-2 | Projections Load In Production | Proposed | With `DEBUG=false` against collected static, a `tap_viz` projection panel loads its runtime module graph and its data-resolved layout module. | The failure this prevents is silent |
| req-tap-serving-static-unhashed-3 | Coherent Module Generation | Proposed | No configuration serves part of the `tap_viz` module graph under immutable caching while serving the rest under a short max-age. | The versioning-split failure |

#### Future

- Coherent module versioning via import maps, including a strategy for the data-resolved layout URL.
  Until then static is served without long-lived cache headers, which is the deliberate trade.

### `DEBUG` Governs Error Presentation Only
----
RID: `req-tap-serving-debug-scope`

Status: `Proposed`

`DEBUG` controls whether the application renders detailed error pages. **No other behavior branches
on it.** Static serving, database connection lifetime, worker configuration and asset caching each
have their own named lever.

This is the spec's central structural rule. A single boolean standing in for "development versus
production" accumulates unrelated meanings until no one can predict what flipping it does — and in
this codebase it already had, twice, silently.

**The known coupling:** `DEBUG` is the reason assets reach browsers at all. The cost is that the
product cannot be hardened without being visibly broken.

**The one nobody had written down — `DEBUG` selects the authentication security posture.**
`tap_boot/orchestrator.py:267` calls:

```python
apply_auth_boot_section(profile.auth or {}, deploy=not settings.DEBUG, echo=say)
```

and `deploy` is what `tap_auth/boot.py:194` uses to choose the strict posture: live provider
self-tests and the Django deploy-security gate are **enforced, and a FAIL aborts boot**; a dev boot
relaxes both and logs instead. So the shipped default does not merely render friendlier error
pages — it decides whether authentication providers are actually proven at boot.

**This is also the explanation for tap#272**, which reports the deploy security-posture gate as
"mostly unreachable and impossible to pass." It is unreachable because `_check_deploy_posture` runs
only when `deploy=True`, which requires `DEBUG=False`, which nothing has ever set. A gate that cannot
execute is not a gate; it is a presence test that has never once been a correctness test. Landing
[`req-tap-serving-fail-closed`](#unsafe-configuration-has-no-default) is what makes that gate run for
the first time — and is why tap#272's second half, *impossible to pass*, has to be resolved in the
same wave rather than discovered afterwards.

Each lever therefore stands alone, so that a difference between environments is legible as itself.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-debug-scope-1 | Single Responsibility | Proposed | No setting or code path outside error presentation reads `DEBUG` to decide serving, static, or database behavior. | |
| req-tap-serving-debug-scope-2 | Flip Is Cosmetic | Proposed | Toggling `DEBUG` on a running configuration changes only error-page rendering; pages render styled and requests behave identically either way. | |
| req-tap-serving-debug-scope-3 | Auth Posture Named Separately | Proposed | The auth boot posture is selected by its own named setting, not by `DEBUG`. | `tap_boot/orchestrator.py:267` |

### The Dev/Prod Delta Is Enumerated
----
RID: `req-tap-serving-delta`

Status: `Proposed`

Development and production run the **same** serving stack. Everything that differs is in this table,
and nothing else does. Adding a row is a change to this spec, which is the point: the list stays
short because lengthening it costs something.

| | Development | Production |
| --- | --- | --- |
| Server | gunicorn, `--reload` | gunicorn |
| Static | WhiteNoise, finders + autorefresh | WhiteNoise over collected `STATIC_ROOT` |
| `DEBUG` | `true` | `false` |
| `TAP_DB_CONN_MAX_AGE` | `600` | `600` |

`TAP_DB_CONN_MAX_AGE` appears with the same value in both columns deliberately: it is listed because
it is a lever this spec governs, and its identical values are evidence that the parity goal is met
rather than asserted. Connection behavior is one of the things this spec exists to make the same
everywhere.

#### Status Details

The reloader is the known adoption risk. gunicorn's `--reload` watches Python source and is a
different reloader from the one several active session worktrees rely on daily. Editable plugin edits
already require a container restart, so that flow does not regress — but the change reaches every
session at once, and a serving change that degrades the inner loop will be worked around rather than
fixed. Run it on internal stacks before anything external depends on it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-delta-1 | Table Is Exhaustive | Proposed | Every configuration difference between the development and production serving profiles appears as a row in this table. | |
| req-tap-serving-delta-2 | Same Server Both Sides | Proposed | Both profiles run gunicorn serving the same WSGI application with the same worker class. | |

### Unsafe Configuration Has No Default
----
RID: `req-tap-serving-fail-closed`

Status: `Proposed`

Configuration that is unsafe when defaulted has **no default**. The artifact refuses to start and
names what is missing, rather than starting with a value that is present and wrong.

Currently:

- `tap/settings.py:49` — `DEBUG` defaults to `true`. An operator who sets nothing gets debug mode.
- `docker-compose.yml:166` — `SECRET_KEY: dev-secret-key-change-me`
- `docker-compose.yml:76` — `POSTGRES_PASSWORD: tap`
- `docker-compose.yml:165` — `DEBUG: "true"  # Enable debug mode (never in production!)`

Three shipped comments name the production requirement and three shipped values do not meet it. This
is the presence-is-not-correctness pattern in its purest form: a `SECRET_KEY` that exists and is
publicly known passes every check that asks whether a secret key is configured, and it is worse than
a missing one, because nobody goes looking for the thing the configuration says is handled. The
remedy order is derive, then verify, then detect; here the first applies — remove the second copy so
there is nothing to be wrong.

`DEBUG` therefore defaults to `false`, and development opts *in*.

**A correction worth recording, because the wrong version is widely believed and was written into
this epic's first draft:** `DEBUG=True` does **not** disable `ALLOWED_HOSTS` validation. Django
validates the host header either way; with `DEBUG=True` and `ALLOWED_HOSTS` empty, it substitutes a
permissive default (`.localhost`, `127.0.0.1`, `[::1]`). The real requirement is therefore that a
deployment *configures* its hostnames rather than inheriting the development default — not that
flipping `DEBUG` switches enforcement on.

#### Status Details

Sequenced strictly after [`req-tap-serving-static`](#static-assets-without-debug). Until WhiteNoise
and `collectstatic` are in place, setting `DEBUG=false` does not harden the product — it unstyles it.
Landing this first would produce a visibly broken instance and teach the wrong lesson.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-fail-closed-1 | Refuses To Start Unconfigured | Proposed | An artifact started with no `SECRET_KEY` and no database credentials exits non-zero naming the missing configuration, rather than starting. | |
| req-tap-serving-fail-closed-2 | DEBUG Defaults False | Proposed | With `DEBUG` unset, the application runs with debug mode off. | |
| req-tap-serving-fail-closed-3 | No Shipped Secret Literals | Proposed | No secret or credential literal is shipped in a published compose file or image layer as a working default. | |
| req-tap-serving-fail-closed-4 | Deploy Check Clean | Proposed | `manage.py check --deploy` passes, or every remaining warning is named with a recorded reason. | |
| req-tap-serving-fail-closed-5 | Hosts Configured For The Deployment | Proposed | `ALLOWED_HOSTS` names the hostnames the instance is actually reached by, including the labeled session URLs multi-session development depends on, and is not left to the debug-mode default. | `req-dev-multisession-browser-disambiguation` |

### Readiness Is Server-Independent
----
RID: `req-tap-serving-readiness`

Status: `Proposed`

"Ready" is defined by the artifact answering HTTP and reporting healthy — never by which server is
running or what its log lines say. Readiness probes must survive a server change without edits.

The spawn readiness poll (`scripts/spawn-session.sh:988-1019`) already satisfies this: it asks only
whether HTTP answers on the port. This requirement records that property as deliberate, so a future
probe is not written against a gunicorn startup string the way earlier ones were written against
`runserver`'s.

"Reporting healthy" is doing real work in that sentence: an HTTP response proves only that the web
server is alive, and the artifact runs a second process tree beside it. What the health surface must
distinguish, and what happens when either tree dies, is
[`req-tap-serving-process-failure`](#process-failure-is-visible).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-readiness-1 | Probe Survives Server Swap | Proposed | The readiness probe passes unchanged across the swap from `runserver` to gunicorn. | |
| req-tap-serving-readiness-2 | Liveness Is Not Inferred From HTTP | Proposed | The readiness surface reports on both process trees, not on the web server alone. | Detail in `req-tap-serving-process-failure` |

### A Table Cannot Exist Without Its Grant
----
RID: `req-tap-serving-grants`

Status: `Proposed`

The artifact must not begin serving in a state where a table exists but is invisible to the
least-privilege read role. Creating a table and granting `SELECT` on it to `tap_gryphon_ro` are one
operation, not two that happen to run in the same startup most of the time.

Today they are two, and they run at **different lifecycle points**:

- `migrate` creates the table, and runs on every container start.
- `manage.py boot`'s grid-infra phase (`tap_boot/orchestrator.py:270-292`) calls
  `provision_search_role()`, which reconciles the role's grants against the current registry. It runs
  at **spawn**, not at restart.

`scripts/dc restart web` runs the first and not the second. A table introduced by a migration during
a restart is therefore created and left dark: present, populated, and unreadable by every Gryphon
search and every panel that touches it. The failure is narrow and total — one page 500s with
`permission denied for table <x>` while every other page looks healthy — which is why it survives
undetected until someone opens the wrong page.

**Observed 2026-09-15 on the demo stack:** `github_core__collection_scope`, a table added by that
week's tiered-collection work, had no `tap_gryphon_ro` grant while all 26 sibling `github_core__*`
tables did. The batch viewer panel failed closed with `InsufficientPrivilege`
(`tap_web/panels/batch_viewer/__init__.py:40`). The panel behaved correctly; the grant was the bug.
The triggering restart was a repair for an unrelated fault — fixing one thing produced this one, with
no signal connecting them.

**The recovery is disproportionate, which is the deeper defect.** There is no narrow way to reconcile
grants: `tap_boot/management/commands/` offers `boot`, `cold_boot_gate` and `guards`, and nothing
else. Restoring one missing grant means either a full boot — which also runs population, unacceptable
mid-demo — or hand-calling `provision_search_role()` through a shell one-liner, which is not an
operator action. A recovery that costs more than the failure appears to is a recovery nobody performs
prophylactically.

**Remedy order, per the house rule.** Derive: bind reconciliation to migration itself (a `post_migrate`
hook) so a table cannot come into existence without its grant, removing the failure class. Failing
that, verify: a startup check that fails closed when a registry table lacks its grant, and a
`manage.py` verb that reconciles them so the recovery is one obvious command. Detection alone is the
last resort — it is what we have now, performed by a user hitting a 500.

#### Status Details

Folded into this spec by George's ruling (2026-09-15) rather than filed against tap#431 alone,
because it is a property of what must be true before the artifact serves. It gains urgency from
[`req-tap-serving-codespace`](#the-one-click-codespace-is-the-first-deployment): a Codespace installs
its plugins at container start, so it hits exactly the create-then-serve path where the grant gap
appears, in front of a visitor who has no way to diagnose it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-grants-1 | Grant Rides Creation | Proposed | A table created by a migration is readable by the search role without any further command being run. | The derive remedy |
| req-tap-serving-grants-2 | Restart Is Sufficient | Proposed | `scripts/dc restart web` against a branch carrying a new model leaves no registry table without its grant. | The exact 2026-09-15 path |
| req-tap-serving-grants-3 | Gap Fails Loudly | Proposed | If a registry table somehow lacks its grant, that is reported at startup rather than discovered by a user receiving a 500. | Three states: granted / ungranted / not applicable |

### Process Failure Is Visible
----
RID: `req-tap-serving-process-failure`

Status: `Proposed`

The container runs **two process trees** — the web server and the steady_queue supervisor — and the
artifact must state, and act on, what happens when either dies. An HTTP response establishes that the
web server is alive. It establishes nothing about collector health, and must never be read as though
it does.

The current shape makes silent half-failure the default: `docker/entrypoint.sh:219` backgrounds
`manage.py steady_queue` and the shell then `exec`s into the web server, replacing itself. Three
consequences follow, and all three are live today:

- The supervisor can die while the container stays up and healthy-looking, serving pages with nothing
  running collections. Nothing turns red.
- The `trap ... EXIT` intended to clean up the supervisor **cannot fire**, because `exec` replaces the
  shell that owns the trap — reported independently as tap#229. The graceful-shutdown path that does
  exist is therefore unreachable.
- Shutdown reaches the web server and not the supervisor, so a restart can leave queue work
  interrupted in ways nothing observes.

This is the three-states rule applied to processes: *serving and collecting*, *serving but not
collecting*, and *down* are three distinct states, and today the middle one is reported as the first.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-process-failure-1 | Supervisor Death Turns Readiness Red | Proposed | Killing the steady_queue supervisor causes the readiness surface to report unhealthy while the web server is still answering. | The silent half-failure |
| req-tap-serving-process-failure-2 | Web Death Ends The Container | Proposed | Death of the web server terminates the container rather than leaving an unreachable instance running. | |
| req-tap-serving-process-failure-3 | Shutdown Reaches Both Trees | Proposed | A stop signal reaches both the web server and the supervisor, and the supervisor drains rather than being killed outright. | Requires resolving tap#229 |

### Deployment Behind A Proxy
----
RID: `req-tap-serving-proxy`

Status: `Proposed`

A deployment reached over TLS terminates it in front of the artifact, and the artifact is configured
to trust that terminator and no one else: forwarded-protocol and forwarded-host headers honoured only
from the expected proxy, secure-cookie and HSTS settings on, and the deploy checks that verify all of
it actually passing.

This was initially scoped out of this spec on the grounds that no deployment has a proxy yet. That
was wrong in a specific and checkable way: two existing issues are already about this boundary and
both block any credible production claim.

- **tap#272** — the deploy security-posture gate is both mostly unreachable and impossible to pass.
- **tap#277** — the serving health probe reports unhealthy on any correctly-configured deployment.

A "production-grade serving" epic whose done-test is *a fresh install serves correctly* cannot be
satisfied while the gate that checks deployment posture cannot pass and the health probe fails on a
correct deployment. Those two are part of this boundary, not adjacent to it.

#### Status Details

Proposed, and deliberately not blocking the earlier requirements: the server swap and connection
budget are independently valuable and land first. This is what turns "runs under a real server" into
"can be exposed to a real network," and it is where the customer-facing claim actually rests.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-proxy-1 | Forwarded Headers Trusted Narrowly | Proposed | Protocol and host are taken from forwarded headers only when they arrive from the configured proxy; a client-supplied header does not change either. | |
| req-tap-serving-proxy-2 | Secure Cookies Under TLS | Proposed | Session and CSRF cookies are marked secure in a TLS deployment. | |
| req-tap-serving-proxy-3 | Posture Gate Passable | Proposed | The deploy security-posture gate is reachable and passes on a correctly-configured deployment. | Closes tap#272 |
| req-tap-serving-proxy-4 | Health Probe Correct Behind A Hostname | Proposed | The health probe reports healthy on a correctly-configured deployment reached by its deployment hostname. | Closes tap#277 |

### Durability Tuning Is Confined To Disposable Databases
----
RID: `req-tap-serving-durability`

Status: `Proposed`

Database settings that trade durability for speed apply **only** to databases that are expected to be
thrown away. They must not reach a deployment holding data anyone intends to keep.

The shipped base compose currently disables all three of PostgreSQL's crash-safety mechanisms
(`docker-compose.yml:45-55`):

```
-c fsync=off  -c synchronous_commit=off  -c full_page_writes=off
```

The accompanying comment is honest about the cost — an unclean shutdown can corrupt the cluster,
rebuild with `down -v` and re-seed — and reasons that CI replaces the command entirely, so "this base
tuning affects local stacks only." That reasoning holds for developers and **does not hold for a
product install**, which stands up its stack from this same compose file. Swapping the web server and
fixing the credentials leaves `fsync=off` exactly where it is, under a real database with a
customer's collected history in it.

This is the same shape as the shipped `SECRET_KEY`: a value that is correct for the environment it
was written for, inherited by an environment nobody re-read it against. The remedy is structural —
the disposable-database tuning belongs in a development overlay, so a durable deployment cannot
receive it by default.

Backup and restore are a separate concern and are **not** in this spec; this requirement only ensures
that a deployment is crash-safe enough for a backup to mean something.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-durability-1 | Durable By Default | Proposed | A stack stood up from the shipped configuration without a development overlay runs with `fsync`, `synchronous_commit` and `full_page_writes` at their safe defaults. | |
| req-tap-serving-durability-2 | Development Keeps Its Speed | Proposed | A development session stack still applies the fast, disposable tuning via an explicit overlay. | No inner-loop regression |

### The One-Click Codespace Is The First Deployment
----
RID: `req-tap-serving-codespace`

Status: `Proposed`

The first environment this spec is judged against is a **GitHub Codespace** launched from a public
repository by someone who is not us (`git-serious-tap#86`, `git-serious-friends` milestone). The
serving stack must be correct there before it is correct anywhere else, and this requirement exists
to record what that environment demands — so the ordering of everything above is driven by a real
deployment rather than by taste.

**What a Codespace imposes that a laptop does not:**

| Property of the environment | What it makes load-bearing |
| --- | --- |
| Port forwarding produces a generated `https://<name>-<port>.app.github.dev` origin, per Codespace | Hostname configuration cannot be a fixed list; `ALLOWED_HOSTS` and CSRF trusted origins must accommodate a hostname not known at build time — see [`req-tap-serving-fail-closed`](#unsafe-configuration-has-no-default) |
| GitHub terminates TLS in front of the container; the app sees plain HTTP | Forwarded-protocol trust and secure-cookie behavior — [`req-tap-serving-proxy`](#deployment-behind-a-proxy) — move to critical path, not Future |
| The health probe is reached by that deployment hostname | tap#277 (probe reports unhealthy on any correctly-configured deployment) blocks the done-test directly |
| Plugins install at container start, from a profile | [`req-tap-serving-static-plugins`](#plugin-assets-are-collected-after-plugin-install) must be resolved, and resolved *in favor of boot-time collection* — a Codespace builds no per-product image |
| The whole environment is disposable | [`req-tap-serving-durability`](#durability-tuning-is-confined-to-disposable-databases) is **satisfied by the development overlay here**; the durable-deployment case is not exercised by this target |
| A stranger is looking at it | `DEBUG=false` matters for the first time in earnest — a traceback page in front of a trial user leaks the environment and ends the trial |

**What this target does not settle.** Authentication is the open question and it is not this spec's
to answer: `git-serious-tap#86` records that passkeys cannot work on a Codespaces hostname, because a
forwarded port's origin differs per Codespace while the passkey RP ID is pinned to exactly one
origin. That is an auth-boundary problem, tracked there. This spec's obligation is narrower and must
not be confused with it: the serving layer must present a correct, trusted origin over TLS so that
whatever auth mechanism is chosen has a sound foundation to stand on.

#### Status Details

Proposed, and it is the pacing item rather than a deliverable of its own. It carries no
implementation separate from the requirements it prioritizes; its acceptance criteria are the
end-to-end proof that they hold together in the environment that matters.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-codespace-1 | Serves Correctly In A Codespace | Proposed | A Codespace launched from the public repo serves git-serious over its forwarded HTTPS origin with `DEBUG=false`, all core and plugin assets styled, and no manual configuration step. | The one-click claim |
| req-tap-serving-codespace-2 | Health Green Behind The Hostname | Proposed | The health and readiness surfaces report healthy when reached by the generated Codespace hostname. | Requires tap#277 |
| req-tap-serving-codespace-3 | Budget Holds On A Small Box | Proposed | The connection budget holds on Codespaces-class resources during a first collection run concurrent with a visitor navigating the UI. | The default machine is small; this is where an over-generous worker count bites |
| req-tap-serving-codespace-4 | No Secret Ships | Proposed | The Codespace generates or is provided its own `SECRET_KEY` and database credentials; no shipped default is in use. | |

#### Future

- A non-Codespace durable deployment, which is the first environment to exercise
  [`req-tap-serving-durability`](#durability-tuning-is-confined-to-disposable-databases) and backups
  in earnest.

## Out Of Scope (v0)

- **Horizontal scaling and multi-instance deployment.** The connection budget assumes one artifact
  against one database.
- **Connection pooling** (PgBouncer or in-process). The budget derivation is the v0 answer; pooling
  is the answer when the budget stops fitting, and it changes the arithmetic rather than removing it.
- **Static CDN offload.**
- **Backup, restore and disaster recovery.** [`req-tap-serving-durability`](#durability-tuning-is-confined-to-disposable-databases)
  ensures a deployment is crash-safe enough for a backup to be meaningful; producing and testing
  backups is a separate spec and a separate claim.
- **How an operator reaches a running instance** — `spec-product-install.md` owns that.

## Future

- Static cache-busting via import maps, including the data-resolved layout-module URL that no
  build-time rewriting can follow.
- An ASGI serving profile, if a requirement ever needs async concurrency. It re-opens the connection
  arithmetic in [`req-tap-serving-connection-budget`](#the-connection-budget-is-derived).
- Connection pooling, once the derived budget stops fitting a real deployment.
