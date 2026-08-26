"""Host-runnable, pure-stdlib helper for ``spawn-session --dev-plugins``.

Derives a **mixed editable+git boot profile** from a base profile (the plugin
workspace of ``spec-dev-plugin-workspace.md``): each ``--dev-plugins`` slug is a
*selector into the base profile's ``install`` list*, not a source in itself. The
base profile is the source authority — every git install entry already carries the
exact ``source.url`` / ``source.rev`` / ``source.credential``. For each named slug we
clone that exact repo at that rev into ``<worktree>/_dev-plugins/<slug>`` and flip its
source ``git`` → ``editable`` (path → the nested checkout); every other plugin stays
git-pinned. The slug is never used to *derive* a URL (that would hardcode the org/naming
and break forks, renames, and cross-org product repos — ``req-dev-workspace-spawn-5``).

Host-runnable, pure stdlib (``json``/``subprocess``/``pathlib``), like ``tap.boot_pointer``:
``spawn-session.sh`` runs it venv-free after the worktree exists. It reuses
``boot_pointer``'s stdlib credential + ``GIT_ASKPASS`` helpers so the token never touches
the URL, argv, or filesystem.

Usage:
    python -m tap.dev_workspace --base-profile samsite --dev-plugins compliance_core \\
        --worktree /path/to/worktree
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tap.boot_naming import profile_path
from tap.boot_pointer import BootPointerError, _git_askpass, _resolve_token
from tap.git_invocation import run_git

#: Nested location (under the harness worktree, gitignored) for editable dev-plugin
#: checkouts — the "nested first-cut" decision (spec-dev-plugin-workspace.md).
DEV_PLUGINS_DIR = "_dev-plugins"


class DevWorkspaceError(Exception):
    """Raised on an unresolvable slug, a non-git source, or a clone failure."""


@dataclass(frozen=True)
class CloneSpec:
    """A dev plugin to clone editable: the git source resolved from the base profile."""

    slug: str
    url: str
    rev: str
    credential: str | None


def derive_profile(profile: dict[str, Any], dev_slugs: list[str]) -> tuple[dict[str, Any], list[CloneSpec]]:
    """Return (derived profile, clone specs) for a base profile + the slugs to make editable.

    The returned profile is a deep copy with each named git-sourced slug flipped to an
    ``editable`` source at ``_dev-plugins/<slug>``. A slug already ``editable``/``path`` is
    left as-is (idempotent, no clone). Raises ``DevWorkspaceError`` if a named slug is absent
    from the base profile's install list, or present but not a git/editable source.
    """
    derived = copy.deepcopy(profile)
    plugins = derived.get("install", {}).get("plugins", [])
    by_slug = {p.get("slug"): p for p in plugins}

    specs: list[CloneSpec] = []
    for slug in dev_slugs:
        entry = by_slug.get(slug)
        if entry is None:
            available = ", ".join(sorted(s for s in by_slug if s)) or "(none)"
            raise DevWorkspaceError(
                f"--dev-plugins slug '{slug}' is not a plugin in the base profile's install list "
                f"[{available}]. A dev plugin must already be declared in the profile you are "
                f"overriding — the profile is the source authority for its url/rev/credential."
            )
        source = entry.get("source", {})
        stype = source.get("type")
        if stype in ("editable", "path"):
            # Already local in the base profile — nothing to resolve or clone.
            continue
        if stype != "git":
            raise DevWorkspaceError(
                f"--dev-plugins slug '{slug}' has source type '{stype}', expected 'git' (or already "
                f"editable). Only a git-sourced plugin can be resolved to a clone URL."
            )
        url = source.get("url")
        rev = source.get("rev")
        if not url or not rev:
            raise DevWorkspaceError(
                f"--dev-plugins slug '{slug}' git source is missing url/rev (url={url!r}, rev={rev!r})."
            )
        specs.append(CloneSpec(slug=slug, url=url, rev=rev, credential=source.get("credential")))
        entry["source"] = {"type": "editable", "path": f"{DEV_PLUGINS_DIR}/{slug}"}

    base_desc = derived.get("description", "")
    derived["description"] = f"[dev workspace] editable: {', '.join(dev_slugs)} — {base_desc}"
    return derived, specs


def _run_git(args: list[str], env: dict[str, str]) -> None:
    """Run git for the dev-workspace clone, raising DevWorkspaceError on failure."""
    run_git(args, env, error_cls=DevWorkspaceError)


def clone_editable(spec: CloneSpec, worktree: Path, secrets_root: Path | None) -> Path:
    """Clone *spec* into ``<worktree>/_dev-plugins/<slug>`` at its rev. Idempotent.

    A blobless clone + ``checkout <rev>`` gives a real working tree at the pinned rev while
    staying light, and resolves a tag, branch, or commit sha uniformly. The credential (a
    private repo's read-only PAT) is fed via ``GIT_ASKPASS`` — never the URL or argv.
    """
    dest = worktree / DEV_PLUGINS_DIR / spec.slug
    if dest.exists():
        return dest  # reuse an existing checkout — do not clobber the developer's work
    dest.parent.mkdir(parents=True, exist_ok=True)

    token_tuple = _resolve_token(spec.credential, secrets_root)
    with _git_askpass(token_tuple) as overlay:
        env = {**os.environ, **overlay}
        _run_git(["clone", "--filter=blob:none", "--no-checkout", spec.url, str(dest)], env)
        _run_git(["-C", str(dest), "checkout", spec.rev], env)
    return dest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tap.dev_workspace",
        description="Derive a mixed editable+git boot profile for a plugin dev workspace.",
    )
    parser.add_argument("--base-profile", required=True, help="base profile id (boot/<id>.boot.json in the worktree)")
    parser.add_argument("--dev-plugins", required=True, help="comma-separated plugin slugs to make editable")
    parser.add_argument("--worktree", required=True, type=Path, help="the session worktree root")
    parser.add_argument(
        "--secrets-root",
        type=Path,
        default=None,
        help="secrets root for resolving credentials (default: $TAP_SECRETS_ROOT or ~/tap-secrets)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    worktree = args.worktree.resolve()

    base_path = profile_path(worktree / "boot", args.base_profile)
    if not base_path.is_file():
        print(f"error: base profile not found: {base_path}", file=sys.stderr)
        return 1

    dev_slugs = [s.strip() for s in args.dev_plugins.split(",") if s.strip()]
    if not dev_slugs:
        print("error: --dev-plugins is empty", file=sys.stderr)
        return 1

    try:
        profile = json.loads(base_path.read_text(encoding="utf-8"))
        derived, specs = derive_profile(profile, dev_slugs)
        for spec in specs:
            clone_editable(spec, worktree, args.secrets_root)
    except (DevWorkspaceError, BootPointerError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out_id = f"{args.base_profile}__dev"
    out_path = profile_path(worktree / "boot", out_id)
    out_path.write_text(json.dumps(derived, indent=2) + "\n", encoding="utf-8")

    # stdout carries ONLY the staged profile path (spawn reads it to set BOOT_PROFILE).
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
