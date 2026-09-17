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
    """Return the heartbeat directory, refusing to start unless it is really there and really RAM.

    Fails closed, deliberately and early. gunicorn already refuses a missing
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
    - Not observable (no `/proc/self/mountinfo`, i.e. not Linux) — proceed, and say so on
      stderr. Absence of evidence is not evidence of a disk; refusing here would break
      every non-Linux developer for a fact nobody could read.

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
