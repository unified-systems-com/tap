"""Stdlib-only primitives for invoking git with a credential.

Shared by both git-authenticating paths, which live on opposite sides of a real
import boundary:

- **In-container, venv-present** — ``tap/plugin_source_auth.py`` (the install
  system): resolves a declared ``tap_plugins.source`` credential, validating the
  envelope kind AND the ``data`` block against the ``github_pat`` source schema
  (jsonschema, venv-only), then installs plugins.
- **On the host, bare ``python3``** — ``tap/boot_pointer.py`` stage-0 and
  ``tap/dev_workspace.py``: they run during ``spawn-session``, *before the
  container exists*, so they cannot import ``tap.jsonfiles`` /
  ``tap.runtime_secrets`` / ``tap.plugin_source_auth`` (all reach
  ``import jsonschema`` at module scope).

That boundary excuses the host side's *reduced validation*. It never excused
duplicating the credential-handoff mechanism itself, which is pure stdlib — yet
the askpass script and its temp-file context manager were byte-identical copies
in ``plugin_source_auth`` and ``boot_pointer``, on the never-leak-the-token
surface where a future hardening applied to one copy would silently miss the
other (2026-08 code-clone sweep, finding S1). This module is that mechanism's
one home, importable from either side.

Uses only ``os``/``stat``/``tempfile``/``subprocess``/``contextlib`` — adding a
non-stdlib import here would break the host tools at spawn time.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager

# The one kind a git source credential may declare — shared type axis with the
# github_core collector, though that consumer carries a different data schema
# (req-tap-plugin-arch-source-secret-1).
GITHUB_PAT_KIND = "github_pat"

DEFAULT_HOST = "github.com"
DEFAULT_USERNAME = "x-access-token"

# The GIT_ASKPASS helper git invokes. git calls it with a single argument — the
# prompt string ("Username for '...': " / "Password for '...': ") — and reads the
# answer from stdout. The script carries NO secret; it echoes the username/token
# the env overlay supplies, so the token never touches the filesystem.
ASKPASS_SCRIPT = (
    "#!/bin/sh\n"
    'case "$1" in\n'
    '  Username*) printf "%s" "$TAP_GIT_USERNAME" ;;\n'
    '  *)         printf "%s" "$TAP_GIT_PASSWORD" ;;\n'
    "esac\n"
)


@contextmanager
def askpass_env(*, username: str, token: str, prefix: str = "tap-askpass-") -> Iterator[dict[str, str]]:
    """Yield an env overlay that feeds a git credential via ``GIT_ASKPASS``.

    Writes a short-lived, owner-only (``0700``) askpass script that reads the
    username/token from the environment, and yields the env keys to merge into
    the git subprocess. The token rides in ``TAP_GIT_PASSWORD`` (child env only),
    never in the URL, the argument list, or the script body.
    ``GIT_TERMINAL_PROMPT=0`` forbids an interactive fallback so a bad/absent
    credential fails fast instead of hanging. The script is deleted on exit.

    Args:
        username: The git HTTPS username (for a PAT, typically a fixed sentinel).
        token: The secret. Never logged, never written to disk.
        prefix: Temp-file prefix, so a leaked file from a crashed run is
            attributable to its stage (e.g. stage-0 vs the install system).
    """
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".sh")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(ASKPASS_SCRIPT)
        os.chmod(path, stat.S_IRWXU)  # rwx------ : only this user runs it
        yield {
            "GIT_ASKPASS": path,
            "GIT_TERMINAL_PROMPT": "0",
            "TAP_GIT_USERNAME": username,
            "TAP_GIT_PASSWORD": token,
        }
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def run_git(
    args: list[str],
    env: dict[str, str],
    *,
    error_cls: type[Exception],
) -> subprocess.CompletedProcess[bytes]:
    """Run ``git <args>`` with ``env``, raising ``error_cls`` on a non-zero exit.

    Output is captured (never inherited), so git's stderr cannot interleave into
    a caller's structured output. The caller supplies its own exception type so
    each tool keeps its domain error while sharing this mechanism.

    Args:
        args: Arguments after ``git``.
        env: The complete child environment (callers merge :func:`askpass_env`'s
            overlay into it) — note this REPLACES the parent environment.
        error_cls: Exception type raised on failure.
    """
    result = subprocess.run(["git", *args], capture_output=True, env=env)  # noqa: S603
    if result.returncode != 0:
        raise error_cls(
            f"git {' '.join(args)} failed (exit {result.returncode}): {result.stderr.decode(errors='replace').strip()}"
        )
    return result
