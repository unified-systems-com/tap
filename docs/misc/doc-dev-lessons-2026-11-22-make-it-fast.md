---
title: Lessons learned — the make-it-fast session (2026-11-21 to 2026-11-22)
date: 2026-11-22
status: record
audience:
  - developer
  - llm
related:
  - tap#1275
  - tap#1276
  - tap#1282
  - tap#1299
  - tap#1302
  - tap#1309
  - rampart-20x-playground-tap#135
  - specs/spec-tap-baked-instance.md
  - specs/spec-tap-serving.md
  - docs/misc/doc-dev-lessons-2026-09-02-status-wall-day.md
---

> One session over two days: 36 rounds, three repositories, about a dozen merged PRs, two tap releases
> (0.4.3 and 0.4.5). It was written at the close from the session's per-round register, which kept
> every measurement with its evidence. It is meant for the next push on time-efficiency. Each lesson is
> written as a rule that would have saved time at the moment it applied, followed by the numbers behind
> it. A lesson that doesn't pass that test is listed under Observations.

# What the session did

It worked on three things, in this order.

1. **Migrations.** A shallow-reload road for `migrate` (tap#1275, tap#1276). A from-zero migrate
   with aws_core and computing_core went from 1,582 s to 216 s. The playground's 15 plugins went
   from 2,084 s to 271 s, and an upgrade from 200 s to 19 s. All three roads produced identical SQL
   and identical databases.
2. **PR CI.**
   - Plugin suites moved off the critical path: `line` went from 573 s to 436 s (tap#1299).
   - The specs tier runs only the tests that measurably read specs: 84 s against 306 s locally
     (tap#1302, tap#1305).
3. **Codespace launch.** The target was "a fresh playground Codespace serves in under 2 minutes,
   through a bake-and-personalize mechanism that isn't specific to the playground" (epic tap#1282).
   - The design spec merged as tap#1283.
   - A prebuilt Codespace used to never serve at all. Now it serves in 256 s (tap#1309 in 0.4.5,
     playground#135).
   - Still to build: the product image, the seed and the initializer.

# Rules

## 1. Break the real run into phases before choosing a cut

George's starting intuition was that a Codespace should come up "with nearly zero migrations". It
already did: the schema was built from the models in 32 s. The 403 s went elsewhere:

| Phase | Time |
| --- | --- |
| Machine, clone and image pull, before `web` even started | 170 s |
| Plugin install from git | 68 s |
| Population | 90 s |
| Schema | 59 s |

A local spawn takes 90 s for reasons that don't carry over to a Codespace. Its images are already
cached, it installs 1 plugin rather than 15, and it runs 2 population steps rather than 11.

**Rule:** before proposing a speedup, take the timestamps from a log of the real environment and
build the phase table. The slow part is rarely the one everyone suspects, and a spawn-to-Codespace
comparison is between two different boots.

## 2. A speedup ships with its equivalence proof

The shallow reload was accepted on evidence, not on speed. Both roads ran the same 14,192
schema-editor statements in the same order. A strict `tap.schema_parity` compare then found the
schema, the rows and `django_migrations` identical. The same test ran three more times, each with
identical results:

- the playground's 15 plugins;
- an upgrade, done on `CREATE DATABASE ... TEMPLATE` copies of one migrated database;
- a reverse migration followed by a forward one.

**Rule:** a faster road must name the oracle it is equivalent to, and how that was checked. Build
the comparison instrument first (here, statement capture plus a strict compare). A speedup with no
parity check is a behaviour change nobody has reviewed.

## 3. Re-check the ticket's premise against today's code before building it

Q14d was "a content-addressed CI image, so PR CI stops rebuilding it". When I re-read `ci-web-image`
before building it, the image was already pull-first. Of 65 merges to main, 19 touched the image's
inputs, and 8 of those were releases. So the change would not have shortened the critical path. It
would also have needed PR CI to write images that other runs pull, a permission the workflow doesn't
hold (`contents: read`). It was dropped from CI and became X1's product image instead, where a
published, attested image is the point.

**Rule:** before building a cache, read the path it would replace and count how often it would hit.
A cache that the existing path already approximates buys nothing and costs a trust boundary.

## 4. Narrow a test tier by measuring it, and fail closed on what the measurement can't attribute

The specs tier used to run the whole core walk. Now it runs a generated list of 23 test files: a
pytest audit hook (`tap/spec_read_audit.py`) records which tests open files under `specs/`. In review,
Codex found a real hole: reads made at conftest setup time were dropped, so a test fed spec content
through a fixture would go unlisted. The fix installs the hook at import and makes `--check` fail on
any read it can't attribute to a test.

**Rule:** derive a narrowed tier from a measurement the tree regenerates, never from a list someone
keeps by hand. Then make it fail on anything it can't attribute. A narrowing that drops unattributed
reads silently gets less safe with every change.

## 5. Moving tests off the critical path only helps if the gate still requires them

tap#1299 moved the plugin suites from `line` into `cold-boot`, cutting `line` from 573 s to 436 s.
Both review seats asked the same question: is the moved run still in force? The answer was the run
itself. `cold-boot` executed 419 of 422 corpus tests under `--require`. `gate` needs `cold-boot`, and
its `R_COLD` arm accepts only success.

**Rule:** when tests move to another job, cite the run where they executed in their new home, and
the gate condition that makes a failure there block the merge.

## 6. Fix the leak before adding parallelism

`worksteal` scheduling would have spread collector tests across every xdist worker. aws_core leaked
about 1.2 GB per collector run per worker, which is how a consolidation PR had already run a runner
out of memory. The aws-build session found the cause: one boto3 session per cached client, each with
its own copy of the service model. Sharing one session cut RSS from 1.7–2.9 GB to about 0.7 GB, and
the tests from 75 s to 39 s. That fix was worth more than the scheduling change, and the scheduling
change waited for it.

**Rule:** before turning up parallelism, measure memory per worker. When a peer session owns the
files involved, coordinate with it rather than editing around it.

## 7. Spike the platform early, on a throwaway branch, and budget the cloud asks up front

The prebuild question looked like a settings change. One spike branch with a prebuild configuration
answered it in a few runs:

- A prebuild cut the machine phase from 99 s to 41 s.
- But a prebuilt Codespace never served, because `web` aborted with `CODESPACE_NAME` unset.

None of that was in GitHub's documentation, and no amount of reading would have found it. Each spike
step also needed a cloud resource or an outward action: `gh codespace create`, a workflow dispatch,
and a force-push. Auto mode refused each one and it cost a round, which matches the standing rule to
ask George first.

**Rule:** when a speedup depends on platform behaviour, plan a real-platform spike before writing
the design. List every cloud resource and outward action it will need, and ask the human once for
all of them. A refusal is a stop, not an obstacle to route around: get authorization for the action
itself. The force-push here was refused only as a method. The human had already authorized putting
the fix on the throwaway spike branch, so the non-destructive method served instead: a fast-forward
built with `git commit-tree <tree> -p <remote-branch>`, which the report then named.

## 8. The platform's timing and contents are facts to observe, and they change the design

The first fix read Codespaces' shared `.env` once, at start. Watching it on a real Codespace showed
three things:

- **A race.** The file was written 3 s *after* `web` restarted, so the reader has to wait for the
  name.
- **Tokens.** The file holds `GITHUB_TOKEN` and `GITHUB_CODESPACE_TOKEN`, so the design moved to a
  three-key identity file written by the dev container.
- **A wrong doc claim.** In the visitor layout, `web` *is* the dev container, so Codespaces mounts
  the whole file there whatever compose says. The spec had claimed the token stayed out of `web`. The
  measured run disproved that, and tap#1314 corrected it.

**Rule:** a security property in a spec, such as "the token never reaches `web`", is re-checked
against the measured run before the requirement moves to Implemented. A wrong security claim in a
spec is worse than none, because readers trust it.

## 9. Speed fixes that ship through published images need the release choreography planned

Twice, tap's release PR merged before release-please had refreshed it to list the fix that had just
landed: tap#1274 in round 12 and tap#1310 in round 33. The code shipped, but the changelog line was
missing, and it had to be added by hand afterwards. The playground runs published images, so it
couldn't use the prebuild fix until a tag and an image existed. The 90-minute tag watcher timed out,
and release-please tagged the release a little later.

**Rule:** when a downstream depends on the fix through a release, say so on the fix PR, and check
the release PR's body lists it before that PR merges. Pin downstream by digest, and verify the digest
with `gh attestation verify --signer-workflow .../publish-images.yml` rather than by tag. The digest
doesn't move when the tag lands.

## 10. Check the timer, and record the contention

- The first dump-and-restore timing produced nonsense from a broken timer. The repeat gave dump
  10.8 MB, `pg_restore -j4` 5 s, and a template clone 0.9 s.
- The stock and shallow migrate runs shared a 12-core box with each other and with pytest, so both
  numbers are a little high.
- Two of the three manual `web` recreates on the spike Codespace failed because of my own test setup,
  not TAP's code. Relative mounts resolved against the host's Docker daemon, and an `--env-file` was
  missing.

**Rule:** sanity-check a timer on a known quantity before trusting its first number. Record what
else was running, and repeat the key measurement. When a reproduction fails, suspect the harness
before the product.

# Design conclusions worth carrying forward

These came out of the deep dive (round 18) and the spike. The spec is `specs/spec-tap-baked-instance.md`, from
tap#1283; this list is only a pointer to it.

- **Bake, then personalize.** Bake identity-free artifacts in CI, then personalize them at first
  start. This is how Lambda SnapStart, sysprep, cloud-init and Sentry self-hosted work, and the same
  artifacts can serve Codespaces, local spawns and hosted launches.
- **Ship the seed as an attested `pg_dump`, not a baked data directory.**
  - A data directory would save about 10 s per launch.
  - But tap-db declares `VOLUME /var/lib/postgresql/data`, and whether build-time writes there survive
    depends on which Docker builder ran.
  - A data directory also bakes in both role passwords and ties the seed to one Postgres binary.
  - RDS and Aurora can't use one at all.
- **A prebuild initializes nothing and mints no secrets.** Identity arrives at start, through the
  identity file the dev container writes.
- **The entrypoint must not undo a baked venv.**
- **Order the work by what churns.** Build the product image first, because a schema change just
  produces a new image on the next main build. A seed captures the schema, so build it after the
  entity-spine changes settle, or it gets built twice.
- **The remaining budget, measured.** A prebuilt start takes 256 s against the 120 s target. Most of
  it is plugin install (about 68 s) and population (about 90 s), which the image and the seed remove.
  The estimated floor with all three cuts is 60 to 120 s. That is an estimate, not a measurement, and
  the target still has to be measured on a real Codespace.

# Observations

- **The review cap held, and it was worth it.** tap#1309 ran three rounds: 8 findings, 4 fixed and 4
  answered. Round 1 found a real injection. `TAP_CODESPACE_NAME_WAIT` went into `$(( ))`, where bash
  evaluates an array subscript like `x[$(cmd)]` as a command. Speed work in shell entrypoints sits on
  a trust boundary, so read every environment-driven number as untrusted.
- **A per-round register with evidence made this document cheap.** Every number above was copied
  from a row that already named its run, sha or comment. The rows that were terse (rounds 1 to 20)
  were the hardest to reuse.
- **Two clean wins came from moving work rather than speeding it up.** The plugin suites moved to
  `cold-boot`, and schema and population move from launch time into CI. When a phase can't get
  faster, ask whether it has to happen on the critical path at all.
