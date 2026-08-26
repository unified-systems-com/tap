"""Host-runnable, pure-stdlib core for ``scripts/release-plugin.sh`` (req-dev-workspace-release).

A plugin release is one command: ``release-plugin <slug> <version>`` runs the conformance
gate + the plugin's tests, tags the plugin repo with an immutable ``v<version>``, and **bumps
every consuming boot profile's pinned rev** for that slug. This module owns the last, pure part
— the profile bump — so it is unit-testable with no git, network, or Django.

The boot profiles under ``boot/`` are the bill of materials: each git-sourced plugin entry pins
an exact ``source.rev``. Bumping is a plain JSON edit (these deployment-profile records carry no
inline integrity hash — that guard is for *in-package* boot records, one level up; see
``tap.boot_records``). We also refresh any ``vX.Y.Z`` occurrence inside the entry's human ``note``
so the prose does not silently drift stale.

Substrate-first ordering (``req-dev-workspace-release-3``) is the operator's discipline across
*calls*: release the substrate plugin first (this bumps its consumers' pins), then release the
consumers — by which point their profiles already carry the fresh substrate pin. Each single call
bumps every consumer of the one slug it releases, which is the mechanism that makes that ordering
hold.

Host-runnable, pure stdlib (``json``/``re``/``pathlib``), like ``tap.dev_workspace`` and
``tap.boot_pointer``: ``release-plugin.sh`` runs it venv-free.

Usage:
    python -m tap.plugin_release --slug compliance_core --version 0.2.0 --boot-dir boot
    python -m tap.plugin_release --slug compliance_core --version 0.2.0 --boot-dir boot --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tap.boot_naming import RECORD_SUFFIX

#: A release tag: ``v`` + a semver-ish core, optional pre-release / build suffix. Kept as a plain
#: regex (not ``packaging``) so this module stays stdlib-only and host-runnable venv-free.
_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


class PluginReleaseError(Exception):
    """Raised on a malformed version or an unreadable/malformed boot profile."""


@dataclass(frozen=True)
class ProfileBump:
    """One boot profile whose pinned rev for a slug was (or would be) advanced."""

    path: Path
    slug: str
    old_rev: str
    new_rev: str


def normalize_tag(version: str) -> str:
    """Return the canonical ``v<version>`` git tag for *version*.

    Accepts ``0.2.0`` or ``v0.2.0`` (both normalize to ``v0.2.0``). Raises
    ``PluginReleaseError`` on anything that is not a ``vMAJOR.MINOR.PATCH`` tag (with an
    optional pre-release/build suffix), so a typo never becomes a real tag.
    """
    candidate = version if version.startswith("v") else f"v{version}"
    if not _TAG_RE.match(candidate):
        raise PluginReleaseError(
            f"version {version!r} is not a valid release tag: expected vMAJOR.MINOR.PATCH "
            f"(e.g. '0.2.0' or 'v0.2.0'), optionally with a -pre/+build suffix."
        )
    return candidate


def _git_pin(entry: dict[str, Any]) -> str | None:
    """Return a plugin entry's pinned git rev, or ``None`` if it is not git-sourced."""
    source = entry.get("source", {})
    if source.get("type") != "git":
        return None
    rev = source.get("rev")
    return rev if isinstance(rev, str) else None


def _refresh_note(note: str, old_rev: str, new_rev: str) -> str:
    """Replace whole-token occurrences of *old_rev* in *note* with *new_rev*.

    Only rewrites tag-shaped old revs (``v...``); a commit-sha pin is left untouched in prose
    (it has no natural word boundary and the note rarely embeds a raw sha).
    """
    if not old_rev.startswith("v"):
        return note
    return re.sub(rf"(?<![0-9A-Za-z.]){re.escape(old_rev)}(?![0-9A-Za-z.])", new_rev, note)


def find_consumers(boot_dir: Path, slug: str) -> list[Path]:
    """Return the boot profiles under *boot_dir* that git-source *slug*, sorted by path."""
    consumers: list[Path] = []
    for path in sorted(boot_dir.glob(f"*{RECORD_SUFFIX}")):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PluginReleaseError(f"cannot read boot profile {path}: {exc}") from exc
        for entry in profile.get("install", {}).get("plugins", []):
            if entry.get("slug") == slug and _git_pin(entry) is not None:
                consumers.append(path)
                break
    return consumers


def bump_profiles(boot_dir: Path, slug: str, tag: str, *, dry_run: bool = False) -> list[ProfileBump]:
    """Advance every git-pinned rev for *slug* to *tag* across the profiles in *boot_dir*.

    Returns one :class:`ProfileBump` per profile that changed (a profile already at *tag* is a
    no-op and omitted). When *dry_run* is true, nothing is written — the bumps are computed and
    returned for reporting only. Refreshes any matching tag inside the entry's ``note`` prose.
    """
    bumps: list[ProfileBump] = []
    for path in sorted(boot_dir.glob(f"*{RECORD_SUFFIX}")):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PluginReleaseError(f"cannot read boot profile {path}: {exc}") from exc

        changed = False
        for entry in profile.get("install", {}).get("plugins", []):
            if entry.get("slug") != slug:
                continue
            old_rev = _git_pin(entry)
            if old_rev is None or old_rev == tag:
                continue
            entry["source"]["rev"] = tag
            if isinstance(entry.get("note"), str):
                entry["note"] = _refresh_note(entry["note"], old_rev, tag)
            bumps.append(ProfileBump(path=path, slug=slug, old_rev=old_rev, new_rev=tag))
            changed = True

        if changed and not dry_run:
            path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")

    return bumps


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tap.plugin_release",
        description="Bump every consuming boot profile's pinned rev for a released plugin slug.",
    )
    parser.add_argument("--slug", required=True, help="the released plugin's slug")
    parser.add_argument("--version", required=True, help="the released version (e.g. 0.2.0 or v0.2.0)")
    parser.add_argument("--boot-dir", required=True, type=Path, help="directory holding the *.boot.json profiles")
    parser.add_argument("--dry-run", action="store_true", help="report bumps without writing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        tag = normalize_tag(args.version)
        bumps = bump_profiles(args.boot_dir, args.slug, tag, dry_run=args.dry_run)
    except PluginReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    verb = "would bump" if args.dry_run else "bumped"
    if not bumps:
        print(f"note: no boot profile in {args.boot_dir} git-sources '{args.slug}' at a stale rev (nothing to bump)")
        return 0
    for bump in bumps:
        print(f"{verb} {bump.path.name}: {args.slug} {bump.old_rev} -> {bump.new_rev}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
