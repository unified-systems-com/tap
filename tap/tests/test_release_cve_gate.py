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
    code, lines = gate.classify(_write(tmp_path, _sarif()), scanner_ok=True, root=tmp_path)
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
    code, lines = gate.classify(report, scanner_ok=False, root=tmp_path)  # trivy exits 1 when it finds things
    assert code == gate.EXIT_FINDINGS
    rendered = "\n".join(lines)
    assert "CVE-2026-1111" in rendered and "CVE-2026-2222" in rendered
    # The operator gets package, installed version and the fix — enough to act without rerunning.
    assert "openssl 3.0.1-r0" in rendered and "fixed in 3.0.2-r0" in rendered
    assert "HIGH" in rendered and "CRITICAL" in rendered


def test_a_crashed_scanner_is_not_a_clean_bill_of_health(tmp_path) -> None:
    """The failure this gate exists to refuse: no results because nothing ran."""
    code, lines = gate.classify(_write(tmp_path, _sarif()), scanner_ok=False, root=tmp_path)
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
    code, lines = gate.classify(_write(tmp_path, payload), scanner_ok=True, root=tmp_path)
    assert code == gate.EXIT_NOT_OBSERVABLE
    assert "NOT OBSERVABLE" in lines[0]


def test_a_missing_report_blocks(tmp_path) -> None:
    code, lines = gate.classify(tmp_path / "never-written.sarif", scanner_ok=True, root=tmp_path)
    assert code == gate.EXIT_NOT_OBSERVABLE
    assert "no report" in lines[0]


def test_the_three_verdicts_use_distinct_exit_codes() -> None:
    assert len({gate.EXIT_CLEAN, gate.EXIT_FINDINGS, gate.EXIT_NOT_OBSERVABLE}) == 3
    assert gate.EXIT_CLEAN == 0


def test_main_prints_an_actionable_refusal(tmp_path, capsys, monkeypatch) -> None:
    # main() contains reads to the working directory, which on the runner is the checkout.
    monkeypatch.chdir(tmp_path)
    report = _write(tmp_path, _sarif(_result("CVE-2026-3333", "zlib", "1.3.2-r7", "1.3.3-r0")))
    code = gate.main(["--report", str(report), "--scanner-outcome", "failure", "--subject", "tap-web:sha-abc -> 0.1.8"])
    out = capsys.readouterr().out
    assert code == gate.EXIT_FINDINGS
    assert "::error::" in out
    assert "CVE-2026-3333" in out
    assert "tap-web:sha-abc" in out
    # Names the remedy, not just the refusal.
    assert ".trivyignore" in out


def test_main_is_quiet_and_zero_when_clean(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    code = gate.main(["--report", str(_write(tmp_path, _sarif())), "--scanner-outcome", "success"])
    out = capsys.readouterr().out
    assert code == gate.EXIT_CLEAN
    assert "::error::" not in out


def test_a_report_outside_the_workspace_is_refused(tmp_path) -> None:
    """S8707: the verdict is read from the scan's own output, not an arbitrary path."""
    outside = tmp_path / "elsewhere" / "trivy.sarif"
    outside.parent.mkdir()
    outside.write_text(json.dumps(_sarif()), encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    code, lines = gate.classify(outside, scanner_ok=True, root=workspace)
    assert code == gate.EXIT_NOT_OBSERVABLE
    assert "refusing to read" in lines[0]


def test_a_traversal_out_of_the_workspace_is_refused(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "escape.sarif").write_text(json.dumps(_sarif()), encoding="utf-8")
    code, _ = gate.classify(workspace / ".." / "escape.sarif", scanner_ok=True, root=workspace)
    assert code == gate.EXIT_NOT_OBSERVABLE


def test_a_non_sarif_file_is_refused(tmp_path) -> None:
    report = tmp_path / "trivy.txt"
    report.write_text("clean, honest", encoding="utf-8")
    code, _ = gate.classify(report, scanner_ok=True, root=tmp_path)
    assert code == gate.EXIT_NOT_OBSERVABLE


# --- plugin CI's closure gate (tap#772) --------------------------------------------------------


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-10")
def test_the_plugin_closure_gate_names_its_own_remedy(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    report = _write(tmp_path, _sarif(_result("CVE-2026-4444", "django", "4.2.0", "4.2.1")))
    code = gate.main(
        [
            "--report",
            str(report),
            "--scanner-outcome",
            "failure",
            "--subject",
            "github_core",
            "--gate",
            "plugin-closure",
        ]
    )
    out = capsys.readouterr().out
    assert code == gate.EXIT_FINDINGS
    assert "CVE-2026-4444" in out and "github_core" in out
    assert "pyproject.toml" in out and ".trivyignore" in out
    assert "promote" not in out, "the release refusal is not this gate's"


def test_the_default_gate_is_still_the_release_one(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    report = _write(tmp_path, _sarif(_result("CVE-2026-4444", "zlib", "1", "2")))
    gate.main(["--report", str(report), "--scanner-outcome", "failure"])
    assert "refusing to promote" in capsys.readouterr().out


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-10")
def test_markdown_lists_every_finding_worst_first(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    report = _write(
        tmp_path,
        _sarif(
            _result("CVE-1", "pyyaml", "6.0.1", ""),
            _result("CVE-2", "django", "4.2.0", "4.2.1"),
            _result("CVE-3", "httpx", "0.27.0", "0.27.1"),
            rules=[_rule("CVE-1", "LOW"), _rule("CVE-2", "CRITICAL"), _rule("CVE-3", "HIGH")],
        ),
    )
    assert gate.main(["--report", str(report), "--markdown"]) == gate.EXIT_CLEAN
    out = capsys.readouterr().out
    assert "3 finding(s): 1 CRITICAL, 1 HIGH, 1 LOW." in out
    rows = [line for line in out.splitlines() if line.startswith("| ") and "CVE-" in line]
    assert [row.split(" | ")[1] for row in rows] == ["CVE-2", "CVE-3", "CVE-1"]
    # An unfixed finding is listed, with no fix, rather than hidden because the gate ignores it.
    assert rows[-1].endswith("| — |")


def test_markdown_of_a_clean_report_says_so(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert gate.main(["--report", str(_write(tmp_path, _sarif())), "--markdown"]) == gate.EXIT_CLEAN
    assert "No findings." in capsys.readouterr().out


def test_markdown_of_a_missing_report_is_not_observable_not_clean(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert gate.main(["--report", str(tmp_path / "never.sarif"), "--markdown"]) == gate.EXIT_NOT_OBSERVABLE
    assert "NOT OBSERVABLE" in capsys.readouterr().out


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-10")
@pytest.mark.parametrize(
    ("ledger", "missing"),
    [
        pytest.param("# CVE-1 (x): not reachable; accepted G, 2026-09-25.\nCVE-1\n", [], id="reasoned"),
        pytest.param("CVE-1\n", [(1, "CVE-1")], id="bare-entry"),
        pytest.param("#\nCVE-1\n", [(2, "CVE-1")], id="empty-comment"),
        pytest.param("# reason\n\nCVE-1\n", [(3, "CVE-1")], id="blank-line-breaks-the-link"),
        pytest.param("# reason for one\nCVE-1\nCVE-2\n", [(3, "CVE-2")], id="one-reason-one-entry"),
        pytest.param("# header only\n\n", [], id="no-entries"),
    ],
)
def test_every_waiver_needs_a_reason_directly_above_it(ledger: str, missing: list[tuple[int, str]]) -> None:
    assert gate.unreasoned_waivers(ledger) == missing


def test_cores_own_waiver_ledger_meets_the_rule_it_sets() -> None:
    assert gate.unreasoned_waivers((REPO_ROOT / ".trivyignore").read_text(encoding="utf-8")) == []


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-10")
def test_check_waivers_fails_an_unreasoned_ledger(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "plugin").mkdir()
    (tmp_path / "plugin" / ".trivyignore").write_text("CVE-2026-9\n", encoding="utf-8")
    assert gate.main(["--check-waivers", "plugin/.trivyignore"]) == gate.EXIT_FINDINGS
    assert "CVE-2026-9" in capsys.readouterr().out


def test_check_waivers_passes_a_reasoned_ledger(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".trivyignore").write_text("# why, who, when\nCVE-2026-9\n", encoding="utf-8")
    assert gate.main(["--check-waivers", ".trivyignore"]) == gate.EXIT_CLEAN


@pytest.mark.parametrize("name", ["ledger.txt", "../.trivyignore"])
def test_check_waivers_reads_only_a_trivyignore_inside_the_workspace(tmp_path, monkeypatch, name) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    (workspace / "ledger.txt").write_text("# r\nCVE-1\n", encoding="utf-8")
    (tmp_path / ".trivyignore").write_text("# r\nCVE-1\n", encoding="utf-8")
    assert gate.main(["--check-waivers", name]) == gate.EXIT_NOT_OBSERVABLE


def test_the_two_waiver_parsers_agree() -> None:
    """`tap_plugins.validate.repo` carries a second copy of `unreasoned_waivers`, deliberately.

    `scripts/release_cve_gate.py` is stdlib-only and runs on the runner's bare interpreter under
    `scripts/`, which is not shipped in the `tap_plugins` wheel; the checker's copy has to work
    from an installed wheel against a repository that is not TAP. Duplication is the right call
    there and the wrong one to leave unheld — two implementations of "waived" that drift are two
    different gates wearing one name. This is the corpus that keeps them one rule, and every case
    in it is a shape that has to be decided the same way on both roads.
    """
    from tap_plugins.validate.repo import unreasoned_waivers as checker_side

    corpus = [
        "",
        "\n\n\n",
        "CVE-1\n",
        "# reason\nCVE-1\n",
        "#\nCVE-1\n",
        "#   \nCVE-1\n",
        "# reason\n\nCVE-1\n",
        "# reason\nCVE-1\nCVE-2\n",
        "# a\n# b\nCVE-1\n",
        "  # indented reason\n  CVE-1\n",
        "# reason\nCVE-1\n\n# other\nCVE-2\n",
        "# reason\nCVE-1\n# no id follows\n",
        "CVE-1\n# reason\nCVE-2\n",
    ]
    for text in corpus:
        assert gate.unreasoned_waivers(text) == checker_side(text), f"the two parsers disagree on {text!r}"


def test_each_gates_verdict_says_what_it_actually_gated_on(tmp_path: Path) -> None:
    """A clean line must not claim more than the scan made (Q94d, 2026-09-26).

    The two roads no longer share a severity scope: the release gate passes `--ignore-unfixed`
    and blocks only on a FIXABLE High/Critical; the plugin closure gate blocks on any. Before
    this, both printed "no fixable High/Critical" — so a plugin run that had in fact blocked on
    unfixable findings reported itself in the release gate's narrower words. The flag changed and
    the sentence did not, which is the defect a live run surfaced.
    """
    empty = _write(tmp_path, _sarif())

    release_code, release_lines = gate.classify(empty, scanner_ok=True, root=tmp_path, scope=gate.SCOPES["release"])
    plugin_code, plugin_lines = gate.classify(
        empty, scanner_ok=True, root=tmp_path, scope=gate.SCOPES["plugin-closure"]
    )

    assert release_code == plugin_code == gate.EXIT_CLEAN
    assert "no fixable High/Critical" in release_lines[0]
    assert "no High/Critical" in plugin_lines[0]
    assert "fixable" not in plugin_lines[0], "the plugin road does not ignore unfixed, so it must not say fixable"
    assert "fixable" not in gate.REFUSALS["plugin-closure"]
    assert "fixable" in gate.REFUSALS["release"]
