"""scripts/scanner-ratchet: main's absolute scanner state held against a committed baseline (tap#325).

Offline: every oracle is injected. The two-sided compare, the three states (matches / moved /
not observable), the baseline round-trip, the org table and the one-issue upsert are each tested.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_loader = SourceFileLoader("scanner_ratchet", str(REPO_ROOT / "scripts" / "scanner-ratchet"))
_spec = importlib.util.spec_from_loader("scanner_ratchet", _loader)
assert _spec is not None
sr = importlib.util.module_from_spec(_spec)
sys.modules["scanner_ratchet"] = sr  # dataclasses resolve annotations through sys.modules
_loader.exec_module(sr)

SONAR_MEASURES = {
    "component": {
        "measures": [
            {"metric": "alert_status", "value": "ERROR"},
            {"metric": "bugs", "value": "3"},
            {"metric": "vulnerabilities", "value": "9"},
            {"metric": "code_smells", "value": "31"},
            {"metric": "security_hotspots", "value": "0"},
        ]
    }
}
SONAR_ISSUES = {
    "total": 43,
    "facets": [
        {
            "property": "severities",
            "values": [
                {"val": "MAJOR", "count": 29},
                {"val": "MINOR", "count": 10},
                {"val": "BLOCKER", "count": 4},
                {"val": "CRITICAL", "count": 0},
            ],
        }
    ],
}
CODACY_REPO = {"data": {"issuesCount": 208, "gradeLetter": "B"}}
CODACY_SEARCH = {"data": [], "pagination": {"total": 171}}


def _fetch_all(
    url: str, *, method: str = "GET", body: dict[str, object] | None = None, tries: int = 3
) -> dict[str, object] | None:
    if "measures/component" in url:
        return SONAR_MEASURES
    if "issues/search" in url and "sonarcloud" in url:
        return SONAR_ISSUES
    if url.endswith("/issues/search?limit=1"):
        return CODACY_SEARCH
    if "codacy" in url:
        return CODACY_REPO
    return None


def _fetch_codacy_down(
    url: str, *, method: str = "GET", body: dict[str, object] | None = None, tries: int = 3
) -> dict[str, object] | None:
    return None if "codacy" in url else _fetch_all(url, method=method, body=body, tries=tries)


TODAY = {
    "sonar.gate": "ERROR",
    "sonar.vulnerabilities": 9,
    "sonar.bugs": 3,
    "sonar.code_smells": 31,
    "sonar.security_hotspots": 0,
    "sonar.blocker": 4,
    "sonar.critical": 0,
    "sonar.major": 29,
    "codacy.issues": 208,
    "codacy.error_high": 171,
}


@pytest.mark.spec("req-dev-validation-scanner-ratchet-1")
def test_observe_reads_both_oracles():
    assert sr.observe("o", "r", fetch=_fetch_all) == TODAY


@pytest.mark.spec("req-dev-validation-scanner-ratchet-2")
def test_baseline_round_trip(tmp_path):
    text = sr.render_baseline(TODAY, repo="o/r", at="now")
    assert sr.parse_baseline(text) == TODAY
    with pytest.raises(ValueError, match="unknown scanner metric"):
        sr.parse_baseline("sonar.made_up = 1\n")


@pytest.mark.spec("req-dev-validation-scanner-ratchet-3")
def test_compare_is_two_sided():
    findings = sr.compare(TODAY, TODAY, baseline_path="b.txt")
    assert {f.verdict for f in findings} == {"ok"} and sr.exit_code(findings) == 0
    worse = {**TODAY, "sonar.vulnerabilities": 10}
    f = {x.metric: x for x in sr.compare(worse, TODAY, baseline_path="b.txt")}
    assert f["sonar.vulnerabilities"].verdict == "regression" and "regressed above" in f["sonar.vulnerabilities"].detail
    better = {**TODAY, "codacy.error_high": 100, "sonar.gate": "OK"}
    f = {x.metric: x for x in sr.compare(better, TODAY, baseline_path="b.txt")}
    assert f["codacy.error_high"].verdict == "improvement" and f["sonar.gate"].verdict == "improvement"
    assert sr.exit_code(sr.compare(better, TODAY, baseline_path="b.txt")) == 1


@pytest.mark.spec("req-dev-validation-scanner-ratchet-4")
def test_not_observable_is_a_state_not_a_pass():
    state = sr.observe("o", "r", fetch=_fetch_codacy_down)
    assert state["codacy.issues"] is None and state["sonar.bugs"] == 3
    findings = sr.compare(state, TODAY, baseline_path="b.txt")
    verdicts = {f.metric: f.verdict for f in findings}
    assert verdicts["codacy.issues"] == "not_observable" and verdicts["sonar.bugs"] == "ok"
    assert sr.exit_code(findings) == 3
    assert "NOT OBSERVABLE" in sr.render_check("o/r", findings, baseline_path="b.txt")
    # but a regression elsewhere still wins over the unobservable oracle
    worse = {**state, "sonar.bugs": 4}
    assert sr.exit_code(sr.compare(worse, TODAY, baseline_path="b.txt")) == 1


@pytest.mark.spec("req-dev-validation-scanner-ratchet-5")
def test_org_report_lists_unbaselined_repos_instead_of_skipping():
    baseline_text = sr.render_baseline(TODAY, repo="o/tap", at="now")

    def raw(url: str) -> str | None:
        return baseline_text if url.endswith("/o/tap/HEAD/tap/guards/baselines/scanner.txt") else None

    rows = sr.org_report("o", fetch=_fetch_all, fetch_raw=raw, repos=["tap", "tap-plugin-github-core"])
    by = {r.repo: r for r in rows}
    assert by["tap"].verdict == "ok" and by["tap"].baseline_path == "tap/guards/baselines/scanner.txt"
    assert by["tap-plugin-github-core"].verdict == "unbaselined"
    assert sr.baseline_candidates("tap-plugin-github-core")[0] == "tap_plugin/github_core/guards/baselines/scanner.txt"
    assert sr.baseline_candidates("git-serious-tap")[0] == "tap_plugin/git_serious/guards/baselines/scanner.txt"
    body = sr.render_issue(rows, org="o", at="now")
    assert sr.ISSUE_MARKER in body and "| tap-plugin-github-core | unbaselined |" in body and "1 unbaselined" in body


_FAKE_GH = """\
#!/bin/bash
echo "$*" >> "$GH_LOG"
case "$*" in
  *"issue list"*) cat "$GH_LIST_JSON" ;;
  *"issue view"*) cat "$GH_BODY" ;;
  *"issue create"*) echo "https://example.test/issues/9" ;;
  *) : ;;
esac
"""


@pytest.fixture
def fake_gh(tmp_path, monkeypatch):
    gh = tmp_path / "gh"
    gh.write_text(_FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "gh.log"
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GH_LOG", str(log))
    monkeypatch.setenv("GH_LIST_JSON", str(tmp_path / "list.json"))
    monkeypatch.setenv("GH_BODY", str(tmp_path / "body.txt"))
    (tmp_path / "list.json").write_text("[]")
    (tmp_path / "body.txt").write_text("")
    return tmp_path, log


@pytest.mark.spec("req-dev-validation-scanner-ratchet-6")
def test_issue_upsert_is_marker_deduped_and_closes_on_recovery(fake_gh):
    tmp, log = fake_gh
    assert sr.upsert_issue("body", keep_open=True).startswith("created")
    (tmp / "list.json").write_text(json.dumps([{"number": 7, "title": sr.ISSUE_TITLE}]))
    (tmp / "body.txt").write_text("someone else's issue with the same title")
    assert sr.upsert_issue("body", keep_open=True).startswith(
        "created"
    ), "a title match without the marker is a stranger"
    (tmp / "body.txt").write_text(sr.ISSUE_MARKER + "\nours")
    assert sr.upsert_issue("body", keep_open=True) == "updated issue #7"
    assert sr.upsert_issue("body", keep_open=False) == "closed issue #7 (recovered)"
    calls = log.read_text()
    assert "issue edit 7" in calls and "issue close 7" in calls
