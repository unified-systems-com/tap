---
name: triage-requirements
description: Drain the Unaccounted requirement set toward the traceability Definition of Done — map each requirement to code (TAP-IMPLEMENTS claim / test-cited ACID) or document its exclusion (Trace: disposition), one spec-batch at a time. Use for any "triage requirements", "drain Unaccounted", "wave C batch", or "map spec X to code" request.
allowed-tools: Read Write Edit Bash(scripts/implements-tag *) Bash(scripts/dc *) Bash(git log *) Bash(git show *) Bash(grep *) Bash(python3 *) Glob Grep
argument-hint: <spec-path or batch-theme>
---

# Triage Requirements — Drain the Unaccounted Set

You are closing the gap toward the traceability Definition of Done: **every requirement mapped or
documented-excluded** (`specs/spec-tap-requirement-traceability.md` §Definition of Done). The
Unaccounted count in the spec's generated Accounting Report is the progress bar; your batch makes
it smaller and proves it with the regenerated report.

## Authoritative sources (read first; do not guess from memory)

- **`specs/spec-tap-requirement-traceability.md`** — the claim grammar, the `Trace:` disposition
  vocabulary, the bucket model, the ratchet. Canonical; this skill is operational summary.
- **`docs/misc/doc-tap-traceability-closure-plan.md`** — the wave plan and decision log.
- The per-spec **fragments** (`specs/traceability/<spec>.md`, the committed form) and the
  on-demand corpus table (`scripts/dc exec -T web uv run python manage.py guards --accounting`)
  — pick batches from the per-spec Unaccounted counts.

## The decision tree, per requirement

Work spec-by-spec. For each Unaccounted requirement, in this order:

1. **Fix the status first.** The bucket derivation reads `Status:`; a missing or drifted status
   line blocks everything else. The prose usually states it plainly ("Implemented 2026-08-09…",
   "the entire deploy half is unbuilt" → `Backlog`). Unbuilt statuses (`Proposed`, `Backlog`,
   `In Development`, `Approved for Development`, `Refactoring`) and retired ones (`Deprecated`,
   `Deprecating`, `Retired`) drain the requirement **by status alone** — no marker needed, done.
   Normalization rules, earned in the batch-3 pass:
   - **Check the template before inventing** — `Refactoring` and `Deprecating` looked like
     drift and were canonical all along (`specs/spec-req-template.md` §Status Vocabulary is
     the authority); the fix belonged in the bucket model, not the specs.
   - **Decorated statuses parse as None** — `Status: `Proposed (Deferred)`` defeats the
     status regex. Strip to the canonical value; the deferral note lives in the prose.
   - Off-vocabulary values are illegal *everywhere* they appear, so per-file global replaces
     are safe: `Partially Implemented` → usually `In Development` (read first — a
     "forward note, not a build" row is `Proposed`); `Open`/`Deferred` → `Backlog`.
   - **A body contradicting the tree is a dispute, not a status call** — mark `Disputed` only
     with the full pairing (ledger row + Requirement Review Needed section in the owning
     spec), never as a drive-by.
2. **Is there an obvious enforcement claim?** Check the guard registry: a `Guard` subclass whose
   `rid` names this requirement is a pre-verified claim candidate — the guard→requirement edge
   was already authored and machine-checked. Mint `(enforcement)` on the guard module.
   `grep -rniE '^\s*rid = "req-' tap/guards/ */guards/` is the shortlist. Four refinements the
   shortlist needs (each earned in batch 2):
   - **Declared-surface registries are pointers, never targets.** `tap/guards/surfaces.py` rows
     declare that a surface exists elsewhere (a workflow, a script) — claiming the registry
     would map the requirement to a table of contents.
   - **A rid naming an ACID enforces one criterion, not the requirement.** A guard on
     `req-x-15` does not own `req-x`; claiming the parent is over-claim. Leave it.
   - **A hedging header is a partial slice.** A guard whose docstring says "`req-a` +
     `spec-b.md`" enforces a piece of each — skip rather than stretch.
   - **Two guards, one rid: claim THE primary.** The uniqueness guard would trip anyway; the
     sub-guard defending the primary's ledger is support, not a second owner.
   The inverse also pays: a module whose header says "Spec: … (`req-a`, `req-b`, `req-c`)" and
   calls itself "the single artifact" supports one claim per named requirement, each with its
   own role — the gate command carried three.
3. **Does the spec name its implementation?** Grep the requirement body for `scripts/`, `.yml`,
   `.py`, module paths. Spec build-notes ("lives in `tap/foo.py`", "`scripts/spawn-session.sh`
   provisions…") make the mapping obvious: a Python target gets a claim; a shell/YAML/compose
   target gets `Trace: non-python — <path>`.
4. **Walk the test suite backwards (the cheapest probe — try before git archeology).** Most
   Implemented-status requirements already have *unmarked* tests exercising them. Grep the
   suite for the requirement's feature vocabulary (its clause names, error strings, function
   names quoted in the body); a hit pays twice in one visit:
   - add `@pytest.mark.spec("<acid>")` to the test — the requirement drains IMMEDIATELY via
     test evidence, no claim needed;
   - the test's imports name the implementing functions — the claim shortlist, if one is
     warranted (claims stay scarce; the marker alone maps it).
   Where markers already exist, they are authored, verified edges (the guard-rid logic):
   `collect_spec_markers` inventories all of them, a marker-bearing test file is the anchor
   map for its spec, and the 18 currently test-only requirements are the `Verified` shortlist
   — their test bodies point at the claim candidates. (Measured 2026-08-21: existing markers
   cluster in already-drained specs — only ~6 Unaccounted live near one — so the *unmarked*
   walk is the burn-down play; the marked walk is the Verified play.)
5. **Commit co-occurrence for the hard cases.** The RID's authoring commit shortlists its
   implementation (75% land same-day — measured, `doc-dev-requirement-traceability.md` §5b):

       git log --reverse --format='%H %ad' --date=short -S'RID: `<rid>`' -- '*.md' | head -1
       git show --name-only --format= <commit> | grep '\.py$'

   Candidates, not answers: read the function against the requirement body before minting.
6. **Exclusion, with the category honest:**
   - `process` — humans/workflow conform, code never will (branch discipline, review rules).
   - `narrative` — umbrella statement; the substance lives in its ACIDs/children.
   - `non-python — <path>` — implemented in a surface claims can't reach. Payload is **exactly
     one existing repo-relative path** (validator checks existence; one file only — pick the
     primary).
   - `external — <name>` — outside the repo (GitHub settings, an evicted plugin, org config).
6b. **Zero-ACID spec touched? Backfill the table while you're there.** A built requirement
   with no ACIDs cannot take a marker and can never earn `Verified`
   (`req-tap-traceability-acid-floor`; the zero-ACID ratchet tracks the debt). Its existing
   tests name the testable criteria — author the ACID rows from them (test → criterion →
   ACID), then mark. Adding the table churns the requirement's content hash: end the batch
   with a claim resync pass.
7. **Skip, deliberately.** Not obvious = not this batch. Two named skip classes:
   - **Mixed-surface** (implementation spread over several files/systems, no primary): leave
     Unaccounted rather than stretch a category.
   - **Stale prose** (body contradicts observable reality, e.g. "no releases exist" when tags
     ship): that is a **Disputed lead**, not a triage call — record it for the review ledger.

## Batch mechanics

1. Pick the spec(s) from the per-spec Unaccounted counts (`guards --accounting` or the burndown dashboard), largest honest wins first.
2. Print the batch inventory before editing:

       scripts/dc exec -T web uv run python -c "
       import sys; sys.path.insert(0, '.')
       from pathlib import Path
       from tap.spec_trace import load_corpus, unaccounted_rids
       root = Path.cwd(); corpus = load_corpus(root); un = unaccounted_rids(root)
       spec = '<spec-path>'
       for rid, req in corpus.requirements.items():
           if req.spec_path.relative_to(root).as_posix() == spec and rid in un:
               print(rid, [req.status], ' '.join(req.body.split())[:100])"

3. Apply `Status:`/`Trace:` lines (both are hash-neutral — they never churn claims). Claims are
   minted, never typed: `scripts/implements-tag <rid> <role>`, paste the placeholder line into
   the docstring, `scripts/implements-tag --resync <file>` stamps the code hash.
4. Close the loop, in this order:

       scripts/implements-tag --check                     # zero problems
       # regenerate the ratchet baseline — SHRINK-ONLY BY CONSTRUCTION: intersect the
       # measurement with the committed baseline, so an entry can leave but a NEW one
       # cannot silently enter. A new unaccounted RID must FAIL the ratchet and force a
       # real disposition — a full rewrite here is how the acid-floor requirement once
       # grandfathered itself on arrival (caught by AI review on PR #105).
       scripts/dc exec -T web uv run python -c "
       import sys; sys.path.insert(0, '.')
       from pathlib import Path
       from tap.spec_trace import unaccounted_rids
       p = Path('tap/guards/baselines/unaccounted_rids.txt')
       old = {l for l in p.read_text().splitlines() if l and not l.startswith('#')}
       header = [l for l in p.read_text().splitlines() if l.startswith('#')]
       keep = sorted(unaccounted_rids(Path.cwd()) & old)
       p.write_text('\n'.join(header + keep) + '\n')"
       # one artifact since the fragmentation: per-spec files in specs/traceability/
       # (either flag or both; only YOUR batch's specs' fragments change)
       scripts/dc exec -T web uv run python manage.py guards --sync-accounting --sync-evidence
       scripts/dc exec -T web uv run pytest tap/tests/test_requirement_dispositions.py \
           tap/tests/test_requirement_evidence.py tap/tests/test_implements_claims.py \
           tap/tests/test_guards.py -q

5. Commit the spec edits + code claims + baselines + the CHANGED FRAGMENTS ONLY
   (never `git add` the whole fragments dir blindly) with the drain in the message ("Unaccounted N → M"). Record Disputed leads and
   mixed-surface skips in the commit body so the next batch inherits them.

## Traps (each earned)

- **Editing ACID-table cells (including their Status column) churns the parent requirement's
  content hash** — only the `Status:`/`Trace:` LINES are hash-excluded. Expect the staleness
  guard to fire after status flips inside ACID tables; re-verify, then `--resync`.
- **A spec-side edit to a claimed requirement orphans its claims by design.** `--resync` after
  review is one command; never re-stamp without the re-read.
- **The `non-python` payload is one path, verified to exist.** No parentheticals, no lists —
  the validator rejects what it cannot point at.
- **Never add to the ratchet baseline.** It shrinks or it stays; a new entry means a requirement
  claimed `Implemented` without earning it — fix the requirement, not the baseline.
- **Markers on doctrine or disputed requirements fail** — those buckets derive from status.
  Unbuilt requirements MAY carry a marker (a process requirement carries its exclusion from
  birth, so its later status flip needs no triage).
- **Agent sweep findings are leads, not verdicts** — every claim is human-verified
  requirement-body-against-code before minting; every exclusion category is checked against
  what the code/tree actually shows.
