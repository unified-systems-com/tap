"""The release CVE gate classifies a Trivy report into clean / FINDINGS / NOT OBSERVABLE.

`scripts/release_cve_gate.py` exists because Trivy's exit code collapses two different events:
`1` is "found something" and anything else non-zero is "the scan never happened". A release must
block on both, but an operator needs to know which — and which CVE. Treating a crashed scanner
as a clean bill of health is the presence-is-not-correctness failure this whole gate exists to
prevent (tap#526).

`publish-release-tags.yml` runs only on a `v*` tag push, so PR CI cannot exercise the gate; the
classifier is therefore a unit with its own tests rather than shell buried in a workflow.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from tap.guards.base import REPO_ROOT

_SPEC = importlib.util.spec_from_file_location("release_cve_gate", REPO_ROOT / "scripts" / "release_cve_gate.py")
assert _SPEC and _SPEC.loader
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)


def _sarif(*results: dict[str, Any], rules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "Trivy", "rules": rules or []}}, "results": list(results)}],
    }


def _result(rule_id: str, package: str, installed: str, fixed: str) -> dict[str, Any]:
    # The shape Trivy writes: the fields an operator needs live in the message text.
    text = f"Package: {package}\nInstalled Version: {installed}\nVulnerability {rule_id}\nFixed Version: {fixed}\n"
    return {"ruleId": rule_id, "message": {"text": text}}


def _rule(rule_id: str, severity: str) -> dict[str, Any]:
    return {"id": rule_id, "properties": {"tags": ["vulnerability", severity], "security-severity": ""}}


def _write(tmp_path: Path, payload: Any) -> Path:
    report = tmp_path / "trivy.sarif"
    report.write_text(json.dumps(payload) if not isinstance(payload, str) else payload, encoding="utf-8")
    return report


def test_a_clean_scan_lets_the_release_through(tmp_path) -> None:
    code, lines = gate.classify(_write(tmp_path, _sarif()), scanner_ok=True)
    assert code == gate.EXIT_CLEAN
    assert "clean" in lines[0]


def test_findings_block_and_name_every_cve(tmp_path) -> None:
    report = _write(
        tmp_path,
        _sarif(
            _result("CVE-2026-1111", "openssl", "3.0.1-r0", "3.0.2-r0"),
            _result("CVE-2026-2222", "curl", "8.1.0-r0", "8.1.1-r0"),
            rules=[_rule("CVE-2026-1111", "HIGH"), _rule("CVE-2026-2222", "CRITICAL")],
        ),
    )
    code, lines = gate.classify(report, scanner_ok=False)  # trivy exits 1 when it finds things
    assert code == gate.EXIT_FINDINGS
    rendered = "\n".join(lines)
    assert "CVE-2026-1111" in rendered and "CVE-2026-2222" in rendered
    # The operator gets package, installed version and the fix — enough to act without rerunning.
    assert "openssl 3.0.1-r0" in rendered and "fixed in 3.0.2-r0" in rendered
    assert "HIGH" in rendered and "CRITICAL" in rendered


def test_a_crashed_scanner_is_not_a_clean_bill_of_health(tmp_path) -> None:
    """The failure this gate exists to refuse: no results because nothing ran."""
    code, lines = gate.classify(_write(tmp_path, _sarif()), scanner_ok=False)
    assert code == gate.EXIT_NOT_OBSERVABLE
    assert "NOT OBSERVABLE" in lines[0]
    assert "failed to run" in lines[0] or "failed to run" in " ".join(lines)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("", id="empty-file"),
        pytest.param("{not json", id="unparseable"),
        pytest.param(json.dumps({"version": "2.1.0"}), id="no-runs-key"),
        pytest.param(json.dumps([1, 2]), id="not-an-object"),
    ],
)
def test_an_unreadable_report_blocks_rather_than_passing(tmp_path, payload) -> None:
    code, lines = gate.classify(_write(tmp_path, payload), scanner_ok=True)
    assert code == gate.EXIT_NOT_OBSERVABLE
    assert "NOT OBSERVABLE" in lines[0]


def test_a_missing_report_blocks(tmp_path) -> None:
    code, lines = gate.classify(tmp_path / "never-written.sarif", scanner_ok=True)
    assert code == gate.EXIT_NOT_OBSERVABLE
    assert "no report" in lines[0]


def test_the_three_verdicts_use_distinct_exit_codes() -> None:
    assert len({gate.EXIT_CLEAN, gate.EXIT_FINDINGS, gate.EXIT_NOT_OBSERVABLE}) == 3
    assert gate.EXIT_CLEAN == 0


def test_main_prints_an_actionable_refusal(tmp_path, capsys) -> None:
    report = _write(tmp_path, _sarif(_result("CVE-2026-3333", "zlib", "1.3.2-r7", "1.3.3-r0")))
    code = gate.main(["--report", str(report), "--scanner-outcome", "failure", "--subject", "tap-web:sha-abc -> 0.1.8"])
    out = capsys.readouterr().out
    assert code == gate.EXIT_FINDINGS
    assert "::error::" in out
    assert "CVE-2026-3333" in out
    assert "tap-web:sha-abc" in out
    # Names the remedy, not just the refusal.
    assert ".trivyignore" in out


def test_main_is_quiet_and_zero_when_clean(tmp_path, capsys) -> None:
    code = gate.main(["--report", str(_write(tmp_path, _sarif())), "--scanner-outcome", "success"])
    out = capsys.readouterr().out
    assert code == gate.EXIT_CLEAN
    assert "::error::" not in out
