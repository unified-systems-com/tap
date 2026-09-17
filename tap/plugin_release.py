"""Host-runnable, pure-stdlib core for ``scripts/release-plugin.sh`` (req-dev-workspace-release).

Releasing and adopting are **two deliberate commands** (tap#421). ``release-plugin <slug>
<version>`` runs the conformance gate + the plugin's tests and tags the plugin repo with an
immutable ``v<version>`` — it advances no consumer. *Adopting* that release into a stack is
this module's job, run on purpose by whoever owns that stack.

The boot profiles under ``boot/`` are the bill of materials: each git-sourced plugin entry pins
``source.rev`` (the readable tag) **and** ``source.commit`` (the 40-hex SHA that decides what
installs, tap#512). Adopting writes the two as ONE pair: the commit is resolved from the forge
through :mod:`tap.git_pin` — the one resolver — and never hand-typed. A rev-only bump would
leave the previous commit installed and raise a moved-tag security Flaw on every boot (tap#513).

**Fail closed at authoring.** Boot is the lenient side: it installs by the pinned commit and
*reports* tag drift. Here nothing is written unless the forge answers that the tag names a
commit — ``missing`` and ``not_observable`` both refuse — and a tag that has MOVED under an
already-adopted entry refuses rather than quietly re-pinning it: that is the supply-chain event
a human must see, not launder. A refusal leaves every profile untouched, because all edits are
planned before the first write.

These deployment-profile records carry no inline integrity hash (that guard is for *in-package*
boot records, one level up; see ``tap.boot_records``). We also refresh any ``vX.Y.Z`` occurrence
inside the entry's human ``note`` so the prose does not silently drift stale.

Substrate-first ordering (``req-dev-workspace-release-3``) is the operator's discipline across
*calls*: release and adopt the substrate plugin first, then the consumers — by which point their
profiles already carry the fresh substrate pin.

Host-runnable, pure stdlib (``json``/``re``/``pathlib`` plus the stdlib-only
:mod:`tap.git_pin`), like ``tap.dev_workspace`` and ``tap.boot_pointer``: ``release-plugin.sh``
runs it venv-free.

Usage:
    python -m tap.plugin_release --slug compliance_core --version 0.2.0 --boot-dir boot
    python -m tap.plugin_release --slug compliance_core --version 0.2.0 --boot-dir boot --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from tap.boot_naming import RECORD_SUFFIX
from tap.git_pin import TAG_MATCHES, TagCheck, is_commit_sha, resolve_tag

#: Resolve a tag to the commit it names: ``(url, tag) -> TagCheck``. The default is
#: :func:`tap.git_pin.resolve_tag` (the ONE resolver, tap#512); tests pass a stub so the
#: JSON-edit logic stays exercisable with no git and no network.
TagResolver = Callable[[str, str], TagCheck]

#: A release tag: ``v`` + a semver-ish core, optional pre-release / build suffix. Kept as a plain
#: regex (not ``packaging``) so this module stays stdlib-only and host-runnable venv-free.
_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


class PluginReleaseError(Exception):
    """Raised on a malformed version or an unreadable/malformed boot profile."""


@dataclass(frozen=True)
class ProfileBump:
    """One boot profile whose pin for a slug was (or would be) advanced.

    ``old_commit`` is ``None`` when the entry carried no ``commit`` — a pre-tap#512 profile
    being pinned for the first time, which is a fill-in rather than a move.
    """

    path: Path
    slug: str
    old_rev: str
    new_rev: str
    new_commit: str
    old_commit: str | None = None


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


def _safe_url(url: str) -> str:
    """``scheme://host/path`` with userinfo, query and fragment dropped — safe to print.

    An error message naming a source URL reaches stderr and CI logs, and the branch that
    reports a MALFORMED url is exactly the one where that url may carry a credential
    (``https://user:token@forge/repo``): the accepted shapes forbid userinfo, so the
    rejected ones are where it hides. Same rule as ``tap.preboot`` on a refused source
    (req-tap-plugin-arch-source-secret-4: a token never reaches the log stream).
    """
    parts = urlsplit(url)
    if not parts.scheme:
        return "<unparseable url>"
    if not parts.hostname:
        return f"{parts.scheme}://<no host>"
    return f"{parts.scheme}://{parts.hostname}{parts.path}"


def _resolve_commit(url: str, tag: str, slug: str, resolver: TagResolver, cache: dict[str, str]) -> str:
    """The commit *tag* names at *url*, or raise :class:`PluginReleaseError`.

    Only ``matches`` yields a commit. ``missing`` (no such tag — usually an adopt run before
    the release was pushed) and ``not_observable`` (the forge could not be asked) both refuse:
    an authoring tool that could not look has not verified anything, and writing a pin it never
    confirmed is the false declaration this pair exists to prevent. One lookup per URL.
    """
    if url in cache:
        return cache[url]
    try:
        found = resolver(url, tag)
    except ValueError as exc:  # url/rev outside the accepted shape (tap.git_pin validates its argv)
        raise PluginReleaseError(f"plugin '{slug}': cannot resolve {tag} at {_safe_url(url)}: {exc}") from exc
    if found.state != TAG_MATCHES or not is_commit_sha(found.observed):
        detail = f" — {found.detail}" if found.detail else ""
        raise PluginReleaseError(
            f"plugin '{slug}': tag {tag} at {_safe_url(url)} is '{found.state}'{detail}. Refusing to write a pin "
            f"this command could not verify; nothing was changed."
        )
    commit = str(found.observed)
    cache[url] = commit
    return commit


def bump_profiles(
    boot_dir: Path,
    slug: str,
    tag: str,
    *,
    dry_run: bool = False,
    resolver: TagResolver | None = None,
) -> list[ProfileBump]:
    """Adopt *slug* at *tag* across the profiles in *boot_dir*, writing ``rev`` + ``commit``.

    The commit is resolved from the forge through *resolver* (default
    :func:`tap.git_pin.resolve_tag`) — one lookup per distinct URL, never a hand-typed SHA.
    Returns one :class:`ProfileBump` per profile that changed; an entry already carrying both
    *tag* and that commit is already adopted, so it is a no-op and omitted. Refreshes any
    matching tag inside the entry's ``note`` prose.

    Every profile is read and resolved BEFORE the first write, so a refusal leaves the whole
    tree untouched rather than half-adopted. When *dry_run* is true nothing is written at all,
    but the forge is still consulted — a dry run that skipped the lookup would report a pin it
    had not verified.

    Raises:
        PluginReleaseError: On an unreadable/malformed profile; when the tag cannot be resolved
            (``missing`` / ``not_observable``); or when the entry is already at *tag* with a
            DIFFERENT commit — a moved tag, which is a supply-chain event for a human to look
            at (tap#493), not something to re-pin silently.
    """
    resolve = resolver or (lambda url, tag_: resolve_tag(url, tag_))
    commits: dict[str, str] = {}
    planned: list[tuple[Path, dict[str, Any]]] = []
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
            if old_rev is None:
                continue
            source = entry["source"]
            old_commit = source.get("commit") if is_commit_sha(source.get("commit")) else None
            commit = _resolve_commit(str(source.get("url")), tag, slug, resolve, commits)

            if old_rev == tag and old_commit == commit:
                continue  # already adopted: same tag, same commit
            if old_rev == tag and old_commit is not None:
                raise PluginReleaseError(
                    f"{path.name}: plugin '{slug}' is already pinned at {tag}, but that tag now names "
                    f"{commit} instead of the pinned {old_commit}. The tag MOVED — a release is supposed "
                    f"to be immutable (tap#493). Nothing was changed; investigate before re-pinning."
                )

            source["rev"] = tag
            source["commit"] = commit
            if isinstance(entry.get("note"), str):
                entry["note"] = _refresh_note(entry["note"], old_rev, tag)
            bumps.append(
                ProfileBump(
                    path=path, slug=slug, old_rev=old_rev, new_rev=tag, new_commit=commit, old_commit=old_commit
                )
            )
            changed = True

        if changed:
            planned.append((path, profile))

    if not dry_run:
        for path, profile in planned:
            path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")

    return bumps


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tap.plugin_release",
        description=(
            "Adopt a released plugin into every consuming boot profile: write the tag and the "
            "commit it names, resolved from the forge, as one pair."
        ),
    )
    parser.add_argument("--slug", required=True, help="the released plugin's slug")
    parser.add_argument("--version", required=True, help="the released version (e.g. 0.2.0 or v0.2.0)")
    parser.add_argument("--boot-dir", required=True, type=Path, help="directory holding the *.boot.json profiles")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="resolve and report the pin (including the commit) without writing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        tag = normalize_tag(args.version)
        bumps = bump_profiles(args.boot_dir, args.slug, tag, dry_run=args.dry_run)
    except PluginReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    verb = "would adopt" if args.dry_run else "adopted"
    if not bumps:
        print(f"note: no boot profile in {args.boot_dir} git-sources '{args.slug}' at a stale pin (nothing to adopt)")
        return 0
    for bump in bumps:
        before = bump.old_commit or "(unpinned)"
        print(
            f"{verb} {bump.path.name}: {args.slug} {bump.old_rev} -> {bump.new_rev}, "
            f"commit {before} -> {bump.new_commit}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
