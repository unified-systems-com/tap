"""Drive TAP rooms in Chromium and record what a QA reviewer needs: shots, behaviour checks, axe results.

Run with the drive-browser venv python (Playwright + Chromium; axe-core from axe-playwright-python, or
--axe-js). One JSON report and one screenshot set per run, written under --out (created mode 700:
screenshots of a real stack hold its data).

    qa_drive.py --session-file logs/.drive-session --out logs/refine/round-1 \
        --room stage=/stage --room hosts=/stage/hosts [--widths 1440,900] [--crawl]

Per room and width: HTTP status, console errors, horizontal overflow, a full-page shot, the structural
sidebar (present, aria-current, collapses to a rail, no hamburger), the first drawer-enabled table (a row
click opens the drawer with seven categories and ?drawer= in the URL, Escape closes it and returns focus,
a shot with it open), the first filter bar (a chip click narrows the rows and writes ?f.; a reload keeps
it), and axe-core (WCAG 2 A/AA) violations by impact. Every check reports what it saw, never just "ok".
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import Locator, Page, sync_playwright

CATEGORIES = ["overview", "findings", "relationships", "configuration", "tags", "provenance", "raw"]


def _port(worktree: Path) -> str:
    env = worktree / ".env.local"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("WEB_PORT="):
                return line.split("=", 1)[1].strip()
    return "8000"


def _session(path: Path) -> dict[str, str]:
    pairs = (line.split("=", 1) for line in path.read_text().split() if "=" in line)
    env = dict(pairs)
    if "SESSIONKEY" not in env or "SESSIONCOOKIE" not in env:
        sys.exit(f"{path}: needs SESSIONKEY=... and SESSIONCOOKIE=... (see drive-browser mint_session.py)")
    return env


def _axe_source(explicit: str | None) -> str | None:
    if explicit:
        return Path(explicit).read_text()
    try:
        import axe_playwright_python  # type: ignore[import-not-found]

        return (Path(axe_playwright_python.__file__).parent / "axe.min.js").read_text()
    except (ImportError, OSError):
        return None


def settle(page: Page, ms: int = 1200) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def check_sidebar(page: Page) -> dict[str, Any]:
    out: dict[str, Any] = {"present": page.locator("aside.tap-sb").count() > 0}
    out["hamburger_like"] = page.evaluate(
        "() => [...document.querySelectorAll('button,[role=button]')].filter(b => /menu|hamburger|☰/i.test((b.getAttribute('aria-label')||'') + b.textContent) && !b.closest('.tap-usermenu')).length"
    )
    if not out["present"]:
        return out
    out["items"] = page.locator("aside.tap-sb a.tap-sb-link").count()
    current = page.locator('aside.tap-sb a[aria-current="page"]')
    out["current"] = current.first.inner_text().strip() if current.count() else None
    toggle = page.locator("[data-tap-sb-collapse]")
    before = page.evaluate("() => document.querySelector('aside.tap-sb').getBoundingClientRect().width")
    toggle.click()
    page.wait_for_timeout(250)
    after = page.evaluate("() => document.querySelector('aside.tap-sb').getBoundingClientRect().width")
    out["width_expanded_then_toggled"] = [round(before), round(after)]
    out["collapse_label"] = toggle.get_attribute("aria-label")
    toggle.click()  # restore
    page.wait_for_timeout(250)
    return out


def check_drawer(page: Page, shot_path: Path) -> dict[str, Any]:
    rows = page.locator("[data-tap-table-drawer] .tabulator-row[data-tap-row-entity]")
    out: dict[str, Any] = {"enabled_rows": rows.count()}
    if not out["enabled_rows"]:
        return out
    row = rows.first
    row.scroll_into_view_if_needed()
    # A cell that holds a link navigates by design; the drawer opens from the rest of the row.
    plain = row.locator(".tabulator-cell:not(:has(a))")
    out["clicked_plain_cell"] = plain.count() > 0
    (plain.first if plain.count() else row).click()
    try:
        page.wait_for_selector("#tap-drawer:not([hidden]) [data-tap-drawer-category]", timeout=8000)
    except Exception:  # noqa: BLE001 — a timeout is the finding
        out["opened"] = False
        return out
    page.wait_for_timeout(300)
    out["opened"] = True
    out["title"] = page.locator("#tap-drawer-title").inner_text().strip()
    out["categories"] = page.eval_on_selector_all("#tap-drawer [data-tap-drawer-category]", "els => els.map(e => e.dataset.tapDrawerCategory)")
    out["counts"] = page.eval_on_selector_all("#tap-drawer .tap-drawer-tabs a", "els => els.map(e => e.textContent.trim().replace(/\\s+/g,' '))")
    out["overview_rows"] = page.locator('#tap-drawer [data-tap-drawer-category="overview"] dt').count()
    out["url_has_drawer"] = "drawer=" in page.url
    out["focus_in_drawer"] = page.evaluate("() => !!document.activeElement && !!document.activeElement.closest('#tap-drawer')")
    out["row_marked"] = page.locator(".tap-row--drawer-active").count()
    page.screenshot(path=str(shot_path), full_page=False)
    out["shot"] = str(shot_path)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    out["closed_by_escape"] = page.locator("#tap-drawer[hidden]").count() == 1
    out["focus_returned_to_row"] = page.evaluate("() => !!document.activeElement && document.activeElement.hasAttribute('data-tap-row-entity')")
    out["url_cleared"] = "drawer=" not in page.url
    if out["focus_returned_to_row"]:
        page.keyboard.press("Enter")
        try:
            page.wait_for_selector("#tap-drawer:not([hidden]) [data-tap-drawer-category]", timeout=8000)
            out["opened_by_enter"] = True
        except Exception:  # noqa: BLE001 — a timeout is the finding
            out["opened_by_enter"] = False
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    return out


def table_rows(panel: Locator) -> int:
    """Rows the table holds after filtering. Tabulator renders only the visible rows, so the DOM undercounts."""
    mount = panel.locator("[data-tap-table-mount]").first
    if not mount.count():
        return 0
    return int(
        mount.evaluate(
            "el => { const t = window.Tabulator && Tabulator.findTable(el)[0]; "
            "return t ? t.getDataCount('active') : el.querySelectorAll('.tabulator-row').length; }"
        )
    )


def check_filters(page: Page, base: str) -> dict[str, Any]:
    bar = page.locator("[data-tap-filterbar]").first
    out: dict[str, Any] = {"bars": page.locator("[data-tap-filterbar]").count()}
    if not out["bars"]:
        return out
    out["views"] = bar.locator(".tap-filterbar-view").all_inner_texts()
    chips = bar.locator(".tap-filter:not(.tap-filter--group) a.tap-chip:not(.is-active)")
    out["chips"] = chips.count()
    if not out["chips"]:
        return out
    panel = page.locator(".tap-panel--table", has=bar).first
    rows_before = table_rows(panel)
    label = chips.first.locator(".tap-chip-label").inner_text().strip() if chips.first.locator(".tap-chip-label").count() else chips.first.inner_text().strip()
    expected = chips.first.locator(".tap-chip-count").inner_text().strip() if chips.first.locator(".tap-chip-count").count() else ""
    chips.first.click()
    settle(page, 900)
    panel = page.locator(".tap-panel--table", has=page.locator("[data-tap-filterbar]")).first
    out["clicked"] = label
    out["chip_count_said"] = expected
    out["rows_before_after"] = [rows_before, table_rows(panel)]
    out["url_has_filter"] = "f." in urlsplit(page.url).query
    out["active_after_click"] = page.locator("[data-tap-filterbar] .tap-filter:not(.tap-filter--group) a.tap-chip.is-active").count()
    page.goto(page.url)
    settle(page)
    out["active_after_reload"] = page.locator("[data-tap-filterbar] .tap-filter:not(.tap-filter--group) a.tap-chip.is-active").count()
    return out


def run_axe(page: Page, source: str | None) -> dict[str, Any]:
    if not source:
        return {"skipped": "axe-core not available (pip install axe-playwright-python, or --axe-js)"}
    page.add_script_tag(content=source)
    result = page.evaluate(
        "async () => { const r = await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa','wcag22aa']}}); "
        "return r.violations.map(v => ({id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length, "
        "targets: v.nodes.slice(0, 3).map(n => n.target.join(' '))})); }"
    )
    by_impact: dict[str, int] = {}
    for v in result:
        by_impact[v["impact"] or "unknown"] = by_impact.get(v["impact"] or "unknown", 0) + 1
    return {"violations": result, "by_impact": by_impact}


def page_facts(page: Page) -> dict[str, Any]:
    facts: dict[str, Any] = page.evaluate(
        """() => {
          const main = document.querySelector('main');
          const text = main ? main.innerText : '';
          return {
            title: document.title,
            h1: [...document.querySelectorAll('main h1')].map(h => h.textContent.trim()).slice(0, 3),
            headings: document.querySelectorAll('main h1, main h2, main h3').length,
            words: (text.match(/\\S+/g) || []).length,
            tables: document.querySelectorAll('[data-tap-table-mount]').length,
            rows: document.querySelectorAll('.tabulator-row').length,
            errors: [...document.querySelectorAll('.tap-panel-error')].map(e => e.textContent.trim().slice(0, 160)),
            breadcrumb: [...document.querySelectorAll('nav[aria-label=Breadcrumb] ol li')].map(l => l.textContent.trim()).filter(Boolean),
          };
        }"""
    )
    return facts


def main() -> None:
    worktree = Path(__file__).resolve().parents[3]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=f"http://localhost:{_port(worktree)}")
    ap.add_argument("--session-file", type=Path, default=worktree / "logs" / ".drive-session")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--room", action="append", default=[], help="name=/path (repeatable)")
    ap.add_argument("--widths", default="1440,900")
    ap.add_argument("--tz", default="America/New_York")
    ap.add_argument("--scheme", choices=["light", "dark"], default="light", help="prefers-color-scheme for every page")
    ap.add_argument("--axe-js", default=None)
    ap.add_argument("--crawl", action="store_true", help="also crawl same-origin links from / to depth 3")
    ap.add_argument("--max-pages", type=int, default=60)
    args = ap.parse_args()

    rooms = dict(r.split("=", 1) for r in args.room)
    if not rooms:
        sys.exit("give at least one --room name=/path")
    args.out.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(args.out, 0o700)
    env = _session(args.session_file)
    axe = _axe_source(args.axe_js)
    widths = [int(w) for w in args.widths.split(",")]
    report: dict[str, Any] = {"base": args.base, "scheme": args.scheme, "rooms": {}, "crawl": {}}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width in widths:
            ctx = browser.new_context(viewport={"width": width, "height": 1000}, timezone_id=args.tz, color_scheme=args.scheme)
            ctx.add_cookies([{"name": env["SESSIONCOOKIE"], "value": env["SESSIONKEY"], "domain": urlsplit(args.base).hostname, "path": "/"}])
            ctx.add_init_script("try { localStorage.removeItem('tap-sidebar'); localStorage.removeItem('theme'); } catch (e) {}")
            page = ctx.new_page()
            errors: list[str] = []
            page.on("console", lambda m, errors=errors: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            for name, path in rooms.items():
                errors.clear()
                key = f"{name}@{width}"
                entry: dict[str, Any] = {"path": path}
                resp = page.goto(args.base + path)
                settle(page)
                entry["status"] = resp.status if resp else None
                entry["h_overflow"] = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
                entry["facts"] = page_facts(page)
                shot = args.out / f"{name}-{width}.png"
                page.screenshot(path=str(shot), full_page=True)
                entry["shot"] = str(shot)
                entry["axe"] = run_axe(page, axe) if width == widths[0] else {"skipped": "first width only"}
                entry["sidebar"] = check_sidebar(page)
                entry["drawer"] = check_drawer(page, args.out / f"{name}-{width}-drawer.png")
                if urlsplit(page.url).path != urlsplit(args.base + path).path:
                    entry["drawer"]["navigated_to"] = urlsplit(page.url).path
                page.goto(args.base + path)
                settle(page)
                entry["filters"] = check_filters(page, args.base)
                entry["console_errors"] = list(errors)
                report["rooms"][key] = entry
            ctx.close()

        if args.crawl:
            ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
            ctx.add_cookies([{"name": env["SESSIONCOOKIE"], "value": env["SESSIONKEY"], "domain": urlsplit(args.base).hostname, "path": "/"}])
            page = ctx.new_page()
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            seen: dict[str, Any] = {}
            per_kind: dict[str, int] = {}
            queue = deque([("/", 0)])
            host = urlsplit(args.base).netloc
            while queue and len(seen) < args.max_pages:
                path, depth = queue.popleft()
                kind = re.sub(r"/object/([^/]+)/.*", r"/object/\1", path.split("?")[0])
                if path in seen or per_kind.get(kind, 0) >= 4:
                    continue
                per_kind[kind] = per_kind.get(kind, 0) + 1
                errors.clear()
                resp = page.goto(args.base + path)
                settle(page, 800)
                seen[path] = {"status": resp.status if resp else None, "depth": depth, "console": list(errors)}
                if depth >= 3:
                    continue
                for h in page.eval_on_selector_all("main a[href], aside.tap-sb a[href]", "els => els.map(e => e.getAttribute('href'))"):
                    if not h or h.startswith(("#", "javascript:", "?")):
                        continue
                    u = urlsplit(urljoin(args.base + path, h))
                    if u.netloc == host and not u.path.startswith(("/auth/", "/admin/", "/static/")):
                        queue.append((u.path + (f"?{u.query}" if u.query else ""), depth + 1))
            report["crawl"] = seen
            ctx.close()
        browser.close()

    out = args.out / "qa-report.json"
    out.write_text(json.dumps(report, indent=1))
    os.chmod(out, 0o600)
    print(out)


if __name__ == "__main__":
    main()
