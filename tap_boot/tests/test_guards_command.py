"""Tests for the `guards` management command's flag dispatch.

Regression coverage for the silent flag-drop found by the ai-guards session
(2026-08-23): `--sync-accounting --sync-evidence` ran only the first sync and
said nothing about the second — the handler returned after the first matching
flag. Cost two red gate runs on PR #117 before it was caught. Sync flags must
COMPOSE: every requested sync runs in one invocation.

The sync targets are committed repo files, so these tests pin the dispatch
seam (which sync methods run) rather than executing real syncs against the
working tree.
"""

from __future__ import annotations

from django.core.management import call_command

from tap_boot.management.commands.guards import Command


def _spy_syncs(monkeypatch) -> list[str]:
    """Replace every _sync_* method with a recorder; returns the call log."""
    calls: list[str] = []
    for name in ("_sync_accounting", "_sync_evidence", "_sync_mypy", "_sync_map"):
        monkeypatch.setattr(Command, name, lambda self, _n=name: calls.append(_n))
    return calls


def test_combined_sync_flags_all_run(monkeypatch) -> None:
    """--sync-accounting --sync-evidence runs BOTH syncs — the regression case."""
    calls = _spy_syncs(monkeypatch)
    call_command("guards", "--sync-accounting", "--sync-evidence")
    assert calls == ["_sync_accounting", "_sync_evidence"]


def test_all_four_sync_flags_compose(monkeypatch) -> None:
    calls = _spy_syncs(monkeypatch)
    call_command("guards", "--sync-accounting", "--sync-evidence", "--sync-mypy", "--sync-map")
    assert calls == ["_sync_accounting", "_sync_evidence", "_sync_mypy", "_sync_map"]


def test_single_sync_flag_runs_only_itself(monkeypatch) -> None:
    calls = _spy_syncs(monkeypatch)
    call_command("guards", "--sync-evidence")
    assert calls == ["_sync_evidence"]
