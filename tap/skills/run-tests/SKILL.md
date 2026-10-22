---
name: run-tests
description: Decide which tests to run locally, how, and when to leave the rest to CI — a decision table by what changed, the CPU rules for a machine that several sessions share, and the known flakes that mimic code reds. Use before running any pytest, scripts/test, guard suite or coverage ratchet in tap or a plugin repo, and before opening a PR.
allowed-tools: Read Grep Glob
argument-hint: <what-you-changed>
---

# Run tests

Local tests are **fast feedback on what you touched**. The server's required `gate` check
(`core_ci` lane + cold-boot + lean-boot + api-fuzz) is the **authority** on whether a PR lands
(`req-dev-validation-suite-tiers-4`). A plugin's own suite belongs to that plugin's repo CI. Run
locally what answers your question in seconds or a few minutes; push and let the runners do the rest.

Why this exists (2026-10-21): five stacks share one 8-CPU, 7.7 GB Docker VM. One promote's local lane
ran every installed plugin's suite uncapped (`aws_core` alone took 25 minutes), outlived the merge it
was meant to precede, and held ~6 CPUs while a second pytest overlapped it. Load average hit ~14. The
rules were in memory notes and nowhere a session reads before running a suite (tap#1092).

## Words used below

- **stack**: this session's own containers (`web` + `db`), started with `scripts/dc up -d`.
- **`-n0`**: pytest-xdist with zero workers, i.e. serial. Right for a handful of files (no per-worker test-DB build).
- **`TAP_TEST_JOBS`**: caps the workers of `scripts/test` only; `TAP_TEST_JOBS=0` means no workers at all (`-n 0`, serial in one process), the right setting for a small plugin lane because each worker builds its own test DB. It is read host-side by that script and does nothing for a hand-run `scripts/dc exec ... pytest`, which takes `-n0` or `-n 3` directly.
- **the guard trio**: three fast guard checks, listed in section 1.

## What requests nothing

`Read`, `Grep`, `Glob` only, like its siblings. Everything that runs is the operator's, in the
container (`scripts/dc exec -T web uv run ...`), never host Python.

## 1. What changed → what to run

Times are what this repo's suites took on a loaded machine in the session that wrote this table
(measured, `-n0` unless noted; plugin suites were `-n auto` at load: playground 2.5 min unloaded and 12–16 min loaded, `aws_core` 25 min, `compliance_core` over 8 min). Re-measure before quoting them.

| You changed | Run locally | Leave to CI |
| --- | --- | --- |
| Docs, specs only | `scripts/implements-tag --check`; `manage.py guards --sync-accounting --sync-evidence` (no pytest) | everything else |
| Anything with a `TAP-IMPLEMENTS` claim or a `@pytest.mark.spec` marker | the two above, then the **guard trio** (below) | the lane |
| A few core files | the test files for them, `-n0` (seconds) | the lane, other apps |
| Gryphon (`tap_grid/`, `tap_api/routers/gryphon.py`) | `-k gryphon` under `tap_grid/tests` (~80 s), plus the effect/temporal files | the corpus, unless you touched the executor |
| A plugin | that plugin's tests via `--pyargs <package>.tests`, scoped with `-k` or one file (Gridkin corpus + internals ~4 min), run from the core root | the plugin repo's CI, which boots core `main` — **if it has CI** (see below) |
| `tap_viz/static`, `tap_web` templates or validation, panel schemas | the guard trio, then the demo project plugin's suite: `scripts/test --fast-relevant --plugins <slug>` (or `scripts/pytest-serial _dev-plugins/<slug> -q -p no:xdist`) (2.5 min unloaded, 12–16 min at load ~15) — playground suites pin this behaviour and core PRs #1089/#1091 each needed playground test edits | the lane |
| A UI change you need to see rendered | the ORM is write-guarded from a shell (`UnguardedOperation`), so you cannot create a throwaway page there. Reported to work (rampart-pg, #1100): a Playwright `page.route` rewrite of the served HTML, or importing a throwaway GRIFT batch and removing it with a `deletes` batch | — |
| Runtime JavaScript (`tap_viz`) | the JS harness on the HOST with a Node that has cytoscape — the container has neither, so the JS behaviour tests SKIP there. A green container run is not JS tested | — |
| A model or migration | the app's tests with `--create-db` (the test DB may be stale), and check `makemigrations --check` | the lane |
| Scripts / hooks | `bash -n`, then the script's own test file | the lane |

**The demo plugin's clone is on someone else's branch.** The playground clone may be on another agent's
feature branch with uncommitted work, so do not run its suite there and do not disturb it. Run it from a
clean checkout of the plugin's `main` (a second worktree), or skip it and SAY SO in the PR body ("demo
suite not run: clone busy; run on main after merge") so the gap is visible instead of silent.

**Plugins without CI.** Some plugin repos report no checks on any PR (`rampart-20x-playground-tap` today). For them "leave it to the plugin's CI" means nothing runs, so the local plugin suite is the only gate: run it. Check `gh pr checks` on a recent PR before relying on a plugin's CI.

**The guard trio** — the three checks that have actually reddened PRs, and what `.githooks/pre-push`
runs (~20 s together):

    scripts/dc exec -T web uv run pytest -q -n0 -p no:cacheprovider \
      "tap/tests/test_guards.py::test_guard_holds[mypy-static-typing]" \
      tap/tests/test_requirement_dispositions.py::test_committed_fragments_are_in_sync \
      tap/tests/test_guards.py::test_spec_map_in_sync

## 2. Run these locally only when the PR needs them

- **The full guard suite** (`tests/test_guards.py`, 6–15 min): when a guard is failing and you need
  the failing one, or you changed a guard. Name it with `-k`; do not run the lot to be safe.
- **The coverage ratchet** (`scripts/gryphon-coverage-ratchet`, ~6.5 min): when a PR could move
  executor branch coverage and may need `coverage-baseline.json` bumped.
- **The full lane** (`scripts/test`): never as a pre-PR habit. `PR# 742 - tap` went red on a
  drifted fragment, which the guard trio above catches in seconds; the lane was not what was missing.

## 3. Opening the PR

`scripts/promote-to-main.sh` (see `open-a-pr`) runs a **scoped, capped** local lane after the PR is
open: the core walk, plus the Gryphon corpus only when the diff touches the executor, no other
plugin's suite, `TAP_TEST_JOBS` defaulting to 3 (`req-dev-validation-suite-tiers-6`/`-7`). Do not
hand-run the same lane first. If the machine is loaded, push the branch and read the server checks
instead; the promote can be stopped after the PR opens, and the server `gate` still decides.
**Never bare `scripts/test` as a gate.** Run non-interactively it forces the Gryphon corpus in, and in a
profile without `gryphon_playground` it goes RED with nothing actually failing; use `--fast-relevant`.

**Stopping the lane means merging by hand or re-arming:** the promote arms auto-merge only after its
local lane is green (`req-dev-multisession-promote-script-4a`), so a stopped lane leaves the PR open
and unarmed until the human merges it, or you re-run the promote, or the human arms it. Tell the human
plainly: "the lane was stopped, so auto-merge is not armed; the server gate decided — merge by hand". A green but
unarmed PR gets no merge and then falls behind a moved base (tap#893 sat that way).

**A core change can break a plugin's own tests** that only that plugin's suite sees (the playground
suites pin `tap_web` / `tap_viz` behaviour), because the server's `core_ci` is fixtures-only. The scoped
lane does not run them unless you ask: `scripts/test --fast-relevant --plugins <slug>[,<slug>]` adds the named installed suites (an uninstalled slug is refused, not skipped); `--plugins auto` adds the suites the diff can reach — plugins that import the changed core code, plus those whose tests declare `PINS_CORE_SURFACES = ("tap_viz/static", ...)` for coupling that has no import edge (it is a conservative guess, not a proof: over-selecting by app, blind to anything neither imported nor declared); add `--no-core` for just those suites, under the lock, without paying for the core walk. For a plugin repo with no CI of its own this one command is the gate. See the `tap_viz` / `tap_web` row in section 1.

**A plugin PR is a different path.** A plugin repo has no promote; its PRs are opened by hand with
`gh`. Run the targeted tests from the core root, run your own plugin's suite with
`scripts/test --fast-relevant --no-core --plugins <slug>` (the variant that takes the lock; the tooling
lives in the stack's own tap checkout, so a plugin workspace on an older checkout must merge `main` first
or `--plugins` is simply not there), merge `origin/main`
immediately before opening (`open-a-pr` step 5 makes the author own the derived-artifact checks and
that merge there), push, and read the plugin's CI (if it has any).

## 4. How: rules for a shared machine

0. **Name the branch for the change.** The promote needs a `session/<name>` branch; a leftover name from
   the last task misleads every reader of the PR. Rename it before the first commit:
   `git branch -m session/<new-name>`.
1. **One heavy run per stack.** Never start a second pytest while one is running in the same stack.
   A polling "is pytest running?" check is NOT reliable: it fires in the gap between two plugin
   suites, which is how a subagent's run overlapped a lane on 2026-10-21. `scripts/test` and
   `scripts/pytest-serial <pytest args>` take one lock per stack, so a second run WAITS and names the
   holder (`python -m tap.pytest_lock status` shows it). Hand-typed `scripts/dc exec ... pytest` does
   not take it: for anything bigger than a file or two, and from parallel subagents, use
   `scripts/pytest-serial`. If you spawn subagents that run tests, say so in each brief: they use
   `scripts/pytest-serial` and never poll `ps` for a running pytest.
2. **Cap parallelism.** Export `TAP_TEST_JOBS=3` for any `scripts/test` (the promote already does); a single file needs `-n0`
   (bare `-n auto` adds a per-worker DB build that costs more than the test). Under load each xdist
   worker builds and migrates its own test DB, which can dominate a small lane — when the load
   average exceeds the CPU count, use fewer workers or `-n0` (the lane prints a warning), or set
   `TAP_TEST_REUSE_DB=1` to reuse each worker's DB — and drop it after a model or migration change.
3. **Check load first** (`docker stats --no-stream`). For a HEAVY run (full lane, guard suite, ratchet):
   if another stack is above ~300% CPU, wait or push and use CI. For a SHORT lane (one plugin, under
   a minute) do not wait for a quiet machine — one stack can sit at 700% all day: run it serial and
   capped (`TAP_TEST_JOBS=0 scripts/test --fast-relevant --no-core --plugins <slug>`).
4. **`--create-db` only when the test DB is stale** (after a migration reset). It rebuilds every time.
5. **Never `timeout` a lane** — it leaves stale test DBs behind.
6. **No edits while a promote lane runs**; they void its verdict.
7. **Stop your stack when you are not testing** (`scripts/dc stop`; volumes survive). `scripts/dc down -v`
   is the expensive one: it drops the volumes, and the rebuild cost about 3 minutes of image install and
   boot on the shared VM. Use it only to clear data you must clear.
8. **Plugin CI is slow and review rounds multiply it.** A plugin's server-side boot-and-test took 4–5
   minutes per push, and AI-review rounds meant 4–5 pushes per PR. One local plugin lane before each
   push (rule 3, the short-lane form) is what saves the CPU there.

## 4b. A plugin PR (no promote)

Most PRs in plugin repos are opened by hand with `gh`, so this is its own short path:

1. Branch from the plugin repo's latest `main`. Run tests **from the core root**, never `uv run` inside
   the plugin clone: it creates a stray `.venv` and `uv.lock` that make the manifest tests fail.
2. `scripts/test --fast-relevant --no-core --plugins <slug>` (serial, under the lock), or
   `scripts/pytest-serial _dev-plugins/<slug> -q -p no:xdist`. If you edited grift batches, re-import
   them with `import_plugin_grift --force-batches` first (an edited batch is skipped on a plain boot).
3. Check `git log -1 --format=%B`: the `Signed-off-by` trailer comes from the repo's commit hook, which a
   plugin clone may not have installed. A commit without it fails the `dco` job.
4. Open the PR by hand (`gh pr create` is allowed in plugin repos), merge `origin/main` first, then read
   the checks. Some plugin repos report **no checks and no AI review at all** (`rampart-20x-playground-tap`
   today): there the local plugin suite is the only gate.
5. **`scripts/pr-review-triage` reads only the core repo for now** (it has no `--repo` flag), so on a
   plugin PR it reports a different PR's reviews, or none. Read a plugin PR directly:
   `gh pr view <n> --repo <owner/plugin-repo> --json reviews,comments` and
   `gh api repos/<owner/plugin-repo>/pulls/<n>/comments`.

## 5. Stopping a lane

Stopping the host-side `promote-to-main.sh` (or a `scripts/dc exec` client) does **not** stop the run:
`docker exec` does not forward the signal, so `tap.lane_run` keeps launching suites in the container.
Use `scripts/test --stop` BEFORE killing by pid: it TERMs the process holding the stack's pytest lock, which kills its pytest
and every xdist worker as one process group. Stale `test_tap*` DBs may remain, so use `--create-db` on
the next run. Only a run started through `scripts/test`, `tap.lane_run` or `scripts/pytest-serial` holds
the lock; a hand-typed `pytest` has to be killed by pid inside the container.

If the holder itself dies (`kill -9`, an OOM), its pytest child inherits the lock and keeps it held, so a
second run still waits instead of starting on top of the orphan; `scripts/test --stop` then notices the
holder is gone and kills the orphaned process group.

## 6. Reds that are not your code

Verify serially (one test, `-n0`) before believing a red.

| Symptom | Cause | Fix |
| --- | --- | --- |
| `import file mismatch`, collection differs between workers | stale `__pycache__` | clear caches in the container, re-run |
| exit 137, `Errno 12`, `node down: Not properly terminated` | OOM on the shared VM | lower `TAP_TEST_JOBS`; stop idle stacks |
| `failed to resolve host 'db'` | DNS flake under load | re-run serially |
| mass ERRORs, `CapabilityDenied` | stale `test_tap*` DBs, or two pytest sessions on one DB | drop the stale DBs; one run at a time |
| server `core_ci line` fails at boot (`black` install, FIPS self-check) | CI runner permission error, before any test | `gh run rerun <id> --failed` |
| a plugin PR is red in code you did not touch, after a core merge | core `main` moved: with the promote scoped and `core_ci` fixtures-only, a core change that breaks a plugin is found on the plugin side, where it looks like the plugin author's fault | check core's recent merges before debugging the plugin |
| `mypy` rc=2, `INTERNAL ERROR` | corrupt mypy cache | `rm -rf /app/.mypy_cache`; run `mypy .` canonically and compare with the baseline, do not chase it |
| a plugin PR fails host syntax after `ruff format` | py314 rewrites `except (A, B):` to the unparenthesised PEP 758 form | never run `ruff format` or `black` in a plugin repo; it reformats the whole repo |
| release-please PR red on conformance | the ci record's sha256 is stale after a rev bump | `python -m tap.boot_records --refresh --root <dir with _dev-plugins>` |
| `guards --check` looks green | it runs about 2 of 187 guards | the real gate is `pytest tap/tests/test_guards.py` |
| a hand-run migration works, then the next boot fails | it skipped the search-role grant | let boot run migrations |
| editable plugin edit has no effect | the worker has the old code | restart the worker, wait for the pre-boot install and migrate |
| profile switched, data missing | a container recreate installs and migrates but does not seed | run `manage.py boot` |
| a Renovate PR is blocked on an image digest | Chainguard serves `:latest` only; pinned digests rot | refresh the pin on the blocked PR |
| plugin manifest tests fail with `Crypto providers are FIPS-validated ... weak-digest-md5 ... faker` | a stray `.venv` and `uv.lock` in a plugin clone, made by `uv run` run inside the plugin dir | delete both; run plugin tests from the core root |
| teardown: `database test_tap is being accessed by other users` | two sessions on the base test DB at once | harmless alone; treat it as the signal of an overlap |
| edited grift batches skipped on a plain boot | batch identity | re-import with `import_plugin_grift --force-batches` |
| playground CI fails with `cannot import name` after a core merge | "rerun failed jobs" reuses the first run's pinned core ref | dispatch a fresh run, or close and reopen the PR |

## 7. A red PR: watch it, and work it when it goes red

CI is where the heavy tests run now, so a red PR has to reach you without you polling for it. A
background loop that prints a summary "wakes nobody": #1093 sat red on an unused import because its
watcher was exactly that. The repo's standard watcher is the one to arm (`open-a-pr` step 7,
`close-out-pr` step 1):

1. **Arm it as a Monitor, on open and after every push** (a push is a new head), from a trusted
   checkout of the upstream repo, never the PR's own branch worktree:

       scripts/pr-review-triage <pr> --watch 60     # first ten minutes; then --watch 300 (step 2)

   It emits one line per event: `CHECKFAIL` the moment an individual check fails (a Sonar, Codacy or
   lane red is workable before the whole run ends), `CONFLICT` when the base moves, reviews and bot
   comments, and every merge-state change. At most two watchers at once; stop one when its PR merges.
2. **Poll fast right after a push, then slow down.** A check that fails in six seconds should not wait
   five minutes to be noticed: arm `--watch 60` for the first ten minutes after each push or open, then
   re-arm at `--watch 300`. Keep to two watchers at once (three hit GitHub's secondary burst limit).
3. **On a `CHECKFAIL`, act at once — do not wait for the other jobs.** A failed required check already
   blocks the merge, so the rest of the run only spends runner minutes. In this order:
   - Read the failure itself (`gh run view <run> --log-failed`, or the check's annotations for Codacy;
     SonarCloud's PR issues are public at `sonarcloud.io/api/issues/search?...&pullRequest=<n>`).
     Do not guess from the check's name.
   - Match it against section 6. An infrastructure red (CI boot, DNS, OOM, stale cache) is
     `gh run rerun <id> --failed`, nothing else.
   - A code or metadata red: fix it, run the targeted tests and the guard trio (section 1), then start the
     new run (below), and re-arm the watcher.
   - **You do not need to cancel the old run.** The workflow has a `concurrency` group per ref with
     `cancel-in-progress: true` (`product-lines.yml`), so the new run cancels the one still going. The
     fix that starts a new run IS the kill-and-restart.
4. **How to start the new run depends on what failed.**
   - A code, spec or lint fix: commit and push (a new head, a new `pull_request` run).
   - **The PR title** (`pr-title` fails in seconds): `gh pr edit <n> --title "..."` alone does NOT re-run
     it. `pull_request` is deliberately not triggered on `edited` (a title edit would skip every job and
     turn a healthy PR permanently red), and a re-run of the failed job reuses the original event's
     frozen title. So after editing the title, close and reopen the PR (`gh pr close <n> && gh pr reopen
     <n>`) to get a fresh run. This is read from the workflow's comments, not yet exercised; confirm on the
     first real title failure.
   - A failed `dco` or `check-issue-link` needs a rewritten commit, which is a force-push: that is
     NOT in the list below. Tell the human.
5. **Actions you may take on your own PR without asking:** edit its title or body, close/reopen it, re-run
   failed jobs, push a new commit to its own branch. **Not without the human:** force-push or amend, merge
   or approve, arm or disarm auto-merge on someone else's PR, change a ruleset or a required check, push to a
   PR you did not open. A local promote lane that is still running must finish first: an edit mid-lane
   voids its verdict.
6. **Stop after two failed rounds** on the same red and say what you tried: a third guess is the
   expensive one. A red the author cannot fix (a required review, a ruleset, a permission) goes to the
   human, not around them.
7. **What this does and does not do.** The Monitor wakes the session that armed it; a session that has
   ended will not act on a later red. Nothing here starts work unattended. An always-on watcher that
   opens or resumes a session on red is a larger design (a scheduled or remote trigger), not built.

## 8. Say what you ran

A PR body names the commands and counts, and what was left to CI and why. "Tests pass" without the
command is the claim `AGENTS.md` says to name the method behind.
