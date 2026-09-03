---
title: Lessons learned — the status-wall day (2026-09-02)
date: 2026-09-03
status: record
audience:
  - developer
  - llm
related:
  - git-serious-tap#6
  - tap#305
  - tap#322
  - tap#323
  - docs/misc/doc-grid-reobservation-prior-art.md
  - docs/misc/doc-grid-provenance-placement-prior-art.md
---

> One session, one day, five concurrent sessions in the same worktree, three repositories, eleven
> PRs, two design rulings. Written the morning after from the session transcript. Each lesson is
> stated as a rule that would have intercepted the mistake at the moment it was typed (the
> build-domain-vocabulary test for a rule worth keeping); a lesson that fails that test is listed
> as an observation instead. Memory files are not durable enough for this — that is why it is here.

# What the day was

Build the first table-stakes table (the status wall) beneath git-serious's machinery graph, tweak
it live with George until it read well, add a workflow page, lay down the `build-github-corpus`
skill, bake five vocabulary concepts and two collector fixes through agents, and — the part that
turned into architecture — discover why an auto-refreshing table over a scheduled collector is
not a feed until re-observation stops being recorded as change (tap#322, tap#323).

# Rules

## 1. A selector that matches nothing is not a passing test

The first graph-panel fix (8324f466) turned a `NameError` into an `UnboundLocalError`. My check
was a Playwright selector for error markup that matched zero elements, and I reported the landing
fixed. A peer session read the server log and told me the panels were still down. The second fix
was verified by fetching the panel fragment and counting 170 nodes in its seed payload with zero
`[b601]` log lines after the fetch.

**Rule:** verify a fix by observing the thing that must be *present* (nodes in the payload, a
green row in the table, a record in the database), never by the absence of the thing that must
be *absent*. Absence of error markup is a presence test wearing a correctness test's clothes —
the same failure class as `presence-is-not-correctness`, pointed at one's own verification.

## 2. Mint every id at the moment of use

I minted a pool of fourteen UUIDs at the start of the GRIFT work and drew from it across four
bundles over six hours. Twice the pool handed back an id that was already an edge or a batch
elsewhere (git-serious-tap#44's batch id was an edge's; the workflow page's v0.1.1 batch id was the
landing's v0.5.0 batch id). The importer refused both; a peer caught one before I did.

**Rule:** `scripts/uuid7` per id, in the command that writes it, never from a variable minted
earlier. And every bundle-writing script asserts the ids inside the bundle are unique before
writing — the importer's cross-bundle check is the second net, not the first.

## 3. zsh: `path` is PATH, arrays start at 1, and `cd` outlives the line

Three shell traps in one day, each costing a round trip: assigning `path=` inside a loop clobbered
`$PATH` mid-loop (`curl`, `wc`, `cat` all vanished); `${U[0]}` on a zsh array is empty, so a batch
id was written as `""`; and `cd "$worktree"` in a compound command made the `scripts/dc` calls after
it fail because the cwd persists.

**Rule:** in this shell, never name a variable `path`; index arrays from 1 or avoid arrays; and
invoke `scripts/dc` from an absolute path or a fresh `cd /Users/.../viz-git-serious ||
exit 1` at the head of every command that needs it.

## 4. The baseline's third field is a count, not a line

The promote's mypy ratchet reported the search-model test's `no-untyped-call` moving "from 29 to
32". I regenerated the baseline and wrote "moved from line 29 to 32" in the commit message. A
review seat pointed out that lines 1–136 of that file had not changed. The field is a count: the
peer's new tests added three untyped calls.

**Rule:** before explaining a ratchet delta, read the baseline's format line and reproduce the
number with the canonical command (`mypy . | grep <file>`). A confident explanation of a number
you have not reproduced reads exactly like a checked one — and outlives the session.

## 5. Envelope mode for tables, projection mode for badges

A Gryphon search that `RETURN`s aliases yields `rows` and zero `nodes`; the v1 table panel reads
only `nodes`. Bound to a table it renders nothing, silently. Envelope mode (`RETURN r`) hydrates
nodes. ORDER BY on a field path works only in envelope mode and never on a traversal pattern.

**Rule:** a table's search returns the variable; a badge's search returns a projection; check
`nodes` is non-empty in the envelope before binding either. Filed as tap#297 (rows mode) and
tap#298 (ordering on traversals) so the rule can eventually be deleted.

## 6. Ten per repository is not a window

The collector's first-boot fetch is `initial_run_limit` runs *per repository*, so a repository
with seventeen workflows and ten runs shows seven workflows as "no run observed" when the truth
is "outside the window". The not-observed table shipped with that limit stated in its panel text
so the grey state could not overclaim (github-core#34 widens it).

**Rule:** when a view renders a third state ("not observed"), the panel text names the window
that produced it. A grey cell that reads as "never" when it means "not in the last ten" is the
`bypass_actors` failure again.

## 7. Split what sorts

"Elapsed 3m 30s ▲3.0×" in one cell was one glance and zero sorts. George's ask to split elapsed,
ratio and sample size into three sortable columns, with the ratio's baseline population disclosed
in `n`, was right on first use: sorting by `vs usual` is the outlier view, sorting by `n` is the
thin-history view.

**Rule:** a derived number that a reader would sort by is its own column; a decoration
(the ▲) never carries the only copy of a number.

## 8. A moving number in a table is a distraction, not an affordance

The first auto-refresh pill counted down every second. George: "a moving number is too
distracting." Prior art (Grafana, Kibana) is a ↻ button beside a static interval selector.

**Rule:** the affordance for a periodic action is a control (button + interval), never a timer
the reader can watch. Load the prior art before inventing chrome.

## 9. A live table over a static grid is theatre

The wall refreshed every sixty seconds against a grid nothing wrote to. The scheduler (tap_cares
Schedule, minute tick, fire records, admin pages) already existed in core; this instance had no
schedule declared. One bundle later the collector fires every ten minutes; the first unattended
fire ran a 3m25s job and the run count moved 599 → 826.

**Rule:** before adding "live" to a view, name the process that moves the data and observe it
moving once. `manage.py shell` → `Schedule.objects.count()` is a thirty-second check.

## 10. Re-observation is not change — and the specs already said so

After the first scheduled pass every unchanged workflow had gained a history version. The diff
between versions was `batch_id` and `flip_map` only. `spec-grid-flip.md:57` says a FLIP value is
"the batch that last **set**" the value; `spec-grid-history.md:28` says history exists "because
TAP stored a change, not because an external source observed something". The importer disagreed
with both, and nobody had run a second pass to notice. Fourteen systems surveyed; none keeps a
versioned row per re-observation. Rulings: diff-before-write; the batch stores only the unchanged
set; the row-level batch pointer moves to the spine; `flip_map` stays typed (tap#322, tap#323).

**Rule:** the second collector pass is part of the collector's done-test. A collector verified
on one pass has been verified for creation, not for observation.

## 11. Route a review finding to the code's owner, and say where you put it

Copilot, Codex and Grok all flagged the peer session's ranked-layout code on the promote PR that
carried both our commits. Editing under an active session is the 2026-08-27 failure. Each finding
went to the peer's issue (tap#293) with verified anchors; the peer fixed them on the same branch
before approval.

**Rule:** on a shared branch, a review finding on code you did not write becomes a comment on
its issue with `file:line`, never an edit — and the PR comment says so, so the reviewer sees it
was routed, not ignored.

## 12. Name the repo with every number

Four repositories in play; `#44` meant a skill PR on github-core, a wall PR on git-serious-tap and
nothing on tap. CLAUDE.md gained the rule mid-day; every comment after it carries `repo#n` and a
full URL in messages to the human.

## 13. Sequence peers by structure, not by preference

Two sessions had rewritten the same landing bundle with colliding batch names. The reconciliation
was decided by which change was the landing's future (the machinery view) and which was a delta
on it (the wall); the delta re-applied on top as a PR against the peer's branch, ids stable,
batch id moved. Twice more that day the same arrangement absorbed further tweaks in minutes.

**Rule:** when two branches touch one declarative bundle, the branch that changes the bundle's
*shape* lands first; deltas ride it as PRs against that branch, entity ids untouched.

# Observations (true, but not rules that intercept a keystroke)

- A skill built the morning after a research pass costs an hour; the same skill six months later
  costs a re-survey. `build-github-corpus` shipped with its coverage script the same day.
- The bake agent's first concept taught the ranking three things the survey could not (stacked
  PRs, an edge target that does not exist, a parser label that was a false declaration); the
  skill's tips section is where that went.
- Agents report on a watcher's schedule, not on completion; asking for the report explicitly,
  with "do not wait", produced it in one turn each time.
- The interactive peer's message stayed held for approval all day; coordination ran through the
  two background sessions instead. Cross-session messages need a fallback path that is not a
  human approval.

# Numbers, for the record

| | |
| --- | --- |
| PRs opened | 11 across tap, git-serious-tap, github-core |
| Issues filed | 14, with anchors |
| Core commits on tap#305 | 12, lane green at every push |
| Collection batches on the instance by end of day | 80+ |
| Duplicate natural keys after those batches | 0 |
| History versions per unchanged node per pass | 1 (the defect) |
