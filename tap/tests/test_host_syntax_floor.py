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


@pytest.mark.spec("req-dev-localexec-host-syntax-floor-1")
def test_the_floor_is_below_the_container_interpreter() -> None:
    """A floor equal to the container's version would assert nothing about hosts.

    The container version is DERIVED from `requires-python`, not restated here — a
    second copy of that number is the drift this whole file exists to prevent.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'requires-python\s*=\s*">=\s*(\d+)\.(\d+)"', pyproject)
    assert match, "could not read requires-python from pyproject.toml"
    container = (int(match.group(1)), int(match.group(2)))
    assert HOST_SYNTAX_FLOOR < container, (
        "the host floor must be strictly older than the container interpreter, or the "
        "check degenerates into 'does this parse where it already parses'"
    )
