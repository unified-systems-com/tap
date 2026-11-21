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

# `python3 path/to/x.py`, `python3 "$ROOT/path/to/x.py"`, `python3 "${ROOT}"/x.py`, and the
# same with interpreter options in front: `python3 -I x.py`, `python3 -X dev x.py`.
#
# The option clause is not decoration. Without it `python3 -u tap/tool.py` derives nothing,
# and a module could be host-run — and therefore subject to the floor — while sitting
# outside the checked set entirely. No call site in this tree uses an option today, which
# is exactly why it would go unnoticed the day one does (Codex seat, PR# 404 - tap).
# `-c` and `-m` fall through harmlessly: neither is followed by a `.py` path, and `-m` has
# its own pattern below.
_OPTS = r"""(?:\s+-[A-Za-z]\w*(?:\s+\w+)?)*"""
# The interpreter token: bare `python3` (what host tools used to call) or the host resolver
# `scripts/py` by any path ending `/py`, quoted or not (tap#1277). Every host call site goes through
# the resolver now, so a derivation that only knew `python3` would derive nothing at all.
_INTERP = r"""(?:python3(?:\.\d+)?|/py"?)"""
_INVOKE_PATH = re.compile(rf"""{_INTERP}{_OPTS}\s+(?:"?\$\{{?\w+\}}?"?/)?"?([\w./-]+\.py)""")
# `python3 -m tap.something`, `scripts/py -m tap.something`
_INVOKE_MODULE = re.compile(rf"""{_INTERP}{_OPTS}\s+-m\s+"?([\w.]+)"?""")

# `python3 - <<'PY' … import tap.something … PY` — an inline script, which has no `.py` path
# for either pattern above to find, and whose IMPORTS are the host-run modules.
#
# This hole hid a live defect. `scripts/implements-tag` reads its Python from a heredoc that
# does `from tap.spec_trace import …`; `tap/spec_trace.py` used PEP 758 (`except A, B:`), so
# that script was broken on any host below 3.14 — and the floor checker passed, because
# `spec_trace` was in neither the derived set nor the declared list. Exactly the failure the
# derivation was built to end (the stale hand-written list), one level deeper: a call site the
# scan could not see is a module nothing held to the floor.
_INLINE_HEREDOC = re.compile(rf"""{_INTERP}(?:\s+-[A-Za-z]\w*)*\s+-\s""")
_INLINE_IMPORT = re.compile(r"""^\s*(?:from|import)\s+(tap(?:_\w+)?(?:\.[\w.]+)?)""", re.M)

# Modules reached by something this scan cannot see (an external installer, a
# `uv run` that falls back to system python, a doc'd manual step). A FLOOR, never
# the whole list — anything derivable must come from the derivation.
DECLARED_HOST_MODULES = (
    "tap/git_invocation.py",
    "tap/git_pin.py",
    "tap/secrets_root.py",
    "tap/boot_pointer.py",
    "tap/dev_workspace.py",
    "tap/install_credentials.py",
    ".githooks/precommit_secret_scan.py",
    "docker/seed_manifest.py",
)


# A host-side file that IS Python, found by its shebang rather than a `.py` suffix:
# `scripts/check-issue-link` is run directly by the pre-push hook and by CI, so it is host-run
# exactly as much as a `python3 x.py` target is (tap#1277).
_PY_SHEBANG = re.compile(r"""\A#!\s*\S*(?:/env\s+(?:-S\s+)?)?python3(?:\.\d+)?\b""")

# A bare `python3` in command position inside a shell host source: the call the resolver replaces.
_BARE_PYTHON3 = re.compile(r"""(?<![\w./-])python3(?![\w.-])""")


def _module_to_path(dotted: str) -> str:
    return dotted.replace(".", "/") + ".py"


def _is_python_source(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            return bool(_PY_SHEBANG.match(fh.readline()))
    except OSError:
        return False


def _imported_tap_modules(rel: str, source: str) -> set[str]:
    """Repo-relative paths of every first-party module *source* imports, absolute or relative.

    Importing `tap.a.b` runs `tap/__init__.py` and `tap/a/__init__.py` first, so each enclosing
    package is returned too. Only first-party `tap*` packages are followed; the stdlib and
    third-party imports are not ours to hold to the floor.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()  # unparseable at all: floor_violations reports the file itself
    package = rel[:-3].replace("/", ".").rsplit(".", 1)[0] if rel.endswith(".py") else ""
    if rel.endswith("/__init__.py"):
        package = rel[: -len("/__init__.py")].replace("/", ".")
    dotted: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            dotted.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                if node.level > 1:
                    base = base[: -(node.level - 1)]
                stem = ".".join(base + ([node.module] if node.module else []))
            else:
                stem = node.module or ""
            if stem:
                dotted.add(stem)
                dotted.update(f"{stem}.{alias.name}" for alias in node.names)
    out: set[str] = set()
    for name in dotted:
        if not re.match(r"tap(?:_\w+)?(?:\.|$)", name):
            continue
        parts = name.split(".")
        for i in range(1, len(parts) + 1):
            stem = "/".join(parts[:i])
            out.update(c for c in (f"{stem}.py", f"{stem}/__init__.py"))
    return out


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
            if _INLINE_HEREDOC.search(text):
                # A file that pipes an inline script to python3 runs whatever that script
                # imports. Scanning the WHOLE file rather than the heredoc body is deliberate:
                # delimiters vary (PY, EOF, quoted, indented), and an over-wide match costs a
                # module being held to a floor it already has to meet, while a narrow one costs
                # a module nothing checks at all.
                candidates += [_module_to_path(m.group(1)) for m in _INLINE_IMPORT.finditer(text)]
            for cand in candidates:
                # A PREFIX, not a character set: `lstrip("./")` turned `.githooks/x.py` into
                # `githooks/x.py`, which is no file, so a hook's own module silently dropped out.
                rel = cand[2:] if cand.startswith("./") else cand.lstrip("/")
                if (root / rel).is_file():
                    found.add(rel)
            if path.suffix != ".py" and _is_python_source(path):
                found.add(path.relative_to(root).as_posix())
    return found


def import_closure(root: Path, start: set[str]) -> set[str]:
    """*start* plus every first-party module it imports, transitively.

    This is the hole tap#1277 found. `.githooks/precommit_secret_scan.py` was held to the floor and
    `tap/credential_patterns.py`, which it imports, was not, so the scan died on a 3.13 host with
    `SyntaxError` while the checker passed. A module is host-run when anything host-run imports it.
    """
    seen = set(start)
    todo = sorted(start)
    while todo:
        rel = todo.pop()
        try:
            source = (root / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        for dep in _imported_tap_modules(rel, source):
            if dep not in seen and (root / dep).is_file():
                seen.add(dep)
                todo.append(dep)
    return seen


def host_modules(root: Path) -> list[str]:
    """Everything held to the floor: derived call sites plus the declared remainder."""
    declared = {rel for rel in DECLARED_HOST_MODULES if (root / rel).is_file()}
    return sorted(import_closure(root, derive_host_modules(root) | declared))


def bare_interpreter_calls(root: Path) -> list[tuple[str, int, str]]:
    """`(path, line, text)` for every bare `python3` in a shell host source under scripts/ or .githooks/.

    Host tools reach Python through `scripts/py`, which picks an interpreter that meets the floor
    and fails loud when there is none (tap#1277). A bare `python3` takes whatever the host has, and
    on macOS that is 3.9. Comments are ignored, Python sources are not shell, and the resolver
    itself is the one place allowed to name the interpreter.
    """
    out = []
    for rel_dir in ("scripts", ".githooks"):
        base = root / rel_dir
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            rel = path.relative_to(root).as_posix()
            if not path.is_file() or rel == "scripts/py" or "__pycache__" in path.parts or _is_python_source(path):
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for n, line in enumerate(lines, 1):
                if line.lstrip().startswith("#"):
                    continue
                if _BARE_PYTHON3.search(line):
                    out.append((rel, n, line.strip()))
    return out


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
