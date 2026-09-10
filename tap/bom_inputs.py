"""The bill-of-materials inputs, declared ONCE (tap#379).

"What gets booted" is decided by more than ``boot/*.boot.json``: the resolved core
dependencies (``uv.lock``), their bounds and groups (``pyproject.toml``), the image
(``docker/Dockerfile*``, the entrypoint, the OpenSSL FIPS provider pin and its key file),
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
    "docker/Dockerfile*",
    "docker/entrypoint.sh",
    "docker/build-openssl-fips.sh",
    "docker/openssl-release-keys.asc",
    "docker-compose*.yml",
    ".env",
    "tap/preboot.py",
    "tap_boot/**",
)


def _match(path: str, pattern: str) -> bool:
    """fnmatch with the two GitHub-glob idioms the declaration uses: ``**/`` means "at any depth,
    including the top", and a trailing ``/**`` means "anything under"."""
    if pattern.startswith("**/"):
        tail = pattern[3:]
        return fnmatch.fnmatch(path, tail) or fnmatch.fnmatch(path, f"*/{tail}")
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-3] + "/")
    return fnmatch.fnmatch(path, pattern)


def record_source_paths(repo_root: Path) -> list[str]:
    """Repo-relative paths that boot records install editable/from-path — unpinned by nature,
    so a change UNDER one of them is a change to what boots (Codex/tap#379 F3)."""
    paths: list[str] = []
    for record in sorted(repo_root.glob("boot/*.boot.json")):
        try:
            data = json.loads(record.read_text())
        except OSError, ValueError:
            continue
        for entry in (data.get("install") or {}).get("plugins") or []:
            source = entry.get("source") if isinstance(entry, dict) else None
            if isinstance(source, dict) and source.get("type") in ("editable", "path") and source.get("path"):
                paths.append(str(source["path"]).rstrip("/"))
    return sorted(set(paths))


def is_bom_input(path: str, repo_root: Path | None = None) -> bool:
    """True when a change to ``path`` (repo-relative, POSIX) moves the bill of materials."""
    if any(_match(path, pattern) for pattern in BOM_INPUTS):
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
        if any(is_bom_input(path, args.root) for path in changed):
            print("boot")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
