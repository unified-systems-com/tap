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

#: gunicorn default: 30. NetBox ships 120. Ours is derived from the slowest request TAP
#: legitimately serves rather than inherited from either.
#:
#: The upper bound on a legitimate slow request is the database, not the view: Gryphon /
#: graph reads run on the search connection under `statement_timeout=30s`
#: (`tap/settings.py` SEARCH_STATEMENT_TIMEOUT, `req-grid-traversal-exec-resource-bounds.sec`),
#: so a panel backed by a graph query cannot legitimately spend more than ~30s in the
#: database. 60 leaves a full statement timeout of headroom for connection acquisition,
#: serialization and template rendering on top of it, and still kills a genuinely wedged
#: worker in half the time NetBox would. Copying 120 would mean a stuck worker sits four
#: times longer than any legitimate request can take.
#:
#: If a surface ever needs longer than this, the answer is to move the work off the request
#: (steady_queue) rather than to raise the number — a request that outlives its own database
#: timeout is not slow, it is stuck.
timeout = 60

#: gunicorn default: 30. KEPT, on evidence rather than by omission. Measured reload
#: teardowns are 4-9s, and one observed cycle used the FULL 30s before the arbiter sent
#: SIGABRT (tap#495, recorded in spec-tap-serving.md). Raising it would let that pathology
#: wait longer without fixing it; lowering it would start SIGABRTing the healthy 4-9s
#: cycles. The number stays until tap#495 explains the outlier.
graceful_timeout = 30

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
