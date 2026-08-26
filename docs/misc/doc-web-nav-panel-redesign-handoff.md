---
title: Navigation-as-Panel redesign — superseded handoff
spec: tap_web/specs/spec-web-chrome.md
covers:
  - req-web-chrome-migration
  - req-web-nav-panel
---

# Navigation-as-Panel redesign — handoff (superseded)

> **Superseded 2026-07-02.** This handoff captured the security/architecture
> thread that originally proposed navigation as a built-in **Panel**. That
> direction is no longer the target. The canonical architecture is now
> [`tap_web/specs/spec-web-chrome.md`](../../tap_web/specs/spec-web-chrome.md):
> navigation becomes built-in `ChromeEntry` objects on a persistent
> `ChromeSurface`, and graph-backed chrome activates only after Page/chrome read
> authorization. This doc is retained as historical context only — do not
> implement from it.

## What this thread was

The tap_web navigation security review surfaced one architectural defect:
universal chrome performed a graph read (the breadcrumb's `Page` lookup) on
every render, so pre-auth and error surfaces either read the grid or 500'd — the
root cause behind the login-500 regression. The first proposed fix modeled
navigation as a standard built-in **Panel** running a gated Search, auto-mounted
by the page builder (`req-web-nav-panel` in `spec-web-navigation.md`, now
`Deprecated`).

That framing was superseded by the chrome-system design, which resolves the same
security property more directly: graph-backed chrome is simply **not active**
before the read gate, rather than a Panel that has to degrade to a read-free
shell.

## Where the live work is

- **Target architecture:** [`tap_web/specs/spec-web-chrome.md`](../../tap_web/specs/spec-web-chrome.md)
  — `ChromeSurface` / `ChromeEntry`, the authorization boundary, and the
  incremental migration plan (`req-web-chrome-migration`), which carries its own
  open design questions. Judge scope against `plan/road-products.md` and
  `specs/spec-security-posture.md` before building.
- **Interim security fix (still in force):** the breadcrumb `Page` read is
  wrapped in `caller_can_read()` (read-free chrome) in `tap_web/navigation.py`;
  it stays until the chrome migration replaces the context-processor path
  (`req-web-nav-chrome-read-free`, `req-web-chrome-migration-2`).
- **Deprecated:** `req-web-nav-panel` (+ `-1..-4`) in
  [`spec-web-navigation.md`](../../tap_web/specs/spec-web-navigation.md).

## Relevant memory

`service-layer-guards-sprint` (the breadcrumb thread origin),
`codex-security-gateway-refactor-merged` (the gated service layer chrome builds
on), `ground-in-canon-before-building`, `subgrid-collapses-into-grid`.
