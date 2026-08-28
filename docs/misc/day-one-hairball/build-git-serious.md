# build-git-serious

I spent the day turning the domain-vocabulary corpus into types, collecting our own
organization with them, and then rebuilding the credential seam underneath when George changed
the design mid-flight. Written first-person and unreconciled; where I disagree with another
session below, I have left the disagreement standing.

## What I did

Got the `git_ref` ruling from George and built to it. Six new models in `github_core` —
`workflow_job`, `git_ref`, `github_ruleset`, `github_environment`, `actions_cache`,
`app_installation` split out of `github_app` — twelve edges, migration 0003, the config-layer
GraphQL query extended to carry rulesets, environments and every ref alongside the workflow
bodies it already inlined. Then the auth seam, twice: first as an either/or dispatch on the
envelope's `kind`, then rebuilt as one envelope holding an App and a token chosen per source
after George changed the design. All of it is on `feat/self-vocabulary`, PR #4, 143 tests green,
pushed.

I collected the org with it: 19 repos, 1014 nodes, 1352 edges. 163 refs, 65 declared jobs, 6
rulesets, 4 environments, 220 caches.

Then the gate view — four Gryphon-backed table panels in `git_serious`, seeded and rendering
against that data. Committed on `feat/gate-view`, not pushed, because it must carry the
`ci/nightly.boot.json` pin bump to v0.5.0 and that tag does not exist yet.

## What I believe is true

**The `git_ref` decision paid for itself on the first run.** Our org has a `tag-protection`
ruleset whose target is `tag`, and it resolved onto a tag through the same `PROTECTS` edge as the
five branch rulesets. The hypothetical in the decision was already sitting in the organization
that prompted it.

**A property that qualifies an absence belongs on the node, not on the edge.** The corpus put
`observable` on the `BYPASSES` edge. That cannot work as the only home: when the answer is *none*
or *unknown* there are no edges, so a view reading edges renders both as an empty list. The three
states live on the `github_ruleset` node. I think this generalizes past this domain and it is the
most transferable thing I produced today.

**47 of 220 cache entries in our org are scoped to pull-request refs.** Written from outside a
branch, sitting in the same repository a privileged job restores from. I am confident in the
number and confident it was invisible before this morning.

**Four of our environments have no job behind them.** `USES_ENVIRONMENT` returned zero against
four `github_environment` nodes. The gates exist; nothing routes through them.

**Neither credential dominates.** An App reads the installed-App inventory and the org's
fine-grained PAT grants; those 404 for a token. That half I verified directly.

## What I am unsure is true

**Whether the App can see a bypass actor when one exists.** This is the important one, and I want
to be precise about what I did and did not establish.

What I measured: with our read-only App, the REST ruleset detail omits `bypass_actors` entirely
(HTTP 200), while GraphQL returns `bypassActors` with `totalCount: 0` and **no `errors` entry at
all**. Separately, with George's owner credential via `gh`, every one of our six rulesets has a
genuinely empty bypass list.

What I concluded, and still hold: because our org has no bypass actors anywhere, **none of my
observations could discriminate "empty" from "withheld"**, so I shipped
`observable = REST carried the key OR GraphQL returned a NON-EMPTY list` — a non-empty answer
proves itself, an empty one proves nothing. False presence is impossible; false absence is the
whole risk.

**Where I now sit differently from the model-git-serious session.** That session says the question
is closed and bypass actors are observable, having created a probe ruleset with a real bypass
actor and read it back populated with no errors. I accept that finding for credentials that clear
the documented write bar, and I accept the mechanism they give — an App installation has no user
whose role it inherits, so `administration: read` never clears that bar. But their own next
paragraph asks me to run the measurement that would settle the App case, which tells me the App
case is *not* closed. **I do not think "bypass actors are observable" and "the App cannot see
them" are in conflict; I think the headline is broader than the evidence behind it.** Until the
App is pointed at a ruleset that genuinely has an actor, I would not weaken the `observable`
derivation, and I would not let a view render an App-sourced empty bypass list as "nobody".

**What I asserted today and no longer fully stand behind.** In the spec and the build log I wrote
that the empty-versus-withheld case "cannot be tested here without adding a bypass actor to a live
ruleset, which is a change to our security posture rather than a measurement." The other session
did exactly that — created, read, deleted — and it was a measurement. My framing made a cheap
experiment sound off-limits, and it was wrong to close that door rhetorically. The derivation it
justified is still right for the wrong-ish reason: the App's blindness is structural, not
incidental.

**I am unsure the manifest's permission claims are true.** `github_collection_manifest.json`
declares a permission triple per source and the App's least-privilege set is derived from it. I
added four sources today and widened the set by one entry
(`organization:administration:read`, for the account-wide installed-App inventory). Every
verification of those claims to date ran under a credential with `admin: true`, which
structurally cannot demonstrate that a *read*-level grant suffices. So the permission set is
plausible and unproven.

## The credential, and the run that collapses two threads

**I hold it.** `tap_secrets/github_core/collector.secret.json` in this worktree: the read-only
App `git-serious-exploratory`, app_id 4741739, installation 157103378 on `unified-systems-com`,
all 19 repos. Its self-test passes the whole chain — key signs, installation resolves, token
mints, 19 repos enumerate. **Yes, I can run `verify_app.py` tomorrow.**

**One blocker I created today, and it is on the path of exactly that run.** I changed the envelope
shape (kind `github`, with nested `app` / `pat` blocks) and migrated the placed credential to it.
`verify_app.py` still opens with `if envelope.get("kind") != "github_app": return 1` and reads
`d["app_id"]` / `d["private_key"]` at the top level. **So the verifier is currently broken against
the credential it is meant to verify.** It is a ~10-line fix — route it through
`secret.normalize_credentials`, the same function the collector uses — and I deliberately did not
do it tonight because George is stopping. It is the first thing to do tomorrow, before the run.

I also think that run should print, per permission, *which credential* answered, because the
manifest question and the bypass question want different things from the same output: the bypass
question needs a ruleset that actually has an actor, and the permission question needs each probe
attributed to the grant that satisfied it.

## The two questions I was asked

**The 13 uncommitted files in `~/tap-sessions/git-serious/_dev-plugins/github_core` are not
mine.** They are on `feat/org-scope` in the `git-serious` worktree; I worked in
`build-git-serious/_dev-plugins/github_core` on `feat/self-vocabulary`, which is committed and
pushed with nothing outstanding. I did introduce `github.observation: "declaration"` on
`workflow_job` and its edges, but that is committed on my branch. Whoever did the sweep across the
six existing models and six edge JSONs still has it unsaved, and I agree it is the real overnight
risk on that checkout — I have not touched it and will not.

**`REFERENCES_RESOURCE` carrying no `github.observation` is deliberate and correct.** Its sources
are `github_workflow` (a declaration) and `github_actions_run` / `github_actions_job`
(executions), so no single value on the edge type is true for more than a third of the edges it
emits. The observation layer is a property of the source endpoint, not of the edge type, and the
enrichment pass should set it per emitted edge from the source's own default. Worth noting: **the
uncommitted sweep already says exactly this in the edge file's description**, referencing
`req-github-core-dimensions-6`. So the domain article recording it as unresolved is stale relative
to work sitting unsaved on that checkout — which is one more reason to commit that checkout.

## What I left half-done

- **PR #4 is open and unmerged**, so **v0.5.0 is not cut**. Three things queue behind that tag:
  the cleanup session's pin + credential-kind change to the shipped record, my gate-view PR's
  `ci/nightly.boot.json` bump, and the product record's declared kind (which must become `github`
  now, not `github_app` — I changed the shape after that conversation).
- **`verify_app.py` does not read the new envelope.** Described above. Mine, and I broke it.
- **The gate view is committed but unpushed** on `feat/gate-view` off git-serious-tap main.
- **`status_check` does not exist**, so the gate page shows required check contexts as text with
  nothing joining them to the jobs that produce them. It is the next type and the corpus already
  has it at self tier with six sources.
- **The declared-to-observed cache join is a named gap.** Cache key expressions are stored as
  written and never evaluated; nothing claims a declared step wrote a particular entry.
- **`_emit_github_app` still stamps a shared app node with one repository's dimensions.** I fixed
  this for `github_ruleset` (an org ruleset was inheriting whichever repo emitted it last) and
  deliberately did not touch the pre-existing app case, because changing an existing type's
  dimensions was outside what I was doing. Same defect class, still there.

## One process note

Three of my test runs today were slow — twelve minutes against a normal two — and the cause was
entirely mine: my own polling loops had eight `docker compose` processes competing with the suite.
After clearing them the same suite ran in 23 seconds. Separately, a `pkill` I used to clear a
stuck run left a test database wedged mid-`CREATE TABLE`, which then looked exactly like a hanging
test. Both cost more of the day than any code problem did.
