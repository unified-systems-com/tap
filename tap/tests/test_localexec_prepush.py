"""The pre-push bookkeeping gate (req-dev-localexec-prepush, tap#345).

Asserts the properties that make the hook trustworthy rather than its text: that it exists and is
executable, that it consults the consent gate, that it checks the four bookkeeping surfaces CI
rejects pushes over, and — the two that are easy to regress — that it does NOT run a test lane and
that a missing stack degrades visibly instead of silently.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / ".githooks" / "pre-push"


def _text() -> str:
    return HOOK.read_text(encoding="utf-8")


def test_the_hook_exists_and_is_executable() -> None:
    """
    TAP-IMPLEMENTS: req-dev-localexec-prepush@9790b4032923/8fea7fc4deda (enforcement) — the
        client-side push gate's existence and executability are asserted here; the hook itself is
        shell, so the requirement's enforcement claim lives with the test that holds it to shape.
    """
    assert HOOK.is_file(), "the pre-push gate is the client-side half of the bookkeeping guards"
    assert HOOK.stat().st_mode & 0o111, "a hook git cannot execute is a hook that silently does nothing"


def test_it_parses_under_a_posix_shell() -> None:
    """It runs on a bare host before any container exists, so `sh` has to accept it."""
    assert subprocess.run(["sh", "-n", str(HOOK)], capture_output=True).returncode == 0


def test_it_consults_the_consent_gate() -> None:
    body = _text()
    assert "_consent_check.sh" in body
    assert "tap_consent_gate" in body


def test_it_is_protective_rather_than_certifying() -> None:
    """A consent mismatch must warn and still run: a checker that no-ops when its consent is stale
    still reads as a green push. `prepare-commit-msg` makes the opposite call because it certifies."""
    assert "tap_consent_gate || true" in _text()


@pytest.mark.parametrize(
    ("needle", "why"),
    [
        ("implements-tag", "a stale implements claim reddened PR# 343 - tap"),
        ("check-dco", "the DCO trailer is checked on both roads to main"),
        ("check-issue-link", "an unlinked range reddens the dco job"),
        ("mypy-static-typing", "the mypy ratchet reddened PR# 818 - tap after a local run went stale"),
        ("test_committed_fragments_are_in_sync", "an unsynced fragment reddened PR# 343 - tap"),
        ("test_spec_map_in_sync", "an unsynced Validation Map row reddened PR# 343 - tap"),
        ("host_syntax_floor", "host code that will not parse on a host interpreter fails before it reports"),
    ],
)
def test_it_checks_each_surface_that_has_reddened_a_push(needle: str, why: str) -> None:
    assert needle in _text(), why


def test_it_does_not_run_a_test_lane() -> None:
    """The lanes stay the promote's job and CI's. A hook long enough to make people reach for
    --no-verify protects nothing, and that cost is observed rather than hypothetical."""
    body = _text()
    assert "scripts/test" not in body
    # Targeted node ids are fine; a bare suite path is not.
    assert "pytest tap/tests/test_guards.py -q" not in body
    assert 'pytest "$_t"' in body or 'pytest "$_t"' in body


def test_a_missing_stack_degrades_visibly() -> None:
    """A silent skip reads as a pass, which is the failure this whole surface exists to remove."""
    body = _text()
    assert "no running stack" in body
    assert "skipped" in body.lower()


def test_it_names_the_fix_for_every_finding() -> None:
    """A gate that reports a failure without its remedy just moves the search."""
    body = _text()
    for command in (
        "scripts/implements-tag --check",
        "guards --sync-accounting",
        "guards --sync-map",
        "mypy .",
    ):
        assert command in body, f"the finding for {command} must name the command that fixes it"


def test_the_bypass_is_gits_own() -> None:
    """Deliberate and visible in a transcript, rather than an env var nobody can see afterwards."""
    assert "--no-verify" in _text()


def test_a_delete_only_push_is_not_gated() -> None:
    """Deleting a ref adds no commits, so there is nothing to check and refusing would be noise."""
    assert "0000000000000000000000000000000000000000" in _text()
