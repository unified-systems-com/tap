---
spec: ../../specs/spec-tap-requirement-traceability.md
audience: [developer, llm]
covers:
  - ../../specs/spec-tap-requirement-traceability.md
  - req-tap-traceability-disposition
  - req-tap-traceability-accounting
update-triggers:
  - A wave lands — mark it, update the Unaccounted numbers, and re-point "current wave"
  - The exclusion vocabulary changes (category added/removed, payload rules changed)
  - The Definition of Done is amended in the owning spec
  - A ledger ruling lands on the sphinx capability-blocks or gridkin rows (they gate batches here)
assumes:
  - The claim system as built — @<spec-hash>/<code-hash> claims, five guards, placeholder-then-resync minting
  - The review-ledger discipline (docs/misc/doc-tap-requirement-review-ledger.md)
provides: |
  The execution plan for the requirement↔code mapping project's Definition of Done: every
  requirement in the tap + plugins corpus bi-directionally mapped or documented-excluded.
  Waves, sequencing constraints, decision log, and the honest effort estimate.
---

# Requirement Traceability — Closure Plan

**Definition of Done** (canonical statement in
[spec-tap-requirement-traceability.md](../../specs/spec-tap-requirement-traceability.md) §Definition
of Done): every requirement in the tap + plugins corpus is either **bi-directionally mapped**
(implementation claim and/or test-cited ACID) or **documented excluded** (a `Trace:` disposition
from the closed vocabulary). The remainder is **Unaccounted**, counted, and ratcheting to zero —
that count is the progress bar.

Total *accounting*, never total *claiming*: scarcity governs which bucket a requirement lands in;
the DoD demands only that it lands in exactly one.

## Decision log

| Date | Decision | By |
| --- | --- | --- |
| 2026-08-20 | DoD declared: whole tap + plugins corpus, mapped-or-excluded | George |
| 2026-08-20 | Doorstop model for code-side staleness (`@<spec-hash>/<code-hash>`), placeholder-then-resync minting | George |
| 2026-08-20 | Exclusion marker lives spec-side: `Trace:` line beside `Status:` in the requirement block | George |
| 2026-08-20 | Exclusion vocabulary: `process`, `narrative`, `non-python` (mandatory path), `external` (mandatory name); doctrine/disputed/archival/mapped derived, never hand-marked | George |
| 2026-08-20 | `unbuilt` + `retired` become derived buckets (status IS the disposition for future/withdrawn work); consequence: flipping to `Implemented` without evidence or exclusion fails the ratchet — the DoD enforced at the flip | session (Wave C), pending George ratify |

## Waves

### Wave A — accounting model (DONE 2026-08-20)

The DoD into the spec's Philosophy; `req-tap-traceability-disposition` and
`req-tap-traceability-accounting` authored (`Proposed`); `req-tap-traceability-scope` amended —
the "needs no code" deferral expired when the denominator was declared. This document.

### Wave B — the engine (DONE 2026-08-20)

Everything Wave A specified, built in its stated order — hash-neutral `Trace:` parsing landed
first, then the disposition parser (closed vocabulary, near-miss fail-closed, mandatory
payloads, contradiction and derived-bucket checks), then the accounting (`## Accounting Report`
generated block, drift-tested, `manage.py guards --sync-accounting`) with the Unaccounted
ratchet (`tap/guards/baselines/unaccounted_rids.txt`, fail-closed for new requirements). Two
new guards (`disposition-integrity`, `unaccounted-requirements`) in the Validation Map; both
requirements flipped to `Implemented`.

**Starting number: 1,072 Unaccounted** (of 1,132: 39 mapped, 1 excluded, 19 doctrine, 1
disputed). Dogfood landed with the engine: the convention's own machinery now carries 18
claims on the traceability requirements it implements (the `_CONVENTION_MODULES` exclusion
narrowed to the test fixtures), and `req-tap-traceability-minting` — implemented in bash —
is the first live `Trace: non-python` disposition.

### Wave C — bulk triage, batched by spec (IN PROGRESS — 1,072 → 509 after batch 1)

**Batch 1 (2026-08-20):** the structural move first — 528 unbuilt + 16 retired drained by the
derived buckets (a requirement declaring itself future work or withdrawn is accounted by its own
status) — then hand-triage of `spec-cicd-hardening` (9: statuses restored from prose, 5
`non-python`/`external` exclusions, 3 `Backlog`, 1 enforcement claim on the workflow
least-privilege guard) and `spec-dev-multisession` (10: 9 `non-python` script exclusions, 1
`process`). Skips recorded: `req-cicd-security-scanning` + `req-cicd-base-image-lifecycle`
(mixed-surface), `req-cicd-product-releases` (stale prose — says "no product releases" while
tagged releases ship; **Disputed lead** for the review ledger),
`req-dev-multisession-browser-disambiguation` (mixed shell + web surface).

The method is now a repeatable skill: **`tap/skills/triage-requirements/`** (`/triage-requirements`),
carrying the decision tree (status-first → guard-rid claims → spec-names-its-file → commit
co-occurrence → test-cite → exclusion → deliberate skip) and the earned traps.

**Batch 2 (2026-08-20): 509 → 495.** The guard-rid shortlist run corpus-wide: 7 guards claimed
their own requirements (collection-completeness, json-naming, known-dupes, mypy-ratchet,
rid-integrity, secret-leak, secret-pattern) plus `tap.spec_trace` claiming the
rid-integrity derivation it already declared in prose. Then `spec-dev-validation`: the Map
(`tap/guards/report.py`), the ratchet harness (`tap/ratchet.py`), and three claims on the
cold-boot gate command whose header names all three requirements; `gate-lean` and the promote
hook excluded as `non-python`. Four shortlist refinements folded into the skill: declared-surface
registries are pointers not targets; ACID-scoped rids don't own the parent; hedging headers are
partial slices; two guards on one rid → claim the primary. Remaining drift-status rows
(`Partially Implemented`, `Partial`) left deliberately — status normalization is its own pass.

**Batch 7 (2026-08-22): cares + plugins claims-first, 396 → 371.** The inverse corpus of the
grid: the harvest found exactly ONE test-docstring ACID citation here (vs 45 in the grid), and
36 of the ~90 requirements are zero-ACID — so the mix flipped to claims on self-naming anchors:
9 on the manifest parser (`load_manifest`, the per-section `_parse_*` family, module-wide
strictness), 9 on the validator (`validate_plugin` carrying scope+levels, per-level and
per-check functions, the management-command surface), 4 on the scheduler (tick, both models,
`Schedule.validate` for the five-field cron rule). Three task-backend exclusions (the two
executed migration plans → `process`; supervisor deployment → `non-python` entrypoint).
Placement upgrade earned: functions without docstrings get one authored carrying the claim.
Deferred whole: administrivia (11 — web-surface anchors need a proper look), scheduler tick
internals, validator CLI family (no `__main__` found — possible spec-vs-tree lead worth a
check). 111 claims live.

**Batch 6 (2026-08-21): the backwards test walk proves out, 434 → 396.** George's technique on
the grid family (import-grift / service-batch / service-write / entity) — and the walk found a
fourth authored-edge generator on arrival: **test docstrings already cite ACIDs**
("req-grid-service-batch-diag-1: operation is populated…"), so 45 markers were promoted from
the tests' own narrative citations (mechanical, spot-verified — and it reached far beyond the
four target specs: purge, search, hotlink, dimensions, occ, gryphon-limit — the requirement the
CLAIMS walk had to skip, mapped by its tests instead). 23 more markers hand-verified
name-to-criterion (the observation suite is 1:1 with its ACIDs), and the zero-ACID import-grift
spec — markers impossible — took 7 claims on the importer's self-naming anchors. 89 claims
live; 68 markers added; every touched test still green (1,252).

**Batch 5 (2026-08-20): boot + cares-secrets sweeps, 446 → 434.** (446 after the sam-dev-dupes
session's coordinated landing — their boot_records claim + a test-cite that drained
req-web-panel-obj.) Eleven claims on self-documenting anchors — the module headers already
declared their requirements in prose (boot.py/orchestrator/profile for the boot family,
loader/registry/redaction for cares-secrets, `load_secret_envelope` for the size guard) — and
two `non-python` exclusions (spawn-bridge → spawn-session.sh, precommit → the githooks scanner,
which is Python the claim scanner cannot reach). One anchor correction from verification: the
search-role derivation is `tap_grid/search_role.py`, not the orchestrator that calls it.
Deliberate skips: idempotent/trust/report/abort-signal (cross-cutting properties, no single
derivation), secrets-shape (two parse candidates — a possible dupe surface flagged to the dupes
session), consumer-scoping (their Tier-3 turf), install-section/population/collector-timeout
(spread; need the deeper read). Unblocked by the ledger row 2
ruling; the stripped `:implements:` mapping (commit `5068ce89`'s diff) was the shortlist, and
the block authors' "canonical review anchor" placements held up under verification — 21 claims
minted across `ast_nodes.py` (4 AST comparison nodes + `required_params`) and `executor.py`
(13 scopes, several carrying two claims: multihop+envelope, filters+combinators, count+rows,
string-match+regex). Judgment calls: `order-by-envelope` anchored on the type-scan-envelope
applier (its body describes exactly that lane), `exec-sql-capture` is a `surface` role (the
body calls it a developer seam), and **`req-grid-gryphon-limit` skipped** — the shortlist
grouped it with order-by resolution, but `_resolve_order_cols` doesn't derive LIMIT and
claiming it there would be a stretch. 70 claims live.

**Batch 3 (2026-08-20): status normalization, 495 → 467.** Two discoveries: `Refactoring` and
`Deprecating` were canonical template vocabulary all along — the bucket model, not the specs,
was behind (`Refactoring` now derives unbuilt: "being re-worked" is in-flight by its own words);
and two "missing" statuses were parse casualties — `Status: `Proposed (Deferred)`` defeats the
status regex, so decorated statuses read as None. All 18 off-vocabulary rows normalized to
canon (`Partially Implemented`→`In Development` mostly, `Open`/`Deferred`→`Backlog`,
forward-note rows→`Proposed`), the two parenthetical statuses stripped to `Proposed`, and
`req-cicd-product-releases` marked **Disputed** with the full pairing (ledger row 5 + the
Requirement Review Needed section in spec-cicd-hardening) — the stale-prose lead from batch 1,
now a recorded dispute instead of a silent contradiction.

Spec-by-spec lanes, priority order: security-posture / FIPS / service-boundary → `tap_auth` /
`tap_boot` → remaining apps → the tail. For each requirement: claim it, test-cite it, or mark
its `Trace:` disposition. Candidate generation via commit co-occurrence (the RID's authoring
commit shortlists the implementing files — 75% land same-day, measured in
[doc-dev-requirement-traceability.md](doc-dev-requirement-traceability.md) §5b). Sweep findings
are leads, not verdicts — every claim minted is human-verified requirement-body-against-code,
the citation-batch discipline.

Estimate, honestly: ~1,130 core requirements; classification is lighter than deep verification,
so 100–200 per session → **6–12 sessions** for core. Citation batches 1–2 already cleared much
of `tap_grid` and `tap/`.

Gated items: claims on gryphon executor functions wait on ledger row 2 (sphinx
capability-blocks); the core↔plugin RID boundary waits on row 4 (gridkin modeling).

### Wave D — the test direction (folded into C)

Wire `@pytest.mark.spec` ACID citations where tests already exist, in the same batches — you are
already reading each requirement. `Verified` accrues where both classes land; it is the stretch
tier, not the DoD bar.

### Wave E — plugins corpus (last)

Evicted plugins carry their own specs in their own repos. The machinery ships in the core wheel
(`tap.spec_trace` already does); plugin CI gains the guards; each plugin repo drains its own
Unaccounted count against its own specs (the two-mains model). Sequenced last because the
per-repo mechanics are identical once core proves the model.

### Follow-on, on demand only

- Extending the claim grammar to `#`-comment surfaces (shell/YAML/Dockerfile) — measured first:
  the `non-python` payload inventory from Wave C is the demand signal.
- The ACID-diff prompt ("this edits acceptance criteria without a revision bump — intentional?")
  from the design doc's candidate list.

## Standing constraints

- Every claim/marker minted, never hand-typed; near-misses fail closed; one source per fact.
- An exclusion is an assertion something can check: mandatory payloads where the category names
  a thing (LOBSTER's rule).
- The branch ships via the normal promote gate; specs-tier changes ride the test_all lane.
