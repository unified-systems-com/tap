---
name: resolve-traceability-conflict
description: Resolve a merge conflict involving the traceability surfaces — per-spec fragments (specs/traceability/, the current committed form; monolithic generated blocks only on pre-fragmentation branches), ratchet baselines, or two sessions editing the same spec's requirements. Use for any "conflict in spec-tap-requirement-traceability", "fragment conflict", "baseline conflict", or promote aborted on a traceability file.
allowed-tools: Read Write Edit Bash(git status *) Bash(git diff *) Bash(git log *) Bash(git checkout *) Bash(git add *) Bash(git commit *) Bash(git merge *) Bash(scripts/dc *) Bash(scripts/implements-tag *) Grep Glob
argument-hint: <conflicted-file or "promote aborted">
---

# Resolve a Traceability Conflict

The governing fact, learned across three conflicts in one day (2026-08-24): **git cannot
compute the true merge of a generated artifact — the generator can.** Every resolution
below is a variation of "make the merged TREE correct, then let the machinery re-derive
the artifact." Never hand-edit generated content into agreement; never resolve by
picking a side and stopping there.

Trust boundary: this skill runs generators and tests from the MERGED tree. For your own
session branches that is the normal local-gate trust model (the lane already executes
branch code). Resolving a branch containing ANOTHER author's unreviewed code, read the
COMPLETE diff (`git diff main...<branch>`) before invoking anything — generators and
tests transitively import broad swaths of the tree, so a partial path list cannot
establish trust; if the diff is too large to review, STOP and hand the resolution to a
human rather than executing the merge.

Authoritative context: `specs/spec-tap-requirement-traceability.md` (the machinery),
`tap/skills/triage-requirements/SKILL.md` (the close-the-loop sequence this skill reuses).

## First: classify the conflict

Run `git diff --name-only --diff-filter=U` and match each file:

| Conflicted file | Class | Section |
| --- | --- | --- |
| `specs/spec-tap-requirement-traceability.md` (generated blocks) | Generated render | §A |
| `specs/traceability/<spec-slug>.md` (post-fragmentation) | Generated fragment | §B |
| `tap/guards/baselines/unaccounted_rids.txt`, `zero_acid_rids.txt` | Shrink-only baseline | §C |
| Any spec's requirement sections (both sides edited the same spec) | Source overlap | §D |
| Renderer code (`tap/spec_trace.py` render functions) + every fragment at once | Format change | §E |

A promote may auto-resolve §A when that file is the SOLE conflict (the
`promote-to-main.sh` band-aid: checkout --theirs + both syncs + commit). If it aborted
instead, more than one class is present — resolve each per its section, worst first
(§D before the generated classes: source facts drive the renders).

## §A — Generated blocks (HISTORICAL — pre-fragmentation branches only)

Only reachable when merging a branch cut before the fragmentation landed (2026-08-24).
After both sides are post-fragmentation, this class cannot occur — the spec carries
static pointers, and §B is the live recipe.

1. FIRST check the conflict is confined to the generated block: `git diff` on the
   file — conflict hunks touching requirement sections mean BOTH generated and source
   edits collided, and a whole-file `--theirs` would silently discard your side's
   source facts (Copilot, PR #122). In that case resolve the SOURCE hunks by hand
   (§D), take either side of the generated hunks only, then continue.
2. Generated-only conflict: when ONE side is post-fragmentation (static pointers,
   no generated blocks), THAT side wins the spec file — the sync flags write only
   fragments now and will never strip a resurrected legacy block, and the
   no-committed-aggregates test reds until it is gone. Between two
   pre-fragmentation sides, either works. `git add` it and complete the merge
   commit.
3. Regenerate on the merged tree (flags compose since PR #119; separate invocations
   equally fine):

       scripts/dc exec -T web uv run python manage.py guards --sync-accounting --sync-evidence

4. Amend the merge commit with the regenerated file, or commit as an immediate
   follow-up. NEVER leave the regeneration for "the next push" — the drift test reds
   the gate and the red arrives at the worst time (the PR #105 lesson: the loop is not
   optional under urgency).

## §B — Generated fragments (post-fragmentation)

A fragment conflict means BOTH sessions triaged the SAME spec — a true overlap the
fragmentation design deliberately leaves visible.

1. Before resolving mechanically, check the overlap semantically: did both sides
   disposition the same requirement differently (one claimed it, one excluded it)?
   That is a judgment conflict — reconcile the SOURCE spec first (§D applies to the
   dispositions), because excluded+evidence is a guard-fatal contradiction.
2. Then the §A recipe scoped to the fragment: take either side, merge, re-sync; only
   the touched spec's fragment rewrites.

## §C — Shrink-only baselines

Both branches removed entries (drained requirements). The correct merged baseline is
the INTERSECTION of what each side kept — i.e. all removals apply.

1. Sorted line-sets usually auto-merge; a conflict means overlapping hunks, nothing
   deeper. Take either side, complete the merge.
2. Regenerate shrink-only-by-construction — measurement ∩ committed, so every
   removal from both sides lands and nothing new can slip IN through the merge:

       scripts/dc exec -T web uv run python -c "
       import sys; sys.path.insert(0, '.')
       from pathlib import Path
       from tap.spec_trace import unaccounted_rids, zero_acid_built
       for name, fn in [('unaccounted_rids', unaccounted_rids), ('zero_acid_rids', zero_acid_built)]:
           p = Path(f'tap/guards/baselines/{name}.txt')
           lines = p.read_text().splitlines()
           old = {l for l in lines if l and not l.startswith('#')}
           keep = sorted(fn(Path.cwd()) & old)
           p.write_text('\n'.join([l for l in lines if l.startswith('#')] + keep) + '\n')
           print(f'{name}: {len(old)} -> {len(keep)}')"

3. If the regenerated set is LARGER than either parent's: a merge resurrected a
   requirement neither side accounts for (e.g. a status flip from one side without the
   other side's evidence). That is not a baseline problem — find the requirement and
   give it an honest disposition. NEVER add the entry back to the baseline.

## §D — Source overlap (both sides edited the same requirements)

The only class needing human judgment. Resolve the semantics first, then pay the
hash consequences:

1. Merge the prose/ACID/status edits for what the requirement should SAY. Remember
   which lines are metadata: `Status:` and `Trace:` are hash-excluded (flips are
   free); body and ACID-table edits churn the content hash.
2. Body churn orphans claims BY DESIGN. `scripts/implements-tag --check` lists them;
   re-read each claimed function against the merged requirement text, then
   `scripts/implements-tag --resync <file>`. The re-stamp records that you checked —
   it does not check for you.
3. Contradiction sweep: a requirement that ended up with BOTH a `Trace:` line and
   evidence (claim or marked test) fails the disposition guard — decide which side
   was right and delete the other.

## §E — Renderer format change

One side changed the render code; every generated artifact conflicts at once. The
code side wins by definition: take the renderer's side of the CODE, take either side
of every generated artifact, merge, regenerate everything (§A step 3 + fragments),
run the format-owner's tests. This is why format changes are single-session events —
if you are the one landing a format change, land it ALONE, never inside a triage batch.

## Close the loop (every class, no exceptions)

    scripts/implements-tag --check                     # zero problems
    scripts/dc exec -T web uv run pytest \
        tap/tests/test_requirement_dispositions.py tap/tests/test_requirement_evidence.py \
        tap/tests/test_implements_claims.py tap/tests/test_guards.py -q

Green means the merged tree derives cleanly. Commit the regenerated artifacts WITH
(or immediately after) the merge commit — the drift tests treat "committed equals
derived" as the definition of resolved.

## Traps (each paid for)

- **The container is single-lane.** Never run a second pytest/xdist suite while a
  promote's local lane runs — two suites sharing test DBs produced 1,462 phantom
  errors and a red gate. A killed `docker exec` leaves the container-side pytest
  ALIVE: `scripts/dc exec -T web sh -c 'pkill -f pytest'` before retrying.
- **Read the failing check before theorizing.** Two of the three reds on PR #119 were
  four mypy generic annotations; the timeline-based theory ("mid-flight edit") was
  wrong and cost a full gate cycle. `gh run view <id> --log-failed` names the truth.
- **mypy ratchets new files too** — it runs canonically (`mypy .`), so a brand-new
  test file with bare `dict`/`CaptureFixture` generics reds the gate.
- **Never `git add -A`** in a shared worktree; stage the files this skill names.
- **Never TaskStop a backgrounded promote** — the pipeline survives the kill and can
  act on the tree later; check `pgrep -fl promote-to-main` before assuming it's gone.
- **A stray `__pycache__` after heavy file churn** produces xdist "import file
  mismatch" errors: `find /app -name __pycache__ -prune -exec rm -rf {} +` inside
  the container.
