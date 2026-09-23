#!/usr/bin/env python3
"""Headless-Chromium driver for the running TAP web app (drive-browser skill).

Drives a real browser (Playwright + Chromium) against the running dev server so
you can verify client-side behavior an HTTP fetch can't see — JS rendering,
local-time localization, Tabulator formatters, HTMX swaps.

Two things make it useful for TAP specifically:

* ``--session`` injects a Django ``sessionid`` cookie so auth-walled pages load
  without driving the Google OIDC flow. Mint one with ``mint_session.py``.
* ``--tz`` sets the browser's IANA zone, so viewer-local time rendering
  (spec-web-time-display) is deterministic and provable (render as
  ``America/New_York`` vs ``America/Los_Angeles`` and watch the display shift
  while the UTC ``title``/``datetime`` stay fixed).

Prints the text/title/datetime of every element matching ``--select`` (default
``time``) after JS runs, any console errors, and optionally a full-page
screenshot. Run with the skill's venv python — see SKILL.md.
"""

from __future__ import annotations

import argparse

from playwright.sync_api import sync_playwright


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", required=True, help="Full URL to load, e.g. http://localhost:8030/administrivia/batches")
    ap.add_argument(
        "--session", default="", help="Django sessionid cookie value (from mint_session.py); omit for public pages"
    )
    ap.add_argument(
        "--cookie-name",
        default="sessionid",
        help="Session cookie name — per stack, printed by mint_session.py as SESSIONCOOKIE (tap#773)",
    )
    ap.add_argument("--host", default="localhost", help="Cookie domain (default: localhost)")
    ap.add_argument(
        "--tz", default="America/New_York", help="IANA timezone the browser reports (default: America/New_York)"
    )
    ap.add_argument("--select", default="time", help="CSS selector to dump text/title/datetime for (default: time)")
    ap.add_argument("--shot", default="", help="Full-page screenshot output path (.png); omit to skip")
    ap.add_argument(
        "--wait-ms",
        type=int,
        default=1500,
        help="Extra settle time after networkidle for JS formatters (default: 1500)",
    )
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(timezone_id=args.tz, viewport={"width": 1400, "height": 1000})
        if args.session:
            ctx.add_cookies([{"name": args.cookie_name, "value": args.session, "domain": args.host, "path": "/"}])
        page = ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(args.url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(args.wait_ms)

        hits = page.eval_on_selector_all(
            args.select,
            """els => els.map(e => ({
                text: e.textContent,
                title: e.getAttribute('title'),
                datetime: e.getAttribute('datetime'),
            }))""",
        )
        print(f"TZ={args.tz}  URL={args.url}")
        print(f"console_errors={errors}")
        print(f"match_count[{args.select}]={len(hits)}")
        for h in hits[:15]:
            print("  ", h)
        if args.shot:
            page.screenshot(path=args.shot, full_page=True)
            print(f"screenshot={args.shot}")
        browser.close()


if __name__ == "__main__":
    main()
