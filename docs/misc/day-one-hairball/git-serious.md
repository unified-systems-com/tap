# git-serious — the original session

First person, unreconciled. I ran from the naming of the problem through to the vocabulary corpus,
the collector work, and the GitHub App. I own the corpus, which means I own its errors, and there
are several.

## What I did

Named the problem and the promise with George. Built the vocabulary corpus (30 node concepts, 27
edges) from four research passes and wrote `build-domain-vocabulary` to generalise the method.
Landed tap#145 (the `<slug>-tap` convention). Took `github_core` from a one-repo collector to
account scope, then re-architected its config layer onto GraphQL. Created the GitHub App and its
manifest-driven creation skill. Produced three HTML briefings and the build log.

## What I believe is true

**The GraphQL/REST split is real and useful.** GitHub exposes no Actions runs or jobs in GraphQL —
verified against the live schema, `Repository` has no field for them. One request returned 19 repos,
46 workflow files with 172 KB of YAML inlined, 60 rulesets, at a cost of 2 rate-limit points against
~85 REST calls. That measurement is solid; I watched the cost field.

**The three org-scale collector defects were real**, and each cost the entire collection before it
was guarded: shared nodes emitted once per repo (18 duplicates), one transient TLS timeout aborting
all 19 repos, and runs naming deleted workflows (3 dangling edges). All three are invisible at one
repo. I trust these — I saw each fail and each pass.

**The declared-versus-executed job gap is the corpus's most important finding.** It was reached
independently by two passes that never spoke: the incident corpus needed it for ~20 of 35
compromises, and the published BloodHound schema models declaration only. `github_actions_job`
carries `github.observation: "execution"`; I read the model source.

**Twelve days with admin holding `bypass_mode: always`** on `main-required-checks`, 28 pushes
through it, on a ruleset that reads empty today. That came from `bypass-git-serious` via ruleset
version history. I did not measure it; I believe it because the version ids and timestamps were
specific and internally consistent.

## What I asserted and was wrong about

**1. I called a credential read-only in its own envelope without checking.** I wrote
`"Read-only fine-grained GitHub PAT for the github_core collector"` into the secret description when
I moved it to account scope. Verified just now against `/repos/unified-systems-com/tap`:

```
{"admin": true, "maintain": true, "push": true, "triage": true, "pull": true}
```

Full admin. **Every comparison I drew all day between "the PAT" and "the App" was admin-versus-read,
not read-versus-read.** So my headline — *"the App sees less than a read-only PAT, which is a
surprise"* — was not a surprise at all: GitHub documents that `bypass_actors` requires write access,
the PAT had it, the App did not. I presented an expected result as an anomaly, and I did it in a
credential description that the next operator would have trusted.

**2. That collapses most of the "upstream defect" framing I put in the corpus.** I recorded the
403s as an over-restriction contradicting GitHub's published read-level table. With the admin
correction, a single rule explains every observation: **any response that can carry `bypass_actors`
requires write access.** Repo list (no field) 200; detail (field) 200 stripped; history (full prior
state) 403; org list (field) 403. The App holds read everywhere, so it is refused everywhere the
field could appear. What remains genuinely inconsistent is only the *mechanism* — strip in one place,
refuse in another — and possibly the docs stating the endpoint level without the field-driven
escalation. That is a much smaller claim than the one I wrote. **The corpus currently overstates it
and should be corrected.**

**3. I told `model-git-serious` that two of the day's findings "contradicted the docs".** It checked
and I was wrong: the docs were correct, including the `bypass_actors` write rule quoted verbatim in
our own research pass. My real lesson was narrower and better: documentation states the permitted
path and not the denied one — a refused caller gets HTTP 200 with a field absent, not an error.

**4. My probe methodology had a bug that produced a false negative.** I reported "version detail not
reached — no version id obtainable" when I had gated the version fetch on the list call succeeding.
Version ids were obtainable from another session. The 403 held when retested, so the conclusion
survived, but the first report was a statement about my script rather than about GitHub.

**5. I invented `~/tap-products/` and documented it as convention** in the build log, in the voice of
established practice. Nobody agreed to it, `_dev-plugins/` already covered the need, and the log is
mined for the `create-product` skill — so it would have told the next operator to do it too.
Corrected and the directory removed.

## What I am unsure is true

**Every bypass measurement I took was unfalsifiable, and `model-git-serious` is right about this.**
Our org has genuinely zero bypass actors everywhere. When the true answer is empty, "empty" and
"withheld" are close to identical. I did measure *field presence* — the PAT got `bypass_actors: []`,
the App got no key at all — and that difference is real. But I never demonstrated that a **populated**
list is withheld from the App, because no populated list existed. The corpus says "measured against
our own org", which implies more discrimination than the measurement delivered. One call with the
App against a non-empty ruleset settles it; `build-git-serious` holds the credential.

**Whether org-level ruleset endpoints behave differently from repo-level for reasons beyond the
field rule.** Three org endpoints answer 200 for the App (installations, PAT grants, members) while
org rulesets 403. The field rule explains it if the org list embeds `bypass_actors`; nobody has
confirmed that shape with a credential that can read it.

**The four research passes are cited but not audited by me.** I read their summaries and spot-checked
the claims I repeated. The incident counts, the "3+ independent sources" convergence numbers, and the
standards citations are theirs, not mine.

## Which corpus claims rest on documentation versus on executed calls

This is the distinction that turned out to matter most, and the corpus does not currently mark it.

**Executed, and I watched them run:** GraphQL cost and payload; no Actions runs in the GraphQL
schema; the three collector defects; `github_actions_job` being an execution; App JWT chain and
installation; the App-only 404s becoming 200s; every 403 recorded today; the repo ruleset list
returning 200 without the field.

**Documentation or another session's report, repeated by me as fact:** the `bypass_actors` write
rule (correct, verbatim in the research pass); GitHub's fine-grained permission table (which I used
to argue an upstream defect — see error 2); the twelve-day history window; the SPDX 59-verb
dictionary; the BloodHound node and edge counts; every "3+ sources" convergence claim.

**Neither, and it should not have been stated:** "the App sees less than a read-only PAT". The
premise was untested and false.

## Left running or half-done

- **The `repository → github_ruleset` edge is unminted.** Corpus line 163 justifies the node with
  "which many repositories point at" — a node test passed by an edge absent from the edge table. That
  is my error and it reads as settled, which is worse than a gap. All three sessions declined to
  mint. **The corpus's own Naming rule says to check the 59-verb SPDX dictionary first, and nobody
  has run it** — the one piece of process the corpus asks for by name.
- **Corpus open question 3 needs rewriting** per errors 1 and 2 above. It is on `feat/org-scope`,
  which `bypass-git-serious` took; I did not edit it after handing the branch over.
- **`git_ref` versus `git_branch` is unruled.** George's answer was cut off mid-sentence and I
  carried it to `build-git-serious` rather than assuming.
- **`dcom_core` is named but not built** — the principles-as-predicate substrate, placement decided
  (not core), `compliance_core`-versus-new-substrate open.
- Three secret stores in play, deliberately unreconciled; `cleanup-git-serious` owns it.

## The one rule worth carrying into tomorrow

It surfaced four separate times today, in four unrelated systems: **a missing fact and a negative
fact must never render the same way.** Gryphon accepting a filter and dropping it; a partial
collection that could not be distinguished from a complete one; `time_period` defaulting to a day so
an empty list reads as "never"; and `bypass_actors` absent reading as "nobody can bypass". My own
credential error is the same shape one level up — an *unverified* claim written down as an
*asserted* one, indistinguishable to the next reader.
