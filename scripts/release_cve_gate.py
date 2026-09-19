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
    # Parenthesised deliberately: this module runs under the RUNNER's bare python3 before any
    # container exists, and PEP 758's unparenthesised form is 3.14-only — the exact shape that
    # killed every publish for 15 days (tap#518). The host-syntax-floor guard caught it here.
    except (OSError, RuntimeError, ValueError):
        return None
    if not inside or resolved.suffix != ".sarif":
        return None
    return resolved


def classify(report: Path, scanner_ok: bool, root: Path | None = None) -> tuple[int, list[str]]:
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
        lines = [
            "FINDINGS: {} fixable High/Critical vulnerabilit{}".format(len(found), "y" if len(found) == 1 else "ies")
        ]
        lines.extend("  " + finding.render() for finding in sorted(found, key=lambda f: f.rule_id))
        return EXIT_FINDINGS, lines
    if not scanner_ok:
        return EXIT_NOT_OBSERVABLE, [
            "NOT OBSERVABLE: the scanner exited non-zero but reported no results — it failed to "
            "run (database download, registry pull, auth), rather than finding nothing."
        ]
    return EXIT_CLEAN, ["clean: no fixable High/Critical vulnerability outside .trivyignore"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path, help="the SARIF file Trivy wrote")
    parser.add_argument(
        "--scanner-outcome",
        required=True,
        choices=("success", "failure"),
        help="the scan step's own outcome, so a crash is not read as a clean bill of health",
    )
    parser.add_argument("--subject", default="", help="what was scanned, for the message")
    args = parser.parse_args(argv)

    code, lines = classify(args.report, scanner_ok=args.scanner_outcome == "success")
    prefix = "::error::" if code != EXIT_CLEAN else ""
    subject = f" ({args.subject})" if args.subject else ""
    print(f"{prefix}{lines[0]}{subject}")
    for line in lines[1:]:
        print(line)
    if code != EXIT_CLEAN:
        print(
            f"::error::refusing to promote{subject} — a release must not ship a fixable High/Critical "
            "vulnerability, and a scan that did not complete is not a pass (tap#526). Waive with a "
            "reason in .trivyignore, or rebuild on a patched base."
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
