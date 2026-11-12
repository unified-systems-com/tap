"""Turn a qa_drive.py report into the qa-page gates: one PASS/FAIL line per gate per room, with the evidence.

    python3 qa_gates.py logs/refine/round-1/qa-report.json > logs/refine/round-1/qa-gates.md

Exit status 1 when any blocking gate fails, so a loop can stop on it. The gates are the mechanical half
of a QA review; the editorial half (does the page answer its job) is the reviewer's, from the shots.
"""

from __future__ import annotations

import json
from typing import Any
import sys
from pathlib import Path

CATEGORIES = ["overview", "findings", "relationships", "configuration", "tags", "provenance", "raw"]


def gates(entry: dict[str, Any]) -> list[tuple[str, bool, bool, str]]:
    """``(gate, passed, blocking, evidence)`` for one room at one width."""
    out: list[tuple[str, bool, bool, str]] = []
    facts = entry.get("facts", {})
    out.append(("http", entry.get("status") == 200, True, f"status {entry.get('status')}"))
    errs = entry.get("console_errors", [])
    out.append(("console", not errs, True, f"{len(errs)} error(s)" + (f": {errs[0][:120]}" if errs else "")))
    panel_errors = facts.get("errors", [])
    out.append(("panel errors", not panel_errors, True, "; ".join(panel_errors)[:160] or "none rendered"))
    out.append(("no horizontal overflow", not entry.get("h_overflow"), True, f"overflow={entry.get('h_overflow')}"))

    sb = entry.get("sidebar", {})
    if sb.get("present"):
        w = sb.get("width_expanded_then_toggled", [0, 0])
        ok = bool(sb.get("items")) and sb.get("hamburger_like", 0) == 0 and w[0] != w[1]
        out.append(("sidebar", ok, True, f"{sb.get('items')} items, current={sb.get('current')!r}, toggle {w[0]}→{w[1]}px, hamburger-like={sb.get('hamburger_like')}"))
        out.append(("sidebar marks current", sb.get("current") is not None, False, f"current={sb.get('current')!r}"))
    else:
        out.append(("sidebar", False, True, "no aside.tap-sb"))

    dr = entry.get("drawer", {})
    if dr.get("enabled_rows"):
        cats_ok = dr.get("categories") == CATEGORIES
        ok = bool(dr.get("opened")) and cats_ok and dr.get("url_has_drawer") and dr.get("closed_by_escape")
        out.append(("drawer opens", ok, True, f"opened={dr.get('opened')} title={dr.get('title')!r} categories={'7/7' if cats_ok else dr.get('categories')} url={dr.get('url_has_drawer')} esc={dr.get('closed_by_escape')}" + (f" navigated_to={dr['navigated_to']}" if dr.get("navigated_to") else "")))
        out.append(("drawer focus", bool(dr.get("focus_in_drawer")) and bool(dr.get("focus_returned_to_row")), True, f"in={dr.get('focus_in_drawer')} returned={dr.get('focus_returned_to_row')}"))
        if dr.get("opened"):
            out.append(("drawer opens from keyboard", bool(dr.get("opened_by_enter")), True, f"Enter on the focused row: opened={dr.get('opened_by_enter')}"))
            rows = dr.get("overview_rows", 0)
            out.append(("drawer overview identifies", rows >= 4, False, f"{rows} overview rows (type and id are two; fewer than four rarely names the thing)"))
    fl = entry.get("filters", {})
    if fl.get("chips"):
        before, after = fl.get("rows_before_after", [0, 0])
        ok = fl.get("url_has_filter") and fl.get("active_after_click", 0) >= 1 and fl.get("active_after_reload", 0) >= 1
        out.append(("filter chip", bool(ok), True, f"clicked {fl.get('clicked')!r} (said {fl.get('chip_count_said')}), rows {before}→{after}, url={fl.get('url_has_filter')}, kept on reload={fl.get('active_after_reload')}"))
        said = fl.get("chip_count_said", "")
        if said.isdigit() and after and int(said) < 200:
            out.append(("chip count matches rows", int(said) == after, False, f"chip said {said}, table shows {after} rows"))

    axe = entry.get("axe", {})
    if "violations" in axe:
        serious = [v for v in axe["violations"] if v["impact"] in ("serious", "critical")]
        out.append(("axe serious/critical", not serious, True, ", ".join(f"{v['id']}×{v['nodes']}" for v in serious) or "none"))
        minor = [v for v in axe["violations"] if v["impact"] not in ("serious", "critical")]
        out.append(("axe moderate/minor", not minor, False, ", ".join(f"{v['id']}×{v['nodes']}" for v in minor) or "none"))
    return out


def main() -> int:
    report = json.loads(Path(sys.argv[1]).read_text())
    failed_blocking = 0
    print(f"# QA gates — {sys.argv[1]}\n")
    print("| Room | Gate | Result | Evidence |\n| --- | --- | :---: | --- |")
    for key, entry in report["rooms"].items():
        for gate, passed, blocking, evidence in gates(entry):
            mark = "PASS" if passed else ("FAIL" if blocking else "WARN")
            if not passed and blocking:
                failed_blocking += 1
            print(f"| {key} | {gate} | {mark} | {evidence.replace('|', '/')} |")
    crawl = report.get("crawl") or {}
    if crawl:
        bad = {p: e for p, e in crawl.items() if e.get("status") != 200 or e.get("console")}
        print(f"\nCrawl: {len(crawl)} pages, {len(bad)} with a non-200 status or console errors.")
        for p, e in list(bad.items())[:20]:
            print(f"- `{p}` status {e.get('status')} console {e.get('console')[:1]}")
        failed_blocking += len(bad)
    print(f"\n**Blocking failures: {failed_blocking}**")
    return 1 if failed_blocking else 0


if __name__ == "__main__":
    sys.exit(main())
