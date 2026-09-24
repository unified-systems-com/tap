---
name: gryphon-defect-response
description: What to do the moment you hit a Gryphon defect — a wrong result, a silently dropped clause, a crash — anywhere: a plugin build, a vendor page, a demo. The standing procedure is FIX IT ON THE FLY, not log it and route around it. A DEFECT you fix on the fly without asking, via gryphon-fix-bug. A MISSING CAPABILITY you do NOT build unilaterally — you stop and tell the user, because it changes what the language is. Use BEFORE gryphon-fix-bug or build-gryphon-capability; this is the first response and it decides which road you are on.
allowed-tools: Read Grep Glob Bash(scripts/dc *) Bash(scripts/*) Bash(grep *) Bash(git *) Bash(gh *)
argument-hint: <a one-line description of what Gryphon did wrong>
---

# You hit a Gryphon defect

**Ruled 2026-09-23 by George: we fix Gryphon on the fly.** The work stops being "ship the
feature despite Gryphon" and becomes "fix Gryphon, then ship the feature".

**Logging it is not the response. It is one step of the response.** A workaround nobody revisits
is how a query language acquires folklore — and by 2026-09-23 there were already three different
workarounds for one missing predicate, in four plugins, one of which silently over-matches.

Gryphon is the canonical graph read path (`AGENTS.md`). A wrong result from it is not a rough
edge to be routed around; it is the read path lying, and every caller inherits the lie.

## Best practices for TAP

The shared list is [AGENTS.md § Best practices for TAP](../../../AGENTS.md#best-practices-for-tap). For this skill, lead with:

- **Read the graph through Gryphon** (11): when it cannot answer, fix Gryphon so the next query can.
- **Name the evidence behind every claim** (12): read, grepped, ran or inferred, with the file:line, output or commit.


## The governing doctrine

**Apply-or-reject, never accept-and-drop.** A query that parses must either change what executes,
or be refused with a named remedy. Accepted-and-ignored is the one forbidden outcome, and it is
the shape most Gryphon correctness bugs take. `docs/doc-gryphon-commandments.md` is the law.

## The procedure

### 1. Notify the user explicitly

Do not bury it in a status line. It changes what the session is doing.

### 2. Capture the defect while you still have it

This is the step whose cost is invisible and whose omission is expensive. Capture:

- **The verbatim failing query.** Not a paraphrase. If you narrowed it to a minimal reproducer,
  keep the original too.
- **The fixture it ran against** — which plugins, which profile, the shape of the data. Gryphon
  bugs often only reproduce on a particular edge or node shape.
- **Expected versus actual, with COUNTS.** "It was wrong" is not a capture. `expected 1 row
  (local); got 4: local, local, foreign, foreign` is — the counts are frequently what identifies
  the mechanism.
- **Whether it raised or answered.** A wrong answer with no error is the worse bug and the easier
  one to lose.
- **What did NOT reproduce it.** Negative results stop the next person re-walking your dead ends,
  and they are never written down unless you do it now.

### 3. Log it in the wishlist

`docs/misc/doc-dev-gryphon-wishlist.md`, under **Known Issues**. Resolved entries stay as a
record. This is the durable artifact when the fix lands later or elsewhere.

### 4. Spawn a Gryphon playground session and fix it NOW

The playground is a boot profile away. `core_ci`, `soak` and `test_all` install
`gryphon_playground`; `soak` is reserved for the fuzz campaign, so a dedicated session is:

    scripts/spawn-session.sh <name> cli core_ci

Then route — and the two roads are NOT symmetric:

| What you hit | What you may do |
| --- | --- |
| A DEFECT — a wrong answer, a dropped clause, a crash | **Fix it. No permission needed.** Spawn an agent and track it to ground via [`gryphon-fix-bug`](../gryphon-fix-bug/SKILL.md). |
| A MISSING CAPABILITY — the construct does not exist and callers are inventing workarounds | **STOP. Tell the user. Do not build it.** |

**This asymmetry is a ruling, not a preference (George, 2026-09-23).**

A defect is a **closed problem**. The correct behaviour is already defined — by the spec, by the
other spellings of the same query, by what the engine does everywhere else. You are restoring a
known answer, and you are free to begin diving into what the fix takes the moment you find one.
Nobody needs to decide anything for you.

A capability is an **open problem**. It changes what the language IS. There is no pre-existing
right answer to restore, only a design someone has to choose and live with — and once a construct
ships, every query written against it is a commitment. That decision is the user's, and
[`build-gryphon-capability`](../build-gryphon-capability/SKILL.md) exists to run it with an
independent design review and an explicit sign-off BEFORE any code. **Do not open that skill and
start building because the gap is obvious and the fix looks small.** Obvious-and-small is exactly
how a language grows a construct nobody chose.

### When you are hard-blocked

The same split decides what to do when you cannot proceed:

- **Blocked because a feature is missing** — that is fine. **Stop and check with the user.** You
  have found a real gap and the decision about filling it is not yours. Say what you needed, what
  you tried, and what the workaround would cost; then wait.
- **Blocked because you hit a bug** — that is NOT fine, and stopping is not the answer. Spawn an
  agent and track it to ground. A defect standing between you and your work is a defect standing
  between everyone and theirs.

**If you want the Gridkin scenarios (step 5), spawn with the plugin as a dev checkout.** A plain
spawn installs `gryphon_playground` as a WHEEL, and you cannot author scenarios into a wheel.
Two agents discovered this the hard way on 2026-09-23 and neither could complete that deliverable.

**Parallel defects are parallel subagents — but give each its own worktree.** On 2026-09-23 two
agents were pointed at one worktree; their changes interleaved across four files and one ran
`git checkout` on a shared file for a non-vacuity check, nearly destroying the other's work. If
you must share a tree, commit between agents so nothing valuable is ever uncommitted.

### 5. Lock it with tests — and write the failing test FIRST

Gridkin scenarios in the `gryphon_playground` plugin, plus a case in
`tap_grid/tests/test_gryphon.py`.

**Reproduce the failure as a test and watch it fail before you fix anything.** A scenario that
has never failed is not evidence. After fixing, revert the fix and confirm the test goes red
again — if it stays green, the test is vacuous and you have locked nothing.

Never route around a failing case by reshaping callers.

### 6. Go back and remove the workarounds

**A fix that leaves the workarounds in place has not finished.** The callers keep paying for a
bug that no longer exists, and the next reader cannot tell a deliberate shape from a scar.

Find them by their own comments, specs and tests — a good workaround documents itself, and a
strict `xfail` is often planted deliberately as a tripwire that starts failing the moment the
underlying fix lands. Tell whoever is carrying them; they are frequently in another repo and
another session.

## Traps, all observed

**The oracle can model the bug.** `gridkin/model_oracle.py` is an independent implementation of
Gryphon's semantics, and on 2026-09-23 it reproduced the very defect under repair — its chain
walk overwrote a repeated variable instead of requiring unification, exactly as the engine did.
A judge that agrees with the bug certifies it.

**The generator bounds what the oracle is trusted on.** `gridkin/fuzz.py::_gen_chain` hard-codes
its variable names, so it can never emit a repeated variable — meaning the differential lane
could not have caught that bug, and the oracle's agreement proved nothing. **Every construct the
generator cannot emit is a construct the oracle is unverified on.** When you fix a defect, ask
whether the generator can produce it at all.

**Fix the oracle BEFORE the generator.** If the generator learns to emit a construct while the
oracle still models the old behaviour, the differential lane reports your correct fix as a
regression.

**A container restart re-installs the pinned wheel and silently undoes `uv pip install -e`.**
On 2026-09-23 an agent's plugin edits stopped taking effect mid-session because the `web` service
restarted and reinstalled `0.5.0` over its editable install — and ONE TEST RUN CAME BACK GREEN
AGAINST THE OLD WHEEL before it noticed. Use `-e PYTHONPATH=/app/_dev-plugins/<plugin>` instead;
it survives a restart. If a plugin change appears to have no effect, check what is actually
installed before you debug the change.

**A cross-worktree brief must name the worktree a file lives in.** The same day, an agent was told
to read a skill that existed only in a different worktree, uncommitted. It checked `git log --all`,
found nothing, said so plainly and fell back — but a less careful agent would have invented what
the skill probably said. Either commit and merge the file first, or say which tree it is in.

**A brief that says "follow this skill" must also say the skill's GATES BIND.** On 2026-09-23 an
agent was told to follow `build-gryphon-capability` and to fix the gap; that skill requires an
independent design review and George's explicit sign-off BEFORE any code, and the agent built
through both — reasonably, because the brief asked for a fix and never said the gates were
binding. It flagged the omission itself and called its own commit "a proposal, not gate-cleared
work". When you delegate, say which gates stop the work and that stopping at one is the correct
outcome, not a failure to deliver.

**One pytest at a time per container.** Two concurrent runs against the same test DB produce
mass ERRORs — `database "test_tap" is being accessed by other users`. That is a collision, not a
failure. Re-run serially before believing any red, and never force-drop the shared test DB.

**A spec row can be wrong and the code can be obeying it.** On 2026-09-23 a requirement said
"nested-key lookup" and the executor implemented precisely that; the row was the bug. When the
code matches the spec and the behaviour is still wrong, suspect the row.

**An inferred mechanism that fits the row counts can still be wrong.** The same 2026-09-23 defect
was reported as a cross product — the counts fit exactly — and was actually a missing join on an
unbound position. The fix lived somewhere the inference did not point. Trace it; do not fix the
hypothesis.

## Related

- `docs/doc-gryphon-commandments.md` — the law both repair and build cycles answer to.
- `docs/misc/doc-dev-gryphon-wishlist.md` — Known Issues, and the wishlist organised by
  demand-shape.
- `AGENTS.md` — Gryphon is the canonical read path; raw ORM querying is break-glass.
