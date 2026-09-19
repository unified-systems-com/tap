"""gunicorn configuration — the serving stack, identical in development and production.

Loaded by the gunicorn master before it imports `tap.wsgi`, which is why everything it
reads comes from `tap.serving` (settings-free, stdlib-only) rather than Django settings.

The dev/prod delta this file expresses is exactly one line — `reload` — and that is the
point of `req-tap-serving-delta`: the server, the worker class and the worker count are
the same on both sides, so a production incident is reproducible on a laptop.

Spec: `specs/spec-tap-serving.md` — `req-tap-serving-server`, `req-tap-serving-delta`.
"""

from __future__ import annotations

import os
import sys

# The gunicorn master imports this file by path, so `/app` is not guaranteed to be on
# sys.path yet. Insert the repo root explicitly rather than relying on gunicorn's own
# chdir handling, which is an implementation detail of the version we happen to pin.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tap import serving  # noqa: E402  (must follow the sys.path insert above)

# Nothing below this line means anything if `GUNICORN_CMD_ARGS` is set: gunicorn applies
# that variable AFTER the config file (`app/base.py` 23.0.0 `load_config()`), so it
# outranks every value here. Refused at import — the last moment before it would be
# applied — so this file is the configuration rather than a suggestion.
serving.refuse_generic_gunicorn_env_override()

#: Container-internal bind. The host port is mapped by compose (`WEB_PORT`), so this
#: never varies per session.
bind = "0.0.0.0:8000"

#: Sync workers only — the connection budget is arithmetic on this number, and an
#: async/gevent class would forfeit that (`req-tap-serving-server-2`).
worker_class = serving.WORKER_CLASS

#: Explicit, named configuration; never a library default (`req-tap-serving-server-3`).
workers = serving.worker_count()

#: Development only. gunicorn's reloader watches the files behind `sys.modules`, which
#: includes editable-installed plugin packages mounted from `_dev-plugins/` — the inner
#: loop several session worktrees depend on. Left off in production, where a code change
#: arrives as a new container.
reload = serving.is_development()

#: Log to stdout/stderr so `docker compose logs web` remains the one place to look.
accesslog = "-"
errorlog = "-"

#: The steady_queue supervisor and the entrypoint both write to the same stream; the
#: access log is the noisiest thing in it, so keep it terse.
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms'

# ---------------------------------------------------------------------------
# Everything below is stated because it would otherwise arrive from a library
# default nobody chose (`req-tap-serving-server-5`). Each value names WHY it is
# that value — including the ones that keep gunicorn's own default, because the
# point is the choice, not the number. Every one of them holds the SAME value in
# both serving profiles: the dev/prod delta is the short enumerated list in
# `req-tap-serving-delta`, and nothing here joins it.
#
# Defaults quoted below were read from the pinned gunicorn 23.0.0 source.
# ---------------------------------------------------------------------------

#: gunicorn default: False. KEPT — `reload` above requires it off (gunicorn refuses the
#: combination), and the reloader is the inner loop several session worktrees depend on.
#: Stated so that "preload to save memory" never lands as a silent optimization: the two
#: settings are incompatible, and the test in `tap/tests/test_serving_stack.py` says so.
preload_app = False

#: BUDGET 2 of 4 — the WORKER HEARTBEAT WATCHDOG. gunicorn default: 30. NetBox ships 120.
#: Ours is DERIVED (`serving.worker_timeout()` = statement bound + overhead headroom), so an
#: operator who moves `TAP_SEARCH_STATEMENT_TIMEOUT` moves this with it and the two numbers
#: cannot silently disagree. The four budgets and their order are stated in `tap/serving.py`.
#:
#: What it actually is: the arbiter compares `now - worker.tmp.last_update()` against this
#: and sends SIGABRT past it (`gunicorn/arbiter.py` 23.0.0 `murder_workers`). That is a
#: LIVENESS watchdog. It doubles as the whole-request deadline only because a sync worker
#: heartbeats between requests, not during one.
#:
#: What it is NOT: a guarantee that a request fits. `statement_timeout` is PER STATEMENT and
#: one graph response issues several (path query, Entity fetch, Edge fetch —
#: `tap_grid/gryphon/executor.py`), so the database-side ceiling can exceed this timer and
#: such a request is killed by the watchdog. Deliberate: the statement count is not knowable
#: across views, and a watchdog sized for the worst imaginable one detects nothing. The
#: missing whole-request budget is tracked as tap#530.
#:
#: Cost, stated rather than discovered: this is larger than gunicorn's default, so the
#: worst-case hang of a worker that will not exit (tap#495) grows with it. That is the price
#: of not murdering a worker whose statement PostgreSQL still permits, and tap#495's fix is
#: in the reloader/worker-exit path, not in this timer.
timeout = serving.worker_timeout()

#: BUDGET 3 of 4 — the GRACEFUL DRAIN. gunicorn default: 30.
#:
#: CORRECTED 2026-09-17: an earlier version of this comment justified the value from the
#: SIGABRT recorded in tap#495. That attribution was wrong, and the correction matters more
#: than the number. `graceful_timeout` is read in exactly one place — `Arbiter.stop()`
#: (`gunicorn/arbiter.py` 23.0.0 ~line 390), the MASTER's own shutdown, where it SIGTERMs the
#: workers, waits, then SIGKILLs. A source reload never enters `stop()`: the reloader thread
#: inside the worker sets `alive = False` and calls `sys.exit(0)` from a non-main thread
#: (`gunicorn/workers/base.py`), which ends that thread only. If the worker's main thread is
#: blocked it stops heartbeating, and the SIGABRT then comes from the WATCHDOG above — the
#: 31s in tap#495 is `timeout=30` plus one arbiter poll, not this timer.
#:
#: The value is 20 and the ordering is a decision, not an oversight: the drain is SHORTER
#: than the watchdog, so a shutdown can cut short a request that was permitted to run. TAP
#: accepts that — a restart must not wait out a pathological request, and the reasoning is on
#: `serving.GRACEFUL_DRAIN_SECONDS`. It is paired with compose's `stop_grace_period`, which
#: must be larger or Docker kills the container mid-drain.
graceful_timeout = serving.GRACEFUL_DRAIN_SECONDS

#: gunicorn default: 2. KEPT, and INERT with our worker class — stated for exactly that
#: reason. The sync worker calls `resp.force_close()` on every response
#: (`gunicorn/workers/sync.py` 23.0.0, `handle_request`), so it never keep-alives at all
#: and this value is not read. It is written down so that a future worker-class change
#: (which would make it live) inherits a chosen value rather than discovering that keeping
#: connections open for 2s is wrong for a directly-exposed server with no proxy in front.
keepalive = 2

#: gunicorn default: 0 (disabled). A recycle bounds any slow leak — per-process caches,
#: registry growth, a C-extension leak — at a known number of requests instead of at
#: "whenever someone notices memory".
#:
#: 5000 is reasoned, not copied from NetBox (which also picked 5000). Two forces: an HTMX
#: page view is MANY requests (each panel is its own request), so the counter climbs far
#: faster than page views; and a recycled worker pays a full cold import of Django plus
#: every installed plugin — measured at tens of seconds on this image — with no
#: `preload_app` to amortize it, while only 3 workers exist. So recycling must be rare
#: enough to be invisible and frequent enough to bound a leak: ~5000 requests is on the
#: order of hundreds of page views per worker.
#:
#: The in-flight-connection trap from benoitc/gunicorn#3038 was checked against OUR worker
#: class rather than assumed away. It is filed against `gthread`; the sync worker in 23.0.0
#: increments `self.nr` and sets `self.alive = False` INSIDE `handle_request`, before the
#: response body is written, and then completes that response — and it accepts exactly one
#: connection at a time, so nothing else is in flight to drop. Connections still queued in
#: the kernel backlog are held by the shared listening socket, not by the exiting worker,
#: and are accepted by its siblings. Verified by reading `gunicorn/workers/sync.py` and
#: `workers/base.py` at the 23.0.0 tag.
max_requests = 5000

#: gunicorn default: 0. Without jitter, workers that started together hit the same request
#: count together and recycle simultaneously — a self-inflicted outage in a 3-worker stack.
#: `base.py` computes `max_requests + randint(0, jitter)` once per worker at fork, so 500
#: spreads the recycles over a 10% band of the interval. The pairing is the correctness
#: argument, and the test asserts it: jitter > 0 whenever recycling is on.
max_requests_jitter = 500

#: The worker heartbeat file's directory. Authored once in `tap.serving` (the reasoning for
#: a dedicated tmpfs — and against `/dev/shm` — lives on the constant); the compose file
#: mounts a small tmpfs at that path. Refuses to start if that directory is absent — or is
#: observably NOT RAM-backed — at config load rather than at first fork: a missing or
#: disk-backed mount is loud, never a silent fall back to the overlay this setting exists to
#: leave. Existence alone would be a presence check where the property wanted is the
#: filesystem type.
worker_tmp_dir = serving.worker_tmp_dir()

#: gunicorn defaults: 4094 / 100 / 8190. KEPT, and stated because these three are the
#: request-parsing surface — the one place where a library default is also a security
#: boundary, and where "unset" reads as "unbounded" to anyone auditing the file.
#:
#: They are kept rather than tightened because each is already comfortably above what TAP
#: sends: panel URLs carry entity ids, limits and offsets (hundreds of bytes, not thousands),
#: and a request's headers are a session cookie plus a handful of `HX-*` headers. They are
#: kept rather than RAISED because raising them widens a request-smuggling / resource surface
#: to buy nothing. A future surface that puts a Gryphon query in a query string must raise
#: `limit_request_line` deliberately here, with a reason, instead of meeting it as a 414 in
#: production.
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190
#: HTTP PARSING STRICTNESS. gunicorn defaults: all False, and `header_map = "drop"`. KEPT,
#: and stated because these five are the request-smuggling surface proper — every one of
#: them is a knob that LOOSENS parsing, so the risk is not that they are wrong today but
#: that one gets turned on for a misbehaving client and never turned back. Stating them
#: makes that a visible diff rather than an invisible one.
#:
#: `casefold_http_method` accepts `get` for `GET`; `permit_unconventional_http_method` and
#: `..._version` accept request lines outside the registered sets;`permit_obsolete_folding`
#: re-enables RFC 7230-obsoleted header line folding; `strip_header_spaces` accepts a space
#: before the header colon. Each of those is a documented desync primitive when a proxy and
#: an origin disagree about it. `header_map = "drop"` discards headers that would collide in
#: the WSGI environ rather than mapping them together (`refuse` is stricter still, and is
#: the deliberate escalation if a collision is ever observed).
casefold_http_method = False
permit_unconventional_http_method = False
permit_unconventional_http_version = False
permit_obsolete_folding = False
strip_header_spaces = False
header_map = "drop"

#: PROXY TRUST. gunicorn's `forwarded_allow_ips` default is
#: `os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1,::1")` — an ENVIRONMENT VARIABLE that
#: can widen proxy trust to `*` without touching this repository. Pinning the value here
#: takes that variable out of play, which is the whole reason to state a setting whose value
#: is otherwise unchanged.
#:
#: What it gates: `gunicorn/http/message.py` (23.0.0) applies `secure_scheme_headers` and
#: `forwarder_headers` ONLY when the peer address is in this list (or it is `*`, or the peer
#: is a unix socket). Requests here arrive from the Docker bridge, not loopback, so no peer
#: is trusted and a client-supplied `X-Forwarded-Proto` cannot make a plaintext request look
#: secure. There is no proxy in front of TAP today; when there is, this is one of the values
#: `req-tap-serving-proxy` requires to be set deliberately, as a reviewed change.
forwarded_allow_ips = "127.0.0.1,::1"

#: PROXY protocol, off. gunicorn defaults: `"off"` / loopback. Stated for the same reason:
#: enabling it makes gunicorn parse a PROXY header from the peer and TRUST the client address
#: in it, which is a spoofing primitive the moment the peer is not what you think it is.
#:
#: The literal is `"off"` and not `False` since 24.1.0, which widened this from a boolean to
#: a VERSION SELECTOR — `off` / `v1` / `v2` / `auto`, and a bare `--proxy-protocol` now means
#: `auto`, i.e. "accept either wire format from the peer". `validate_proxy_protocol` still
#: coerces our old `False` to `"off"`, so nothing was broken; the literal moved anyway,
#: because a boolean written against a four-valued setting reads as "off/on" and hides that
#: turning it on is also a choice of which parser to expose. An ALB does not speak PROXY
#: protocol to an HTTP target group, so the value does not move for tap#558's ECS shape.
proxy_protocol = "off"
proxy_allow_ips = "127.0.0.1,::1"

# ---------------------------------------------------------------------------
# gunicorn 26 (23.0.0 -> 26.2.0, tap#585). Twenty-six settings arrived across 24.x,
# 25.x and 26.2.0 and landed in this file by name, which is what the partition test
# below exists to do. What follows is the deliberate pass over them: the ones that
# open a surface are assigned here, the two families that belong to a concurrency
# model TAP does not run are acknowledged as groups at the bottom.
#
# Defaults quoted below were read from the gunicorn 26.2.0 registry, not from the
# changelog.
# ---------------------------------------------------------------------------

#: THE CONTROL SOCKET, OFF. gunicorn 25.1.0's default is ON: `control_socket_disable`
#: defaults to False, so `Arbiter._start_control_server()` (26.2.0, arbiter.py ~line 1009)
#: starts a background thread on a unix socket at `$XDG_RUNTIME_DIR/gunicorn.ctl` or
#: `$HOME/.gunicorn/gunicorn.ctl`, creating the parent directory if needed. Read from the
#: source rather than assumed: "a new setting whose default is a path" is not a setting
#: that is off.
#:
#: What it exposes (`gunicorn/ctl/handlers.py`): `worker add`, `worker remove`,
#: `worker kill <pid>`, `reload`, `reopen`, `shutdown`, and `show all/workers/config/
#: stats/listeners`. There is no authentication — the control is the socket's file mode.
#:
#: Why off rather than 0600-and-shrug. The threat model is not a remote attacker; it is
#: anything already executing inside this container as the same uid — a compromised
#: worker, a plugin's subprocess, an operator's `docker exec`. For that peer this is an
#: unauthenticated shutdown switch. It is also a live lever on the ONE number the whole
#: connection budget is arithmetic on: `worker add` raises `workers` past the value
#: `serving.worker_count()` derived, and the PostgreSQL connection ceiling stops being a
#: budget the moment it can move at runtime (`req-tap-serving-connection-budget`). That is
#: the same failure `refuse_generic_gunicorn_env_override()` above refuses from the
#: environment — refusing one lever while a socket offers the other would be theatre.
#:
#: What is given up: `gunicornc show workers` as an observability surface. TAP already has
#: one (`manage.py health`, and the container HEALTHCHECK from tap#521), and it is the one
#: that reports on the application rather than on the arbiter.
control_socket_disable = True

#: Inert while the socket is disabled, and assigned anyway so that re-enabling it is one
#: reviewed decision rather than one flag. gunicorn's default path is under `$HOME`; an
#: empty value resolves against the CURRENT WORKING DIRECTORY (`_get_control_socket_path`),
#: which in this image is the source tree. Neither is where a command channel belongs, so
#: the path names the RAM-backed, container-private directory the heartbeat already uses —
#: one fact reused rather than a second copy of the path.
control_socket = os.path.join(serving.WORKER_TMP_DIR, "gunicorn.ctl")

#: gunicorn default: 0o600 (owner only). KEPT, and stated because the documented alternative
#: is `0o660` "to allow group access" — widening an unauthenticated command channel to a
#: whole gid is exactly the edit that should show up in a diff.
control_socket_mode = 0o600

#: HTTP VERSIONS SERVED. gunicorn default: `"h1"`. KEPT and pinned, because the setting is
#: new (25.0.0) and the direction of travel is additive: `h2` here is what makes the five
#: `http2_*` knobs below live at all, and `h3` is reserved for a protocol gunicorn has not
#: implemented. HTTP/2 over TLS is negotiated by ALPN and TLS terminates outside this
#: artifact (`req-tap-serving-proxy`), so there is nothing for h2 to do here today.
http_protocols = "h1"

#: CLEARTEXT HTTP/2, OFF. gunicorn default: `"off"` (26.2.0). KEPT, and stated because it
#: is the single most consequential knob the upgrade added: `h2c` is HTTP/2 with no TLS,
#: and gunicorn's own note is "Do not expose a cleartext HTTP/2 port to the internet".
#:
#: It would also be the wrong kind of safe to leave unstated. Its guard is that it honours
#: only peers in `forwarded_allow_ips` — the same list tap#503 is open about, because that
#: list is loopback today and will have to widen the moment a real proxy (an ALB, a mesh
#: sidecar) sits in front. Widening proxy trust for the SCHEME header would, with this knob
#: on, also hand those peers a second protocol parser. Pinning `off` here means #503 can be
#: decided on its own merits; it does not decide this one by accident, and this comment
#: does not decide #503.
http2_cleartext = "off"

#: HTTP/2 RESOURCE BOUNDS. gunicorn defaults: 65535 / 100 / 16384 / 65536 — the HTTP/2
#: specification's own numbers. KEPT, and INERT while `http_protocols` is `h1`, stated for
#: the same reason `keepalive` above is: they are the per-connection memory and concurrency
#: bounds that become load-bearing the instant h2 is switched on, and a future engineer
#: turning it on should inherit chosen values rather than discover them. The trap worth
#: naming: `http2_max_header_list_size = 0` means UNLIMITED post-HPACK header bytes, i.e.
#: a decompression-bomb surface, and 0 is a value someone reaches for meaning "no limit
#: needed". These four are the HTTP/2 analogue of the `limit_request_*` trio above.
http2_initial_window_size = 65535
http2_max_concurrent_streams = 100
http2_max_frame_size = 16384
http2_max_header_list_size = 65536

#: THE PARSER ITSELF. gunicorn default: `"auto"` — use the `gunicorn_h1c` C extension
#: (picohttpparser + SIMD) if it is importable, else the pure-Python parser. PINNED to
#: `python`, which is the one decision in this block that changes behaviour from the
#: default rather than confirming it.
#:
#: `auto` means the request parser is selected by whether an optional wheel happens to be
#: present in the image — a transitive dependency, a `gunicorn[fast]` extra someone adds for
#: throughput, a base-image change. That is a silent swap of the exact component the five
#: strictness flags above were reasoned against: `permit_obsolete_folding`,
#: `strip_header_spaces` and the two `permit_unconventional_*` flags were read out of
#: `gunicorn/http/message.py`, and a second implementation of those checks in C is a second
#: thing to review, not the same thing faster.
#:
#: The cost is stated rather than discovered: this forfeits the faster parser. TAP's
#: requests are small (panel URLs and a session cookie — see the `limit_request_*` note),
#: so parsing is not the bottleneck at our scale. Moving to `fast` is a legitimate future
#: change; it is a change that must re-verify the strictness flags against the C parser,
#: which is why it should be a diff on this line and not an install-time coin flip.
http_parser = "python"

#: THE WIRE PROTOCOL. gunicorn default: `"http"`. KEPT and stated because the alternative
#: is `"uwsgi"`, which turns this port into a uWSGI binary-protocol listener for an nginx
#: `uwsgi_pass` upstream. That is a whole second request-parsing surface selected by one
#: string, and TAP speaks HTTP to whatever terminates in front of it.
protocol = "http"

#: Who may speak the uWSGI protocol. gunicorn default: `"127.0.0.1,::1"`. KEPT, and pinned
#: rather than acknowledged so it travels WITH `protocol` above: if that ever moves to
#: `uwsgi`, the peer allowlist is already stated on the line below it instead of being
#: rediscovered. `*` here would be the uWSGI-side twin of `forwarded_allow_ips = "*"`.
uwsgi_allow_ips = "127.0.0.1,::1"

#: The ASGI scope's mount point. gunicorn default: `""`. KEPT, and assigned rather than
#: filed with the other ASGI settings because the QUESTION it answers is not ASGI-specific:
#: TAP is mounted at `/`, and the WSGI way to say otherwise is Django's
#: `FORCE_SCRIPT_NAME`, not this. Stated so that "we are behind a proxy at /tap" is answered
#: in one place if it is ever asked, rather than half-answered here by a setting the sync
#: worker never reads.
root_path = ""

#: Every gunicorn setting this file does NOT assign, grouped by the reason it is left at its
#: library default (`req-tap-serving-server-5`).
#:
#: This exists because "state every knob" is otherwise an unfalsifiable claim: nobody can tell
#: a setting that was considered and left alone from one nobody has heard of, and a gunicorn
#: upgrade that ADDS a knob changes behaviour with no diff anywhere. A test partitions
#: gunicorn's own `KNOWN_SETTINGS` registry against this map plus the assignments above and
#: fails on anything in neither — so the next upgrade to add a setting fails here, by name,
#: and someone has to decide which group it belongs in.
#:
#: This is the enumeration that makes the requirement true rather than asserted. It is not a
#: claim that each default is CORRECT — only that it was seen.
LIBRARY_DEFAULTS_ACKNOWLEDGED = {
    # Lifecycle hooks. TAP defines none; adding one is a code change reviewed on its own
    # merits, and `docker/entrypoint.sh` (not a hook) owns process startup.
    "hooks": (
        "on_starting",
        "on_reload",
        "when_ready",
        "pre_fork",
        "post_fork",
        "post_worker_init",
        "worker_int",
        "worker_abort",
        "pre_exec",
        "pre_request",
        "post_request",
        "child_exit",
        "worker_exit",
        "nworkers_changed",
        "on_exit",
        "ssl_context",
    ),
    # TLS. gunicorn serves plain HTTP inside the container; termination happens outside the
    # artifact and is `req-tap-serving-proxy`'s subject, not this file's.
    "tls": (
        "ca_certs",
        "cert_reqs",
        "certfile",
        "ciphers",
        "do_handshake_on_connect",
        "keyfile",
        "ssl_version",
        "suppress_ragged_eofs",
    ),
    # Process identity, daemonization and CLI plumbing. The container is the process manager
    # (`exec` in the entrypoint, `restart:` in compose), so daemonizing, pidfiles, uid/gid
    # switching and chdir are decided a layer up or not at all.
    "process_identity": (
        "daemon",
        "pidfile",
        "user",
        "group",
        "initgroups",
        "umask",
        "chdir",
        "pythonpath",
        "raw_env",
        "proc_name",
        "default_proc_name",
        "spew",
        "print_config",
        "check_config",
        "config",
        "wsgi_app",
        "paste",
        "raw_paste_global_conf",
        "enable_stdio_inheritance",
        "reuse_port",
        "sendfile",
        "tmp_upload_dir",
        "backlog",
    ),
    # Meaningful only to worker classes `req-tap-serving-server-2` forbids. A sync worker
    # ignores both; setting either would imply a concurrency model TAP does not run.
    "other_worker_classes": (
        "threads",
        "worker_connections",
    ),
    # The ASGI worker class (added 24.0.0, extended 25.0.0). TAP serves
    # `tap.wsgi:application` over sync workers, and `req-tap-serving-server-2` forbids the
    # alternatives for a reason that is arithmetic, not stylistic: a sync worker holds one
    # connection per alias, so the database ceiling is countable. These three tune an event
    # loop (`asgi_loop`), a startup/shutdown protocol (`asgi_lifespan`) and a disconnect
    # grace period that only exists because an async task can be cancelled mid-request —
    # none of which a forked sync worker has. Each is documented "only affects the `asgi`
    # worker type", so they are unreachable rather than merely unused. `root_path`, the
    # fourth setting the ASGI work introduced, is ASSIGNED above: the question it asks —
    # where is this application mounted — has a WSGI answer, and deserves one.
    "asgi_worker": (
        "asgi_disconnect_grace_period",
        "asgi_lifespan",
        "asgi_loop",
    ),
    # The DIRTY ARBITER (25.0.0, beta): a SECOND process tree beside the HTTP workers, for
    # long-blocking work — an ML model, a heavy computation — held in memory across calls.
    # It is off unless BOTH `dirty_workers > 0` and `dirty_apps` is non-empty
    # (`gunicorn/arbiter.py` 26.2.0, `maybe_spawn_dirty_arbiter`), and TAP sets neither.
    #
    # Acknowledged as a group rather than pinned because TAP already answers this question
    # elsewhere and the answer is not "tune gunicorn": long-running work is Django Tasks
    # under the steady_queue supervisor the entrypoint starts, which is where the grid's
    # provenance and the service layer already reach. Adopting dirty workers would be a
    # third process tree in one container with its own timeouts and its own share of the
    # connection budget — an architecture decision, not a knob.
    #
    # Note what makes that acknowledgement safe: `dirty_workers` DEFAULTING to 0. That is a
    # value, and the value ratchet below is what keeps this group honest if it ever moves.
    "dirty_arbiter": (
        "dirty_apps",
        "dirty_graceful_timeout",
        "dirty_post_fork",
        "dirty_threads",
        "dirty_timeout",
        "dirty_worker_exit",
        "dirty_worker_init",
        "dirty_workers",
        "on_dirty_starting",
    ),
    # Logging transport and formatting. `spec-tap-logging.md` owns this: the contract is
    # stdout/stderr and `tap/logging.py`'s dictConfig, so syslog/statsd/logconfig plumbing is
    # deliberately unused rather than unconsidered.
    "logging_plumbing": (
        "loglevel",
        "logger_class",
        "logconfig",
        "logconfig_dict",
        "logconfig_json",
        "capture_output",
        "disable_redirect_access_to_syslog",
        "syslog",
        "syslog_addr",
        "syslog_facility",
        "syslog_prefix",
        "statsd_host",
        "statsd_prefix",
        "dogstatsd_tags",
        # `enable_backlog_metric` (26.x) emits a `gunicorn.backlog` histogram — i.e. it is
        # a statsd emitter, and lands with the rest of the statsd plumbing that has no
        # sink configured. Worth naming for later: the socket backlog is the one number
        # that would distinguish "workers are saturated" from "the site is slow", which is
        # the question the 2026-09-15 outage could not answer. It needs a metrics sink to
        # be worth turning on, and TAP has none yet.
        "enable_backlog_metric",
    ),
    # Reloader tuning. The `auto` engine polling `os.stat` is what was MEASURED over the
    # bind mount (spec-tap-serving.md, Development); changing it invalidates that measurement,
    # and tap#494 is the open question about the reloader's behaviour as it stands.
    "reloader": (
        "reload_engine",
        "reload_extra_files",
    ),
    # Unreachable while no peer is trusted: `gunicorn/http/message.py` reads these only for a
    # peer inside `forwarded_allow_ips`, pinned to loopback above. Named here rather than
    # assigned so the reason travels with them if that pin ever moves.
    "proxy_unreachable": (
        "secure_scheme_headers",
        "forwarder_headers",
    ),
}

#: Why an acknowledged default is NOT compared by value. Three states, never two: a default
#: is either RECORDED below, or it is in the not-compared map with the rule that excluded it
#: — never silently absent, which would turn the count into another presence check.
NOT_COMPARED_CALLABLE = "callable — gunicorn's own no-op hook, a fresh function object on every import"
NOT_COMPARED_AMBIENT = "ambient — computed from the environment, cwd, process identity or platform"
NOT_COMPARED_NOT_A_LITERAL = "not a Python literal — an object whose repr is not a durable record"

#: The default VALUE of every acknowledged setting, as observed in the INSTALLED gunicorn
#: (`req-tap-serving-server-5`, closing tap#542).
#:
#: The map above compares NAMES. That catches a release which ADDS a setting or REMOVES an
#: acknowledged one, and says nothing about the release that keeps the name and moves the
#: value underneath it — `forwarded_allow_ips` stays `forwarded_allow_ips`; its default
#: changes; every group above still reads as considered. Across 23.0.0 -> 26.2.0 that was
#: not hypothetical: `proxy_protocol`'s default moved from `False` to `"off"` when 24.1.0
#: turned a boolean into a version selector. It happened to be a setting this file ASSIGNS,
#: so the file's own value stood; had it been acknowledged, nothing here would have said a
#: word.
#:
#: So each acknowledged default is recorded here and compared against the installed package
#: at test time. Two properties make that a CHECK rather than a second copy:
#:
#:  - The values are DERIVED, never hand-typed: the test regenerates this literal from the
#:    installed registry and prints the replacement block when it disagrees. Nobody reads a
#:    changelog to fill this in, which is the failure the issue named.
#:  - The exclusions are DERIVED TOO. A hand-kept "skip these" list would rot into the same
#:    unfalsifiable claim the ratchet exists to replace. Instead the test loads a PRIVATE
#:    second copy of `gunicorn.config` under a perturbed ambient context — scrubbed
#:    environment, a fake cwd, a fake euid/egid, a fake `sys.platform` — and anything whose
#:    default MOVES is not a constant and is excluded by OBSERVATION. That is what puts
#:    `chdir`, `user`, `group` and `syslog_addr` below without anybody naming them, and it
#:    is what will catch a setting that BECOMES environment-derived in a future release.
#:
#: What this still does not check: whether a default is CORRECT. It is the record that the
#: value was seen, one level below the record that the name was seen. And it covers the
#: acknowledged settings only — the assigned ones carry their values in this file, where a
#: reviewer already reads them.
#:
#: GENERATED. Do not hand-edit: run the test, paste the block it prints, then re-read the
#: group comment above whichever setting moved and say in the commit why its new default
#: still stands.
LIBRARY_DEFAULTS_OBSERVED = {
    "asgi_disconnect_grace_period": 3,
    "asgi_lifespan": "auto",
    "asgi_loop": "auto",
    "backlog": 2048,
    "ca_certs": None,
    "capture_output": False,
    "certfile": None,
    "check_config": False,
    "ciphers": None,
    "config": "./gunicorn.conf.py",
    "daemon": False,
    "default_proc_name": "gunicorn",
    "dirty_apps": [],
    "dirty_graceful_timeout": 30,
    "dirty_threads": 1,
    "dirty_timeout": 300,
    "dirty_workers": 0,
    "disable_redirect_access_to_syslog": False,
    "do_handshake_on_connect": False,
    "dogstatsd_tags": "",
    "enable_backlog_metric": False,
    "enable_stdio_inheritance": False,
    "forwarder_headers": "SCRIPT_NAME,PATH_INFO",
    "initgroups": False,
    "keyfile": None,
    "logconfig": None,
    "logconfig_dict": {},
    "logconfig_json": None,
    "logger_class": "gunicorn.glogging.Logger",
    "loglevel": "info",
    "paste": None,
    "pidfile": None,
    "print_config": False,
    "proc_name": None,
    "pythonpath": None,
    "raw_env": [],
    "raw_paste_global_conf": [],
    "reload_engine": "auto",
    "reload_extra_files": [],
    "reuse_port": False,
    "secure_scheme_headers": {"X-FORWARDED-PROTOCOL": "ssl", "X-FORWARDED-PROTO": "https", "X-FORWARDED-SSL": "on"},
    "sendfile": None,
    "spew": False,
    "statsd_host": None,
    "statsd_prefix": "",
    "suppress_ragged_eofs": True,
    "syslog": False,
    "syslog_facility": "user",
    "syslog_prefix": None,
    "threads": 1,
    "tmp_upload_dir": None,
    "umask": 0,
    "worker_connections": 1000,
    "wsgi_app": None,
}

#: The acknowledged settings whose default is NOT a constant, each with the rule that says
#: so. GENERATED alongside the map above; one regeneration prints both.
LIBRARY_DEFAULTS_NOT_COMPARED = {
    "cert_reqs": NOT_COMPARED_NOT_A_LITERAL,
    "chdir": NOT_COMPARED_AMBIENT,
    "child_exit": NOT_COMPARED_CALLABLE,
    "dirty_post_fork": NOT_COMPARED_CALLABLE,
    "dirty_worker_exit": NOT_COMPARED_CALLABLE,
    "dirty_worker_init": NOT_COMPARED_CALLABLE,
    "group": NOT_COMPARED_AMBIENT,
    "nworkers_changed": NOT_COMPARED_CALLABLE,
    "on_dirty_starting": NOT_COMPARED_CALLABLE,
    "on_exit": NOT_COMPARED_CALLABLE,
    "on_reload": NOT_COMPARED_CALLABLE,
    "on_starting": NOT_COMPARED_CALLABLE,
    "post_fork": NOT_COMPARED_CALLABLE,
    "post_request": NOT_COMPARED_CALLABLE,
    "post_worker_init": NOT_COMPARED_CALLABLE,
    "pre_exec": NOT_COMPARED_CALLABLE,
    "pre_fork": NOT_COMPARED_CALLABLE,
    "pre_request": NOT_COMPARED_CALLABLE,
    "ssl_context": NOT_COMPARED_CALLABLE,
    "ssl_version": NOT_COMPARED_NOT_A_LITERAL,
    "syslog_addr": NOT_COMPARED_AMBIENT,
    "user": NOT_COMPARED_AMBIENT,
    "when_ready": NOT_COMPARED_CALLABLE,
    "worker_abort": NOT_COMPARED_CALLABLE,
    "worker_exit": NOT_COMPARED_CALLABLE,
    "worker_int": NOT_COMPARED_CALLABLE,
}
