"""Serving-profile facts, derived once and read by every process that needs them.

The serving stack is decided in three places that must agree: the gunicorn master
(`docker/gunicorn.conf.py` — how many workers, which worker class, reload or not),
Django settings (`tap/settings.py` — which static mode, and the worker count the
connection budget is derived from), and any future tooling that reports on the
running artifact. Writing the same `os.environ.get(...)` in each of them is exactly
the duplication `derive a fact once` forbids: the day the default worker count moves,
two of the three copies move with it.

So the facts live here, once, and each consumer calls a function.

**Settings-free and stdlib-only on purpose.** The gunicorn config file is imported by
the gunicorn master *before* `tap.wsgi` loads Django, so this module cannot import
`django.conf.settings` — the same constraint `tap.preboot` and `tap.secrets_root`
live under.

**The profile is a named setting, never `DEBUG`.** `DEBUG` governs error presentation
only (`req-tap-serving-debug-scope`); overloading it is how static serving became
debug-dependent in the first place, which is the failure `spec-tap-serving.md` exists
to undo. The dev/prod delta is the short enumerated list in `req-tap-serving-delta`,
and `TAP_SERVE_PROFILE` is the one lever that selects a column of it.

Spec: `specs/spec-tap-serving.md` — `req-tap-serving-server`, `req-tap-serving-static`,
`req-tap-serving-delta`.
"""

from __future__ import annotations

import os

#: Development: gunicorn with `--reload`, WhiteNoise autorefreshing from the source
#: tree, static served with `max-age=0`. The inner loop several session worktrees
#: edit plugin templates/CSS/JS in, continuously.
PROFILE_DEVELOPMENT = "development"

#: Production: the same gunicorn, the same WhiteNoise finders mode, no reloader.
PROFILE_PRODUCTION = "production"

#: Valid values of `TAP_SERVE_PROFILE`.
PROFILES = (PROFILE_DEVELOPMENT, PROFILE_PRODUCTION)

#: The profile an unset environment gets. Production is the fail-safe default: an
#: operator who never heard of this variable gets no source-watching reloader and
#: no zero-length cache headers. Development is opted into by the dev compose file.
DEFAULT_PROFILE = PROFILE_PRODUCTION

#: Sync workers, when `TAP_WEB_WORKERS` says nothing.
#:
#: Explicit, and explicitly not `multiprocessing.cpu_count()`-derived: the worker
#: count is an INPUT to the connection budget (`req-tap-serving-connection-budget`),
#: and a budget computed from a number that changes with the host is not a budget.
#: Three sync workers is enough concurrency for the HTMX panel pages (each panel is
#: its own request) while keeping the ceiling — workers x aliases — small enough to
#: sit far under PostgreSQL's default `max_connections` of 100 alongside the
#: steady_queue process tree.
DEFAULT_WORKERS = 3

#: The one worker class this spec permits. A sync worker is a forked process handling
#: one request at a time, so it holds exactly one connection per configured alias and
#: the ceiling is arithmetic rather than an estimate. Async/gevent classes forfeit
#: that property — which is the 2026-09-15 incident (`req-tap-serving-server-2`).
WORKER_CLASS = "sync"


def serve_profile() -> str:
    """Return the configured serving profile, defaulting to production.

    An unrecognised value is not silently coerced: a typo'd `TAP_SERVE_PROFILE`
    would otherwise fall back to production on a developer's machine and take the
    reloader away with no message.

    Raises:
        ValueError: if `TAP_SERVE_PROFILE` is set to something outside `PROFILES`.
    """
    raw = os.environ.get("TAP_SERVE_PROFILE", "").strip().lower()
    if not raw:
        return DEFAULT_PROFILE
    if raw not in PROFILES:
        raise ValueError(f"TAP_SERVE_PROFILE={raw!r} is not one of {PROFILES} (spec-tap-serving.md)")
    return raw


def is_development() -> bool:
    """True when the development column of the dev/prod delta applies."""
    return serve_profile() == PROFILE_DEVELOPMENT


def worker_count() -> int:
    """Return the gunicorn sync-worker count.

    Named configuration, readable at runtime, never a library default
    (`req-tap-serving-server-3`) — because the connection budget is derived from it.

    Raises:
        ValueError: if `TAP_WEB_WORKERS` is not a positive integer.
    """
    raw = os.environ.get("TAP_WEB_WORKERS", "").strip()
    if not raw:
        return DEFAULT_WORKERS
    try:
        count = int(raw)
    except ValueError as exc:
        raise ValueError(f"TAP_WEB_WORKERS={raw!r} is not an integer") from exc
    if count < 1:
        raise ValueError(f"TAP_WEB_WORKERS={raw!r} must be at least 1")
    return count


#: Directory the gunicorn worker heartbeat file is created in (`worker_tmp_dir`).
#:
#: Authored here ONCE and read by `docker/gunicorn.conf.py`; the compose `tmpfs:` entry
#: that makes this path RAM-backed names the same literal, and a test compares the two
#: rather than trusting them to stay equal (`tap/tests/test_serving_stack.py`). YAML
#: cannot import Python, so the mount target cannot literally call this constant — but a
#: verified copy is not a second derivation.
#:
#: Why not the default (`None`, i.e. the container's `/tmp`): every heartbeat is a
#: filesystem metadata write (`os.utime` on the open fd — `gunicorn/workers/workertmp.py`
#: 23.0.0), and `/tmp` here is the overlay root, verified from `/proc/mounts` inside a
#: running web container 2026-09-17: there is no separate tmpfs for `/tmp`. RAM is the
#: right home for a zero-byte file the arbiter reads on every liveness check.
#:
#: Why not `/dev/shm`, the folklore answer: that is POSIX shared memory's namespace with
#: a 64MB default budget shared with anything else in the container that wants shared
#: memory. The heartbeat file needs none of that budget — `workertmp.py` creates it with
#: `tempfile.mkstemp` and unlinks it immediately, so it holds one inode and zero bytes —
#: it needs a RAM-backed directory that is ours (tap#504, ruled 2026-09-17).
WORKER_TMP_DIR = "/run/tap-gunicorn"


def worker_tmp_dir() -> str:
    """Return the heartbeat directory, refusing to start if it is not there.

    Fails closed, deliberately and early. gunicorn already refuses a missing
    `worker_tmp_dir` (`workertmp.py` raises `RuntimeError("%s doesn't exist. Can't create
    workertmp.")`), but it does so when the FIRST WORKER FORKS, several seconds and one
    Django import into boot. Calling this from the config file moves the same refusal to
    config-load time and attaches a message naming what to mount.

    A missing directory means the RAM-backed mount is absent, and the alternative to
    refusing is serving on a silently disk-backed heartbeat — a configuration that reads
    as fixed and is not.

    Returns:
        The absolute path gunicorn should create heartbeat files in.

    Raises:
        RuntimeError: if the configured directory does not exist.
    """
    path = os.environ.get("TAP_WORKER_TMP_DIR", "").strip() or WORKER_TMP_DIR
    if not os.path.isdir(path):
        raise RuntimeError(
            f"gunicorn worker_tmp_dir {path!r} does not exist. It is declared as a tmpfs mount in "
            "docker-compose.yml; a runtime that does not use that compose file must mount a small "
            "RAM-backed directory at this path (or point TAP_WORKER_TMP_DIR at one). "
            "See specs/spec-tap-serving.md req-tap-serving-server-5."
        )
    return path
