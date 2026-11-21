"""Host-runnable modules must parse on the oldest interpreter a host may have.

The guard this file replaces checked that host modules IMPORT only stdlib. It never
checked that they PARSE, and it read from a hand-written list of seven names. Both
halves failed at once: `tap/bom_inputs.py` became host-run when `scripts/change-tier`
started invoking it, nobody edited the list, and the module used PEP 758 grammar that
only 3.14 accepts. On the CI runner it died at parse time, `change-tier` swallowed the
error, and every pull request ran the full lane set for weeks (tap#400).

So the controls matter more than the assertion here. A guard that derives its own
targets can be made vacuous by one broken regex, and a vacuous guard is worse than
none — it reports green over exactly the surface it claims to cover.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tap.host_syntax_floor import (
    DECLARED_HOST_MODULES,
    HOST_SYNTAX_FLOOR,
    derive_host_modules,
    floor_violations,
    host_modules,
    parses_at_floor,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Valid on 3.14 (PEP 758), a SyntaxError on everything older.
_PEP758 = "try:\n    pass\nexcept OSError, ValueError:\n    pass\n"


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-1")
def test_every_host_module_parses_at_the_floor() -> None:
    """The assertion itself. Read the controls below before trusting a green here."""
    violations = floor_violations(REPO_ROOT)
    assert violations == [], (
        "these run under bare `python3` before any container exists, so a parse error "
        f"is an import-time death nothing can catch: {violations}"
    )


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-1")
def test_the_floor_check_actually_rejects_newer_grammar() -> None:
    """Negative control: the mechanism must FAIL on the exact construct that broke us.

    Without this, `parses_at_floor` returning "" for everything would look like a pass.
    """
    assert parses_at_floor(_PEP758, (3, 12)), "PEP 758 must be rejected at the 3.12 floor"
    assert parses_at_floor(_PEP758, (3, 13)), "PEP 758 must be rejected at the 3.13 floor"
    assert not parses_at_floor(_PEP758, (3, 14)), "PEP 758 is valid on 3.14 — the floor is the point, not the syntax"


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-2")
def test_the_derivation_finds_a_real_call_site() -> None:
    """Positive control: `tap/bom_inputs.py` IS invoked with bare python3 by
    `scripts/change-tier`, and was the module the hand-written list missed.

    If the invocation regex ever stops matching, this fails loudly instead of the
    guard quietly covering less than it claims.
    """
    caller = REPO_ROOT / "scripts" / "change-tier"
    assert caller.is_file(), "scripts/change-tier is the call site this control depends on"
    assert "bom_inputs.py" in caller.read_text(encoding="utf-8"), (
        "scripts/change-tier no longer invokes tap/bom_inputs.py — re-point this control "
        "at whatever host tool now runs a python module, do not delete it"
    )
    assert "tap/bom_inputs.py" in derive_host_modules(REPO_ROOT), (
        "the invocation scan missed a known `python3 <path>` call site — the derivation "
        "is broken and every other assertion in this file is now vacuous"
    )


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-2")
def test_the_derivation_is_not_empty_and_exceeds_the_hand_written_floor() -> None:
    """Derivation must ADD to the declared names, never silently replace them with nothing."""
    derived = derive_host_modules(REPO_ROOT)
    assert len(derived) >= 5, f"suspiciously few derived host modules ({len(derived)}) — scan likely broken"
    declared_present = {rel for rel in DECLARED_HOST_MODULES if (REPO_ROOT / rel).is_file()}
    assert declared_present, "every declared host module vanished from the tree — re-check the list"
    assert declared_present <= set(host_modules(REPO_ROOT)), "the declared floor must survive derivation"


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-1")
def test_the_checker_obeys_its_own_rule() -> None:
    """It runs under bare python3 from the pre-commit hook, so it is its own subject."""
    source = (REPO_ROOT / "tap" / "host_syntax_floor.py").read_text(encoding="utf-8")
    assert not parses_at_floor(source), "tap/host_syntax_floor.py must parse at the floor it enforces"


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-1")
def test_a_planted_violation_is_caught(tmp_path: Path) -> None:
    """End to end on a fake tree: a module a shell script runs is found AND flagged."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tap").mkdir()
    (tmp_path / "scripts" / "runner.sh").write_text('#!/bin/sh\npython3 "$ROOT/tap/offender.py" --classify\n')
    (tmp_path / "tap" / "offender.py").write_text(_PEP758)

    assert "tap/offender.py" in derive_host_modules(tmp_path)
    violations = floor_violations(tmp_path)
    assert [rel for rel, _ in violations] == ["tap/offender.py"]
    assert "3.14" in violations[0][1]


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-2")
@pytest.mark.parametrize(
    "invocation",
    [
        'python3 "$ROOT/tap/offender.py"',
        'python3 "$ROOT"/tap/offender.py',
        "python3 ${ROOT}/tap/offender.py",
        "python3 tap/offender.py",
        # Interpreter options. Without these the derivation silently covers less than it
        # claims: a module could be host-run, and so subject to the floor, while never
        # entering the checked set. Raised by the Codex seat on PR# 404 - tap, which
        # named `-I` and `-u` specifically; no call site in the tree uses one today,
        # which is precisely why the gap would have gone unnoticed.
        'python3 -I "$ROOT/tap/offender.py"',
        "python3 -u tap/offender.py",
        "python3 -X faulthandler tap/offender.py",
    ],
)
def test_interpreter_options_do_not_hide_a_call_site(tmp_path: Path, invocation: str) -> None:
    """Every ordinary way of spelling the invocation must reach the checked set."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tap").mkdir()
    (tmp_path / "scripts" / "runner.sh").write_text(f"#!/bin/sh\n{invocation} --classify\n")
    (tmp_path / "tap" / "offender.py").write_text(_PEP758)

    assert "tap/offender.py" in derive_host_modules(tmp_path), f"derivation missed: {invocation}"
    assert [rel for rel, _ in floor_violations(tmp_path)] == ["tap/offender.py"]


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-2")
def test_a_heredoc_or_dash_c_is_not_mistaken_for_a_path() -> None:
    """The option clause must not turn `-c`/`-` invocations into phantom targets."""
    from tap.host_syntax_floor import _INVOKE_PATH

    assert _INVOKE_PATH.search("python3 -c 'import os'") is None
    assert _INVOKE_PATH.search("python3 - <<'PY'") is None


def test_an_inline_heredoc_scripts_imports_are_held_to_the_floor(tmp_path: Path) -> None:
    """A heredoc has no `.py` path, so neither path nor `-m` pattern sees it — and whatever it
    imports still runs under bare python3. This hid a live defect: `scripts/implements-tag` reads
    its Python from a heredoc importing `tap.spec_trace`, which used PEP 758, so the script was
    broken on any host below 3.14 while the floor checker passed. A call site the scan cannot see
    is a module nothing holds to the floor — the same failure the derivation replaced the stale
    hand-written list to end, one level deeper."""
    from tap.host_syntax_floor import derive_host_modules

    (tmp_path / "scripts").mkdir()
    (tmp_path / "tap").mkdir()
    (tmp_path / "tap" / "reached.py").write_text("x = 1\n")
    (tmp_path / "scripts" / "tool").write_text(
        "#!/usr/bin/env bash\npython3 - \"$@\" <<'PY'\nfrom tap.reached import x\nPY\n"
    )

    assert "tap/reached.py" in derive_host_modules(tmp_path)


def test_the_real_heredoc_call_site_is_covered() -> None:
    """The specific module that was uncovered, asserted against the real tree rather than a
    fixture — a derivation that works on a synthetic file and misses the actual call site is the
    presence-not-correctness failure this checker exists to catch."""
    from tap.host_syntax_floor import host_modules

    assert "tap/spec_trace.py" in host_modules(REPO_ROOT), (
        "scripts/implements-tag imports it through a heredoc on every pre-push run"
    )


def test_the_formatter_target_matches_the_derived_host_set() -> None:
    """`ruff format` must know about the floor, or it puts the violation back.

    The formatter rewrites to its target version. At `py314` it turns `except (A, B):` into
    PEP 758's `except A, B:` — legal on the container, an import-time SyntaxError on the 3.12 a
    runner or a laptop may have. That is observed, not theoretical: parentheses added by hand to
    `tap/spec_trace.py` were silently removed again by the next `ruff format` in the same session.

    `[tool.ruff.per-file-target-version]` pins each host-run module to the floor. That table is
    hand-written because pyproject cannot compute one — the exact staleness the floor checker
    abandoned its own hand-written list to escape — so it is held to the derivation HERE. A module
    that becomes host-run without its entry fails this test rather than failing on someone's
    laptop months later.
    """
    import tomllib

    from tap.host_syntax_floor import HOST_SYNTAX_FLOOR, host_modules

    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        table = tomllib.load(fh)["tool"]["ruff"].get("per-file-target-version", {})

    floor_tag = "py{}{}".format(*HOST_SYNTAX_FLOOR)
    # ruff formats `.py` files only; an extensionless script held to the floor by its shebang
    # (`scripts/check-issue-link`) is never rewritten by it, so it needs no entry.
    derived = {rel for rel in host_modules(REPO_ROOT) if rel.endswith(".py")}
    pinned = set(table)

    assert derived - pinned == set(), (
        "host-run modules with no formatter target — `ruff format` will rewrite these to 3.14 "
        f"grammar and break them on a {floor_tag} host. Add to [tool.ruff.per-file-target-version]: "
        f"{sorted(derived - pinned)}"
    )
    assert pinned - derived == set(), (
        f"formatter targets for modules that are no longer host-run: {sorted(pinned - derived)}. "
        "Drop them, or the table stops meaning 'these are the host-run ones'."
    )
    assert {v for k, v in table.items()} == {floor_tag}, (
        f"every host-run module's formatter target must be the floor ({floor_tag}), not a mixture"
    )


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-1")
def test_the_floor_is_below_the_container_interpreter() -> None:
    """A floor equal to the container's version would assert nothing about hosts.

    The container version is DERIVED from `requires-python`, not restated here — a
    second copy of that number is the drift this whole file exists to prevent.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # The lower bound only: requires-python also carries an upper bound (`">=3.14,<3.15"`,
    # tap#1008), and the floor is compared with the oldest interpreter the container may run.
    match = re.search(r'requires-python\s*=\s*">=\s*(\d+)\.(\d+)[,"]', pyproject)
    assert match, "could not read requires-python from pyproject.toml"
    container = (int(match.group(1)), int(match.group(2)))
    assert HOST_SYNTAX_FLOOR < container, (
        "the host floor must be strictly older than the container interpreter, or the "
        "check degenerates into 'does this parse where it already parses'"
    )


# --------------------------------------------------------------------------------------------
# tap#1277: the floor follows imports, finds Python by its shebang, sees calls through the
# resolver, and no shell host source names a bare `python3` any more.
# --------------------------------------------------------------------------------------------

_RESOLVER = REPO_ROOT / "scripts" / "py"


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-4")
def test_a_module_a_host_module_imports_is_held_to_the_floor(tmp_path: Path) -> None:
    """The hole tap#1277 found: a hook was checked and the module it imports was not.

    `.githooks/precommit_secret_scan.py` was on the list and `tap/credential_patterns.py`, which it
    imports, was not; the secret scan died with `SyntaxError` on Debian's 3.13 while the checker
    passed. Absolute, relative and package-level imports must all reach the checked set.
    """
    (tmp_path / ".githooks").mkdir()
    (tmp_path / "tap" / "inner").mkdir(parents=True)
    (tmp_path / "tap" / "__init__.py").write_text("")
    (tmp_path / "tap" / "inner" / "__init__.py").write_text("from .deep import y\n")
    (tmp_path / "tap" / "inner" / "deep.py").write_text(_PEP758)
    (tmp_path / "tap" / "direct.py").write_text("from tap.inner import y\n")
    (tmp_path / ".githooks" / "scan.py").write_text("import sys\nfrom tap.direct import thing\n")
    (tmp_path / ".githooks" / "pre-commit").write_text('#!/bin/sh\nscripts/py "$ROOT/.githooks/scan.py"\n')

    modules = set(host_modules(tmp_path))
    assert {"tap/direct.py", "tap/__init__.py", "tap/inner/__init__.py", "tap/inner/deep.py"} <= modules
    assert [rel for rel, _ in floor_violations(tmp_path)] == ["tap/inner/deep.py"]


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-4")
def test_the_real_secret_scan_imports_are_covered() -> None:
    """The specific modules that were uncovered, against the real tree."""
    modules = set(host_modules(REPO_ROOT))
    assert "tap/credential_patterns.py" in modules, "the pre-commit secret scan imports it"
    assert "tap/source_scan.py" in modules
    assert floor_violations(REPO_ROOT) == []


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-4")
def test_a_python_shebang_script_is_a_host_module(tmp_path: Path) -> None:
    """`scripts/check-issue-link` has no `.py` suffix; the pre-push hook and CI run it directly."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "checker").write_text("#!/usr/bin/env python3\n" + _PEP758)
    (tmp_path / "scripts" / "shell-tool").write_text("#!/usr/bin/env bash\necho hi\n")

    assert "scripts/checker" in derive_host_modules(tmp_path)
    assert "scripts/shell-tool" not in derive_host_modules(tmp_path)
    assert [rel for rel, _ in floor_violations(tmp_path)] == ["scripts/checker"]
    assert "scripts/check-issue-link" in host_modules(REPO_ROOT)


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-2")
@pytest.mark.parametrize(
    "invocation",
    [
        '"$ROOT/scripts/py" "$ROOT/tap/offender.py"',
        "scripts/py tap/offender.py",
        '"$SCRIPT_DIR/py" -m tap.offender',
        "scripts/py - <<'PY'\nimport tap.offender\nPY",
    ],
)
def test_a_call_through_the_resolver_is_derived(tmp_path: Path, invocation: str) -> None:
    """Every host call site now goes through `scripts/py`; a derivation blind to it covers nothing."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tap").mkdir()
    (tmp_path / "scripts" / "runner.sh").write_text(f"#!/bin/sh\n{invocation}\n")
    (tmp_path / "tap" / "offender.py").write_text(_PEP758)

    assert "tap/offender.py" in derive_host_modules(tmp_path), f"derivation missed: {invocation}"


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-5")
def test_no_shell_host_source_calls_bare_python3() -> None:
    """Host tools reach Python only through `scripts/py`, never the machine's own `python3`."""
    from tap.host_syntax_floor import bare_interpreter_calls

    offenders = bare_interpreter_calls(REPO_ROOT)
    assert offenders == [], "call scripts/py instead of python3:\n" + "\n".join(
        f"  {path}:{line}: {text}" for path, line, text in offenders
    )


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-5")
def test_the_bare_call_scan_is_not_vacuous(tmp_path: Path) -> None:
    """A planted bare call is found; comments, Python sources and the resolver itself are not."""
    from tap.host_syntax_floor import bare_interpreter_calls

    (tmp_path / "scripts").mkdir()
    (tmp_path / ".githooks").mkdir()
    (tmp_path / "scripts" / "bad").write_text("#!/bin/sh\nx=$(python3 -c 'print(1)')\n")
    (tmp_path / "scripts" / "commented").write_text("#!/bin/sh\n# we used to call python3 here\n")
    (tmp_path / "scripts" / "tool.py").write_text("print('python3 is mentioned here')\n")
    (tmp_path / "scripts" / "py").write_text('#!/usr/bin/env bash\nexec python3 "$@"\n')
    (tmp_path / ".githooks" / "pre-commit").write_text("#!/bin/sh\npython3 scan.py\n")

    assert [(p, n) for p, n, _ in bare_interpreter_calls(tmp_path)] == [
        ("scripts/bad", 2),
        (".githooks/pre-commit", 2),
    ]


def _fake_bin(tmp_path: Path, *, python3_ok: bool, uv: bool) -> Path:
    """A PATH holding only what `scripts/py` needs, plus a `python3` and optionally a `uv`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("cat", "env"):
        found = shutil.which(tool)
        assert found, tool
        (bin_dir / tool).symlink_to(found)
    (bin_dir / "python3").write_text(f"#!/bin/sh\nexit {0 if python3_ok else 1}\n")
    (bin_dir / "python3").chmod(0o755)
    if uv:
        (bin_dir / "uv").write_text('#!/bin/sh\necho "uv $*"\n')
        (bin_dir / "uv").chmod(0o755)
    return bin_dir


def _run_resolver(bin_dir: Path) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash
    return subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — running the committed resolver IS the test; argv list, no shell  # nosec B603  # noqa: S603
        [bash, str(_RESOLVER), "-c", "print(1)"],
        env={"PATH": str(bin_dir)},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-6")
def test_the_resolver_fails_loud_with_no_interpreter(tmp_path: Path) -> None:
    """Too old a `python3` and no uv: exit 127 and say what to install, never pass silently."""
    result = _run_resolver(_fake_bin(tmp_path, python3_ok=False, uv=False))

    assert result.returncode == 127
    assert "brew install uv" in result.stderr
    assert "{}.{}+".format(*HOST_SYNTAX_FLOOR) in result.stderr


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-6")
def test_the_resolver_falls_back_to_uv_at_the_project_interpreter(tmp_path: Path) -> None:
    """Too old a `python3` but uv present: run through uv at `requires-python`, no project."""
    import tomllib

    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        wanted = re.search(r"\d+\.\d+", tomllib.load(fh)["project"]["requires-python"])
    assert wanted
    result = _run_resolver(_fake_bin(tmp_path, python3_ok=False, uv=True))

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"uv run --no-project --quiet --python {wanted.group(0)} -- python -c print(1)"


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-6")
def test_the_resolver_prefers_a_host_python_that_meets_the_floor(tmp_path: Path) -> None:
    """A `python3` at or above the floor is used as it is: no download, no uv."""
    result = _run_resolver(_fake_bin(tmp_path, python3_ok=True, uv=True))

    assert result.returncode == 0, result.stderr
    assert "uv run" not in result.stdout


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-6")
def test_the_resolver_states_the_floor_and_version_its_sources_do() -> None:
    """`scripts/py` is hashed for consent and its two sources are not, so it restates both numbers.

    Reading them from `tap/host_syntax_floor.py` and `pyproject.toml` would let an edit to either one
    change the interpreter every hook runs on without invalidating consent. Restating them is only
    safe while this test holds them equal.
    """
    import tomllib

    text = _RESOLVER.read_text(encoding="utf-8")
    floor = re.search(r"^_fmaj=(\d+) _fmin=(\d+)", text, re.M)
    uv_python = re.search(r"^_uv_python=(\d+\.\d+)", text, re.M)
    assert floor and uv_python, "scripts/py must state _fmaj/_fmin and _uv_python on their own lines"
    assert (int(floor.group(1)), int(floor.group(2))) == HOST_SYNTAX_FLOOR

    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        wanted = re.search(r"\d+\.\d+", tomllib.load(fh)["project"]["requires-python"])
    assert wanted and uv_python.group(1) == wanted.group(0)
    code = "\n".join(line.split("#", 1)[0] for line in text.split("set -euo pipefail", 1)[1].splitlines())
    assert "host_syntax_floor" not in code and "pyproject" not in code, "scripts/py must not read unhashed files"
