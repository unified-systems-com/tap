# git_core Plugin Specification

## Plugin Identity

- **Slug:** `git_core` (dist `git-core-tap`, namespace `tap_plugin.git_core`, AppConfig `GitCoreConfig`)
- **Display name:** Git Core
- **Repository:** `unified-systems-com/git-core-tap` (new; identity is repo-independent)
- **Initial page route:** none — a vocabulary substrate, no pages or panels in v0
- **Initial panel types:** none
- **Initial page variables:** none
- **Depends on:** nothing (Tier 0: none; Tier 1: none). `github_core` will depend on it.

## Philosophy

Git owns repositories, refs and commits. The forge owns hosting, collaboration and policy. The
execution system owns pipelines and jobs. Today all three vocabularies live in `github_core`, and
its Git nodes carry GitHub's dimensions, GitHub's natural keys (`owner/repo#…`) and GitHub's
observations (resolved logins, signature verdicts) as if they were properties of Git objects.

`git_core` is the Git half, extracted (github-core#76, ruled 2026-09-08): three neutral nodes and
the three relations between them, with identities a **second source can mint** without asking
GitHub anything. A GitHub repository and its GitLab mirror are two repositories that happen to share
content; the same commit observed from two hosts is **one commit with two observations**, and the
observation — who the forge resolved the author to, whether the forge verified the signature —
belongs to the observer, never to the commit. The vocabulary spec already marks these concepts
neutral and says extraction is cheapest while a slug change is still a re-collect
(`tap_plugin/github_core/specs/spec-github-core-vocabulary.md:282`); this is that moment.

**In scope:** `git_repository`, `git_ref` (branch and tag, as one type), `git_commit` (intrinsic
metadata only), `HAS_REF`, `RESOLVES_TO`, `CONTAINS_COMMIT`; identity helpers; domain articles;
a synthetic second-source fixture. **Out of scope:** any collector, any GitHub API, credential or
manifest; the full Git object model (trees, blobs, tag objects, parents, messages); pull requests
(forge collaboration); workflows/runs/jobs (CI/CD substrate); artifacts/packages (supply chain);
principals and credential grants (identity_core); network-level commit-observation dedup (needs
`Repository.parent`, not yet collected).

## Goals

| # | Name | Description |
| :---: | --- | --- |
| 1 | Second-source identity | Every id is `uuid5(GIT_CORE_NS, "<type>:<natural key>")` over facts a non-GitHub emitter also has; nothing in the key names GitHub. |
| 2 | One commit, many observations | Commit identity is `(hash_algorithm, object id)`; forge-side facts live on the forge's observation node, linked, never on the commit. |
| 3 | Hosts cannot collide | Same ref path in two repositories → two refs; two hosting records → two repositories; same commit from two hosts → one commit, two observations. |
| 4 | Movement stays visible | A ref that moved shows it in `head_sha` field history across successive collections on one grid, exactly as today. |
| 5 | Safe shared writes | A degraded source never blanks a known intrinsic field; a conflicting intrinsic fact fails loudly; source payloads stay off the shared commit. |
| 6 | Zero GitHub | `git-core-tap` imports no forge client and ships no collector; the kernel test populates it from a synthetic non-forge source. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-git-core-identity | [Identity Helpers](#identity-helpers) | Proposed | `tap_plugin.git_core.identity`: repository / ref / commit ids; namespace `git_core.tap`; the ONE derivation every emitter uses |
| req-git-core-repository | [git_repository](#git_repository) | Proposed | Host-independent, name-independent identity; the neutral node hosting records link to |
| req-git-core-ref | [git_ref](#git_ref) | Proposed | Moved from github_core with its contract intact; key = repository identity + full ref path; neutral dimensions |
| req-git-core-commit | [git_commit](#git_commit) | Proposed | Intrinsic metadata only; identity `(hash_algorithm, oid)`; shared-write rules |
| req-git-core-edges | [Edges](#edges) | Proposed | `HAS_REF`, `RESOLVES_TO`, `CONTAINS_COMMIT` |
| req-git-core-kernel-fixture | [Synthetic Second-Source Fixture](#synthetic-second-source-fixture) | Proposed | A non-forge emitter populating all three types + edges through git_core's helpers; the vocabulary spec's kernel test made concrete |
| req-git-core-consumers | [Consumer Contract](#consumer-contract) | Proposed | What github_core and git-serious must change to consume; owned here as the contract, executed there |
| req-git-core-nongoals | [v0 Non-Goals](#v0-non-goals) | Proposed | The exclusions, stated |

### Identity Helpers
----
RID: `req-git-core-identity`

Status: `Proposed`

`tap_plugin/git_core/identity.py` owns `GIT_CORE_NAMESPACE = uuid5(NAMESPACE_DNS, "git_core.tap")`
and three functions. Each is the single derivation of its id (`derive-a-fact-once`); github_core
imports them (Tier-1 `depends_on`), the kernel fixture imports them, and no consumer re-derives.

- `git_repository_id(forge: str, stable_id: str) -> UUID` — key `"<forge>/<stable_id>"`. `forge` is
  the host instance (`github.com`, `gitlab.example.org`, or a synthetic source name); `stable_id`
  is the host's immutable repository identifier (GitHub's numeric `id`; a second source supplies
  its own). A rename never re-mints; a GitHub repo and its GitLab mirror never merge.
- `git_ref_id(repository: UUID, ref: str) -> UUID` — key `"<repository uuid>#<full ref path>"`.
  `refs/heads/release` and `refs/tags/release` are distinct; the same path in two repositories is
  distinct. Never `owner/repo`.
- `git_commit_id(hash_algorithm: str, oid: str) -> UUID` — key `"<algo>:<oid lower-cased>"`,
  `algo` ∈ `sha1` | `sha256`. Global content identity; repository membership is an edge.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-git-core-identity-1 | Namespace And Keys | Proposed | The three helpers mint `uuid5(GIT_CORE_NAMESPACE, "<entity_type>:<key>")` with the keys above; a rename of a repository changes no id; the same oid from two sources yields one commit id. | Property tests. |
| req-git-core-identity-2 | Nothing GitHub In The Key | Proposed | No helper takes a login, `owner/repo`, URL or forge-specific field other than the opaque `stable_id`; `grep -i github tap_plugin/git_core/identity.py` is empty. | |

### git_repository
----
RID: `req-git-core-repository`

Status: `Proposed`

`git_core__git_repository`: a particular repository, identity independent of its mutable display
name (`req-git-core-identity`). Fields: `forge` (host instance), `stable_id` (the host's immutable
id, string), `name` (display, mutable), `default_ref` (full path, e.g. `refs/heads/main`),
`hash_algorithm` (`sha1` default), `configuration`, `tags`. Default dimensions are neutral
(`git.object: repository`), never `github.*`. A forge's hosting record (github_core's
`github_repository`, kept there) links to it with a forge-owned `HOSTS_REPOSITORY` edge; generic
consumers traverse from the neutral node, forge views still reach the hosting facts.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-git-core-repository-1 | Distinct Hosts, Distinct Repositories | Proposed | Two hosting records with the same content (mirror) produce two `git_repository` nodes; a rename produces a field change on one node, not a second node. | |
| req-git-core-repository-2 | Neutral Contract | Proposed | Dual schema (`FIELD_CRUD_SCHEMA` / `FIELD_VALIDATION_SCHEMA`), neutral `DEFAULT_DIMENSIONS`, domain article `domain/git_repository.md` with Blurb / Purpose / Goals / Identity / Boundaries / Neutrality. | |

### git_ref
----
RID: `req-git-core-ref`

Status: `Proposed`

`git_core__git_ref`, moved from `github_core__git_ref` with the contract that already works kept
whole: `ref` (full path — identity), `ref_type` ∈ branch | tag, `name` (short), `head_sha` (the
peeled commit), `target_sha` / `target_type` (the direct target when it differs — annotated tags),
`is_default`, `configuration`, `tags`. **Dropped:** `full_name` (GitHub's `owner/repo`; the
repository is the `HAS_REF` source and the identity input). **Changed:** default dimensions are
neutral. Movement remains field history on `head_sha`. Branch and tag stay one type (vocabulary
decision 2, 2026-08-27).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-git-core-ref-1 | Identity By Repository + Path | Proposed | `refs/heads/x` and `refs/tags/x` in one repository are two nodes; `refs/heads/x` in two repositories are two nodes. | |
| req-git-core-ref-2 | Movement Visible | Proposed | Two successive collections on the same grid where a tag moved show the old and new `head_sha` in field history and a re-derived `RESOLVES_TO`. | The fixtures repo's drift test, re-pointed at the neutral type. |
| req-git-core-ref-3 | Article Written | Proposed | `domain/git_ref.md` exists (github_core never had one). | |

### git_commit
----
RID: `req-git-core-commit`

Status: `Proposed`

`git_core__git_commit`: commit content identity and intrinsic metadata — `hash_algorithm`, `oid`
(full object id), `authored_date`, `committed_date`, `author_name`, `author_email`,
`committer_name`, `committer_email`. **Nothing observed by a forge**: no `*_login`, no
`signed_by_github`, no `signature_*`. Those move to github_core's `commit_observation` node
(`req-git-core-consumers`). Identity `(hash_algorithm, oid)` — global; membership is
`CONTAINS_COMMIT` from the repository, meaning *observed present*, never complete history.

**Shared-write rules** (ruling 0.3): with global identity there are multiple writers. (a) A write
carrying a blank for a field the node already holds keeps the held value — the service layer's
null-as-absent semantics; confirmed by test, not assumed. (b) A write asserting a DIFFERENT
non-blank value for an intrinsic field (two author emails for one oid) fails loudly at the
seeding boundary with both values named, never last-writer-wins. (c) Source-specific payloads
(logins, verdicts, URLs) are rejected by the schema (`additionalProperties: false`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-git-core-commit-1 | One Commit Per Oid | Proposed | The same oid emitted by GitHub collection and by the kernel fixture is one node with one id. | |
| req-git-core-commit-2 | Degraded Source Cannot Blank | Proposed | Two writers, one with incomplete metadata: the complete intrinsic metadata survives; the writers' observation records (in github_core) stay separate. | |
| req-git-core-commit-3 | Conflict Fails Loudly | Proposed | Two writers asserting different non-blank values for one intrinsic field: the second write is refused with both values in the error. | |
| req-git-core-commit-4 | No Forge Fields | Proposed | The schema rejects `author_login`, `signature_state` and any unknown key. | |

### Edges
----
RID: `req-git-core-edges`

Status: `Proposed`

- `HAS_REF` — `git_repository` → `git_ref`. Moved from github_core (was repository → ref). Property-free.
- `RESOLVES_TO` — `git_ref` → `git_commit`: the peeled commit (branch head; for an annotated tag the
  commit the tag object points at). Replaces `POINTS_AT` (ruling 0.5). Property-free; a moved ref
  re-derives the relation (shape G). **No `TARGETS_OBJECT`**: the tag object is out of scope, so
  `target_sha` / `target_type` stay as fields on the ref.
- `CONTAINS_COMMIT` — `git_repository` → `git_commit`: observed presence. Emitted for every commit a
  source observed in that repository; absence means unobserved, never absent.

All three carry neutral default dimensions and `.edge.json` definitions with the same shape as
github_core's (slug `<NAME>__git_core`, `sources`, `targets`, `default_dimensions`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-git-core-edges-1 | Three Definitions | Proposed | The manifest declares exactly `HAS_REF`, `RESOLVES_TO`, `CONTAINS_COMMIT` with the sources/targets above; `validate_plugin --strict` passes. | |
| req-git-core-edges-2 | Peel Is Explicit | Proposed | For an annotated tag in the fixture, `RESOLVES_TO` targets the peeled commit while `target_sha` on the ref names the tag object. | |

### Synthetic Second-Source Fixture
----
RID: `req-git-core-kernel-fixture`

Status: `Proposed`

`tap_plugin/git_core/fixtures/` ships a small deterministic emitter (a Python module producing a
GRIFT document, plus the committed document it produces) representing a **non-forge** repository:
one repository, a default branch, a lightweight tag, an annotated tag (with a distinct tag object
oid), three commits including one shared with the GitHub fixture's oid. It uses only
`git_core.identity` and knows nothing about GitHub. It is the plugin's own proof that the
vocabulary is populatable from a second source (goal 6) and the substrate for the shared-write
and collision tests. Not seeded by any product record.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-git-core-kernel-fixture-1 | Populates The Vocabulary | Proposed | Importing the fixture creates 1 repository, 3 refs, 3 commits, `HAS_REF` ×3, `RESOLVES_TO` ×3, `CONTAINS_COMMIT` ×3, with ids reproducible from the helpers. | |
| req-git-core-kernel-fixture-2 | Independent Of GitHub | Proposed | The fixture module imports nothing from `tap_plugin.github_core`. | Guard-checked (cross-plugin import gate). |

### Consumer Contract
----
RID: `req-git-core-consumers`

Status: `Proposed`

What consumers change, executed in their repos, contracted here so the extraction has one
definition of done (github-core#76 steps 3–5):

- **github_core v0.6.0:** `depends_on += git_core` (install order git_core first). The collector
  emits `git_repository` (forge `github.com`, `stable_id` = GitHub `id`), `git_ref`, `git_commit`
  via git_core's helpers; keeps `github_repository` as the hosting record with a new
  `HOSTS_REPOSITORY` → `git_repository` edge; adds `commit_observation` keyed
  `github.com + stable repository id + commit identity` (a stable record updated in place)
  carrying `author_login`, `committer_login`, `signer_login`, `signed_by_github`,
  `signature_kind/state/valid`, with `OBSERVES_COMMIT` → commit and `OBSERVED_IN` → hosting record.
  Retargets `PROTECTS` (ref target → neutral ref; repository target STAYS the hosting record),
  `SCOPED_TO`, `EVALUATED_ON_REF`, `TARGETS_REF` → neutral ref. Removes `github_core__git_ref`,
  `github_core__git_commit`, `POINTS_AT`, `HAS_REF`. Updates `github_collection_manifest.json`
  (the declared types, fields and edges), `machinery.js`, tests, the plugin-ci boot profile.
- **git-serious:** the three bundles and two projection modules switch slugs; the gate/ruleset
  views read verification from `commit_observation` (an explicit traversal change); machinery
  containment starts from the hosting record. Dev profiles install git_core.
- **Instances:** fresh-grid re-collect (ruling 0.4); a `retype` migration is a separate issue if
  a production grid ever needs it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-git-core-consumers-1 | GitHub Populates The Same Types | Proposed | A GitHub collection and the kernel fixture on one grid share `git_core__*` types and, for the shared oid, one commit node with two observation records. | |
| req-git-core-consumers-2 | Pages Correct After Traversal Change | Proposed | git-serious's gate page answers "signature required / verified" from `commit_observation`; landing/org/machinery render against the re-collected grid. | |
| req-git-core-consumers-3 | Pinned Composition Released | Proposed | git-core-tap v0.1.0, github_core v0.6.0 and a git-serious release pinning both; the double-tap composition record moves its pins. | |

### v0 Non-Goals
----
RID: `req-git-core-nongoals`

Status: `Proposed`

No collector or forge client here, ever — a forge plugin emits this vocabulary. No tag objects,
trees, blobs, parents or messages (`TARGETS_OBJECT` explicitly dropped). No pull requests, no
CI/CD, no packages, no principals. No network-level observation dedup until `Repository.parent`
is collected (github_core follow-on). No pages or panels in v0.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-git-core-nongoals-1 | Stays A Substrate | Proposed | The package contains no `collectors/`, `panels/`, `templates/` or `static/` directory in v0. | Reviewed on every PR. |
