---
name: update-architecture
description: Refresh architecture.md against what TAP has actually become — verify its current claims, find what moved across the specs and the plumbing since it was last revised, and revise it with the maintainer, one checkpoint at a time. Use when a new Django app or root spec lands, when a ruling changes a core concept, after a breaking plumbing change, when the architecture-doc guard fails, or for the twice-yearly sweep. NOT for editing a spec (specs are canon; this doc points at them) and NOT for AGENTS.md or CLAUDE.md, which are instruction surfaces with their own review rules.
allowed-tools: Read Write Edit Bash(git log *) Bash(git show *) Bash(git diff *) Bash(git rev-parse *) Bash(scripts/dc *) Bash(scripts/change-tier *) Bash(scripts/check-issue-link *) Bash(scripts/check-dco *) Bash(scripts/pr-via *) Bash(scripts/pr-review-triage *) Bash(gh *) Bash(grep *) Bash(ls *) Bash(find *) Bash(python3 *) Glob Grep
argument-hint: [--check]   # --check runs the evidence sweep and stops, changing nothing
---

# Update architecture.md

`architecture.md` is TAP's **orientation surface**: `AGENTS.md` sends every session there before
designing anything, and a cold reader — human or AI — reads it to learn the shape of the system and
where canon lives. This skill revises it against reality.

**What this document is, and is not.** It is a *codemap* plus the invariants that hold across TAP
(matklad's ARCHITECTURE.md form: coarse modules, what each owns, what the system deliberately does
NOT do) and a dated **rulings log** in the spirit of arc42 §9. It is **not** a spec index, not a
tutorial, and not an instruction surface — operational rules for agents live in `AGENTS.md` and
`CLAUDE.md`, and behavior lives in the specs. When this skill's evidence argues for adding process
guidance here, the answer is a pointer, not a copy: a second copy of a rule is the drift generator.

**The failure mode this skill exists to prevent is not omission, it is confident falsity.** The
2026-09 refresh shipped the sentence "the original brief is kept verbatim in the appendix" about an
appendix that had been condensed — a claim that reads as verification, caught by a reviewer rather
than the author. So: every claim in a checkpoint carries the command that produced it. An impression
is not a finding. Where a claim cannot be settled from this tree, it is **NOT OBSERVABLE** — three
states, never two, and never absence rendered as "fine".

## Ground rules

- **Evidence before prose.** No edit to `architecture.md` happens before its checkpoint is answered.
- **Cite RIDs and paths; never line numbers.** RIDs are stable and searchable; line numbers rot on
  the next edit, and the guard rejects them (`req-docs-architecture-fitness-3`).
- **A no-op is a real outcome.** If nothing material moved, say so and stop. A refresh that always
  finds something to rewrite is manufacturing work.
- **Never restate a spec.** Point at it. If the doc and a spec disagree, the spec wins and the doc
  is the bug.
- **The guard is not the truth.** `ArchitectureDocGuard` proves citations resolve, never that a
  sentence is true. Truth is what the checkpoints are for.

## Step 0 — anchor, and decide whether to proceed

```bash
ANCHOR=$(git log -1 --format=%H -- architecture.md)          # last content commit of the doc
git log --oneline "$ANCHOR..HEAD" | wc -l                     # commits since
git log -1 --format='%h %ad' --date=short "$ANCHOR"
```

Everything below is measured from `$ANCHOR`. If the sweep in Steps 1-4 turns up nothing material,
report that and stop — that is a successful run.

## Steps 1-4 — the evidence sweep (one batched checkpoint at the end)

Run all four, then check in once. They produce one picture; splitting them fragments it.

### Step 1 — do the doc's current claims still hold?

Start with the mechanical half, which is already a guard:

```bash
scripts/dc exec -T web uv run pytest tap/tests/test_guards.py -k architecture-doc-fitness
```

That covers subsystem coverage, path citations, RID citations and line-number citations. Then the
half no guard can do — the load-bearing *assertions*. Take each claim in the document and name the
command that settles it. The four classes that rotted last time, as the seed list:

| Claim class | How to settle it |
| --- | --- |
| Auth model | `grep -A6 AUTHENTICATION_BACKENDS tap/settings.py` |
| Plugin mechanism | plugin manifests + `pyproject` entry points; `tap_plugins/specs/` |
| Packaging / runtime shape | `grep image: docker-compose.yml`, the Dockerfile |
| Network posture | what collectors reach (`tap_cares/specs/spec-tap-cares-collector.md`) |

Each claim ends as **true**, **false (with the correction)**, or **NOT OBSERVABLE (with why)**.

### Step 2 — what moved in the specs

```bash
git log "$ANCHOR..HEAD" --name-only --pretty=format: -- '*/specs/*' 'specs/*' \
  | grep -v '^$' | cut -d/ -f1 | sort | uniq -c | sort -rn      # churn ranked by app
git log "$ANCHOR..HEAD" --diff-filter=A --name-only --pretty=format: -- 'specs/spec-*.md' | sort -u
```

Then the **spec drift tables** — the generated per-spec traceability fragments, which carry each
RID's Declared/Derived status and bucket counts:

```bash
for f in specs/traceability/*.md; do
  git diff "$ANCHOR..HEAD" --quiet -- "$f" || echo "MOVED: $f"
done
git diff "$ANCHOR..HEAD" -- specs/traceability/<system>.md   # status flips, bucket deltas
```

A subsystem whose fragment shows requirements flipping to `Implemented`, or whose bucket counts
moved, is a subsystem that actually changed — that is the signal, not an impression of activity.
**Re-verify every RID the doc already cites still exists**, and prefer citing RIDs over paths when
adding anything.

### Step 3 — breaking changes and plumbing

```bash
git log "$ANCHOR..HEAD" --grep='BREAKING CHANGE' --grep='!:' --oneline
git diff "$ANCHOR..HEAD" -- CHANGELOG.md | head -40            # version jumps
git diff "$ANCHOR..HEAD" -- tap/settings.py | grep -E '^[-+].*"tap' # INSTALLED_APPS movement
git log "$ANCHOR..HEAD" --diff-filter=A --name-only --pretty=format: -- '*/migrations/*.py' \
  | cut -d/ -f1 | sort | uniq -c | sort -rn
git diff "$ANCHOR..HEAD" --stat -- boot/ Dockerfile docker-compose.yml
git log "$ANCHOR..HEAD" --diff-filter=DR --name-only --pretty=format: -- 'specs/*' '*/specs/*'
```

Renamed or deleted specs matter twice: the plumbing changed *and* the doc may now cite a path that
no longer exists.

### Step 4 — initiatives actually in flight

Derived, never remembered:

```bash
sed -n '/^## Active/,/^## /p' plan/road-products.md          # the fence
gh project item-list 1 --owner unified-systems-com           # what is committed and moving
gh issue list --repo unified-systems-com/tap --label epic --state open
```

An initiative that neither the fence nor the board knows about does not go in the document.

### CHECKPOINT A (batched, blocking)

Report to the maintainer, in this shape:

- **What I found** — per step, the finding *and the command that produced it*. Claims settled
  true/false/NOT OBSERVABLE, with counts (e.g. "11 specs moved; 3 subsystems show status flips").
- **What I want to change in architecture.md** — at the level of the actual sentence, table row or
  new section. Name what gets deleted, not only what gets added.
- **Why** — the evidence above, and what a reader loses today by the document staying as it is.
- Then the standing response blocks: decisions (i, ii, iii), lessons (a, b, c), actions (1, 2, 3).

**Wait for the answer. Do not edit the document before it arrives.** Record the maintainer's
rulings in a ledger (`scratchpad/architecture-refresh-ledger.md`): one line per decision, the
ruling, and the date. The ledger is mirrored into the PR body so every change traces to a ruling,
and it makes an interrupted run resumable — a later session reads the ledger instead of re-sweeping.

## Step 5 — the rulings log (arc42 §9)

Add a dated entry per ruling that postdates the last revision: what was ruled, the spec that owns
it, and the RIDs. Never restate the spec's content — the entry exists so a reader is not surprised,
and knows where to go.

**CHECKPOINT B (blocking):** the proposed entries, verbatim as they would land, with each spec link
and RID verified to resolve. Same shape: found / want to change / why / blocks.

## Step 6 — subsystems, concepts and corrections

Apply the Step 1-3 findings: new or changed subsystem rows (what each one OWNS — never a build
order, which is what left four apps with nowhere to land), corrected claims, concept changes.

**CHECKPOINT C (blocking):** the diff, sentence by sentence for anything load-bearing.

## Step 7 — spec-driven development and initiatives

Keep it short. Spec-driven development earns a section because it *is* architectural — specs are
canon, requirements carry RIDs and a status, traceability binds requirement to code — and it must
point at `specs/spec-docs.md` and `specs/spec-tap-requirement-traceability.md` rather than restate
them. Initiatives come from Step 4 and are written so they age honestly (dated, with the epic).

**CHECKPOINT D (blocking):** the two sections as they would land.

## Step 8 — land it

1. **Work in your own worktree.** Never in another session's (`hub-session-stack-hygiene`).
2. **Drift check** the docs that point here — `grep -rln 'architecture\.md' docs/ specs/ plan/` —
   and fix any that this revision invalidates, in the same PR (`req-docs-drift-conventions`).
3. **Run the guard** plus the docs lane; `scripts/change-tier` tells you the battery.
4. **The PR body points at the doc; it does not restate it.** The 2026-09 PR body kept a "verbatim"
   claim the doc had already corrected — a second copy that drifted within one PR.
5. **Trailer**: `Part-of:`/`Closes:` the issue, or `No-issue: <reason>` with a real reason.
6. **Open, then triage every push** (`hub-pr-triage-discipline`): `scripts/pr-review-triage <pr>
   --wait`, and **verify the verdict covers your head sha** — the reviewer edits its comment in
   place and its run's `head_sha` is the base, not the PR head (`tap#721`). Read every seat; a
   missing seat is SEAT ABSENT, not a pass.

**CHECKPOINT E (final):** the PR link, what each seat said, and what remains for the maintainer.

## Related skills

| When you are… | Use |
| --- | --- |
| Draining unaccounted requirements | `triage-requirements` |
| Resolving a traceability/fragment conflict | `resolve-traceability-conflict` |
| Adding a model, edge, page, panel, collector | `add-model`, `add-edge`, `add-page`, `add-panel`, `build-collector` |
| Entering an unmodelled domain | `build-domain-vocabulary` |
| Scaffolding a plugin | `new-plugin`, `create-plugin-spec` |
