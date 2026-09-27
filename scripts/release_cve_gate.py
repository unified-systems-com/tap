#!/usr/bin/env python3
"""Classify a release candidate's Trivy report: clean, blocking findings, or NOT OBSERVABLE.

The release CVE gate (`req-cicd-base-image-lifecycle-2`, tap#526) blocks a versioned tag on a
High/Critical vulnerability that HAS A FIX. Trivy's own exit code cannot express the distinction
that matters here: `1` means "findings" and any other non-zero means "the scan did not happen",
but a step that merely fails tells an operator neither which CVE nor whether anything was looked
at. Both block a release; they are different events and must read differently.

Three verdicts, mirroring the attestation gate (tap#525):

* **clean** (exit 0) — the scanner ran and reported nothing at the gated severity.
* **FINDINGS** (exit 1) — named CVEs, each with package, installed and fixed version.
* **NOT OBSERVABLE** (exit 2) — no report, an unparseable report, or the scanner exited
  non-zero without producing results. "Could not look" must never render as "nothing to find".

Why fixed-only: an unfixed CVE (zlib CVE-2026-85091, tap#491 — no upstream fix exists anywhere)
would block every release with no action available, so `--ignore-unfixed` is the scanner's job
and this classifier simply reports what survived it. Waivers live in `.trivyignore`, read from
the TAGGED commit so a later waiver cannot retroactively pass an older release.

The same classifier gates plugin CI's scan of a plugin's own dependency closure
(`plugin-ci.yml`, tap#772) — the same Trivy flags, the same three verdicts, a waiver ledger in
the plugin repository — with `--gate plugin-closure` choosing the refusal text. `--markdown`
renders every finding of a report as a table for a job summary; it reports, it never gates.
`--check-waivers` holds a `.trivyignore` to the ledger's rule: every entry sits directly under
a comment giving its reason.

Stdlib only: it runs on the runner's interpreter under `scripts/` (the host syntax floor).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_NOT_OBSERVABLE = 2


class Finding:
    """One SARIF result, reduced to what an operator needs in the refusal message."""

    def __init__(self, rule_id: str, severity: str, package: str, installed: str, fixed: str) -> None:
        self.rule_id = rule_id
        self.severity = severity
        self.package = package
        self.installed = installed
        self.fixed = fixed

    def render(self) -> str:
        where = self.package or "?"
        if self.installed:
            where = f"{where} {self.installed}"
        fix = f" -> fixed in {self.fixed}" if self.fixed else ""
        return "{} [{}] {}{}".format(self.rule_id or "?", self.severity or "?", where, fix)


def _rules_by_id(sarif: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rules: dict[str, dict[str, Any]] = {}
    for run in sarif.get("runs") or []:
        driver = ((run.get("tool") or {}).get("driver")) or {}
        for rule in driver.get("rules") or []:
            rule_id = rule.get("id")
            if isinstance(rule_id, str):
                rules[rule_id] = rule
    return rules


def _property(rule: dict[str, Any], name: str) -> str:
    value = (rule.get("properties") or {}).get(name)
    return value if isinstance(value, str) else ""


def _message_field(text: str, label: str) -> str:
    """Trivy writes `Package: x`, `Installed Version: y`, `Fixed Version: z` into the message."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(label.lower() + ":"):
            return stripped.split(":", 1)[1].strip()
    return ""


def findings(sarif: dict[str, Any]) -> list[Finding]:
    """Every SARIF result, flattened. An empty list means the scanner reported nothing."""
    rules = _rules_by_id(sarif)
    out: list[Finding] = []
    for run in sarif.get("runs") or []:
        for result in run.get("results") or []:
            rule_id = result.get("ruleId") or ""
            rule = rules.get(rule_id, {})
            text = ((result.get("message") or {}).get("text")) or ""
            out.append(
                Finding(
                    rule_id=rule_id,
                    severity=_property(rule, "security-severity") or _property(rule, "tags") or _severity(rule),
                    package=_message_field(text, "Package"),
                    installed=_message_field(text, "Installed Version"),
                    fixed=_message_field(text, "Fixed Version"),
                )
            )
    return out


def _severity(rule: dict[str, Any]) -> str:
    tags = (rule.get("properties") or {}).get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and tag.upper() in ("HIGH", "CRITICAL", "MEDIUM", "LOW"):
                return tag.upper()
    return ""


def contained(report: Path, root: Path) -> Path | None:
    """The report path, or None if it is not a `.sarif` file inside `root`.

    The gate reads the report ITS OWN scan step just wrote into the workspace. Accepting an
    arbitrary path from argv would let a caller point the verdict at any file on the runner
    (SonarCloud `pythonsecurity:S8707`); allow by exception instead — resolved, inside the
    checkout, and named like what Trivy writes.
    """
    try:
        resolved = report.resolve()
        inside = resolved.is_relative_to(root.resolve())
    # `# fmt: skip` is load-bearing: black runs with target-version py314 and REWRITES
    # `except (A, B, C):` into PEP 758's unparenthesised form, which only 3.14 parses. This
    # module runs under the RUNNER's bare python3 before any container exists, so that
    # rewrite is an import-time death nothing can catch — the shape that produced no SBOM
    # attestations for 15 days (tap#518). Two commits already lost the parentheses to the
    # formatter here; the host-syntax-floor guard caught both.
    except (OSError, RuntimeError, ValueError):  # fmt: skip
        return None
    if not inside or resolved.suffix != ".sarif":
        return None
    return resolved


def classify(
    report: Path, scanner_ok: bool, root: Path | None = None, scope: str = "fixable High/Critical"
) -> tuple[int, list[str]]:
    """Return (exit code, lines to print). `scanner_ok` is the scan step's own outcome."""
    safe = contained(report, root if root is not None else Path.cwd())
    if safe is None:
        return EXIT_NOT_OBSERVABLE, [
            f"NOT OBSERVABLE: refusing to read {report} — a release verdict is read only from a "
            f".sarif report inside the workspace the scan wrote to."
        ]
    report = safe
    if not report.is_file() or report.stat().st_size == 0:
        return EXIT_NOT_OBSERVABLE, [
            f"NOT OBSERVABLE: the scanner produced no report at {report} — the scan did not complete, "
            "so nothing can be said about this candidate's vulnerabilities."
        ]
    try:
        sarif = json.loads(report.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return EXIT_NOT_OBSERVABLE, [f"NOT OBSERVABLE: {report} is not a readable SARIF report: {exc}"]
    if not isinstance(sarif, dict) or "runs" not in sarif:
        return EXIT_NOT_OBSERVABLE, [f"NOT OBSERVABLE: {report} has no SARIF `runs` — refusing to read it as clean"]

    found = findings(sarif)
    if found:
        lines = ["FINDINGS: {} {} vulnerabilit{}".format(len(found), scope, "y" if len(found) == 1 else "ies")]
        lines.extend("  " + finding.render() for finding in sorted(found, key=lambda f: f.rule_id))
        return EXIT_FINDINGS, lines
    if not scanner_ok:
        return EXIT_NOT_OBSERVABLE, [
            "NOT OBSERVABLE: the scanner exited non-zero but reported no results — it failed to "
            "run (database download, registry pull, auth), rather than finding nothing."
        ]
    return EXIT_CLEAN, [f"clean: no {scope} vulnerability outside .trivyignore"]


#: What each gate actually gates on, in words. NOT the same on both roads since Q94d (George,
#: 2026-09-26): the release gate passes `--ignore-unfixed` and so blocks only on a FIXABLE
#: High/Critical, while the plugin closure gate blocks on any of them. The verdict text has to
#: say which, or a clean line reads as a stronger claim than the scan made — the defect this
#: constant exists to prevent was exactly that: the flag changed and the sentence did not.
SCOPES: dict[str, str] = {
    "release": "fixable High/Critical",
    "plugin-closure": "High/Critical",
}

#: The refusal each gate prints after a non-clean verdict. `{subject}` is filled in.
REFUSALS: dict[str, str] = {
    "release": (
        "::error::refusing to promote{subject} — a release must not ship a fixable High/Critical "
        "vulnerability, and a scan that did not complete is not a pass (tap#526). Waive with a "
        "reason in .trivyignore, or rebuild on a patched base."
    ),
    "plugin-closure": (
        "::error::refusing{subject} — the plugin's own dependency closure carries a High/Critical "
        "vulnerability (with or without a fix available, unlike the release gate — Q94d), or the scan "
        "did not complete, and neither is a pass (tap#772). Raise the dependency's floor in "
        "pyproject.toml, drop or swap the dependency, or waive the id with a reason comment in the "
        "plugin repository's .trivyignore."
    ),
}


def _label(rule: dict[str, Any]) -> str:
    return _severity(rule) or "UNKNOWN"


#: Display order for the summary table: worst first.
_SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")


def markdown(sarif: dict[str, Any]) -> list[str]:
    """Every finding in a Trivy SARIF report as a Markdown table, worst severity first.

    Reports and never gates: the table lists what the report holds, including what the gate
    ignores (lower severities, no fix yet), so a reader sees the whole closure's state.
    """
    rules = _rules_by_id(sarif)
    rows: list[tuple[int, str, str, str, str, str]] = []
    for run in sarif.get("runs") or []:
        for result in run.get("results") or []:
            rule_id = result.get("ruleId") or ""
            label = _label(rules.get(rule_id, {}))
            text = ((result.get("message") or {}).get("text")) or ""
            rank = _SEVERITY_ORDER.index(label) if label in _SEVERITY_ORDER else len(_SEVERITY_ORDER)
            rows.append(
                (
                    rank,
                    label,
                    rule_id,
                    _message_field(text, "Package"),
                    _message_field(text, "Installed Version"),
                    _message_field(text, "Fixed Version"),
                )
            )
    if not rows:
        return ["No findings."]
    counts = ", ".join(
        f"{sum(1 for row in rows if row[1] == label)} {label}"
        for label in _SEVERITY_ORDER
        if any(row[1] == label for row in rows)
    )
    out = [f"{len(rows)} finding(s): {counts}.", "", "| severity | id | package | installed | fixed in |"]
    out.append("| --- | --- | --- | --- | --- |")
    for _, label, rule_id, package, installed, fixed in sorted(rows):
        out.append(f"| {label} | {rule_id or '?'} | {package or '?'} | {installed or '?'} | {fixed or '—'} |")
    return out


def _print_markdown(report: Path) -> int:
    safe = contained(report, Path.cwd())
    try:
        sarif = json.loads(safe.read_text(encoding="utf-8")) if safe is not None else None
    except (ValueError, OSError):  # fmt: skip
        sarif = None
    if not isinstance(sarif, dict) or "runs" not in sarif:
        print(f"Report `{report.name}` is missing or unreadable — NOT OBSERVABLE, nothing to list.")
        return EXIT_NOT_OBSERVABLE
    print("\n".join(markdown(sarif)))
    return EXIT_CLEAN


def unreasoned_waivers(text: str) -> list[tuple[int, str]]:
    """Every `.trivyignore` entry whose line is not directly under a reason comment.

    The ledger's rule (core's `.trivyignore` header): a waiver is an operator's decision, and
    the reason sits in the comment immediately above the id. A bare `#` does not count, and a
    blank line between the reason and the id breaks the link — otherwise one comment at the
    top of a file would read as the reason for everything under it.
    """
    missing: list[tuple[int, str]] = []
    previous = ""
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line and not line.startswith("#"):
            reason = previous.lstrip("#").strip() if previous.startswith("#") else ""
            if not reason:
                missing.append((number, line))
        previous = line
    return missing


def _check_waivers(ledger: Path) -> int:
    root = Path.cwd().resolve()
    try:
        resolved = ledger.resolve()
        inside = resolved.is_relative_to(root)
    except (OSError, RuntimeError, ValueError):  # fmt: skip
        inside = False
    if not inside or resolved.name != ".trivyignore" or not resolved.is_file():
        print(f"::error::refusing to read {ledger} — the waiver ledger is a .trivyignore inside the workspace")
        return EXIT_NOT_OBSERVABLE
    missing = unreasoned_waivers(resolved.read_text(encoding="utf-8"))
    for number, entry in missing:
        print(f"::error::{ledger}:{number}: waiver `{entry}` has no reason comment directly above it")
    if missing:
        print(
            f"::error::{len(missing)} waiver(s) without a reason — say what the finding is, why it does not "
            "apply (or is accepted), who accepted it and when, in a comment directly above the id."
        )
        return EXIT_FINDINGS
    print(f"waiver ledger {ledger}: every entry carries a reason")
    return EXIT_CLEAN


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="the SARIF file Trivy wrote")
    parser.add_argument("--check-waivers", type=Path, metavar="TRIVYIGNORE", help="check a waiver ledger; no scan")
    parser.add_argument(
        "--scanner-outcome",
        choices=("success", "failure"),
        help="the scan step's own outcome, so a crash is not read as a clean bill of health (required to gate)",
    )
    parser.add_argument("--subject", default="", help="what was scanned, for the message")
    parser.add_argument("--gate", choices=sorted(REFUSALS), default="release", help="which refusal text to print")
    parser.add_argument("--markdown", action="store_true", help="print every finding as a Markdown table; no verdict")
    args = parser.parse_args(argv)

    if args.check_waivers is not None:
        return _check_waivers(args.check_waivers)
    if args.report is None:
        parser.error("--report is required")
    if args.markdown:
        return _print_markdown(args.report)
    if args.scanner_outcome is None:
        parser.error("--scanner-outcome is required to classify a report")

    code, lines = classify(args.report, scanner_ok=args.scanner_outcome == "success", scope=SCOPES[args.gate])
    prefix = "::error::" if code != EXIT_CLEAN else ""
    subject = f" ({args.subject})" if args.subject else ""
    print(f"{prefix}{lines[0]}{subject}")
    for line in lines[1:]:
        print(line)
    if code != EXIT_CLEAN:
        print(REFUSALS[args.gate].format(subject=subject))
    return code


if __name__ == "__main__":
    sys.exit(main())
