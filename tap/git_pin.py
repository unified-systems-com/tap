"""Git plugin pins: does a source's tag still name the commit it pins? (tap#512, epic tap#493).

A git plugin source pins two things: ``rev``, the human-readable tag, and ``commit``, the
40-hex SHA that decides what gets installed. Tags are mutable — a force-pushed tag
installs different code under an unchanged profile — so the SHA is the authority and the
tag is a claim about it. This module checks that claim, and is the ONE resolver of
"what commit does this tag name" (the adopt tooling reuses it, tap#513).

Four outcomes, never collapsed:

- ``matches``: the tag resolves to ``commit``.
- ``moved``: the tag resolves to a different commit (or a SHA ``rev`` differs from ``commit``).
- ``missing``: the forge answered and has no such tag.
- ``not_observable``: the forge could not be asked (network, auth, timeout, no ``git``).
  Absence of an answer is not an answer — this is never rendered as matches or missing.

Annotated tags: ``git ls-remote`` returns the tag OBJECT's id for ``refs/tags/<t>`` and the
commit only on the peeled ``refs/tags/<t>^{}`` line — which it prints ONLY when that
pattern is requested explicitly (probed against git/git ``v2.44.0``, 2026-09-17). Both
patterns are always requested, and the peeled line wins.

Host-runnable, stdlib only (``tap/host_syntax_floor.py`` ``DECLARED_HOST_MODULES``): the
adopt tooling runs under bare ``python3``. Credentials ride ``GIT_ASKPASS`` via
:mod:`tap.git_invocation`, never the URL or argv (req-tap-plugin-arch-source-secret-4).

CLI (the author-time check): ``python3 -m tap.git_pin --check boot/*.boot.json`` exits 0 when
every git source pins a ``commit`` its tag still names, 1 on any disagreement or unpinned
source, 2 when nothing disagreed but something could not be observed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tap import git_invocation

TAG_MATCHES = "matches"
TAG_MOVED = "moved"
TAG_MISSING = "missing"
TAG_NOT_OBSERVABLE = "not_observable"

# A full, lowercase git commit id. Spelled again as the schema `pattern` on
# install.plugins[].source.commit — see TAP-KNOWN-DUPE(boot-source-input-patterns) in
# tap/preboot.py, which re-exports this constant rather than copying it.
COMMIT_SHA_PATTERN = r"[0-9a-f]{40}"
_COMMIT_SHA_RE = re.compile(rf"\A{COMMIT_SHA_PATTERN}\Z")

#: Seconds to wait for the forge before calling the tag not observable. Boot must not
#: stall on an unreachable forge: an unobservable tag warns and boot carries on.
DEFAULT_TIMEOUT = 20.0


@dataclass(frozen=True)
class TagCheck:
    """The outcome of checking one pin.

    Attributes:
        state: One of ``TAG_MATCHES`` / ``TAG_MOVED`` / ``TAG_MISSING`` / ``TAG_NOT_OBSERVABLE``.
        observed: The commit the tag resolved to, when the forge answered with one.
        detail: Why the state is what it is (git's stderr for ``not_observable``). Carries
            no credential: the token rides the child env only, and source URLs carry no
            userinfo (tap#492).
    """

    state: str
    observed: str | None = None
    detail: str = ""


def is_commit_sha(value: object) -> bool:
    """True when *value* is a full lowercase 40-hex commit id."""
    return isinstance(value, str) and bool(_COMMIT_SHA_RE.match(value))


def peeled_commit(ls_remote_output: str, tag: str) -> str | None:
    """The commit ``tag`` names in ``git ls-remote`` output: peeled line first, else the direct one.

    A lightweight tag has only the direct line (already a commit); an annotated tag's direct
    line is the tag object and its ``^{}`` line is the commit.
    """
    direct: str | None = None
    peeled: str | None = None
    for line in ls_remote_output.splitlines():
        sha, _, ref = line.strip().partition("\t")
        if ref == f"refs/tags/{tag}^{{}}":
            peeled = sha
        elif ref == f"refs/tags/{tag}":
            direct = sha
    return peeled or direct


def _run_ls_remote(args: list[str], env: dict[str, str], timeout: float) -> subprocess.CompletedProcess[str]:
    """Run ``git ls-remote``. The single subprocess seam — tests replace it, never the network.

    ``cwd`` is a neutral directory: ls-remote needs no repository, but git still DISCOVERS one
    from the working directory, and a session worktree mounted into a container carries a
    ``.git`` file pointing at a host path — git then dies with "not a git repository" before
    it ever contacts the forge, which would read as not observable on every dev boot.
    """
    return subprocess.run(  # noqa: S603 — argv list, no shell; URL shape enforced upstream (tap#492)
        ["git", *args], capture_output=True, text=True, env=env, timeout=timeout, cwd=tempfile.gettempdir()
    )


def resolve_tag(
    url: str,
    tag: str,
    *,
    credential: tuple[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    runner: Callable[[list[str], dict[str, str], float], subprocess.CompletedProcess[str]] | None = None,
) -> TagCheck:
    """Ask the forge which commit ``tag`` names.

    Returns ``TagCheck`` with state ``matches`` and ``observed`` set when the tag exists
    (the caller compares), ``missing`` when the forge answered without it, and
    ``not_observable`` when it could not be asked.

    Args:
        url: The git source URL (https/ssh, no userinfo).
        tag: The tag name, without ``refs/tags/``.
        credential: ``(username, token)`` for a private repo, fed via ``GIT_ASKPASS``.
        timeout: Seconds before the forge counts as unreachable.
        runner: Test seam; defaults to running ``git``.
    """
    run = runner or _run_ls_remote
    args = ["ls-remote", "--tags", url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        if credential is None:
            result = run(args, env, timeout)
        else:
            username, token = credential
            with git_invocation.askpass_env(username=username, token=token, prefix="tap-pin-askpass-") as overlay:
                result = run(args, {**env, **overlay}, timeout)
    except subprocess.TimeoutExpired:
        return TagCheck(TAG_NOT_OBSERVABLE, detail=f"git ls-remote timed out after {timeout:g}s")
    except OSError as exc:
        return TagCheck(TAG_NOT_OBSERVABLE, detail=f"git ls-remote could not run: {exc}")
    if result.returncode != 0:
        return TagCheck(TAG_NOT_OBSERVABLE, detail=(result.stderr or "").strip() or f"exit {result.returncode}")
    observed = peeled_commit(result.stdout, tag)
    if observed is None:
        return TagCheck(TAG_MISSING, detail=f"no tag '{tag}' at {url}")
    return TagCheck(TAG_MATCHES, observed=observed)


def check_pin(
    url: str,
    rev: str,
    commit: str,
    *,
    credential: tuple[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    runner: Callable[[list[str], dict[str, str], float], subprocess.CompletedProcess[str]] | None = None,
) -> TagCheck:
    """Check that ``rev`` still names ``commit`` at ``url``.

    A ``rev`` that is itself a full SHA needs no forge: it matches or it does not.

    Args:
        url: The git source URL.
        rev: The pinned tag (or SHA).
        commit: The pinned 40-hex commit id.
        credential: ``(username, token)`` for a private repo.
        timeout: Seconds before the forge counts as unreachable.
        runner: Test seam for the ``git`` subprocess.
    """
    if is_commit_sha(rev):
        if rev == commit:
            return TagCheck(TAG_MATCHES, observed=rev)
        return TagCheck(TAG_MOVED, observed=rev, detail=f"rev is the commit {rev}, not {commit}")
    found = resolve_tag(url, rev, credential=credential, timeout=timeout, runner=runner)
    if found.state != TAG_MATCHES:
        return found
    if found.observed == commit:
        return found
    return TagCheck(TAG_MOVED, observed=found.observed, detail=f"tag '{rev}' names {found.observed}, not {commit}")


# --------------------------------------------------------------------------- #
# Author-time check (CLI)
# --------------------------------------------------------------------------- #


def _git_sources(profile: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    for entry in (profile.get("install") or {}).get("plugins", []):
        source = entry.get("source")
        if isinstance(source, dict) and source.get("type") == "git":
            yield str(entry.get("slug")), source


def check_profiles(
    paths: Iterable[Path],
    *,
    checker: Callable[[str, str, str], TagCheck] | None = None,
) -> tuple[int, list[str]]:
    """Check every git source in the given boot profiles; return ``(exit_code, report_lines)``.

    Exit 1 on any unpinned source (no ``commit``) or any ``moved``/``missing`` pair; else 2 if
    anything was ``not_observable``; else 0. Public repos only — the CLI resolves no
    credentials, so a private source reports ``not_observable`` rather than a false verdict.
    """
    check = checker or (lambda url, rev, commit: check_pin(url, rev, commit))
    failed = unobserved = False
    lines: list[str] = []
    for path in paths:
        profile = json.loads(path.read_text(encoding="utf-8"))
        for slug, source in _git_sources(profile):
            where = f"{path}: {slug}"
            commit = source.get("commit")
            if not is_commit_sha(commit):
                failed = True
                lines.append(f"FAIL {where}: rev '{source.get('rev')}' has no commit — pin the SHA beside it")
                continue
            result = check(str(source.get("url")), str(source.get("rev")), str(commit))
            if result.state == TAG_MATCHES:
                lines.append(f"ok   {where}: {source.get('rev')} = {commit}")
            elif result.state == TAG_NOT_OBSERVABLE:
                unobserved = True
                lines.append(f"???  {where}: could not verify {source.get('rev')} — {result.detail}")
            else:
                failed = True
                lines.append(f"FAIL {where}: {result.state} — {result.detail}")
    return (1 if failed else 2 if unobserved else 0), lines


def main(argv: list[str] | None = None) -> int:
    """CLI entry: ``python3 -m tap.git_pin --check <profile.boot.json>...``."""
    parser = argparse.ArgumentParser(prog="tap.git_pin", description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", nargs="+", type=Path, required=True, metavar="PROFILE")
    args = parser.parse_args(argv)
    code, lines = check_profiles(args.check)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
