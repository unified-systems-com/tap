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

#: PROXY protocol, off. gunicorn defaults: False / loopback. Stated for the same reason:
#: enabling it makes gunicorn parse a PROXY header from the peer and TRUST the client address
#: in it, which is a spoofing primitive the moment the peer is not what you think it is.
proxy_protocol = False
proxy_allow_ips = "127.0.0.1,::1"

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
