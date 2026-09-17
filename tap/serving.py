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

import math
import os
import sys

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


#: Filesystem types that mean "this directory is RAM, not a disk".
#:
#: `tmpfs` is what a compose `tmpfs:` mount and a Kubernetes `emptyDir{medium: Memory}`
#: both produce; `ramfs` is its unbounded elder, which some minimal runtimes still use.
#: Anything else — `overlay`, `ext4`, `xfs`, a virtiofs share — is a disk.
RAM_BACKED_FILESYSTEMS = frozenset({"tmpfs", "ramfs"})


def filesystem_type(path: str) -> str | None:
    """Return the filesystem type `path` lives on, or None when that is not observable.

    Three states, never two. Python exposes no `statfs`, so this reads Linux's
    `/proc/self/mountinfo` and takes the LONGEST mount point containing `path` — the one
    that actually governs it. Off Linux, or with `/proc` unavailable, the answer is
    genuinely unknown and the caller must not read that as "disk" OR as "RAM".

    Args:
        path: An existing absolute path.

    Returns:
        The filesystem type (e.g. `tmpfs`, `overlay`, `ext4`), or None if `/proc/self/mountinfo`
        cannot be read or names no mount containing `path`.
    """
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return None

    real = os.path.realpath(path)
    best_point = ""
    best_type: str | None = None
    for line in lines:
        # `<id> <parent> <maj:min> <root> <mount point> <options> [tags...] - <fstype> <source> ...`
        pre, sep, post = line.partition(" - ")
        if not sep:
            continue
        fields = pre.split()
        post_fields = post.split()
        if len(fields) < 5 or not post_fields:
            continue
        point = fields[4].replace("\\040", " ")
        if (real == point or real.startswith(point.rstrip("/") + "/")) and len(point) >= len(best_point):
            best_point, best_type = point, post_fields[0]
    return best_type


def worker_tmp_dir() -> str:
    """Return the heartbeat directory, refusing a missing one and an observably disk-backed one.

    Refuses early, and refuses on what it can see — the summary line says "observably"
    because the third state below is real and this function is not fail-closed across all
    three. gunicorn already refuses a missing
    `worker_tmp_dir` (`workertmp.py` raises `RuntimeError("%s doesn't exist. Can't create
    workertmp.")`), but it does so when the FIRST WORKER FORKS, several seconds and one
    Django import into boot. Calling this from the config file moves the same refusal to
    config-load time and attaches a message naming what to mount.

    **Existence is not the property we want.** A directory that exists satisfies a presence
    check while sitting on the disk-backed overlay this setting exists to leave — and
    `TAP_WORKER_TMP_DIR` makes that one environment variable away. So the filesystem type
    is checked against its source rather than assumed from the path's presence, and the
    three states are kept distinct:

    - RAM-backed (`tmpfs` / `ramfs`) — proceed.
    - Observably something else — refuse. A configuration that reads as fixed and is not
      is worse than one that is plainly broken.
    - Not observable (no readable `/proc/self/mountinfo`) — proceed, and say so on stderr.
      Absence of evidence is not evidence of a disk, and the outcome in that state is the
      pre-existing status quo rather than a new harm. It is also the door a hardened
      runtime that masks `/proc` could walk a disk-backed directory through, so whether
      this state should refuse instead is an open decision, not a settled one: tap#533.

    Returns:
        The absolute path gunicorn should create heartbeat files in.

    Raises:
        RuntimeError: if the configured directory does not exist, or observably is not
            RAM-backed.
    """
    path = os.environ.get("TAP_WORKER_TMP_DIR", "").strip() or WORKER_TMP_DIR
    if not os.path.isdir(path):
        raise RuntimeError(
            f"gunicorn worker_tmp_dir {path!r} does not exist. It is declared as a tmpfs mount in "
            "docker-compose.yml; a runtime that does not use that compose file must mount a small "
            "RAM-backed directory at this path (or point TAP_WORKER_TMP_DIR at one). "
            "See specs/spec-tap-serving.md req-tap-serving-server-5."
        )

    fs_type = filesystem_type(path)
    if fs_type is None:
        print(
            f"NOTE: cannot observe the filesystem behind gunicorn worker_tmp_dir {path!r} "
            "(no /proc/self/mountinfo) — proceeding without confirming it is RAM-backed.",
            file=sys.stderr,
        )
    elif fs_type not in RAM_BACKED_FILESYSTEMS:
        raise RuntimeError(
            f"gunicorn worker_tmp_dir {path!r} is on a {fs_type!r} filesystem, not RAM "
            f"({'/'.join(sorted(RAM_BACKED_FILESYSTEMS))}). Every worker heartbeat is a filesystem "
            "metadata write and the arbiter kills a worker whose heartbeat goes stale, so this path "
            "must be a RAM-backed mount — docker-compose.yml declares one; other runtimes must mount "
            "their own. See specs/spec-tap-serving.md req-tap-serving-server-5."
        )
    return path


# ---------------------------------------------------------------------------
# The four time budgets (`req-tap-serving-budgets`)
#
# A request's life is governed by four timers owned by four different layers, and
# they only mean anything as a set. Stated once here, in the order they bite:
#
#   1. STATEMENT bound    — PostgreSQL `statement_timeout`, PER STATEMENT.
#   2. WORKER TIMEOUT     — gunicorn's `timeout`; the arbiter's heartbeat watchdog,
#                           and for a SYNC worker the de-facto whole-request deadline.
#   3. GRACEFUL DRAIN     — gunicorn's `graceful_timeout`; how long in-flight work
#                           gets after the MASTER is told to stop.
#   4. CONTAINER STOP     — compose `stop_grace_period`; how long Docker waits before
#                           SIGKILL. It is the outermost, so it must be the largest of
#                           the shutdown pair (3 and 4).
#
# Derived, not re-typed: (2) is computed from (1) here, so an operator who moves the
# statement bound moves the watchdog with it and the two can never disagree silently.
# (3) and (4) are authored here and the compose file's value is verified against the
# constant by a test.
# ---------------------------------------------------------------------------

#: PostgreSQL's duration units. A bare integer means milliseconds; `0` means DISABLED.
#: https://www.postgresql.org/docs/current/config-setting.html
_PG_DURATION_UNITS = {"us": 1e-6, "ms": 1e-3, "s": 1.0, "min": 60.0, "h": 3600.0, "d": 86400.0}


def postgres_duration_seconds(raw: str) -> float | None:
    """Parse a PostgreSQL duration setting into seconds.

    Three states, never two: a duration, DISABLED (PostgreSQL's `0`, meaning no bound at
    all), or a refusal. A value we cannot parse is not quietly treated as the default —
    the whole point of parsing it is that another timer is derived from it.

    Args:
        raw: A PostgreSQL duration string, e.g. `30s`, `500ms`, `2min`, or a bare integer
            (milliseconds, per PostgreSQL's own rule).

    Returns:
        The duration in seconds, or None when the setting is disabled (`0`).

    Raises:
        ValueError: if the value is not a duration PostgreSQL would accept.
    """
    text = raw.strip().lower()
    if not text:
        raise ValueError("empty PostgreSQL duration")
    for unit in sorted(_PG_DURATION_UNITS, key=len, reverse=True):
        if text.endswith(unit):
            number, factor = text[: -len(unit)].strip(), _PG_DURATION_UNITS[unit]
            break
    else:
        number, factor = text, _PG_DURATION_UNITS["ms"]  # bare integer == milliseconds
    try:
        amount = float(number)
    except ValueError as exc:
        raise ValueError(f"{raw!r} is not a PostgreSQL duration (e.g. '30s', '500ms', '2min')") from exc
    if amount < 0:
        raise ValueError(f"{raw!r} is a negative duration")
    return None if amount == 0 else amount * factor


#: Budget 1, the STATEMENT bound: PostgreSQL aborts any single statement that runs longer.
#:
#: Authored here rather than in `tap/settings.py` because it is now an INPUT to the worker
#: timeout, which the gunicorn master must compute before Django exists. Django settings
#: read this same function, so there is one value, not two
#: (`req-grid-traversal-exec-resource-bounds.sec` still owns *why* the bound exists).
SEARCH_STATEMENT_TIMEOUT_DEFAULT = "30s"


def search_statement_timeout() -> str:
    """Return the configured PostgreSQL `statement_timeout` for the search connection."""
    return os.environ.get("TAP_SEARCH_STATEMENT_TIMEOUT", "").strip() or SEARCH_STATEMENT_TIMEOUT_DEFAULT


#: Everything in a request that is NOT the single slowest statement: connection
#: acquisition, the OTHER statements a view issues, serialization, template rendering.
#:
#: Authored as a headroom rather than as a total, so the relationship to the statement
#: bound survives the operator moving it.
REQUEST_OVERHEAD_HEADROOM_SECONDS = 30


def worker_timeout() -> int:
    """Return budget 2: gunicorn's `timeout`, derived from the statement bound.

    **What this timer actually is.** The arbiter compares `now - worker.tmp.last_update()`
    against `cfg.timeout` and sends SIGABRT when it is exceeded (`gunicorn/arbiter.py`
    23.0.0, `murder_workers`). It is a HEARTBEAT watchdog, not a request deadline — but a
    sync worker only heartbeats between requests (`workers/sync.py` notifies at the top of
    its accept loop), so for this worker class the watchdog IS the whole-request deadline.
    That coupling is why this number is derived from a database bound at all.

    **What it is not.** It is not a guarantee that a request fits. A single response can
    issue several statements — the Gryphon path query, then the Entity fetch, then the Edge
    fetch — and `statement_timeout` applies to EACH. The bounds do not compose into a
    whole-request budget, so `statement_timeout * N` can exceed this timer and such a
    request is killed by the watchdog. That is a deliberate choice: N is not knowable
    across views, and a watchdog sized for the worst imaginable N would no longer detect a
    wedged worker. The missing whole-request budget is tracked as tap#530.

    Returns:
        Seconds of silence after which the arbiter kills a worker.

    Raises:
        ValueError: if `TAP_WEB_TIMEOUT` is not a positive integer, if it does not exceed
            the statement bound (the two would then disagree), or if the statement bound is
            disabled and no explicit timeout was given (nothing left to derive from).
    """
    bound = postgres_duration_seconds(search_statement_timeout())

    explicit = os.environ.get("TAP_WEB_TIMEOUT", "").strip()
    if explicit:
        try:
            value = int(explicit)
        except ValueError as exc:
            raise ValueError(f"TAP_WEB_TIMEOUT={explicit!r} is not an integer") from exc
        if value < 1:
            raise ValueError(f"TAP_WEB_TIMEOUT={explicit!r} must be at least 1")
        if bound is not None and value <= bound:
            raise ValueError(
                f"TAP_WEB_TIMEOUT={value}s does not exceed statement_timeout={bound:g}s, so the arbiter "
                "would kill a worker while PostgreSQL still permits the statement it is waiting on. "
                "Raise the timeout or lower TAP_SEARCH_STATEMENT_TIMEOUT."
            )
        return value

    if bound is None:
        raise ValueError(
            "TAP_SEARCH_STATEMENT_TIMEOUT is disabled ('0'), so there is no database bound to derive "
            "the gunicorn worker timeout from. Set TAP_WEB_TIMEOUT explicitly, and know that a request "
            "may then outlive it. See specs/spec-tap-serving.md req-tap-serving-budgets."
        )
    return math.ceil(bound) + REQUEST_OVERHEAD_HEADROOM_SECONDS


#: Budget 3, the GRACEFUL DRAIN: how long in-flight work gets once the MASTER is stopping.
#:
#: Used by exactly one code path — `Arbiter.stop()` — which SIGTERMs the workers, waits up
#: to this long, then SIGKILLs whatever is left (`gunicorn/arbiter.py` 23.0.0 line ~390).
#: It governs the master's own shutdown and NOTHING else: a source reload does not enter
#: `stop()`, and this timer cannot produce the SIGABRT seen there (see `worker_timeout`).
#:
#: It is deliberately SHORTER than the watchdog, which is a decision, not an oversight: a
#: request is permitted to run for `worker_timeout()` seconds, so a shutdown CAN cut one
#: short. TAP accepts that. A restart must not wait out a pathological request; the v0
#: request path is overwhelmingly read-only, writes go through the service layer in short
#: transactions, and a connection lost mid-transaction is rolled back by PostgreSQL rather
#: than left half-applied. The cost is a dropped response, not a corrupt grid.
GRACEFUL_DRAIN_SECONDS = 20

#: Budget 4, the CONTAINER STOP allowance: what compose gives the container before SIGKILL.
#:
#: Must exceed the drain, or Docker kills the container mid-drain and budget 3 is fiction —
#: which is what Docker's 10s default was doing to a 30s drain. The margin above the drain
#: is for the entrypoint's own teardown of the steady_queue supervisor.
#:
#: Whether the signal REACHES gunicorn through the entrypoint's process tree is a separate,
#: open question owned by tap#502 (PID 1 and signal delivery). This constant sizes the
#: allowance; it does not claim the delivery works.
CONTAINER_STOP_GRACE_SECONDS = 30
