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
