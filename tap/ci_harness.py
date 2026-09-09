"""Resolve the core harness a plugin's per-repo CI runs against — the plugin's declared floor.

``req-tap-plugin-extdev-repo-ci-7``: a plugin PR's boot-and-test checks out core AT the lower
bound of the plugin's ``requires_tap`` range, because a harness above the floor does not prove
the floor. A plugin that wants a newer core narrows its claim by raising the floor. The harness
is therefore a *released* core (tag ``v<floor>``), resolved to a commit SHA so the run is
reproducible and the summary can say which core it was. ``--override`` is the one other road —
the nightly's ``main`` (a compatibility forecast, a different question) and debugging — never a
PR default.

Stdlib + ``packaging`` only: it runs on a bare runner before core is on the path (the same
constraint as ``tap.core_version``, whose specifier parser this reuses).

Usage:
    python -m tap.ci_harness --manifest tap_plugin/<slug>/tap-plugin.toml --repo owner/tap
    python -m tap.ci_harness --manifest … --repo owner/tap --override main

Prints ``key=value`` lines (``ref``, ``source``, ``floor``) to stdout and, when
``$GITHUB_OUTPUT`` is set, appends them there. Exit 1 with the reason on stderr when no floor
is declared, the floor is not a released core, or the override does not resolve.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

from tap.core_version import parse_requires_tap

_FLOOR_OPERATORS = (">=", "==", "~=", "===")


class HarnessResolutionError(Exception):
    """The harness for this plugin cannot be determined; the message says why."""


def floor_of(requires_tap: str) -> str:
    """Return the lower-bound version named by a ``requires_tap`` specifier.

    The floor is the version of the ``>=`` (or ``==`` / ``~=``) clause. A range with no lower
    bound (``<0.2``) names no core to test against and is refused; so is a range with two
    (``>=0.1.2,>=0.1.4`` is a contradiction the author should resolve, not the lane).
    """
    spec = parse_requires_tap(requires_tap)
    floors = [s.version for s in spec if s.operator in _FLOOR_OPERATORS]
    if not floors:
        raise HarnessResolutionError(
            f"requires_tap = {requires_tap!r} declares no lower bound — the PR run tests the floor, so the range "
            f'needs a ">=<released core version>" clause'
        )
    if len(floors) > 1:
        raise HarnessResolutionError(f"requires_tap = {requires_tap!r} declares more than one lower bound: {floors}")
    return floors[0]


def read_requires_tap(manifest_path: Path) -> str | None:
    """Return the manifest's ``requires_tap`` string, or None when it declares no floor."""
    with manifest_path.open("rb") as fh:
        data = tomllib.load(fh)
    value = data.get("requires_tap")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HarnessResolutionError(f"requires_tap in {manifest_path} must be a non-empty string, got {value!r}")
    return value


def ls_remote(repo_url: str, ref: str) -> str | None:
    """Return the SHA ``ref`` resolves to on the remote (tag or branch), or None if absent."""
    proc = subprocess.run(
        ["git", "ls-remote", repo_url, ref],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in proc.stdout.splitlines():
        sha, _, name = line.partition("\t")
        if name in (ref, f"refs/tags/{ref}", f"refs/heads/{ref}", f"refs/tags/{ref}^{{}}"):
            return sha.strip()
    return None


def resolve(
    manifest_path: Path,
    *,
    repo: str,
    override: str | None = None,
    remote: str | None = None,
    resolver: Callable[[str, str], str | None] | None = None,
) -> dict[str, str]:
    """Return ``{"ref": <sha>, "source": "floor"|"override", "floor": <version or "">}``.

    Args:
        manifest_path: the plugin's in-package ``tap-plugin.toml``.
        repo: ``owner/name`` of the core repository.
        override: an explicit ref (the nightly's ``main``, a debug SHA); when given, the floor
            is not consulted.
        remote: the clone URL to resolve against (default ``https://github.com/<repo>.git``).
        resolver: injectable ``(repo_url, ref) -> sha | None`` for tests (default: ``ls_remote``).
    """
    look_up = resolver or ls_remote
    repo_url = remote or f"https://github.com/{repo}.git"
    if override:
        sha = look_up(repo_url, override)
        if sha is None:
            raise HarnessResolutionError(f"harness override {override!r} does not resolve on {repo_url}")
        return {"ref": sha, "source": "override", "floor": ""}

    requires_tap = read_requires_tap(manifest_path)
    if requires_tap is None:
        raise HarnessResolutionError(
            f"{manifest_path} declares no requires_tap — the PR run tests the plugin's declared floor "
            f'(req-tap-plugin-extdev-repo-ci-7). Declare requires_tap = ">=<released core version>" '
            f"(a tap release tag v<version>), or pass harness_ref for a one-off run against another core"
        )
    floor = floor_of(requires_tap)
    tag = f"v{floor}"
    sha = look_up(repo_url, tag)
    if sha is None:
        raise HarnessResolutionError(
            f"requires_tap floor {floor} (from {requires_tap!r}) is not a released core: no tag {tag} on {repo_url}. "
            f"A floor must name a release; raise or lower it to one that exists"
        )
    return {"ref": sha, "source": "floor", "floor": floor}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tap.ci_harness", description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", type=Path, required=True, help="the plugin's in-package tap-plugin.toml")
    parser.add_argument("--repo", required=True, help="owner/name of the core repository")
    parser.add_argument("--override", default="", help="explicit harness ref (nightly / debugging only)")
    parser.add_argument("--remote", default="", help="clone URL to resolve against (default: github.com/<repo>)")
    args = parser.parse_args(argv)
    try:
        out = resolve(args.manifest, repo=args.repo, override=args.override or None, remote=args.remote or None)
    except HarnessResolutionError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"::error::cannot resolve the core harness: {exc}", file=sys.stderr)
        return 1
    lines = [f"{key}={value}" for key, value in out.items()]
    print("\n".join(lines))
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
