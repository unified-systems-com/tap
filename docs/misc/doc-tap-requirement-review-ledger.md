---
spec: ../../specs/spec-tap-requirement-traceability.md
audience: [developer, llm]
covers:
  - ../../specs/spec-tap-requirement-traceability.md
  - req-tap-traceability-scope
  - req-tap-traceability-disputed
update-triggers:
  - A collapse, refactor, or audit finds code making a choice no requirement governs — add a row here and the detail section in the owning spec
  - A requirement is marked `Disputed` — add its row here in the same change (req-tap-traceability-disputed-3)
  - A listed decision is made — record the outcome in the owning spec, then strike the row
  - An owning spec's "Requirement Review Needed" section is renamed or moved
---

# Requirement Review Ledger

Places where the code makes a choice **no requirement governs**, and someone has to decide
what the requirement should be. This file is the index only — each entry's evidence and
open questions live in a `## Requirement Review Needed` section in the **owning spec**,
because that is where the answer will eventually be written.

## Why this exists

A fact with no governing requirement is a signal, not an obstacle. Either the fact is not
one, or a requirement is missing — and both want a conversation rather than an edit. The
rule that produced this ledger: **when a collapse or a cleanup has no governing
requirement, stop and record it here instead of deciding in the moment.**

It earned its place immediately. The `cytoscape:cose` entry below was collapsed to a single
constant on 2026-08-14 and reverted the same day: the eight sites shared a *value*, not a
*fact*, and merging them coupled a view's own choice of layout algorithm to an unrelated
fallback. No requirement existed to catch that — its absence was the warning.

**The discriminator**, when judging whether sites share a fact: *if the fact changed, would
every site want to change together?* Same purpose is not required — the secret-file suffix
is read by three callers that find, load, and refuse-to-commit, and a rename must move all
three. Same value is not sufficient — see below.

## Ledger rows come in two kinds

1. **Ungoverned choice** — code makes a choice no requirement governs (the placement entry
   below). The question is whether a requirement should exist.
2. **Disputed requirement** — a requirement exists and its implementation disagrees with it.
   The spec entry carries `Status: Disputed` (`req-tap-traceability-disputed`), the owning
   spec's `Requirement Review Needed` section names the code site and the disagreement, and
   the row lands here in the same change. The question is which side is right.

Both kinds resolve the same way: a human ruling recorded in the owning spec, then the row
moves to Resolved.

## Open

| # | Kind | Decision | Owning spec | Surfaced |
| :---: | --- | --- | --- | :---: |

*(none open)*

## Related backlogs

These carry their own pre-identified decision points; they are **not** duplicated into the
table above until one is actually opened.

- [doc-duplicate-derivation-backlog.md](doc-duplicate-derivation-backlog.md) — Tier 3 is
  seven findings explicitly flagged "needs a decision before editing"; Tier 4 is three
  refactors. Working a tier is the moment to check whether a finding belongs here instead.

## Resolved

| # | Kind | Ruling (all 2026-08-20, George) | Recorded in | Surfaced |
| :---: | --- | --- | --- | :---: |
| 1 | Ungoverned choice | Default graph placement: **no system-wide default, by design** — views are thoughtfully constructed, not default eye-candy. Canonized as `req-viz-panel-placement-per-view` (`In Force`). | [spec-viz-panel.md](../../tap_viz/specs/spec-viz-panel.md) | 2026-08-14 |
| 2 | Disputed requirement | Sphinx capability-blocks: **convert** — `:implements:` stripped everywhere (ownership has one convention, `TAP-IMPLEMENTS`); blocks stay as documentation-only affordance records; requirement re-scoped `Implemented`. Gryphon claims unblocked. | [spec-sphinx-capability-docs.md](../../specs/spec-sphinx-capability-docs.md) | 2026-08-14 |
| 3 | Ungoverned choice | Retired-in-place specs: **move to `specs/archive/`** — location is the fact, scanners exclude it, banner + AGENTS.md carry the signal, filename kept. Executed for spec-tap-auth-assurance-v0; the 16-entry RID-baseline floor is gone. | [spec-docs.md](../../specs/spec-docs.md) | 2026-08-14 |
| 4 | Ungoverned choice | Gridkin: **the contract comes home, the corpus stays evicted** — the Gridkin spec moves to `tap_grid/specs/`, gryphon_playground keeps the corpus and cites core RIDs. Mechanical cross-repo move deferred to the next plugin-workspace session. | [spec-tap-plugin-validation-distribution.md](../../specs/spec-tap-plugin-validation-distribution.md) | 2026-08-14 |
| 5 | Disputed requirement | Product releases: **the machinery is the implementation** — body rewritten to shipped reality, `Implemented`, mapped `non-python` to release-please.yml. SECURITY.md supported-versions found already honored; `-2` flipped to match. | [spec-cicd-hardening.md](../../specs/spec-cicd-hardening.md) | 2026-08-20 |
