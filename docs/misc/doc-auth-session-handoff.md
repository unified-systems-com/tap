---
title: Auth Work — Session Handoff
date: 2026-06-23
status: handoff
audience:
  - llm
  - developer
related_docs:
  - docs/misc/doc-auth-per-app-standards.md
  - docs/misc/doc-auth-codepath-inventory.md
related_specs:
  - tap_auth/specs/spec-tap-auth-v0.md
  - specs/archive/spec-tap-auth-assurance-v0.md  # DEPRECATED/retired 2026-07-08 — surface-centric model rejected
---

# Auth Work — Session Handoff

Handoff from a long design session (2026-06-23). No auth code was changed this session; the
session produced **decisions + written standards**. The next session executes them against a
clean context budget. Read this first, then `doc-auth-per-app-standards.md`.

## The decisions made this session

1. **Stay capability-centric, not surface-centric.** The Cedar/surface-identity assurance
   apparatus (`spec-tap-auth-assurance-v0.md`, drafted with Codex) was evaluated and
   **deliberately rejected** for this scale — every real issue is a forgotten/bypassed
   *capability* gate, none needs surface identity. *That assurance spec needs reconciliation*
   (it still leans surface-centric) — flag for the Codex review pass; do not implement it as-is.

2. **The backstop becomes stateless — delete the decision ledger.** Canonical record:
   `spec-tap-auth-v0.md` req-tap-auth-policy-7/8/9. The contextvar ledger
   (`record_authorization`, `authorized_capabilities`, `push_authorization_scope`,
   `pop_authorization_scope`) is removed. The write/read backstop becomes a direct
   `policy.can(actor, needed_cap)` re-check:
   ```python
   def assert_write_authorized(ctx, *, needs_write, needs_delete):
       if needs_write  and not policy.can(ctx.user, "grid.write"):  raise UnguardedOperation(...stack...)
       if needs_delete and not policy.can(ctx.user, "grid.delete"): raise UnguardedOperation(...stack...)
   ```
   The `@requires_capability` decorator **stays** (primary gate → 403); only the ledger goes.
   Keep the loud `unguarded_operation` + `stack_info=True` (path captured lazily at the failure).

3. **Coverage moves to a static lint** (req-tap-auth-policy-9). In-house AST scanner reusing the
   `tap/tests/test_log_site_ids.py` + `tap/logging.py` scanner + baseline-ratchet machinery
   (`discover_scan_roots`, the `ast.walk` pattern, `_log_site_id_baseline.txt`-style grandfather
   file). **Not Semgrep** — the scanner enumerates graph-managed `BaseModel` subclasses at
   runtime (incl. plugin models) which a syntactic tool can't; revisit Semgrep only at a *suite*
   of rules. Land it lint-first with a grandfathering baseline (green on day one), ratchet to zero.

## Fresh-session task order (auth tightening pass, core-first)

Per `doc-auth-per-app-standards.md` sequencing. All low-cost, reuse existing mechanisms.

1. **Back out the ledger → stateless backstop** (tap_auth/tap_grid core). Remove the ledger
   primitives + scope push/pop; make `assert_write/read_authorized` the `policy.can` re-check;
   simplify the `@requires_capability` decorator (authorize only, no record); drop the
   ledger pre-authorization in `conftest.py`'s autouse fixture (tests then just need the actor to
   *hold* the caps). Update the ~40 test sites that reference ledger scopes. **This deletes the
   leak + empty-batch holes by construction.**
2. **Other core moves:** `{grid.delete}`-only delete backstop (split cover semantics — kills the
   bootloader cover-cap reach); single `is_actor_active` predicate (clears `deactivated_at` drift);
   seal empty-batch.
3. **Build the authz-coverage lint** with grandfather baseline.
4. **tap_web + plugins together:** the single host-side `grid.read` scope at `panel_view`
   (~3 lines, gates every panel incl. plugins); the panel render-read/config-write contract;
   re-raise `AuthzError`+`UnguardedOperation` (stop the swallow); page-shell read gates.
5. **tap_cares:** task-boundary program-actor context helper; `run_collection` human-trigger
   chokepoint; the production-realism test fixture (clear the ambient actor) that closes the
   conftest masking.
6. **tap_boot:** move the Collector upsert out of `ready()`; narrow the catch-all; name the
   cover-cap residual.
7. **tap_api:** authorize-before-lookup idiom; collapse the two `_caller_ctx` helpers; classify
   `list_entity_types`.

## Still open — George's decisions (not yet made)

The 8 open decisions in `doc-auth-per-app-standards.md` (§ Open decisions). George is doing a
per-app thinking pass + Codex review before implementation. The load-bearing ones for the
fresh session: **#5 conftest test-realism** (targeted fixtures vs full flip), **#3 boot cover-cap**
(now nearly free via the `{grid.delete}` split — recommend honor it), **#7 PanelType base class**
(mandatory vs ratchet).

## Provenance note

The static [codepath inventory](doc-auth-codepath-inventory.md) was a useful map but an
*unreliable oracle* — its #9 ("parse-invalid exception syntax") was a confirmed false positive
(PEP 758, valid Python 3.14). Verify inventory claims against source. The per-app standards doc is
the verified, deduplicated picture.
