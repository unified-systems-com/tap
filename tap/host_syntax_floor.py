"""Every module a HOST tool runs must parse on the oldest interpreter that host may have.

The container is Python 3.14. Host tools are not: `scripts/change-tier`, the pre-commit
hooks, and the CI `setup` job all run `python3` from the machine's PATH, before any
container exists. A module that uses 3.14-only grammar dies there with a `SyntaxError`
at import time — before a single line executes, so no `try`/`except` inside it can help.

This is not hypothetical. `tap/bom_inputs.py` used PEP 758 (`except OSError, ValueError:`),
which parses only on 3.14+. `scripts/change-tier` invokes it with bare `python3` and
discarded its stderr, so on the CI runner the classifier produced nothing, the tier
fell closed to `boot`, and EVERY pull request ran the full lane set instead of the
one-minute docs lane. Nobody saw it for weeks (tap#400).

Two halves, because the failure needed both:

1.  THE FLOOR IS CHECKED, NOT ASSUMED. `ast.parse(..., feature_version=)` rejects
    grammar newer than the floor without needing that interpreter installed — pure
    stdlib, offline, milliseconds, and it runs fine on 3.14. There is no excuse for
    this check to live only in CI.

2.  THE TARGET LIST IS DERIVED, NOT HAND-MAINTAINED. The pre-existing stdlib-only
    guard carried a hand-written list of seven modules. `tap/bom_inputs.py` became
    host-run the day `change-tier` started invoking it, nobody edited the list, and
    the guard kept passing while the thing it guarded was broken — presence, not
    correctness. So the list is now read out of the actual `python3 ...` invocations
    in the tree, and the hand-written names survive only as a floor for modules
    reached some other way.

Stdlib-only, and it parses at its own floor ON PURPOSE: the pre-commit hook runs this
file under the developer's bare `python3`, so it is subject to the rule it enforces.
A checker that cannot run on the interpreters it polices is worse than none —
`test_the_checker_obeys_its_own_rule` keeps that honest.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

# The oldest interpreter a host tool may meet. `ubuntu-latest` GitHub runners ship
# 3.12; distro pythons on a developer machine can be older still. Raising this is a
# policy decision — it narrows where TAP's host tools can run — so it lives here,
# once, rather than being spelled out at each call site.
HOST_SYNTAX_FLOOR = (3, 12)

# Directories whose contents run ON THE HOST: shell entry points, git hooks, workflow
# steps (a runner is a host), and the image build's pre-venv stage.
HOST_SOURCE_DIRS = ("scripts", ".githooks", ".github/workflows", "docker")

# `python3 path/to/x.py`, `python3 "$ROOT/path/to/x.py"`, `python3 "${ROOT}/x.py"`.
_INVOKE_PATH = re.compile(r"""python3(?:\.\d+)?\s+(?:"?\$\{?\w+\}?"?/)?"?([\w./-]+\.py)""")
# `python3 -m tap.something`
_INVOKE_MODULE = re.compile(r"""python3(?:\.\d+)?\s+-m\s+"?([\w.]+)"?""")

# Modules reached by something this scan cannot see (an external installer, a
# `uv run` that falls back to system python, a doc'd manual step). A FLOOR, never
# the whole list — anything derivable must come from the derivation.
DECLARED_HOST_MODULES = (
    "tap/git_invocation.py",
    "tap/secrets_root.py",
    "tap/boot_pointer.py",
    "tap/dev_workspace.py",
    "tap/install_credentials.py",
    ".githooks/precommit_secret_scan.py",
    "docker/seed_manifest.py",
)


def _module_to_path(dotted: str) -> str:
    return dotted.replace(".", "/") + ".py"


def derive_host_modules(root: Path) -> set[str]:
    """Repo-relative paths that some host-side source actually runs with `python3`."""
    found = set()
    for rel_dir in HOST_SOURCE_DIRS:
        base = root / rel_dir
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            candidates = [m.group(1) for m in _INVOKE_PATH.finditer(text)]
            candidates += [_module_to_path(m.group(1)) for m in _INVOKE_MODULE.finditer(text)]
            for cand in candidates:
                rel = cand.lstrip("./")
                if (root / rel).is_file():
                    found.add(rel)
    return found


def host_modules(root: Path) -> list[str]:
    """Everything held to the floor: derived call sites plus the declared remainder."""
    declared = {rel for rel in DECLARED_HOST_MODULES if (root / rel).is_file()}
    return sorted(derive_host_modules(root) | declared)


def parses_at_floor(source: str, floor: tuple[int, int] = HOST_SYNTAX_FLOOR) -> str:
    """Empty string when *source* parses at *floor*, else `line N: message`."""
    try:
        ast.parse(source, feature_version=floor)
    except SyntaxError as exc:
        return f"line {exc.lineno}: {exc.msg}"
    return ""


def floor_violations(root: Path, floor: tuple[int, int] = HOST_SYNTAX_FLOOR) -> list[tuple[str, str]]:
    """`(path, reason)` for every host module that will not parse at *floor*."""
    out = []
    for rel in host_modules(root):
        try:
            source = (root / rel).read_text(encoding="utf-8")
        except OSError as exc:
            out.append((rel, f"unreadable: {exc}"))
            continue
        reason = parses_at_floor(source, floor)
        if reason:
            out.append((rel, reason))
    return out


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Host-runnable modules must parse at the syntax floor.")
    parser.add_argument("--root", type=Path, default=None, help="repo root (default: this checkout)")
    parser.add_argument("--list", action="store_true", help="print the modules held to the floor")
    parser.add_argument(
        "--floor",
        default="{}.{}".format(*HOST_SYNTAX_FLOOR),
        help="minimum interpreter, e.g. 3.12 (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    root = (args.root or _repo_root()).resolve()
    try:
        major, minor = (int(part) for part in args.floor.split(".", 1))
    except ValueError:
        print("--floor takes MAJOR.MINOR, e.g. 3.12", file=sys.stderr)
        return 2
    floor = (major, minor)

    if args.list:
        for rel in host_modules(root):
            print(rel)
        return 0

    violations = floor_violations(root, floor)
    if not violations:
        return 0
    print(
        "host-runnable modules must parse on python {}.{} — they run under bare `python3`\n"
        "before any container exists, so this is an import-time death, not a catchable error:".format(*floor),
        file=sys.stderr,
    )
    for rel, reason in violations:
        print(f"  {rel} — {reason}", file=sys.stderr)
    print(
        "\nFix the syntax (parenthesise multi-type `except (A, B):`, drop other 3.13+ grammar).\n"
        "Run `python3 tap/host_syntax_floor.py --list` to see everything held to this floor.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
