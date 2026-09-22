"""The bill-of-materials inputs, declared ONCE (tap#379).

"What gets booted" is decided by more than ``boot/*.boot.json``: the resolved core
dependencies (``uv.lock``), their bounds and groups (``pyproject.toml``), the image
(``Dockerfile``, the entrypoint, the OpenSSL FIPS provider pin and its key file),
the compose files, ``.env``'s image tags, the code that performs the install
(``tap/preboot.py``, ``tap_boot/``), and anything under a path a record installs
editable. The change-tier classifier once decided ``boot`` on two filename globs and
missed a lockfile-only change (PR# 373) — a filename proxy standing in for "the BOM
moved". This module is the one declaration; every consumer derives from it:

* ``scripts/change-tier`` pipes the diff through ``--classify`` for the ``boot`` tier
  (``req-dev-validation-product-line-lanes-9``);
* the workflows' uv-cache keys hash exactly :data:`RESOLUTION_INPUTS`, and a guard
  (``tap/tests/test_bom_inputs.py``) proves each ``hashFiles(...)`` matches — YAML
  cannot read this file at expression time, so the fragment is generated-and-checked;
* ``promote-to-main.sh`` reads the same tier locally.

Host-runnable and stdlib-only on purpose: ``change-tier`` runs on a bare runner and on a
developer's host before anything is installed.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

# Paths whose change means the resolved dependency set may differ (the uv-cache key).
RESOLUTION_INPUTS: tuple[str, ...] = (
    "uv.lock",
    "pyproject.toml",
    "boot/*.boot.json",
    "**/boot/*.boot.json",
)

# Paths whose change means the booted artifact may differ — RESOLUTION_INPUTS plus the
# image, the environment and the code that performs the install. A change to any of
# these is the `boot` tier: the BOM lane boots the full set and `gate` requires it.
BOM_INPUTS: tuple[str, ...] = (
    *RESOLUTION_INPUTS,
    # The image is built from `Dockerfile` at the REPOSITORY ROOT. This said
    # `docker/Dockerfile*` for months and matched nothing at all, so every image change
    # classified `no-boot` (tap#765) — the PR# 373 failure this module exists to prevent,
    # reappearing as a path that was simply wrong. `fnmatch` anchors the whole string, so
    # this matches the root file and not `docker/postgres/Dockerfile` or `spikes/**`.
    "Dockerfile*",
    "docker/entrypoint.sh",
    "docker/build-openssl-fips.sh",
    "docker/openssl-release-keys.asc",
    "docker-compose*.yml",
    ".env",
    "tap/preboot.py",
    "tap_boot/**",
)

# Paths that match BOM_INPUTS but cannot move the bill of materials: prose under the boot
# package. Nothing installs, imports or boots a markdown file.
#
# BOUNDED TWICE, because an exclusion on a fail-closed gate is the dangerous direction:
#   * by path — `tap_boot/skills/` only, not the whole repository and not all of
#     `tap_boot/`. That bound is not invented here: `scripts/change-tier` already routes
#     `*/skills/*.md` to the docs lane under the tap#410 ruling ("a SKILL.md is
#     instructions an agent reads; no boot lane opens the file"). Skill prose under
#     `tap_boot/` was the one place that ruling could not reach, because the BOM
#     classifier answers BEFORE the tier loop runs. This makes it reachable — the
#     exclusion is exactly co-extensive with a decision already in the tree, rather than
#     a new judgement about markdown in general. `tap_boot/README.md` stays `boot`.
#   * by route — exclusions are applied ONLY to the BOM_INPUTS globs below, never to a boot
#     record's editable source paths. A plugin installed from a path is unpinned by nature
#     and its tree is not ours to reason about; its markdown may be package data. That
#     route stays absolute.
#
# Subtractive ON PURPOSE, rather than narrowing `tap_boot/**` into a list of the
# subdirectories that do count. This module exists because the classifier once decided the
# tier on two filename globs and MISSED a lockfile-only change (PR# 373) — an over-narrow
# include is the expensive failure, because it drops the BOM requirement silently. Keeping
# the include broad and naming the exceptions means a NEW subdirectory under `tap_boot/`
# still lands in the `boot` tier by default; only what is named here is ever let go.
#
# The cost being removed is real: a markdown skill file under `tap_boot/skills/` bought a
# ~20-minute `bom-boot` lane it could not possibly affect (observed 2026-09-22 on
# `tap_boot/skills/new-project/SKILL.md`).
#
# Deliberately NOT excluded, though both were considered:
#   * `tap_boot/skills/**` — the whole directory, matching the file type instead. This is
#     `change-tier`'s own reasoning, and it earned it: a skill directory is not prose-only
#     (`tap_web/skills/drive-browser/` ships real executable Python), so a blanket
#     directory rule would let a script through. Match the file type, not the directory.
#   * `tap_boot/tests/**` — Python that imports the boot code. Dropping it is a coverage
#     judgement, not a "cannot affect the artifact" fact like markdown is.
#
# Nothing packages these files: `pyproject.toml` declares no package-data or force-include,
# there is no MANIFEST.in, and the core `tap_*` apps are not separate distributions. The
# image's `COPY . .` does put them in the filesystem, which is why the claim here is the
# narrow one — no boot lane OPENS the file — and not "markdown never reaches the image".
BOM_EXCLUSIONS: tuple[str, ...] = ("tap_boot/skills/**/*.md",)


def _match(path: str, pattern: str) -> bool:
    """fnmatch with the three GitHub-glob idioms the declaration uses: a leading ``**/`` means
    "at any depth, including the top", a trailing ``/**`` means "anything under", and an interior
    ``/**/`` means "under this prefix, at any depth"."""
    if pattern.startswith("**/"):
        tail = pattern[3:]
        return fnmatch.fnmatch(path, tail) or fnmatch.fnmatch(path, f"*/{tail}")
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-3] + "/")
    if "/**/" in pattern:
        head, tail = pattern.split("/**/", 1)
        if not path.startswith(head + "/"):
            return False
        rest = path[len(head) + 1 :]
        return fnmatch.fnmatch(rest, tail) or fnmatch.fnmatch(rest, f"*/{tail}")
    return fnmatch.fnmatch(path, pattern)


def record_source_paths(repo_root: Path) -> list[str]:
    """Repo-relative paths that boot records install editable/from-path — unpinned by nature,
    so a change UNDER one of them is a change to what boots (Codex/tap#379 F3)."""
    paths: list[str] = []
    for record in sorted(repo_root.glob("boot/*.boot.json")):
        try:
            data = json.loads(record.read_text())
        except (OSError, ValueError):
            continue
        for entry in (data.get("install") or {}).get("plugins") or []:
            source = entry.get("source") if isinstance(entry, dict) else None
            if isinstance(source, dict) and source.get("type") in ("editable", "path") and source.get("path"):
                paths.append(str(source["path"]).rstrip("/"))
    return sorted(set(paths))


def is_bom_input(path: str, repo_root: Path | None = None) -> bool:
    """True when a change to ``path`` (repo-relative, POSIX) moves the bill of materials."""
    # Exclusions subtract from the declared globs ONLY. The record-source route below is
    # never reduced: a plugin installed from a path is unpinned, so everything under it
    # counts, markdown included.
    if any(_match(path, pattern) for pattern in BOM_INPUTS) and not any(
        _match(path, pattern) for pattern in BOM_EXCLUSIONS
    ):
        return True
    if repo_root is not None:
        for source in record_source_paths(repo_root):
            if path == source or path.startswith(source + "/"):
                return True
    return False


def hashfiles_expression(inputs: tuple[str, ...] = RESOLUTION_INPUTS) -> str:
    """The exact ``hashFiles(...)`` argument list a workflow must use for the uv-cache key."""
    return ", ".join(f"'{p}'" for p in inputs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tap.bom_inputs", description="the BOM inputs, declared once")
    parser.add_argument(
        "--classify", action="store_true", help="read changed paths on stdin; print `boot` if any moves the BOM"
    )
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="repo root whose boot records name editable paths (default: cwd)"
    )
    parser.add_argument(
        "--hashfiles", action="store_true", help="print the hashFiles(...) argument list for the uv-cache key"
    )
    parser.add_argument("--list", action="store_true", help="print every declared BOM input pattern")
    args = parser.parse_args(argv)
    if args.hashfiles:
        print(hashfiles_expression())
        return 0
    if args.list:
        for pattern in BOM_INPUTS:
            print(pattern)
        for source in record_source_paths(args.root):
            print(f"{source}/  (editable/path source of a boot record)")
        return 0
    if args.classify:
        changed = [line.strip() for line in sys.stdin if line.strip()]
        # ALWAYS answer: silence is indistinguishable from "the classifier did not run", and a
        # caller that reads silence as "not a BOM change" drops the BOM requirement without
        # anyone noticing — the shape tap#379 exists to remove (observed on run 34457835453,
        # where an unrunnable classifier degraded the tier to `full` and `gate` went green).
        print("boot" if any(is_bom_input(path, args.root) for path in changed) else "no-boot")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
