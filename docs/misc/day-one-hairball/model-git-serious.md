# model-git-serious — 2026-08-27

Session scope: build a **domain-article layer** (per-concept background docs beside the
models) and its enforcing guard. That work finished. The rest of this file is the part
that matters more: a credential problem found late in the day that invalidates a chunk of
what several sessions concluded, and the corrections I had to make to my own output.

---

## 1. What shipped, and where it is

**Nothing is pushed.** Both repos hold local-only commits.

| Repo | Branch | Commits | State |
| --- | --- | --- | --- |
| core (`git-serious` worktree) | `session/git-serious` | `b08a32cb`, `258c37d0` | self-contained, green |
| `github_core` (`_dev-plugins/`) | `feat/org-scope` | `5728878`, `c946d4a`, `dd793b6`, `822db1a`, `c91b0b9` | green in the working tree |

`5728878` is **bypass-git-serious's** model commit, not mine; it sits under my three because
I reordered history so every commit is green (my articles referenced a model that landed
after them, which tripped my own orphan-article check). The reorder used a throwaway
worktree plus `git reset --soft` — never `reset --hard`, because the checkout holds a third
session's 13 modified tracked files. Those are still uncommitted and still theirs.

**What the layer is.** One markdown article per node type, edge type and dimension key, at
`<owner>/domain/<concept>.md` and `<owner>/domain/dimensions/<key>.md`. Ten sections; the
load-bearing ones are *Identity* (the natural key and why — unchangeable once set),
*Boundaries* (what was deliberately excluded, so it stops being re-litigated),
*Observability* (which credential and permission populate it, and what is not observable),
and *Authoritative Source* pinned per-model with `Source`/`Version`/`Retrieved` so "this
standard revised — which models does it touch?" is one grep.

**What the guard checks** (`tap/domain_articles.py` + `tap/guards/domain_articles.py`,
spec `specs/spec-domain-articles.md`): every registered type has an article; every required
section is present; every `FIELD_CRUD_SCHEMA` key, every dimension key an edge stamps, and
every value a dimension admits is accounted for; the authoritative source is pinned; no
article outlives the type behind it; and an unresolvable declaration is **reported, never
read as empty** — a false green in a coverage guard is worse than a failure.

Baselines are per-owner (`<owner>/guards/baselines/domain_articles.txt`) so a plugin carries
its documentation debt into its wheel and takes it away on eviction. github_core's was
seeded at 17 and drained to zero the same day; it is empty on purpose.

**Counts:** 21 github_core articles (8 node, 9 edge, 3 dimension, plus `github_ruleset`),
3 core dimension articles, 26 core tests, 2 plugin tests.

---

## 2. The bypass_actors saga — resolved, and the resolution is uncomfortable

This consumed most of three sessions. The short version: **bypass actors are perfectly
observable. GitHub surfaces them over both REST and GraphQL. They are invisible to *the
credential this product chose*, and for a structural reason.**

### How it went wrong

1. GitHub's docs state the rule plainly and the research pass found it: `bypass_actors` is
   returned only to a caller with **write** access to the ruleset. This was read correctly.
   Reading the docs was never the mistake.
2. Sessions measured against `unified-systems-com`, where **every ruleset genuinely has
   zero bypass actors** (verified with a privileged token). When the true answer is empty,
   "empty" and "withheld" are the same bytes — so no measurement there could show whether a
   **populated** list is withheld. *(My original wording — "every measurement ran against a
   case that cannot discriminate" — was too strong, corrected after `git-serious` pushed
   back: the App got **no key at all** while the PAT got `bypass_actors: []`, and
   absent-key versus present-and-empty is a real difference that does demonstrate gating
   exists. What was never demonstrated is what the App receives when a list is populated.)*
3. A read-only GitHub App reportedly saw the field *absent*; a PAT saw it *present as `[]`*.
   That difference was treated as evidence about content. It was not.

### The experiment that settled it

A probe ruleset carrying one bypass actor (`RepositoryRole` 5, `bypass_mode: always`) was
created on `notgeorge/samsite`, read with every available credential, and deleted. Repo is
back to zero rulesets.

| Credential | REST `/rulesets/{id}` | GraphQL `bypassActors` |
| --- | --- | --- |
| Admin token | actor returned | actor returned |
| "Read-only" PAT | actor returned, key present | actor returned, no `errors` |

**Both credentials in that table clear the write bar.** So it shows what an *authorised*
caller receives and says nothing about a *refused* one — which is the only case gating is
about, and the case this product is in. My original wording here ("bypass actors are
observable", "GraphQL does not gate differently from REST") was too broad, and
build-git-serious caught it: the GraphQL claim is proven only where neither transport gates
at all. Corrected in `0d23cc9`. Until the App is read against a non-empty list, keep
`observable` on `BYPASSES` at full strength and **never render an App-sourced empty bypass
list as "nobody can bypass"**.

### The mechanism

**One rule explains every observation** (`git-serious`'s unification, and the cleanest
statement of it): *any response that can carry `bypass_actors` requires write.* Repo ruleset
list, which never carries the field — 200. Detail, which does — 200 with the field stripped.
History, which carries full state — 403. Org list — 403. The App holds `read` everywhere and
is refused everywhere the field could appear. This collapses most of the "upstream
over-restriction" framing in the corpus: what survives is only that the *mechanism* is
inconsistent (strip in one place, refuse in another) and that the docs state permissions at
endpoint level without noting the field-driven escalation. That is a documentation-completeness
nit, not a platform defect. **Corpus open question 3 overstates and needs rewriting** — it
lives on `feat/org-scope`, which `bypass-git-serious` holds.

A **fine-grained PAT is attached to a user and inherits that user's role.** A **GitHub App
installation has no user to inherit from** — it holds exactly what was granted, so
`administration: read` never clears the documented write bar.

So the product's inability to see bypass actors is a consequence of choosing the App
(`req-github-core-app-auth`, which picked it because two other surfaces are App-only). Three
options, none free: mint the App with `administration: write` (abandons read-only on the
permission that matters most); run an admin-attached PAT alongside the App for this one
surface; or publish the gap and use rule-suite *events* for detection rather than enumeration.

### Still unproven — one call

The App half of that table has **not** been measured against a ruleset that actually carries
an actor. Every App observation so far was taken where the list was empty. Read a probe with
the read-only App before treating the mechanism above as fact rather than best-supported
explanation. `verify_app.py` already exists and would settle this in the same run that
validates the permission manifest (see §3).

### Also settled

- The `403` on `/rulesets/{id}/history` is **not App-specific** — a fine-grained PAT gets it
  too, message *"Resource not accessible by personal access token"*. `tap#192` is broader
  than recorded.
- `current_user_can_bypass` is returned to every credential tried. It answers "can *this*
  credential bypass" even where the actor list cannot be read — one honest row when the full
  list is unavailable.

---

## 3. The credential problem — read this before trusting anything measured today

**`tap_secrets/github_core/collector.secret.json` is described "Read-only GitHub PAT for the
TAP github_core collector — notgeorge/samsite". It reports `permissions.admin: true` on every
repository tested, including `unified-systems-com/tap`, which its envelope does not scope it
to.**

**Provenance, volunteered by `git-serious`:** nobody handed us a mislabelled credential — that
session typed the "read-only" description into the envelope during the account-scope move and
never verified it. So this is *an unverified claim asserted into a durable artefact*, where the
next operator could not distinguish it from a checked one. That is the day's pattern one level
up, and it is a better description of the failure than "mislabelled secret".

Consequences, in order of severity:

1. **Any "what a read-only credential can see" conclusion measured with it is unsound.**
   Including several of mine, before I caught it.
2. **The least-privilege claim in the collection manifest has never been validated, and the
   PAT path structurally cannot validate it.** Every triple in
   `github_collection_manifest.json` — `runners` needs `administration:read`, `workflow_yaml`
   needs `contents:read` — is an untested assertion. A PAT held by an admin can never
   demonstrate that a read-level grant suffices, because it inherits the role. Only the App
   can test it.
3. **The rulesets surface is undeclared.** The collector now reads rulesets via the GraphQL
   config query, but the collection manifest has **zero** ruleset sources, so the App's
   derived permission set does not account for it. It works today only because
   `administration:read` is in the union *for runners* — an undeclared dependency riding on
   a coincidence, in the one file whose job is to be the authority on why each permission
   is needed.

**The App-auth refactor itself is sound** and should not be blamed for this. Permissions are
derived from the manifest and never hand-listed; over-requesting is flagged in code as the
specific hazard for a security product; the org-vs-repo namespacing collision was already
caught. `verify_app.py` — "one probe per declared permission" — is the built instrument for
exactly this gap. It has not been run against a real App installation. That is the whole
finding: right design, missing validation, and a mislabelled credential is what let the gap
persist unnoticed.

Fix belongs in `/manage-secret`, not a patch.

---

## 4. Corrections I made to my own output — do not re-trust the originals

I was wrong **three times** today in the same direction: reaching a conclusion broader than
the evidence, and not noticing because the broader version was the satisfying one. Both are corrected in-tree; recording them so
tomorrow does not resurrect them.

0. **"Bypass actors are observable" — too broad.** True only of credentials that clear the
   write bar; both credentials in my experiment did. Says nothing about the refused case,
   which is the product's case. Caught by build-git-serious, corrected in `0d23cc9`.
1. **"The documentation contradicted reality" — false.** I wrote this into
   `spec-domain-articles.md` and the `build-domain-vocabulary` skill. GitHub documented every
   finding correctly. Corrected in `258c37d0` to the true and sharper lesson: *documentation
   describes the permitted path; only a call gives you the denied one.* It tells you the rule,
   never the failure shape — a refused caller gets HTTP 200 with a field absent, not an error,
   and that is what makes absence read as "nobody can bypass".
2. **"The scoped PAT was the product's credential" — false.** `req-github-core-app-auth` is
   explicit that the App is the product credential; the PAT path exists "for first-look and
   repos-only scopes". That PAT is a samsite demo leftover. I used the nearest credential and
   rationalised it afterwards.

---

## 5. Open threads, with owners

| # | Thread | Owner | Notes |
| --- | --- | --- | --- |
| 1 | Push both repos | George | Nothing pushed. github_core commits must stay in order — `5728878` first. |
| 2 | DCO sign-off missing on all `github_core` commits | George | No `core.hooksPath` in that repo, so nothing auto-appends. Neither I nor bypass hand-authored one; it certifies a human. Real setup gap. |
| 3 | Re-mint / re-label the collector PAT | George | `/manage-secret`. See §3. |
| 4 | Run `verify_app.py` against the read-only App | build-git-serious holds the App (`git-serious-exploratory`, 19 repos) | Validates every manifest permission claim **and** settles the outstanding bypass measurement in one pass. Highest value-per-effort item on this list. **Blocked: `verify_app.py` is currently broken** — the envelope shape changed (kind `github`, nested `app`/`pat` blocks) and the script still checks `kind != "github_app"` and reads `app_id`/`private_key` at top level. ~10 lines, route it through `secret.normalize_credentials`. Fix first, then run against a ruleset that *carries* an actor, and print which credential answered each probe. **Reframed by build-git-serious:** the question is not "can the App see bypass actors" but **"when GitHub refuses the App, does GraphQL say so, or does it answer zero?"** Their App data shows REST omitting the field while GraphQL returned `totalCount: 0` with no `errors` — suggestive only, since that org had a truthful zero. So the run must compare **both transports** on a ruleset carrying a real actor. **Do not add `bypassActors` to the collector's GraphQL config query until this is settled** — it is not selected today; if GraphQL answers zero to a refused caller, adding it would land false "no exemptions" on the grid silently. |
| 5 | Declare the rulesets source in the collection manifest | github_core owner | With its permission triple. See §3.3. |
| 6a | Rewrite corpus open question 3 | whoever holds `feat/org-scope` | It overstates: presents an expected, documented result as an anomaly, and claims more discrimination than the measurement delivered. See §2. |
| 6 | Mint the `repository → github_ruleset` edge slug | George | Corpus line 163 justifies the node via an edge that is not in the edge table — internally inconsistent until minted. All three sessions declined to mint into canon. My input: direction repo→ruleset, `GOVERNED_BY` (`GATED_BY` is taken), source as a **node** property, observed-vs-inferred reusing the existing `link_rule`/`matched_value` pair. **The corpus's own Naming rule says to check the 59-verb SPDX dictionary before minting — nobody has run it.** |
| 7 | ~~`REFERENCES_RESOURCE` observation value~~ **CLOSED** | build-git-serious | Deliberate. Its sources span declaration and execution, so no single value is true for more than a third of emitted edges; the layer belongs to the source endpoint, and enrichment should stamp per edge. Articles corrected in `0d23cc9`. |
| 8 | Generate `Dimension` grid nodes from dimension articles | unclaimed | `Dimension` has been a first-class node with a `description` field, spec'd *Implemented*, since before today — and **nothing in production has ever created one**. The articles are now the authored source; generating the nodes at plugin load would make "what dimensions exist and why" a graph query. Deliberately not built today. |
| 9 | Third session's uncommitted work in `_dev-plugins/github_core` | that session | 13 modified tracked files (the `github.observation` sweep) + untracked `test_observation_dimension.py`. Unsaved. **The real overnight risk on this checkout.** |
| 10 | `tap/tests/test_secrets_root.py` modified in core, not mine | unknown | Left unstaged. |

---

## 6. If you read only one thing

The day's pattern, in both the product and in my own work: **a privileged credential was
lying around wearing a "read-only" label, so nobody's read-only measurement meant what they
thought it meant.** Everything else — three sessions on bypass actors, an unfalsifiable
experiment repeated four ways, an unvalidated least-privilege manifest — follows from that
one fact. Fix the credential first; several open questions will collapse on their own.
