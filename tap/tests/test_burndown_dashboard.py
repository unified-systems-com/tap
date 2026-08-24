"""Behavioral tests for `scripts/burndown-dashboard` issue updating.

The script mutates a GitHub issue with the operator's credentials, so its
collision behavior is load-bearing: it must find the marker-bearing issue among
title collisions, refuse to touch impostors, and create only when nothing
matches. Each test runs `update_issue` against a fake `gh` executable on PATH
that logs every invocation and plays canned responses — the subprocess seam is
exercised for real, no GitHub required.

Covers the three branches: marker-bearing match updated (skipping an impostor
ahead of it), all-impostor collision refused with no mutation, and no-match
creation.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_loader = SourceFileLoader("burndown_dashboard", str(REPO_ROOT / "scripts" / "burndown-dashboard"))
_spec = importlib.util.spec_from_loader("burndown_dashboard", _loader)
assert _spec is not None
burndown_dashboard = importlib.util.module_from_spec(_spec)
_loader.exec_module(burndown_dashboard)

MARKER = burndown_dashboard.ISSUE_MARKER

_FAKE_GH = """\
#!/bin/bash
echo "$*" >> "$GH_LOG"
case "$*" in
  *"issue list"*) cat "$GH_LIST_JSON" ;;
  *"issue view 7"*) printf 'an impostor issue with the same title' ;;
  *"issue view 9"*) printf '%s\\nthe real dashboard body' "$GH_MARKER" ;;
  *"issue create"*) echo "https://example.invalid/issues/42" ;;
esac
"""


@pytest.fixture
def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install a fake `gh` on PATH; returns the invocation-log path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "gh"
    shim.write_text(_FAKE_GH, encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "gh.log"
    log.touch()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GH_LOG", str(log))
    monkeypatch.setenv("GH_MARKER", MARKER)
    return log


def _set_open_issues(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rows: list[dict]) -> None:
    listing = tmp_path / "list.json"
    listing.write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setenv("GH_LIST_JSON", str(listing))


def test_updates_the_marker_bearing_issue_among_title_collisions(
    fake_gh: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """With an impostor ahead of the real dashboard, the marked issue is edited."""
    title = burndown_dashboard.ISSUE_TITLE
    _set_open_issues(monkeypatch, tmp_path, [{"number": 7, "title": title}, {"number": 9, "title": title}])

    burndown_dashboard.update_issue("new body")

    log = fake_gh.read_text(encoding="utf-8")
    assert "issue edit 9 --body new body" in log
    assert "issue edit 7" not in log
    assert "issue create" not in log
    assert "updated issue #9" in capsys.readouterr().out


def test_refuses_when_no_title_match_carries_the_marker(
    fake_gh: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """An all-impostor collision produces an error message and NO mutation."""
    _set_open_issues(monkeypatch, tmp_path, [{"number": 7, "title": burndown_dashboard.ISSUE_TITLE}])

    burndown_dashboard.update_issue("new body")

    log = fake_gh.read_text(encoding="utf-8")
    assert "issue edit" not in log
    assert "issue create" not in log
    assert "refusing to overwrite" in capsys.readouterr().err


def test_creates_when_no_issue_matches_the_title(
    fake_gh: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """No title match at all → a fresh issue is created."""
    _set_open_issues(monkeypatch, tmp_path, [])

    burndown_dashboard.update_issue("new body")

    log = fake_gh.read_text(encoding="utf-8")
    assert "issue create" in log
    assert "issue edit" not in log
    assert "created" in capsys.readouterr().out


def test_fake_gh_shim_is_actually_invocable(fake_gh: Path) -> None:
    """Positive control: the shim itself runs and logs (a broken shim would make
    every test above pass vacuously through empty logs)."""
    subprocess.run(["gh", "issue", "probe"], check=True)
    assert "issue probe" in fake_gh.read_text(encoding="utf-8")
