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
nothing; `collectstatic` runs nowhere; and `DEBUG` defaults to `true`. None of
this was decided — it is the shape a project has before anyone writes the serving spec.

(All four have since been decided, in the wave that wrote this spec. The server is now gunicorn and
static is now WhiteNoise — see [`req-tap-serving-server`](#the-production-server) and
[`req-tap-serving-static`](#static-assets-without-debug). `collectstatic` still runs nowhere, but that
is now a ruling with a measurement behind it rather than an omission, which is the whole difference
this spec exists to make. And `DEBUG` now defaults to `false`, with `SECRET_KEY` and the database
credentials carrying no default at all — [`req-tap-serving-fail-closed`](#unsafe-configuration-has-no-default),
landed 2026-09-17 in tap#463.)

Two convictions shape every requirement below.

**The dev/prod delta is a short, named list — never a `DEBUG` branch.** Static serving used to be
*implicitly* coupled to `DEBUG`, because Django's `staticfiles` app serves assets from `runserver`
only in debug mode. That coupling is why `DEBUG=false` could not simply be set on the image: it did
not harden the product, it unstyled it. A single boolean standing in for "everything that
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
| req-tap-serving-server | [The Production Server](#the-production-server) | Implemented | gunicorn, sync workers, serving `tap.wsgi.application`; replaces `runserver` in every environment |
| req-tap-serving-budgets | [The Four Time Budgets](#the-four-time-budgets) | Implemented | Statement bound, worker watchdog, graceful drain, container stop allowance — one ordered policy; the watchdog derives from the statement bound |
| req-tap-serving-server-crypto | [The Server Introduces No Crypto Provider](#the-server-introduces-no-crypto-provider) | Proposed | Standing constraint on this and any future server swap; the deciding factor against granian |
| req-tap-serving-connection-budget | [The Connection Budget Is Derived](#the-connection-budget-is-derived) | Implemented | `max_connections` derived from worker count + queue threads + alias count; the behaviour under load is NOT OBSERVED |
| req-tap-serving-conn-max-age | [Persistent Connections Require Bounded Holders](#persistent-connections-require-bounded-holders) | Implemented | `TAP_DB_CONN_MAX_AGE`, default 0; the precondition is stated, not assumed |
| req-tap-serving-static | [Static Assets Without Debug](#static-assets-without-debug) | Implemented | WhiteNoise over the finders in BOTH environments; nothing is collected |
| req-tap-serving-static-plugins | [Plugin Assets Are Withdrawn From Collection](#plugin-assets-are-withdrawn-from-collection) | Retired | **Withdrawn, not resolved.** Its fork has no answer to get wrong once nothing is collected |
| req-tap-serving-static-unhashed | [Static Filenames Are Not Hashed](#static-filenames-are-not-hashed) | Implemented | Inconsistent module versioning, and a runtime-resolved import no build step can follow |
| req-tap-serving-debug-scope | [`DEBUG` Governs Error Presentation Only](#debug-governs-error-presentation-only) | Proposed | No behavior outside error rendering may branch on `DEBUG` |
| req-tap-serving-delta | [The Dev/Prod Delta Is Enumerated](#the-devprod-delta-is-enumerated) | Implemented | The delta is a table in this spec; adding to it is a spec change |
| req-tap-serving-fail-closed | [Unsafe Configuration Has No Default](#unsafe-configuration-has-no-default) | Implemented | `DEBUG` off by default; `SECRET_KEY` + DB credentials refuse to default; the container-level refusal is NOT OBSERVED |
| req-tap-serving-readiness | [Readiness Is Server-Independent](#readiness-is-server-independent) | Proposed | What "ready" means, and the relationship to the steady_queue supervisor |
| req-tap-serving-grants | [A Table Cannot Exist Without Its Grant](#a-table-cannot-exist-without-its-grant) | Proposed | tap#431; migration and grant reconciliation must be inseparable |
| req-tap-serving-process-failure | [Process Failure Is Visible](#process-failure-is-visible) | Proposed | Two process trees, one container; either dying must turn readiness red |
| req-tap-serving-proxy | [Deployment Behind A Proxy](#deployment-behind-a-proxy) | Proposed | TLS termination, trusted proxy headers, secure cookies; tap#272, tap#277 |
| req-tap-serving-durability | [Durability Tuning Is Confined To Disposable Databases](#durability-tuning-is-confined-to-disposable-databases) | Proposed | The shipped compose disables `fsync`; that must not reach a durable deployment |
| req-tap-serving-codespace | [The One-Click Codespace Is The First Deployment](#the-one-click-codespace-is-the-first-deployment) | Proposed | git-serious-tap#86; sets which requirements are critical path and which can wait |

### The Production Server
----
RID: `req-tap-serving-server`

Status: `Implemented`

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

`docker/entrypoint.sh` ends in `exec /app/.venv/bin/gunicorn --config
/app/docker/gunicorn.conf.py tap.wsgi:application`, replacing `exec uv run python manage.py
runserver_nocache 0.0.0.0:8000`. `exec` is deliberate: gunicorn *is* the container's process, so its
death ends the container rather than leaving an unreachable instance running
([`req-tap-serving-process-failure-2`](#process-failure-is-visible)).

The venv console script is invoked **directly**, not through `uv run`, and that distinction is
load-bearing rather than cosmetic. The `uv run` form shipped first (tap#502): `exec` replaced the
shell with `uv`, which forked gunicorn as a child, so PID 1 was `uv run`. PID 1 of a PID namespace
inherits every orphaned process and is the only thing that can reap one; `uv` does not reap, and
gunicorn's arbiter — which reaps any child, not only its own workers — was not PID 1 to receive
them. A 24-hour container accumulated 266 zombies out of 278 processes, all `PPid 1`, monotonic,
ending in PID-table exhaustion. Signal handling was *not* the broken half: the same measurement
showed `uv run` relaying `SIGTERM` and gunicorn shutting down gracefully well inside the grace
period, so what the direct `exec` buys is reaping. Nothing is lost by dropping the wrapper —
`uv sync --all-packages` and pre-boot's plugin installs have already populated this venv, and the
console script's shebang selects the venv interpreter unaided. `init: true` in Compose (tini as
PID 1) reaps correctly too and was rejected: it is a Compose-only declaration, so the published
image would remain broken under plain `docker run` or Kubernetes. The defect was in the image, so
the fix is in the image.

`docker/gunicorn.conf.py` holds the server configuration and reads every value from `tap/serving.py`,
a **settings-free, stdlib-only** module — the gunicorn master loads its config before `tap.wsgi`
imports Django, the same constraint `tap.preboot` lives under. Django settings read the *same*
functions, so the worker count in `settings.TAP_WEB_WORKERS` is the worker count gunicorn actually
forked, not a second copy of the default that can drift from it. That matters because it is an input
to [`req-tap-serving-connection-budget`](#the-connection-budget-is-derived): a budget derived from a
number nobody checked against the running process is not a budget.

Worker count is `TAP_WEB_WORKERS`, defaulting to **3** sync workers. Explicit, and explicitly not
`cpu_count()`-derived — a ceiling that moves with the host is not a ceiling. A non-integer or
non-positive value raises rather than falling back to the default: a typo must not silently become
the number the budget is computed from.

The profile is `TAP_SERVE_PROFILE` (`development` | `production`), defaulting to **production** when
unset — an operator who never heard of the variable gets no source-watching reloader. An
*unrecognised* value raises; coercing `dev` to production would take the reloader away with no
message. `docker-compose.yml` — the development stack — sets `development`.

`tap_grid/management/commands/runserver_nocache.py` **retired** under this requirement. It existed to
put `no-store` on static responses so a browser stops running stale JS; WhiteNoise's development mode
sets `max-age=0` for the same reason, so the command's job was absorbed rather than ported. Its
docstring already asserted the outcome this spec defines — *"production never runs this; it serves
static through a real web server with proper caching"* — a declaration that had never been true until
this change made it so.

**Fast-fail survived the swap, and was measured rather than assumed.** The concern was real:
gunicorn retries and backs off where `runserver` crash-loops, so an import error could have turned a
seconds-long abort into a 300s readiness timeout.

Two paths, both checked. The canonical failure — a core module reaching a plugin-only dependency —
is caught **upstream of the server**: `migrate` runs `django.setup()` behind the `TAP-ABORT` sentinel
and aborts before gunicorn is reached at all, exactly as before. For an error reachable *only* at WSGI
app load, a deliberate `ModuleNotFoundError` was appended to `tap/wsgi.py` and the stack restarted.
Gunicorn's arbiter does **not** retry: every worker exited with `WORKER_BOOT_ERROR`, `reap_workers()`
raised `HaltServer: <HaltServer 'Worker failed to boot.' 3>`, and the process exited, taking the
container with it. Wall clock from `Starting gunicorn` to exit was **~33 seconds**, essentially all of
it the worker importing Django and thirteen plugins before reaching the bad line.

One honest caveat, recorded so nobody rediscovers it under time pressure: this path emits **no
`TAP-ABORT:` line**, because `exec` has replaced the entrypoint shell that would print one. The spawn
watcher still fails fast on it — via its *other* fast-path, `web_container_dead_check`, which sees the
container exited or crash-looping (`scripts/spawn-session.sh` Step 5 check (b)) — rather than waiting
out the readiness timeout. It is caught by the second backstop, not the first.

#### Development

Coupling to `runserver` was verified to be shallow before this was written, and the swap confirmed it:
the only dependents were `docker/entrypoint.sh`; the spawn readiness poll at
`scripts/spawn-session.sh:988-1019`, which asks only whether HTTP answers on the port and is therefore
already server-agnostic (it passed unchanged — [`req-tap-serving-readiness-1`](#readiness-is-server-independent));
and a warm-up comment at `.github/workflows/api-fuzz.yml`.

The reloader is the part that had to be proven rather than reasoned about, because gunicorn's
`--reload` is a different implementation from `runserver`'s autoreloader and most session worktrees
run plugins installed **editable** from `_dev-plugins/`. gunicorn watches the files behind
`sys.modules`, which includes an editable plugin's source files, so an edit to plugin Python is picked
up on the next request. On macOS the bind mount does not deliver inotify events reliably, and
gunicorn's `auto` reloader engine falls back to polling `os.stat` — which works over a bind mount
precisely because it does not depend on the filesystem notifying anyone.

What the reloader does **not** cover is unchanged from before: the steady_queue supervisor forks its
workers from a boot-time memory image and does not reload, so collector and task code still needs a
container restart (`req-tap-cares-task-backend-deployment-3`).

**Measured, including the part that is not clean.** Eight edits to an editable-installed plugin module
across four runs: five produced a reload within one second, three produced none. The misses are not
random noise — in a controlled run of four edits spaced thirty seconds apart, the first and third
reloaded and the second and fourth did not, which is an alternation rather than a flake. The file's
mtime propagates into the container immediately (verified by `os.stat` from inside it), so the cause is
in gunicorn's poll reloader and its per-worker-generation mtime baseline, not in the bind mount. A
dropped edit means the code on disk is not the code running, which is precisely the silent class this
requirement's adoption risk is about. Filed as its own issue rather than worked around here; the
workaround until then is a second save or `scripts/dc restart web`. **tap#494.**

Reload teardown is also not free: most cycles complete in 4-9 seconds, but one took ~31 seconds and
ended with the arbiter sending `SIGABRT`. **tap#495.**

*Attribution corrected 2026-09-17 (the observation is unchanged; the cause named for it was wrong).*
That `SIGABRT` came from the **heartbeat watchdog**, `timeout` — not from `graceful_timeout`, which an
earlier version of this paragraph and of the config comment both blamed. Read from the pinned 23.0.0
source: `graceful_timeout` is used in exactly one place, `Arbiter.stop()` (~line 390), the master's own
shutdown, which a source reload never enters; `murder_workers()` (~line 497) compares
`now - worker.tmp.last_update()` against `self.timeout` (`= cfg.timeout`, line 101), logs
`WORKER TIMEOUT`, and sends `SIGABRT` (~line 505). The reloader thread inside the worker sets
`alive = False` and calls `sys.exit(0)` from a non-main thread (`workers/base.py`), which ends that
thread only — a worker whose main thread is blocked therefore stops heartbeating rather than exiting,
and the watchdog reaps it. The 31 seconds is `timeout=30` plus one arbiter poll: a fingerprint, not a
coincidence. **Consequence:** raising `timeout` raises that hang with it, and tuning `graceful_timeout`
cannot affect it at all.

#### Every Server Knob Is Chosen

`docker/gunicorn.conf.py` began by stating six things and leaving every other production-relevant knob
on a gunicorn default nobody had chosen (**tap#504**). A default is not neutral: `max_requests` at `0`
is *recycling disabled*, `max_requests_jitter` at `0` is *every worker recycles at the same instant*,
and `worker_tmp_dir` at `None` is *heartbeat onto whatever filesystem `/tmp` happens to be*. Each of
those is a decision; leaving it unstated only hides who made it.

So the file states every one of them, **including the values that keep gunicorn's default**, each with
the reason it is that value. Keeping a default and never mentioning it are different acts, and only one
of them survives review. None of these are dev/prod deltas — the delta remains the short enumerated
list in [`req-tap-serving-delta`](#the-devprod-delta-is-enumerated), and a test loads the config under
both profiles and asserts `reload` is the only setting that differs.

The values that carry a correctness argument, rather than a preference:

- **`timeout`** and **`graceful_timeout`** are two of the four time budgets and are specified
  together, below, in [`req-tap-serving-budgets`](#the-four-time-budgets). They are derived or
  authored there rather than chosen here, because neither means anything alone.
- **`max_requests = 5000` / `max_requests_jitter = 500`**. Recycling bounds a slow leak at a known
  request count. The number is reasoned from this application: an HTMX page view is many requests (one
  per panel), so the counter climbs fast, while a recycled worker pays a full cold import of Django and
  every plugin — with no `preload_app` to amortize it, in a 3-worker stack. Jitter is the correctness
  half: without it, workers forked together reach the count together and the stack briefly has no
  workers. The in-flight-connection report [benoitc/gunicorn#3038](https://github.com/benoitc/gunicorn/issues/3038)
  is filed against `gthread`; it was checked against the **sync** worker at the pinned 23.0.0 rather
  than assumed away — the sync worker flips `alive` inside `handle_request` and still completes that
  response, holds exactly one connection at a time, and leaves queued connections on the shared
  listening socket for its siblings.
- **`preload_app = False`**, stated precisely because it is already correct: it is incompatible with
  `--reload`, so the plausible future regression is someone enabling it as an optimization and silently
  taking the reloader away.
- **`keepalive = 2`** (the default), kept and **inert**: the sync worker calls `resp.force_close()` on
  every response, so it never keep-alives. It is written down so a future worker-class change inherits a
  chosen value rather than discovering one.
- **`limit_request_line` / `limit_request_fields` / `limit_request_field_size`** at their defaults —
  the request-parsing surface, where "unset" reads as "unbounded" to anyone auditing the file.
- **The parsing-strictness knobs** — `casefold_http_method`, `permit_unconventional_http_method`,
  `permit_unconventional_http_version`, `permit_obsolete_folding`, `strip_header_spaces`, `header_map`
  — all at their strict defaults, and stated because every one of them only travels in one direction:
  each loosens parsing, and each is a documented request-smuggling primitive when a proxy and an origin
  disagree about it. The risk is not that they are wrong today; it is that one gets turned on for a
  misbehaving client and never turned back. Stated, that is a visible diff.
- **`forwarded_allow_ips` / `proxy_protocol` / `proxy_allow_ips`**, pinned to loopback and off. This is
  the one place where stating a default CHANGES something: gunicorn's `forwarded_allow_ips` default is
  `os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1,::1")`, so proxy trust could be widened to `*` from
  outside this repository. Pinning it closes that lever, and it is what keeps `secure_scheme_headers`
  unreachable — `gunicorn/http/message.py` consults those headers only for a peer inside the list, and
  requests arrive here from the Docker bridge, not loopback. When a proxy does appear, these are among
  the values [`req-tap-serving-proxy`](#deployment-behind-a-proxy) requires to be set deliberately.

**A pinned value is worth nothing while one variable can restate all of them.** `GUNICORN_CMD_ARGS` is
the general case of the lever above, and it was found while this requirement was being written — the
config FILE is loaded first, then that variable is parsed and applied over it, then the command line
(`gunicorn/app/base.py` 23.0.0, `load_config()`). `--forwarded-allow-ips=*`, `--worker-class=gevent` or
`--timeout=5` in it therefore outrank every decision this file makes, *after* every check in it has
passed. Closing the specific lever while the general one stands would be the same failure one level up:
a control that exists, reads as effective, and is outranked. So the config file refuses to load at all
when `GUNICORN_CMD_ARGS` carries anything — at import, which is the last moment before gunicorn would
apply it. The named `TAP_*` levers remain the way to change a value from the environment, each with its
own validation; the generic one is not a lever, it is a bypass.

**"Every knob" is enumerated, not asserted.** The claim in this requirement's title is unfalsifiable on
its own: a reader cannot tell a setting that was considered and left alone from one nobody had heard of,
and a gunicorn upgrade that ADDS a setting changes behaviour with no diff in this repository. So
`docker/gunicorn.conf.py` carries `LIBRARY_DEFAULTS_ACKNOWLEDGED`, a map of every setting the file does
*not* assign, grouped by the reason its default stands — lifecycle hooks TAP defines none of; TLS, which
terminates outside the artifact; process identity and daemonization, which the container decides; knobs
meaningful only to worker classes [`req-tap-serving-server-2`](#the-production-server) forbids; logging
transport owned by `spec-tap-logging.md`; reloader tuning whose current engine is what was measured; and
the proxy headers made unreachable by the pin above. A test partitions gunicorn's own `KNOWN_SETTINGS`
registry — read from the installed package, not copied into the test — against the assignments plus that
map, and fails on a name in neither, on a name in both, and on an acknowledged name the library no longer
has. The map is not a claim that each default is *correct*; it is the record that each was *seen*.

**What the 26.2.0 upgrade added, and what was decided about it** (tap#585). Twenty-six settings arrived
across 24.x, 25.x and 26.2.0 and landed in this ratchet by name, which is the ratchet doing its job on
its first real firing. Bulk-acknowledging them was rejected: it would have waved through two surfaces
that are ON or auto-selected by default. Four decisions are worth carrying in the spec rather than only
in the file's comments:

- **The control socket is disabled.** gunicorn 25.1.0 added a runtime command channel and defaults it
  ON — a unix socket under `$XDG_RUNTIME_DIR` or `$HOME` (in this image, running as root with neither
  set, `/root/.gunicorn/gunicorn.ctl`), offering `worker add/remove/kill`, `reload`, `shutdown` and
  `show all/workers/config/stats/listeners` with no authentication beyond the file mode. Two reasons it
  is off: for anything already executing in the container as the same uid it is an unauthenticated
  shutdown switch, and `worker add` moves `workers` at runtime — the one input
  [`req-tap-serving-connection-budget`](#the-connection-budget-is-derived) is arithmetic on, and the
  same lever `GUNICORN_CMD_ARGS` is refused for. Its path is assigned anyway, inside the RAM-backed heartbeat
  directory, so that re-enabling it is a reviewed decision and not a single flag that lands a command
  socket in `$HOME` or — through gunicorn's relative-path resolution — in the source tree.
- **HTTP/2 stays off, and cleartext HTTP/2 explicitly so.** `http_protocols` is pinned to `h1` and
  `http2_cleartext` to `off`; the four `http2_*` resource bounds are stated at the specification's own
  values so a future engineer who turns h2 on inherits chosen limits (notably `http2_max_header_list_size`,
  where `0` means unlimited post-HPACK header bytes). h2c is gated on `forwarded_allow_ips`, the same
  list tap#503 is open about — which is the point of pinning it: widening proxy trust for the scheme
  header must not silently hand those peers a second protocol parser as well.
- **The parser is pinned to the pure-Python one.** `http_parser` defaults to `auto`, which selects a C
  extension if it happens to be importable — i.e. the component the five strictness flags above were
  reasoned against could be swapped by a transitive dependency. Pinning `python` forfeits throughput TAP
  does not currently need; moving to `fast` is legitimate, and must re-verify the strictness flags
  against the C parser as part of the change.
- **The ASGI and dirty-arbiter families are acknowledged as groups**, with one honest reason each: both
  belong to concurrency models TAP does not run — a sync worker has no event loop, and long-blocking
  work is Django Tasks under the steady_queue supervisor, not a second in-container process tree. Note
  what makes the dirty-arbiter acknowledgement safe: `dirty_workers` DEFAULTING to `0`. That is a value,
  which is why the next paragraph exists.

**The acknowledged defaults are compared as values, not only as names** (tap#542, closed by the 26.2.0
upgrade). The name partition above passes unchanged when a release keeps a setting's name and moves the
default underneath it — which across 23.0.0 → 26.2.0 was not hypothetical: `proxy_protocol`'s default
moved from `False` to `"off"` when 24.1.0 turned a boolean into a version selector. So the file also
carries `LIBRARY_DEFAULTS_OBSERVED`, the default *value* of every acknowledged setting as read from the
installed package, and a test compares the two. Two properties make that a check rather than a second
copy of upstream: the recorded values are REGENERATED from the installed registry (the failing test
prints the block to paste), so no one transcribes a changelog into them; and the exclusions are derived
the same way rather than hand-listed — the test loads a private second copy of `gunicorn.config` under a
perturbed ambient context (scrubbed environment, fake cwd, fake euid/gid, fake `sys.platform`) and
excludes, by observation, any default that moves, alongside callables and values whose `repr` does not
round-trip. Those exclusions are themselves recorded in `LIBRARY_DEFAULTS_NOT_COMPARED` with the rule
that produced each, so an acknowledged setting is compared or explained, never silently absent: three
states, never two. Today that is 54 compared and 26 not (`chdir`, `user`, `group`, `syslog_addr`, the
hook callables, and the two `ssl` enums). What it still does not assert is that a default is *correct* —
it is the record that the value was seen, one level below the record that the name was.

One limit of the ratchet remains, stated rather than left to be assumed away: it binds the config file,
not the command line. gunicorn
applies CLI arguments after everything, so a launcher that appended flags would outrank this file the way
`GUNICORN_CMD_ARGS` would. `docker/entrypoint.sh` execs a fixed command line with no passthrough
(`exec /app/.venv/bin/gunicorn --config /app/docker/gunicorn.conf.py tap.wsgi:application`) and compose
declares no `command:` for the `web` service, so there is nothing to append through today; keeping it
that way is the entrypoint's contract, not this file's.

**The heartbeat directory is RAM-backed, and its absence is loud.** Every worker rewrites a heartbeat
file's mtime (`os.utime` on an open fd, 23.0.0) and the arbiter stats it to decide the worker is alive.
Read from `/proc/mounts` inside a running web container: there is no separate tmpfs for `/tmp`, so the
default puts that file on the disk-backed overlay root. `worker_tmp_dir` therefore points at a dedicated
tmpfs mount — **not** `/dev/shm`, which is POSIX shared memory's namespace with a 64MB budget shared
with any other consumer; the heartbeat file is created and immediately unlinked, so it needs no budget
at all, it needs a RAM-backed directory that is ours. The mount declares an explicit size (a `tmpfs:`
entry without one defaults to half of host RAM), and the path is authored once in `tap/serving.py` with
a test verifying the compose mount target against that constant rather than trusting two copies to stay
equal.

`tap.serving.worker_tmp_dir()` refuses at config-load time. gunicorn would refuse a missing directory
too, but only when the first worker forks; moving the refusal earlier attaches a message naming what to
mount. Failing closed is the point — the alternative is serving with the heartbeat silently back on
disk, a configuration that reads as fixed and is not.

**Existence is not the property, so existence is not what is checked.** A directory that exists passes a
presence check while sitting on the very overlay this setting exists to leave, and the operator lever
`TAP_WORKER_TMP_DIR` puts that one environment variable away — a deployment that looks configured and is
exactly what the configuration was added to prevent. The filesystem type is therefore verified against
its source (`/proc/self/mountinfo`, longest containing mount) and reported in three states, never two:
RAM-backed (`tmpfs`/`ramfs`) proceeds; an observably disk-backed filesystem refuses; a filesystem that
cannot be observed at all (no readable `/proc/self/mountinfo`) proceeds with a note on stderr, because
absence of evidence must not render as evidence of a disk. That third row is a **proceed**, so this check
is fail-closed on what it can see rather than across all three states — a runtime that masks `/proc`
could walk a disk-backed directory through it. Said here rather than left for a reader to infer from the
code; whether it should refuse instead is an open decision, tracked as tap#533.

**Honest limit, stated rather than implied:** the tmpfs is declared in `docker-compose.yml`, which is
the only way this image is started today (dev sessions, the spawn lifecycle, and the CI boot and test
lanes all go through it). A runtime that does not use that compose file — a bare `docker run`, a future
Kubernetes manifest — does **not** get the mount, and will refuse to boot with a message saying so. That
is deliberate rather than complete: it is loud instead of silently disk-backed, and the operator lever
(`TAP_WORKER_TMP_DIR`) exists, but the declaration is not yet carried by the artifact itself. Tracked in
tap#517.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-server-1 | WSGI Application Served | Implemented | The running artifact serves `tap.wsgi.application` under gunicorn; no environment invokes `runserver` or `runserver_nocache`. | |
| req-tap-serving-server-2 | Sync Worker Class | Implemented | The configured worker class is the sync worker; an async or gevent worker class fails the check that guards the connection budget. | Pairs with `req-tap-serving-connection-budget-2` |
| req-tap-serving-server-3 | Worker Count Is Explicit | Implemented | Worker count is set by named configuration and readable at runtime; it is not left to a library default. | Input to the budget derivation |
| req-tap-serving-server-4 | No-Cache Command Retired | Implemented | `runserver_nocache` is removed, and editing a static asset in a development worktree still serves the new bytes on refresh. | |
| req-tap-serving-server-5 | Every Server Knob Is Chosen | Implemented | Every production-relevant gunicorn setting is stated with the reason for its value, including values that keep gunicorn's default; the worker heartbeat directory is RAM-backed and refuses to start when its mount is absent. | tap#504 |

#### Future

- Front-proxy posture (TLS termination, `SECURE_PROXY_SSL_HEADER`, real client IP) is deliberately
  out of scope until there is a deployment with a proxy in front of it. Named here so its absence is
  a decision rather than an oversight.
- Graceful-restart semantics and their interaction with the steady_queue supervisor's shutdown path
  (see tap#229, which reports the entrypoint's `EXIT` trap cannot fire) belong to a later pass.

### The Four Time Budgets
----
RID: `req-tap-serving-budgets`

Status: `Implemented`

A request's life is governed by four timers owned by four different layers. They were each picked in
isolation — one of them by Docker, on TAP's behalf, without anyone noticing — and a set of timers
picked in isolation is not a policy. Stated here once, in the order they bite:

| # | Budget | Owner | Value | What it bounds |
| :---: | --- | --- | :---: | --- |
| 1 | Statement bound | PostgreSQL `statement_timeout` | `30s` | A single SQL statement on the search connection |
| 2 | Worker heartbeat watchdog | gunicorn `timeout` | **derived**, `60` today | How long a worker may be silent before the arbiter SIGABRTs it |
| 3 | Graceful drain | gunicorn `graceful_timeout` | `20` | How long in-flight work gets after the **master** is told to stop |
| 4 | Container stop allowance | compose `stop_grace_period` | `30s` | How long Docker waits after SIGTERM before SIGKILL |

**Budget 1 is per STATEMENT, and that is not a request policy.** This is the premise an earlier draft
of this spec got wrong, and the error is worth keeping visible because it is the shape that recurs: a
bound that exists, is real, and does not bound the thing the reader assumed. A single graph response
issues at least three statements — the Gryphon path query, the `Entity` bulk fetch, the `Edge` bulk
fetch (`tap_grid/gryphon/executor.py`) — and `statement_timeout` applies to each. The database-side
ceiling on one response is therefore *at least* three times the bound, not equal to it.

**TAP has no whole-request budget.** Stated plainly rather than implied by the timers. Sizing budget 2
for the worst case would require knowing how many statements a view issues; that number is not knowable
across views and grows with every panel. A watchdog large enough for an unbounded statement count
detects nothing, which is the only thing a watchdog is for. So budget 2 is sized for *one slow
statement plus overhead*, and a request that exceeds it is killed by the watchdog — a worker restart,
not a clean 500. That residue is tracked as **tap#530**, not papered over here.

**Budget 2 is derived from budget 1, so the two cannot disagree.** `tap.serving.worker_timeout()`
returns `statement_timeout + REQUEST_OVERHEAD_HEADROOM_SECONDS` (30s: connection acquisition, the other
statements, serialization, rendering). `tap/settings.py` reads the statement bound from the *same*
function, so there is one authored value with two readers rather than two values free to drift — the
failure being closed is an operator raising `TAP_SEARCH_STATEMENT_TIMEOUT` and silently invalidating a
fixed gunicorn timeout derived from its old value. `TAP_WEB_TIMEOUT` remains as an explicit override,
but it is **verified** against budget 1 rather than trusted: a value that does not exceed the statement
bound is refused, because it would recreate exactly the disagreement the derivation removes. A disabled
statement bound (PostgreSQL's `0`) leaves nothing to derive from and refuses rather than guessing.

**Budget 2 is a liveness watchdog that doubles as a request deadline — because of the worker class.**
The arbiter compares `now - worker.tmp.last_update()` against `cfg.timeout` and sends `SIGABRT` past it
(`gunicorn/arbiter.py` 23.0.0, `murder_workers`). A sync worker heartbeats at the top of its accept
loop — *between* requests, not during one (`workers/sync.py`) — so a long request is indistinguishable
from a wedged worker. That coupling is why a database number is an input to a liveness timer at all,
and it would break in both directions under a different worker class.

**`graceful_timeout` does not govern source reload, and never did.** It is read in exactly one place,
`Arbiter.stop()` (~line 390), the master's own shutdown. A source reload does not enter `stop()`: the
reloader thread inside the worker sets `alive = False` and calls `sys.exit(0)` from a non-main thread
(`workers/base.py`), ending that thread only; a worker whose main thread is blocked stops heartbeating
and is reaped by budget 2. The `SIGABRT` recorded in **tap#495** therefore came from the watchdog, and
the ~31s it took is `timeout=30` plus one arbiter poll. The correction matters more than the number:
tuning budget 3 to address tap#495 would tune a knob connected to nothing, and raising budget 2 — as
this spec now does — makes that hang longer, which is a cost accepted deliberately rather than a
side-effect discovered later.

**A shutdown may interrupt a request that was permitted to run.** Budget 3 (20s) is deliberately
*shorter* than budget 2 (60s), so the ordering is an explicit decision, not an accident of numbers:
a restart must not wait out a pathological request. The v0 request path is overwhelmingly read-only;
writes go through the service layer in short transactions, and a connection lost mid-transaction is
rolled back by PostgreSQL rather than left half-applied. The cost is a dropped response, not a corrupt
grid. If that ever stops being true — a long write path, a streaming export — this ordering is the
thing to revisit first.

**Budget 4 must exceed budget 3, or budget 3 is fiction.** Until this requirement landed, the compose
`web` service declared no `stop_grace_period`, so Docker's 10-second default truncated a 30-second
drain: the drain could never have run to completion, and nothing said so. It is now `30s` — the 20s
drain plus 10s of headroom for the master's post-drain work (SIGKILLing whatever the drain did not
retire, closing listeners, exiting) — authored in `tap/serving.py` with the compose copy verified
against it by a test.

**Signal delivery is OBSERVED, and it works.** An earlier draft of this section listed it as an open
question owned by tap#502. That is now answered, and answered the other way: measuring the container
under [`req-tap-serving-process-failure`](#process-failure-is-visible), a SIGTERM produced
`Handling signal: term`, three clean `Worker exiting` lines, master shutdown and exit 0 in **2.3
seconds** through the old `uv run` wrapper, and **1.37 seconds** with the arbiter exec'd as PID 1. What
tap#502 fixed was orphan *reaping*; shutdown was never the broken half. So budget 4 is a ceiling rather
than a cost — observed shutdowns finish in under two seconds, and the allowance binds only when a
request is still draining. It is also **not** a wait for the entrypoint's `trap ... EXIT` on the
steady_queue supervisor: `exec` has replaced that shell by then, so the trap cannot fire (tap#229), and
those processes end with the container rather than through a teardown this budget waits on.

**What is NOT observed.** Every assertion behind this requirement compares *configuration values*. No
test drives a slow request, a reload, or a shutdown, so the lifecycle behaviour these budgets are meant
to produce is **not observed** — only the coherence of the numbers is. Specifically still unobserved:
a shutdown with a long request actually IN FLIGHT (the measurements above were of an idle server, which
is the easy case and says nothing about the drain interrupting work); a request exceeding budget 2 being
killed by the watchdog; and the effect of budget 2 on tap#495's hang, which is inferred from the pinned
source rather than measured on a running stack.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-budgets-1 | Watchdog Derives From The Statement Bound | Implemented | gunicorn's `timeout` is computed from the configured `statement_timeout` rather than authored independently; an explicit override that does not exceed the statement bound is refused, and a disabled or unparseable bound refuses rather than falling back. | Config-value assertions only; lifecycle NOT OBSERVED |
| req-tap-serving-budgets-2 | Shutdown Budgets Are Ordered | Implemented | The container stop allowance exceeds the graceful drain, and the drain is shorter than the watchdog by decision; the compose declaration is verified against the authored constant. | Docker's 10s default previously truncated the drain |

#### Future

- A whole-request budget, or a recorded decision to decline one with the watchdog as the named
  backstop (**tap#530**).
- Observing the budgets rather than asserting them: a test that drives a request past the watchdog and
  a shutdown past the drain, on a running stack, is the only thing that turns these numbers from
  coherent into correct.

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

Status: `Implemented`

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

#### Implementation

`tap.serving.connection_budget()` (tap#463). Every term is a named constant multiplied by the
others — the running gunicorn worker count (the same `worker_count()` the gunicorn master reads),
steady_queue's processes/dispatchers/threads, the alias count from `tap.db_aliases.ALL_ALIASES`, a
restart-overlap factor of 2, and a named admin-session allowance. `tap/settings.py` builds
`STEADY_QUEUE` FROM those thread constants rather than typing them a second time, so raising a
queue's threads raises the derived ceiling with it.

YAML cannot import Python, so the computed value is declared in `docker-compose.yml` and
`docker-compose.ci.yml` and VERIFIED against the derivation by `tap/tests/test_connection_budget.py`
— the same declare-and-check shape as the gunicorn heartbeat mount and the container stop allowance.
Both files, because the CI overlay replaces the base `command:`, and a ceiling set in only one of
them would leave CI running on the default the 2026-09-15 incident hit.

Two numbers fall out, and the difference between them is deliberate: the serving budget (54 at the
current configuration) and the DEVELOPMENT budget (150), which adds the pytest-xdist lane. The test
harness is a property of the development cluster, not of the product, so a deployment's ceiling is
not quietly inflated by it.

#### Status Details

The *shape* was settled before; what this closes is the derivation and its verification. Two terms
remain chosen rather than measured — the admin-session headroom and the upper bound on xdist workers
— and both are named constants with the reasoning beside them rather than numbers in a compose file.

**NOT OBSERVED:** that a running instance stays under the ceiling
([`-2`](#the-connection-budget-is-derived)) and that a rolling restart survives ([`-4`](#the-connection-budget-is-derived)).
Both need a loaded instance; neither is exercised by anything in the suite. A derived ceiling is
arithmetic about demand, not evidence about behaviour, and must not be read as the second thing.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-connection-budget-1 | Ceiling Derived From Threads | Implemented | `max_connections` is computed in one place from the configured gunicorn worker count, the steady_queue worker/thread configuration, and the alias count — not set as an independent literal. | Derive-a-fact-once; the alias count is asserted against the configured alias set |
| req-tap-serving-connection-budget-2 | Budget Holds Under Combined Load | Proposed | Under sustained page navigation **concurrent with a collection run**, `count(*) FROM pg_stat_activity WHERE backend_type='client backend'` stays below the derived ceiling and does not grow monotonically. | The 2026-09-15 signature; NOT OBSERVED — needs a loaded instance |
| req-tap-serving-connection-budget-3 | Queue Threads Counted | Implemented | The derivation reads steady_queue's per-worker `threads` values; changing `threads=3` to another value changes the computed ceiling. | Guards the per-process undercount; settings builds the queue from the same constants |
| req-tap-serving-connection-budget-4 | Restart Overlap Survives | Proposed | A rolling restart under load does not exhaust connections while old and new workers coexist. | The factor of 2 is in the derivation; the survival is NOT OBSERVED |

### Persistent Connections Require Bounded Holders
----
RID: `req-tap-serving-conn-max-age`

Status: `Implemented`

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

**The profile now opts in** (tap#462). `docker/entrypoint.sh` exports `TAP_DB_CONN_MAX_AGE=600`
immediately before it starts the two process trees, because that is the point at which the
precondition becomes true and not one line earlier. Both trees are bounded: gunicorn runs a fixed
count of sync workers, each holding one connection per alias while it handles its one request, and the
steady_queue supervisor forks one worker per declared `Configuration.Worker`. Neither grows with load.

The default in `tap/settings.py` stays `0`, and that is not a leftover. An artifact started some other
way — a management command, a test runner, a future serving mode — has made no claim about how many
holders it can produce, and must not inherit a lifetime that is only safe under one. The opt-in lives
with the thing that makes it safe. `:-` on the export leaves an operator free to override it, including
back to `0`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-conn-max-age-1 | Configurable, Default Zero | Implemented | `TAP_DB_CONN_MAX_AGE` governs `conn_max_age` for every alias and defaults to `0`. | |
| req-tap-serving-conn-max-age-2 | Not Derived From DEBUG | Implemented | No code path sets connection lifetime from `DEBUG`. | |
| req-tap-serving-conn-max-age-3 | Precondition Recorded | Implemented | The setting's comment states that a positive lifetime requires a bounded number of connection-holding processes. | Prevents silent reintroduction |

### Static Assets Without Debug
----
RID: `req-tap-serving-static`

Status: `Implemented`

Static assets are served by **WhiteNoise over Django's staticfiles finders**, in both environments,
independent of `DEBUG`. **Nothing is collected** — there is no `collectstatic` step at image build, at
container start, or anywhere else.

One mode, both sides. The delta is two cache-header values:

- **Both:** `WHITENOISE_USE_FINDERS = True`. WhiteNoise resolves each request through the same finders
  Django uses, serving files from their original locations in the source tree and in every installed
  plugin package. Finders mode is explicitly supported in production by WhiteNoise; it is not a
  development affordance being pressed into service.
- **Development:** `WHITENOISE_AUTOREFRESH = True` and `max-age=0`. A CSS or JS edit in a mounted
  plugin worktree is visible on refresh with no `collectstatic` and no container restart, and the
  browser never runs a stale ES module.
- **Production:** autorefresh off — the finder index is built once at startup — and `max-age=60`.
  Short, because filenames are unhashed ([`req-tap-serving-static-unhashed`](#static-filenames-are-not-hashed)).

**Why nothing is collected** (ruled 2026-09-16, superseding a "collect at boot" ruling from the same
day). WhiteNoise's documented trade for finders mode is losing the storage backends' **caching and
compression**. The caching half was *already* forfeited by
[`req-tap-serving-static-unhashed`](#static-filenames-are-not-hashed) — `tap_viz` imports ES modules
by relative URL and resolves one module URL from grid data, which no build step can rewrite. So
collecting would buy exactly one thing: pre-compressed files. Measured rather than argued — all JS and
CSS across core and every installed plugin is **660K**, the largest single asset 52K
(`tap_viz/js/panel-graph.js`, which gzips 49,293 → 12,965 bytes). A real ratio on trivial absolute
stakes, and on the Codespace target GitHub's proxy terminates TLS in front of the container and
compresses on its own.

Against that: a step on every container start, and a **writable `STATIC_ROOT`**, which forecloses a
read-only root filesystem. Cheap to add the day there is a demand signal — a CDN, or assets that
actually grow. Not cheap to carry now, for 660K.

`STATIC_ROOT` is therefore `None`, Django's own "not set", rather than a path that is declared and
never populated. The declared-but-empty form is the presence-not-correctness shape: it reads as
"assets are collected here", `collectstatic` appears to honour it, and WhiteNoise warns about the
missing directory on every production start.

Before this change neither half existed. `collectstatic` ran nowhere, `STATIC_ROOT` was declared and
never populated, and there was no WhiteNoise dependency; assets reached the browser solely because
Django's `staticfiles` app serves them from `runserver` when `DEBUG` is true. That coupling is what
made the product structurally dependent on debug mode to render itself, and removing it is the
precondition for [`req-tap-serving-fail-closed`](#unsafe-configuration-has-no-default).

Preserving the development inner loop was a first-class constraint, not a concession: several session
worktrees edit plugin templates, CSS and JS continuously, and a serving change that inserted a build
step into that cycle would be worked around rather than adopted. Removing collection entirely is the
strongest possible form of that guarantee — there is no build step to work around.

#### Implementation

`whitenoise.middleware.WhiteNoiseMiddleware` sits directly after `SecurityMiddleware` (WhiteNoise's
own contract) and — the part that matters here — **before** the default-deny login wall
(`tap_auth.middleware.TapLoginRequiredMiddleware`). Static is served without ever reaching
authorization, by construction, rather than by an exempt-prefix list that has to stay correct.

All three WhiteNoise knobs are declared **explicitly** in `tap/settings.py`, including where the value
matches WhiteNoise's own default. WhiteNoise resolves `autorefresh`, `max_age` and `use_finders` from
`settings.DEBUG` when they are absent; leaving any of them unset would rebuild the exact coupling this
spec exists to remove, one layer down, inside a dependency
([`req-tap-serving-debug-scope`](#debug-governs-error-presentation-only)).

The `[brotli]` extra is deliberately **not** installed
([`req-tap-serving-server-crypto-2`](#the-server-introduces-no-crypto-provider)).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-static-1 | Styled With DEBUG Off | Implemented | With `DEBUG=false`, every page renders with its CSS and JS loaded, including plugin-shipped assets. | The test that had never been run |
| req-tap-serving-static-2 | Live Edit Preserved | Implemented | Editing a plugin static asset in a mounted worktree is served on the next refresh with no `collectstatic` and no container restart. | Inner-loop guard |
| req-tap-serving-static-3 | No Stale Modules In Dev | Implemented | Development static responses carry `max-age=0`. | Absorbs `runserver_nocache`'s job |

### Plugin Assets Are Withdrawn From Collection
----
RID: `req-tap-serving-static-plugins`

Status: `Retired`

**Withdrawn, not resolved** (2026-09-16). This requirement existed to answer one question — *when*
does `collectstatic` run, given that plugins install at container start and not at image build? The
answer to a question is not the only way to remove it. [`req-tap-serving-static`](#static-assets-without-debug)
removed it by never collecting at all: **a fork with no answer to get wrong.**

It is kept, retired, rather than deleted, because the analysis under it is the reason the withdrawal is
safe — and because someone will propose collection again the first time compression looks free.

#### The question it asked

Static collection must happen where **the full plugin set is present**. Collecting at image build does
not satisfy that. Plugins are not baked into the image: the entrypoint resolves a boot profile and
installs that profile's plugins at container start (`docker/entrypoint.sh`, via `tap.preboot`), which
is what allows one image to serve git-serious, zizmor or a customer's own plugin set. A `collectstatic`
executed during `docker build` therefore sees core assets only — `tap_web`, `tap_viz` — and none of the
plugin assets every product page depends on. The gap is invisible in development, where finders serve
from source. The epic had assumed **both models at once**: a build-time collect against a boot-time
plugin install. That could not hold.

#### The options, and what happened to them

| Option | Consequence | Disposition |
| --- | --- | --- |
| **Collect at boot**, after pre-boot plugin install, before the server starts | One image serves any plugin set. Adds work to every container start and needs a writable `STATIC_ROOT`, which forecloses a read-only root filesystem. | Ruled, then **superseded the same day**. It was the right answer to the wrong question: it designed around the writable-`STATIC_ROOT` objection instead of asking whether collection was needed. |
| **Build per-product images** with the plugin set baked in | Collection returns to build time; the artifact is fully immutable; start-up stays fast. Abandons one-image-many-profiles and multiplies what must be published, signed and scanned. | **Rejected.** It cannot serve the target: `git-serious-tap#86`, the one-click Codespace, builds no image at all — a visitor clicks Create, the container comes up from the published image and installs plugins from the profile. There is no build step for a per-product collect to run in. |
| **Collect nothing** — WhiteNoise finders in both environments | Assets transfer uncompressed unless something in front compresses them. | **Chosen**, under [`req-tap-serving-static`](#static-assets-without-debug), which carries the measurement. |

One property survives all three and is now load-bearing rather than incidental: **one published image
serves any plugin set, selected by a boot profile at container start.** A future change that breaks it
breaks the Codespace path.

#### Acceptance Criteria

The criteria below are retired with the requirement: two of them presuppose a collected tree that no
longer exists, and the third — "the chosen model is recorded" — is satisfied by this section itself.
The property they were protecting, *a plugin-owned page renders its own plugin's CSS and JS in the
production profile*, did not retire with them; it moved to
[`req-tap-serving-static-1`](#static-assets-without-debug), where finders make it true for the same
reason in both environments.

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-static-plugins-1 | Collection Sees Every Plugin | Retired | In the shipped configuration, collected static contains the assets of every plugin in the booted profile. | Nothing is collected |
| req-tap-serving-static-plugins-2 | Plugin Page Styled In Production | Retired | With `DEBUG=false`, a plugin-owned page renders with its own plugin's CSS and JS, not merely core assets. | Re-homed to `req-tap-serving-static-1` |
| req-tap-serving-static-plugins-3 | Model Recorded | Retired | The chosen model is stated in this requirement with its rationale, and the rejected option is recorded. | Satisfied above |

### Static Filenames Are Not Hashed
----
RID: `req-tap-serving-static-unhashed`

Status: `Implemented`

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

#### Implementation

Satisfied structurally rather than by configuration. `STORAGES["staticfiles"]` is Django's plain
`StaticFilesStorage`, which does not hash, and there is no collected tree for a manifest backend to
be pointed at ([`req-tap-serving-static`](#static-assets-without-debug)) — so the manifest storages
cannot be adopted as an apparently free upgrade without first re-opening the collection decision,
where this analysis lives.

WhiteNoise's `immutable_file_test` looks for a content hash in the filename and finds none, so every
asset is served under the same short `max-age`. The module graph is therefore coherent by
construction: there is no configuration in which the entry module is cached forever while its imports
are cached for a minute.

The compression half of the original wording is deliberately gone: nothing compresses at rest, because
nothing is collected. The 660K measurement behind that is in
[`req-tap-serving-static`](#static-assets-without-debug).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-static-unhashed-1 | Non-Hashing Backend | Implemented | The configured staticfiles backend does not hash filenames. | Compression dropped from the wording: nothing is collected |
| req-tap-serving-static-unhashed-2 | Projections Load In Production | Implemented | In the production serving profile, a `tap_viz` projection panel loads its runtime module graph and its data-resolved layout module. | The failure this prevents is silent |
| req-tap-serving-static-unhashed-3 | Coherent Module Generation | Implemented | No configuration serves part of the `tap_viz` module graph under immutable caching while serving the rest under a short max-age. | The versioning-split failure |

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

**The known coupling — CUT, 2026-09-16 (tap#462).** `DEBUG` used to be the reason assets reached
browsers at all, so the product could not be hardened without being visibly broken. WhiteNoise now
serves static in both profiles ([`req-tap-serving-static`](#static-assets-without-debug)), the page
`no-store` middleware keys off `TAP_SERVE_PROFILE`, and each of WhiteNoise's own `DEBUG`-derived
defaults is overridden explicitly so the coupling cannot re-enter through a dependency. The remaining
coupling is the auth-posture one below, which is the harder half.

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

Status: `Implemented`

Development and production run the **same** serving stack. Everything that differs is in this table,
and nothing else does. Adding a row is a change to this spec, which is the point: the list stays
short because lengthening it costs something.

The column is selected by **`TAP_SERVE_PROFILE`** (`development` | `production`), a named setting that
exists only to pick a column. Unset means production. It is deliberately not `DEBUG`
([`req-tap-serving-debug-scope`](#debug-governs-error-presentation-only)).

| | Development | Production |
| --- | --- | --- |
| `TAP_SERVE_PROFILE` | `development` (set by `docker-compose.yml`) | `production` (the unset default) |
| Server | gunicorn, sync workers, `tap.wsgi:application`, `reload = True` | gunicorn, sync workers, `tap.wsgi:application` |
| Workers | `TAP_WEB_WORKERS`, default `3` | `TAP_WEB_WORKERS`, default `3` |
| Static | WhiteNoise, finders, **autorefresh** | WhiteNoise, finders |
| Static cache | `max-age=0` | `max-age=60` |
| Page cache | `no-store` (`DevNoStoreMiddleware`) | untouched |
| `collectstatic` | never | never |
| `DEBUG` | `true` | `false` |
| `TAP_DB_CONN_MAX_AGE` | `600` | `600` |

Four rows carry the same value in both columns deliberately. The worker count, the finders mode, the
absence of collection and the connection lifetime are all levers this spec governs, and listing them
with identical values is *evidence* that the parity goal is met rather than an assertion that it is.
Their sameness is the property: a connection-exhaustion incident or an unstyled plugin page reproduces
on a laptop exactly as it happens in production.

The three that do differ are each one line of configuration, and each buys something specific: the
reloader buys the inner loop, `max-age=0` buys never running a stale ES module, and `no-store` on
pages buys a reload that actually reloads.

#### Status Details

**The reloader is the adoption risk, and it is why this shipped branch-only** (ruled 2026-09-15).
gunicorn's `--reload` is a different implementation from `runserver`'s autoreloader, and most session
worktrees run plugins installed editable from `_dev-plugins/`. The failure mode — edits silently not
taking effect — is indistinguishable from a dozen unrelated causes, and it would reach every session
at once on their next rebase, at their next `restart web`, while they were debugging something else.
That is precisely how 2026-09-15's `github_core__collection_scope` grant failure played out: a restart
for one reason, a break somewhere else, nothing connecting the two.

So: build it, run it on one stack for a full working day — plugin edits, panel pages, at least one
collector run, the reloader specifically exercised — and announce what changes at the next
`restart web` when it merges. A silent entrypoint change is the thing that ruling exists to prevent.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-delta-1 | Table Is Exhaustive | Implemented | Every configuration difference between the development and production serving profiles appears as a row in this table. | |
| req-tap-serving-delta-2 | Same Server Both Sides | Implemented | Both profiles run gunicorn serving the same WSGI application with the same worker class. | |

### Unsafe Configuration Has No Default
----
RID: `req-tap-serving-fail-closed`

Status: `Implemented`

Configuration that is unsafe when defaulted has **no default**. The artifact refuses to start and
names what is missing, rather than starting with a value that is present and wrong.

What it used to be:

- `tap/settings.py` — `DEBUG` defaults to `true`. An operator who sets nothing gets debug mode.
- `tap/settings.py` — `SECRET_KEY` falls back to the development stack's key, a literal in a public
  repository.
- `tap/settings.py` — `DATABASE_URL` falls back to a `localhost` URL carrying a working username and
  password, both literals in the same public repository.
- `docker-compose.yml` — the same three values again, each under a comment naming the production
  requirement it does not meet.

Three shipped comments named the production requirement and three shipped values did not meet it.
This is the presence-is-not-correctness pattern in its purest form: a `SECRET_KEY` that exists and is
publicly known passes every check that asks whether a secret key is configured, and it is worse than
a missing one, because nobody goes looking for the thing the configuration says is handled. The
remedy order is derive, then verify, then detect; here the first applies — remove the second copy so
there is nothing to be wrong.

`DEBUG` therefore defaults to `false`, and development opts *in*.

**What landed (tap#463).** The APPLICATION has no unsafe default left: `SECRET_KEY` and
`DATABASE_URL` raise `ImproperlyConfigured` at settings import, naming themselves, and `DEBUG`
resolves to `false` through the same `_env_flag` parser as every other security flag — so `DEBUG=flase`
raises rather than being guessed at.

**What deliberately did NOT land, and why.** `docker-compose.yml` still declares a development
`SECRET_KEY` and database password. It is the development stack — it is what makes a fresh clone,
every session worktree, every CI lane and the test suite run — and removing the values would not
delete the hazard, it would relocate it into a `.env.local` every developer writes by hand. So the
second path is closed by REFUSAL instead of removal: the deploy-posture gate refuses both values.

**And it refuses them by DIGEST, not by value.** `settings.DEV_STACK_SIGNING_FINGERPRINT` and
`settings.DEV_STACK_DATABASE_FINGERPRINT` hold lowercase hex SHA-256, and
`tap/dev_credentials.py::matches_dev_stack_digest` does the (constant-time) comparison that both
gates share. A gate that recognises a credential never needs to hold it, and holding it left a
credential-shaped literal in a public repository that no secrets scanner can distinguish from one
that matters — Codacy's, a required check, correctly refused to pass the build over it, and the
`# noqa` that silenced ruff was a different tool's suppression doing nothing about it. That is the
presence-is-not-correctness shape pointed at ourselves: a comment that READS as a handled finding.
SHA-256 rather than something cheaper because this runs inside a FIPS-mode artifact where an
unapproved algorithm is what `req-fips-crypto-bom` fails closed on. The link that could rot — the
digest no longer matching what the compose file actually ships — is asserted by hashing the compose
line in `tap/tests/test_fail_closed_config.py`. Removing the default
closed *inherit it by configuring nothing*; the gate narrows *copy the development stack into a
deployment*.

**Narrows, not closes — and the difference is the kind of overclaim this spec exists to refuse.**
The gate stops the APPLICATION from serving. It does not stop the `db` service from starting with
the password beside it, and the compose `ports:` mapping publishes 5432 either way: compose does not
tear down a sibling container because `web` refused. So a copied stack still stands up a reachable
PostgreSQL with a published password even when the web half fails closed. And a deployment that
copies the file wholesale inherits `DEBUG=true` from it, which turns the gate off altogether — a
deliberate act with a name rather than an inherited default, but not a defended state. Both are why
`req-tap-serving-fail-closed-3` stays `Proposed`. (Caught by the Codex review seat on tap#559; the
first draft of this paragraph claimed the copy path was closed.)

Minting per-session credentials in `scripts/spawn-session.sh`, which would
let the literals leave the repository entirely, is the follow-up — tap#560, which also carries the
traps (the CI lanes read `.env`, not `.env.local`; `POSTGRES_PASSWORD` binds at `initdb`).

**One consequence worth stating for operators.** A deployment that sets `DEBUG` to nothing now also
has to set `TAP_SEARCH_READONLY_PASSWORD`: `tap_grid`'s system checks (`tap_grid.E001`/`E003`) fire
outside `DEBUG`, so `manage.py migrate` refuses before the schema is touched. That refusal names the
variable. It is not a regression; it is the first time that guard has ever been reachable.

**Where `ALLOWED_HOSTS` stands, now that it was looked at.** The dev default
(`localhost,127.0.0.1,.localhost`) is correct and stays. `.localhost` is what carries the labeled
session URLs `<label>.tap.localhost:<port>`
([`req-dev-multisession-browser-disambiguation`](spec-dev-multisession.md)), and a deployment that
inherits this list answers *nothing* — a loud 400 — rather than answering everything. The two
dangerous shapes are the empty list and the wildcard, and the posture gate refuses both. So this is
the third state, not a hole: a default that fails closed needs no removal.

**A correction worth recording, because the wrong version is widely believed and was written into
this epic's first draft:** `DEBUG=True` does **not** disable `ALLOWED_HOSTS` validation. Django
validates the host header either way; with `DEBUG=True` and `ALLOWED_HOSTS` empty, it substitutes a
permissive default (`.localhost`, `127.0.0.1`, `[::1]`). The real requirement is therefore that a
deployment *configures* its hostnames rather than inheriting the development default — not that
flipping `DEBUG` switches enforcement on.

#### Status Details

Sequenced strictly after [`req-tap-serving-static`](#static-assets-without-debug), which landed in
tap#462: until WhiteNoise served assets in both profiles, setting `DEBUG=false` did not harden the
product, it unstyled it.

**What was OBSERVED, and what was not.** The refusals are exercised — `tap/tests/test_fail_closed_config.py`
re-imports the settings module under a spoiled environment and asserts it raises, naming the
variable. The CONTAINER-level half of the done-test is **NOT OBSERVED**: nobody has started an image
with nothing set and watched it exit non-zero, because the change was authored in a worktree with no
Compose stack. Likewise `manage.py check --deploy` has not been run against a deployment-shaped
configuration; what stands in for it is the deploy-posture gate's own suite, which promotes five of
Django's deployment checks to fatal and asserts a correctly-configured deployment passes. Those are
three states, not two: none / some / not observable — and this is *some*.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-fail-closed-1 | Refuses To Start Unconfigured | Implemented | An artifact started with no `SECRET_KEY` and no database credentials refuses, naming the missing configuration, rather than starting. | Settings-import refusal observed; the container exiting non-zero is NOT OBSERVED |
| req-tap-serving-fail-closed-2 | DEBUG Defaults False | Implemented | With `DEBUG` unset, the application runs with debug mode off. | Parsed by the one `_env_flag`; a typo raises |
| req-tap-serving-fail-closed-3 | No Shipped Secret Literals | Proposed | No secret or credential literal is shipped in a published compose file or image layer as a working default. | Half done: no application default remains, but the development compose still declares both, refused by the posture gate. Closing it needs spawn-minted per-session credentials — tap#560 |
| req-tap-serving-fail-closed-4 | Deploy Check Clean | Proposed | `manage.py check --deploy` passes, or every remaining warning is named with a recorded reason. | The promoted/advisory split is enumerated in `tap_boot/posture.py`; the command itself is NOT OBSERVED against a deployment-shaped configuration |
| req-tap-serving-fail-closed-5 | Hosts Configured For The Deployment | Implemented | `ALLOWED_HOSTS` names the hostnames the instance is actually reached by, including the labeled session URLs multi-session development depends on, and is not left to the debug-mode default. | `req-dev-multisession-browser-disambiguation`; the labeled hosts are asserted through Django's own `validate_host` |

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

**Proven, not assumed** (tap#462): the runserver → gunicorn swap was made with the poll unedited, and
a session spawned against the new entrypoint reached ready without touching it —
[`req-tap-serving-readiness-1`](#readiness-is-server-independent) satisfied by observation rather than
by reading the code.

"Reporting healthy" is doing real work in that sentence: an HTTP response proves only that the web
server is alive, and the artifact runs a second process tree beside it. What the health surface must
distinguish, and what happens when either tree dies, is
[`req-tap-serving-process-failure`](#process-failure-is-visible).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-serving-readiness-1 | Probe Survives Server Swap | Implemented | The readiness probe passes unchanged across the swap from `runserver` to gunicorn. | |
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
| Plugins install at container start, from a profile | Settled by withdrawing collection entirely ([`req-tap-serving-static-plugins`](#plugin-assets-are-withdrawn-from-collection)): a Codespace builds no per-product image, so WhiteNoise's finders serve every profile's plugin assets with no build or boot step to place them |
| The whole environment is disposable | [`req-tap-serving-durability`](#durability-tuning-is-confined-to-disposable-databases) is **satisfied by the development overlay here**; the durable-deployment case is not exercised by this target |
| A stranger is looking at it | `DEBUG=false` matters for the first time in earnest — a traceback page in front of a trial user leaks the environment and ends the trial |

**What the origin derivation is, concretely.** `scripts/codespace-env` runs once before the stack
starts, reads `CODESPACE_NAME` and `GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN`, and writes the derived
values into `.env.local`. It is a standup step, not a runtime mechanism: nothing in the serving path
inspects the environment for a hostname, so a deployment that is not a Codespace is unaffected and
the derived values are ordinary configuration by the time Django reads them.

Two of them are easy to conflate and are different facts. `ALLOWED_HOSTS` takes bare hostnames and
answers *"is this Host header mine?"*. `CSRF_TRUSTED_ORIGINS` takes scheme-qualified origins and
answers *"did this POST come from me?"*. A Codespace makes the distinction sharp, because the browser's
origin is `https` where the container serves `http`: the host matches and the origin does not, so an
instance with only the first configured renders every page correctly and rejects every form submission.

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
| req-tap-serving-codespace-5 | The Origin Is Derived, Never Authored | Implemented | Every value that depends on the generated hostname — `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, the forwarded-protocol header to trust, `TAP_BASE_URL` — is derived at standup from the Codespace environment. No committed file names a per-instance hostname. The derivation runs INSIDE the container from `docker/entrypoint.sh`, before settings are read, and is authoritative over what compose supplied. | `scripts/codespace-env`. It cannot run on the host: compose substitutes only from the shell and from the checked-in `.env`, never from `.env.local`, and devcontainer.json has no hook to pass `--env-file`. It cannot defer to pre-set values either — compose gives every one of these keys a default, so "already set" cannot distinguish an operator from a default; `TAP_CODESPACE_DERIVE=false` is the opt-out |
| req-tap-serving-codespace-6 | A Cross-Origin POST Succeeds | Implemented | A form POST arriving from the forwarded `https` origin at a container serving `http` is accepted rather than rejected for CSRF. Django's `CSRF_TRUSTED_ORIGINS` default is empty and the setting did not exist in `tap/settings.py`, so every POST on such a deployment failed — including login, and only after the page had rendered correctly. | The failure reads as a bad credential, not as a missing setting |
| req-tap-serving-codespace-7 | The Owner Is The Visitor, Not The Repository | Implemented | `TAP_AUTH_INSTANCE_OWNER` is derived from the account that OPENED the Codespace (`GITHUB_USER` / `GITHUB_TOKEN`), never from the repository it was opened on, and carries the numeric user id. An account that cannot be resolved leaves the value empty, which DENIES every login under `owner_only` rather than admitting anyone. | `tap#741`: deriving from `GITHUB_REPOSITORY` locks out a visitor who opens a Codespace on our repo rather than their copy |

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
