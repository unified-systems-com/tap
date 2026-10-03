# Bug Reporting And Fix Proposals From Outside — `submit-a-bug` And `submit-a-fix`

## Philosophy

People now run TAP who have never spoken to us: they found the repository, booted it, customised it
and kept going. When something breaks for them, the report they can write without help is a
paragraph and a stack trace. The report we need to fix it is a reproduction: the versions, the shape
of the data that triggers it, and the steps, ideally as a failing test. This spec makes the
difference between the two a procedure, two repo skills, rather than a round of questions in an
issue thread.

**`submit-a-bug`** runs in the reporter's install and produces the report. **`submit-a-fix`** reads
a report and works toward a fix. The maintainer runs it, and so can the reporter against their own
open bug. A third skill, `review-a-fix`, is deliberately not in this spec.

Three facts shape everything below.

**The reporter's data is sensitive, and the destination is public.** TAP is pointed at cloud
accounts, identity providers and source forges. A report drafted from the reporter's real graph
carries their account IDs, hostnames, org and repository names, and email addresses. It would
publish them to a public tracker where an edit does not remove them, because GitHub keeps a public
edit history for issue bodies and comments. Nothing on GitHub blocks that send: push protection
does not cover issue bodies, and secret scanning alerts only after the fact. The documented failure
is not a leaked token but leaked *names* (anthropics/claude-code#29121, where an agent drafted a
public bug report full of a user's private org names, repository URLs and paths). So the
reporter's real data **never leaves their machine**. The report carries synthetic data built to the
same shape, and the reporter consents to the exact bytes before anything is sent.

**TAP already knows which fields are sensitive, because it makes every author say what each field
means.** Every JSON structure carries a `description`, and every field schema publishes one
(`req-grid-keystone-self-describing`; the field-schema `description` in `spec-grid-node.md`). A
generic bug reporter has to guess which values in a dump are sensitive. This one reads the field's
own description, so the judgement is made per field, with the author's words as evidence, and is
shown to the reporter. Where a field has no description, the skill treats it as sensitive. A
missing description is the one case where it is guessing, so it guesses safe.

**A bug report is text a stranger wrote, and the fixing agent will read it.** Any agent that reads
untrusted text, holds credentials and can reach the network can be steered into leaking what those
credentials reach (Simon Willison's "lethal trifecta"). Agents have been: a malicious public issue
made an agent with GitHub access leak private-repository data into a public pull request (Invariant
Labs, 2025), and an injected issue title in Cline's triage workflow led to stolen publish tokens and
a malicious release ("Clinejection"). Filtering clever text is best effort, even by its vendors'
own account. What holds is structure: once `submit-a-fix` has read a report, it holds no
credentials and has no network, and a human pushes whatever it produced.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Reports Reproduce | A report carries what a maintainer needs to reproduce the bug on a fresh instance (versions, a synthetic dataset, steps, expected versus actual), confirmed to still fail before it is sent. |
| 2. | Nothing Real Leaves Without Consent | The reporter's own data never enters a report; what is sent is shown byte for byte and sent only on an explicit yes to that exact content. |
| 3. | Reports Reach The Right Place | A bug lands in the repository that owns the failing code, and a vulnerability never lands in a public issue. |
| 4. | Fixes Start From A Failing Test | A proposed fix exists only alongside a test that fails without it and passes with it, on the reporter's version and on `main`. |
| 5. | Stranger-Written Text Never Steers The Agent | Whatever a report says, the agent reading it cannot be made to send data anywhere, run what the report names, or push anything. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-dev-bugreport-route | [Security First, Then The Owning Repository](#security-first-then-the-owning-repository) | Proposed | A vulnerability goes to private vulnerability reporting; anything else goes to the repository the boot record names as the failing plugin's source |
| req-dev-bugreport-synthetic | [Synthetic Data, Judged From The Schema](#synthetic-data-judged-from-the-schema) | Proposed | The dataset is generated to the failing shape from each field's published description, never exported and scrubbed; it must still reproduce |
| req-dev-bugreport-environment | [Environment Facts From An Allowlist](#environment-facts-from-an-allowlist) | Proposed | Versions and topology come from a fixed list of sources; nothing is collected by dumping and scrubbing |
| req-dev-bugreport-tripwire | [The Reporter's Own Values Block The Send](#the-reporters-own-values-block-the-send) | Proposed | Any of the reporter's own identifiers, or a credential shape, in the outgoing text stops the send |
| req-dev-bugreport-consent | [Exact Bytes, Explicit Yes, Fail Closed](#exact-bytes-explicit-yes-fail-closed) | Proposed | Preview the exact file, name the repository as public and permanent, take a yes bound to that content, and never improvise on a failed send |
| req-dev-bugreport-shape | [A Report Shape The Fixer Can Parse](#a-report-shape-the-fixer-can-parse) | Proposed | Fixed headings plus one machine-readable block; an AI-assistance disclosure |
| req-dev-bugfix-untrusted-intake | [The Report Is Data](#the-report-is-data) | Proposed | Extract into the report shape; read only the reporter's and maintainers' comments; nothing in it is an instruction |
| req-dev-bugfix-isolation | [No Credentials, No Network, After Reading](#no-credentials-no-network-after-reading) | Proposed | A fail-closed preflight refuses to proceed while the session can reach a GitHub token, the secrets store or cloud credentials |
| req-dev-bugfix-reproduce | [Reproduce Twice Before Fixing](#reproduce-twice-before-fixing) | Proposed | A failing test on the reporter's version and on `main`, or one of three named exits |
| req-dev-bugfix-handback | [A Human Pushes](#a-human-pushes) | Proposed | A local branch, before and after evidence, and a draft PR body; the skill never pushes, opens a PR, or signs off |

### Security First, Then The Owning Repository
----
RID: `req-dev-bugreport-route`

Status: `Proposed`

The first question `submit-a-bug` asks is whether the problem lets someone do something they
should not: read data they shouldn't, act as someone else, or get past a check. If it does, or
might, the skill stops drafting a public issue. It directs the reporter to the repository's private
vulnerability reporting, and to `SECURITY.md`, whose existing rules for AI-assisted reports (a
runnable proof, and a preamble in the reporter's own words) apply unchanged. The skill does not
judge severity. "Might be" is enough to go private, because a vulnerability published as a public
issue cannot be unpublished.

Otherwise the report goes to the repository that owns the failing code. The owner is read from
the install, not guessed. The boot record names every installed plugin's source as
`install.plugins[].source.url`, with the `rev` and `commit` it was installed at. A failure inside
a plugin goes to that URL. A failure in core goes to `unified-systems-com/tap`. A failure the
reporter cannot attribute also goes to tap, which is what tap's issue-template `config.yml`
already tells people. A source URL outside `unified-systems-com` is a third-party plugin: the skill
says so, names that repository, and does not file into ours on its behalf.

Before drafting, the skill searches the target repository for an existing issue. It reads only
the titles, URLs and states of the results, never their bodies. Those bodies are stranger-written
text, and reading them would put that text in the context of the session that holds the reporter's
real data (`req-dev-bugfix-isolation` explains why that combination is the one to avoid).

The search is outbound too: its query reaches GitHub before any consent gate. So the query is built
only from TAP's own vocabulary: the plugin slug when the plugin is ours, an error class or message
template with its values removed, or a model or field name from the published schema. It passes the
tripwire (`req-dev-bugreport-tripwire`) before it is sent. It is shown to the reporter, who can
skip the search altogether.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugreport-route-1 | Possible Vulnerability Goes Private | Proposed | When the reporter answers that the problem might give someone access or capability they should not have, the skill produces no public issue draft and names the private vulnerability reporting URL for the target repository. | |
| req-dev-bugreport-route-2 | Owner From The Boot Record | Proposed | For a failure in an installed plugin, the target repository is the `install.plugins[].source.url` of that plugin in the running instance's boot record, not a name the agent infers. | |
| req-dev-bugreport-route-3 | Third-Party Plugins Are Not Ours To File | Proposed | A source URL outside `unified-systems-com` is reported to the reporter as a third-party repository; the skill does not open an issue in a `unified-systems-com` repository for it. | |
| req-dev-bugreport-route-4 | Duplicate Search Reads Titles Only | Proposed | The duplicate search requests titles, URLs and states and nothing else, so no issue body or comment reaches the session. | |
| req-dev-bugreport-route-5 | The Search Query Is Checked Before It Leaves | Proposed | The duplicate-search query passes the tripwire and is shown to the reporter before it is sent; a query containing a planted instance value is blocked, and the reporter can skip the search. | |

### Synthetic Data, Judged From The Schema
----
RID: `req-dev-bugreport-synthetic`

Status: `Proposed`

The dataset in a report is **generated**, not exported. The skill never attaches an export of the
reporter's graph, including `export_grift` output, a database dump or log excerpts that contain
their values, and never "cleans" one. Redaction of real data is the approach prior art shows
failing. The best secret detectors compared in one 2023 study caught 52–88% of secrets
(arXiv 2307.00714), and the names that leak most are not secret-shaped at all.

The procedure:

1. **Find the shape that fails.** With the reporter, identify which node and edge types, which
   fields and which relationships are involved. The shape is types, field names, cardinalities and
   value *forms*, never values.
2. **Classify every field from its own description.** For each field in the shape, read its
   published schema entry: the `description`, its type and format, and `x-tap-absence` where
   present. Judge whether a real value would identify the reporter, their organisation, their
   infrastructure or a person, or would grant access. Show the reporter the classification as a
   table of field, description quoted, judgement and why, and let them overrule toward *more*
   sensitive, never less. **A field with no description is sensitive.** A missing description is
   a gap in the schema contract, so the skill fails safe and names the field as a gap worth its own
   report.
3. **Generate values.** A sensitive field gets a synthetic value of the same form, drawn from
   ranges reserved for documentation: IPs from RFC 5737, domains under RFC 2606 (`example.com`,
   `.test`, `.invalid`), the AWS account ID `123456789012` from AWS's documentation, and names such
   as `example-org` and `user-1@example.com`. The mapping is consistent, so one real value always
   becomes the same fake value wherever it appears. A bug that depends on two fields matching still
   reproduces, which is what consistent replacement in `sos clean` and Elastic's support bundles
   preserves. A non-sensitive field, such as an enum, a count or a boolean flag, keeps a value of
   its real form when the bug depends on it.
4. **Write it as a GRIFT document.** GRIFT is TAP's interchange format, so a maintainer can load
   the synthetic graph into a fresh instance through the importer
   (`req-grid-import-grift-preflight` validates the whole file before anything is written).
5. **Shrink it.** Remove nodes, edges and fields while the failure persists, so the dataset in the
   report is the smallest that still fails.
6. **Confirm it still fails.** Load the synthetic document into a throwaway project on the
   reporter's install and rerun the steps. A report whose synthetic data does not reproduce is not
   sent as reproducible. It is either sent marked "did not reproduce on synthetic data", with the
   reporter's consent, or reworked.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugreport-synthetic-1 | No Export Leaves | Proposed | The report never contains output of `export_grift`, a database dump, or a log line taken from the reporter's instance without passing the tripwire (`req-dev-bugreport-tripwire`). | |
| req-dev-bugreport-synthetic-2 | Classification Quotes The Schema | Proposed | Every field in the failing shape is shown to the reporter with its published `description` quoted and a sensitive or not-sensitive judgement with a reason. | |
| req-dev-bugreport-synthetic-3 | Undescribed Means Sensitive | Proposed | A field whose schema entry has no `description` is classified sensitive and named as a schema gap. | |
| req-dev-bugreport-synthetic-4 | Reserved Ranges Only | Proposed | Every synthetic IP, domain, AWS account ID and email address falls in the documentation-reserved ranges named above. | |
| req-dev-bugreport-synthetic-5 | Consistent Mapping | Proposed | One real value maps to one synthetic value everywhere in the document, so a relationship between fields is preserved. | |
| req-dev-bugreport-synthetic-6 | Reproduced Before Sending | Proposed | The report states whether the synthetic GRIFT document, loaded into a throwaway project, reproduced the failure, and a report that did not is never labelled reproducible. | |

### Environment Facts From An Allowlist
----
RID: `req-dev-bugreport-environment`

Status: `Proposed`

The environment section is built from a fixed list of sources and nothing else:

- the TAP version and image tag;
- the boot record's plugin list with each plugin's `slug`, `rev` and `commit`, for plugins sourced from `unified-systems-com`. Any other plugin appears only as "third-party plugin" with its `rev`, because its slug and repository may be private;
- the boot profile's `profile_kind`;
- the host OS and architecture;
- the Docker and Compose versions;
- how TAP is being run, from the bug template's existing dropdown;
- `manage.py health` output, after it passes the tripwire.

Anything else is added only by the reporter's explicit request and passes the tripwire like
everything else.

The skill never reads `.env`, `.env.local` or anything under the secrets store to build the report.
The env files are where the instance's hostnames and credentials live, which is why they are
excluded rather than filtered.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugreport-environment-1 | Fixed Source List | Proposed | Every environment fact in a report comes from a source on the list above or from text the reporter explicitly added. | |
| req-dev-bugreport-environment-2 | Env Files And Secrets Are Never Read | Proposed | Building a report reads no `.env*` file and nothing under the secrets store. | |

### The Reporter's Own Values Block The Send
----
RID: `req-dev-bugreport-tripwire`

Status: `Proposed`

Before the preview, the skill builds a **deny list from the reporter's own instance**:

- the values held in the fields classified sensitive in `req-dev-bugreport-synthetic`, read locally and kept local;
- the instance's own hostnames;
- every repository owner and repository name in the boot record's plugin sources outside `unified-systems-com`, plus those plugins' slugs;
- the local username and home path.

The outgoing text is checked against that list, and against `tap/credential_patterns.py`, the
scanner the repository's own guards use. Any hit blocks the send and names the match, with its
line, to the reporter. A clean pass means only that the deny list found nothing, and the skill says
so in exactly those words: it is a tripwire, not a guarantee. The deny list itself is never written
into the report, the repository, or anywhere outside the session.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugreport-tripwire-1 | Planted Value Is Caught | Proposed | A value present in the reporter's instance and planted into the draft blocks the send and is named with its line. | The X3 done-test |
| req-dev-bugreport-tripwire-2 | Planted Credential Is Caught | Proposed | A string matching a `CREDENTIAL_PATTERNS` shape planted into the draft blocks the send. | |
| req-dev-bugreport-tripwire-3 | Clean Is Not Called Safe | Proposed | On a pass, the skill reports "no match against your instance's values" and does not call the report safe. | |
| req-dev-bugreport-tripwire-4 | Private Plugin Names Are Caught | Proposed | A third-party plugin's slug or repository name, planted into the draft or the environment section, blocks the send. | |

### Exact Bytes, Explicit Yes, Fail Closed
----
RID: `req-dev-bugreport-consent`

Status: `Proposed`

The report is written to a local file, and that file is what gets sent. The skill shows the
reporter:

- the file's path;
- its full contents;
- the target repository by name, with the words "public" and "permanent";
- the list of what was replaced with synthetic values.

It asks for a typed yes. The yes is bound to a hash of that file's contents. Any change, by the
reporter or the agent, produces a new preview and needs a new yes.

The send is `gh issue create --body-file <file>`. If it fails for any reason, the skill stops and
reports the failure verbatim. It does not retry with another method, re-quote the body, split it,
or post it some other way. Improvising after a failed post is how an agent once posted internal
documents as PR comments (anthropics/claude-code-action#957). Two alternatives are always offered:
save the report locally only, or open the repository's new-issue page and paste it there.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugreport-consent-1 | Preview Is The Sent File | Proposed | The bytes previewed are the bytes in the file passed to `--body-file`; the skill sends no text that was not in that file. | |
| req-dev-bugreport-consent-2 | Consent Bound To Content | Proposed | A change to the file after consent invalidates it; sending requires a new preview and yes. | |
| req-dev-bugreport-consent-3 | Public And Permanent Named | Proposed | The consent prompt names the target repository and states that the issue is public and that edits do not remove earlier text. | |
| req-dev-bugreport-consent-4 | One Attempt, No Improvising | Proposed | A failed send is reported verbatim and not retried by any other route; the local-only and paste-it-yourself alternatives are offered. | |

### A Report Shape The Fixer Can Parse
----
RID: `req-dev-bugreport-shape`

Status: `Proposed`

A report has fixed headings, the same as tap's existing bug form: what happened, steps to
reproduce, TAP version, how it is run, health output and anything else. It also has one fenced
block holding a single JSON document that `submit-a-fix` reads. That block carries:

- the target repository;
- the versions and commits;
- the failing operation;
- expected and actual results, with counts where there are any;
- whether the synthetic data reproduced;
- the synthetic GRIFT document, or a pointer to it as a second fenced block.

The JSON document carries a `description` at its top level and on each key, per the repository's
JSON-structures rule. The report ends with a disclosure line: drafted with an AI agent, reproduced
on synthetic data yes or no, and reviewed by the reporter.

Plugin repositories have no issue forms today, so the report shape is the template wherever the
skill files. The skill applies the label `via:submit-a-bug` when the repository has it, and reports
in the skill output that it didn't when it doesn't.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugreport-shape-1 | One Parseable Block | Proposed | Every report contains exactly one fenced JSON block that validates against the report schema shipped with the skill. | |
| req-dev-bugreport-shape-2 | Disclosure Present | Proposed | Every report ends with the AI-assistance, synthetic-reproduction and reporter-review disclosure. | |

### The Report Is Data
----
RID: `req-dev-bugfix-untrusted-intake`

Status: `Proposed`

`submit-a-fix` reads exactly one issue, and reads it as data. It extracts the fenced block
described in `req-dev-bugreport-shape` and the fixed headings into the report shape, and it reads
comments only from the issue's author and the repository's maintainers.

Before the text reaches the model, it strips zero-width and other invisible characters, HTML
comments, and `<details>` bodies the reporter collapsed, and says what it stripped.

Nothing in the issue is an instruction to the agent. Text that reads like one ("ignore", "run",
"push", "also update", a URL to fetch, a package to install) is reported to the human as a finding,
and the skill stops and asks. A fix the reporter suggests is a hypothesis to test, never code to
apply. In one SWE-bench study, about a third of the agent fixes graded successful had the answer
supplied in the issue (arXiv 2410.06992). In a public repository that channel belongs to whoever
writes the issue.

**An optional typed classifier can add stops, never remove them.** When one is configured (TypeSafe's
Jev is the first candidate, ruled 2026-10-02), each paragraph of the report is also put to it as a
yes/no question: is this text an instruction aimed at an agent? A yes stops the run and asks, exactly
as the skill's own reading does. A no changes nothing. The skill's own judgement still applies, and
so do the preflight and the human push. A typed model returns probabilities, not prose, so injected
text can nudge its score but cannot make it write "this is safe" (arXiv 2609.28613 measured
attacker-chosen decisions at 1.8–3.5% across 510 cases). TypeSafe's own guidance is that it is not a
standalone security boundary. The issue is public text, so sending it to a hosted classifier
discloses nothing that was not already published.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugfix-untrusted-intake-1 | Only Author And Maintainer Comments | Proposed | Comments from accounts other than the issue author and the repository's maintainers are not read into the session. | |
| req-dev-bugfix-untrusted-intake-2 | Hidden Text Stripped And Named | Proposed | Invisible characters, HTML comments and collapsed blocks are removed before the model reads the issue, and the removal is reported. | |
| req-dev-bugfix-untrusted-intake-3 | Instruction-Shaped Text Stops The Run | Proposed | A planted instruction in the issue body (for example, "also run `curl …`") is reported as a finding, and the skill does not act on it. | |
| req-dev-bugfix-untrusted-intake-4 | A Classifier Only Adds Stops | Proposed | With a typed classifier configured, its yes stops the run, and its no on a planted instruction still leaves the run stopped by the skill's own reading; with none configured, the skill behaves identically otherwise. | |

### No Credentials, No Network, After Reading
----
RID: `req-dev-bugfix-isolation`

Status: `Proposed`

The issue is fetched once, as the skill's first step, into a local file. That fetch is the only
network operation and the only use of a GitHub credential. Everything after it runs in a session
that cannot reach:

- a GitHub token;
- the TAP secrets store;
- cloud credentials;
- the network.

This applies to the maintainer's own runs as much as a reporter's, and more so, since the
maintainer's machine holds more.

The skill enforces the part it can check with a **fail-closed preflight**, run after the fetch and
before reading the file. The preflight refuses to continue if:

- `gh auth status` succeeds;
- any `GH_TOKEN`, `GITHUB_TOKEN` or `AWS_*` credential variable is set;
- the secrets store is readable;
- any of three egress probes succeeds: an HTTPS request to `github.com`, a TCP connection to a public IP address with no name lookup, and a DNS resolution of a name nobody controls.

It names which check failed, and does not offer to skip it. Probing only GitHub would prove only
that GitHub is blocked. The three probes test the claim the skill needs, deny-all egress, from
three directions: an allowlisted host, an address with no name, and DNS, the channel sandboxes
most often leave open.

**Deny-all egress is a precondition, not a hope.** The skill does not supply it; the environment it
runs in does, through an agent sandbox. Which sandbox is a separate decision. Until one is chosen,
the preflight's refusal is what holds the line: a session that can reach the network cannot run
this skill past the fetch.

Running the reproduction needs a TAP stack. The skill uses a fresh, throwaway stack, never the
reporter's or the maintainer's working instance, loaded only with the report's synthetic GRIFT
document.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugfix-isolation-1 | Preflight Refuses A Credentialed Session | Proposed | With `gh` authenticated, a token or AWS credential in the environment, or the secrets store readable, the skill stops after the fetch and names the failing check. | |
| req-dev-bugfix-isolation-4 | Preflight Refuses Any Egress | Proposed | With `github.com` blocked but a non-GitHub host, a bare IP or DNS still reachable, the skill stops and names which probe succeeded. | |
| req-dev-bugfix-isolation-2 | One Fetch | Proposed | The skill performs exactly one network operation, the issue fetch, before the preflight, and none after. | |
| req-dev-bugfix-isolation-3 | Throwaway Stack Only | Proposed | Reproduction runs in a stack created for the run and loaded only with the report's synthetic data. | |

### Reproduce Twice Before Fixing
----
RID: `req-dev-bugfix-reproduce`

Status: `Proposed`

Before any change to code, the skill writes a test that encodes the report's expected-versus-actual
and runs it twice:

- at the reporter's versions, the `commit`s their report names;
- at `main`.

There are four outcomes, and three are exits rather than failures:

| Reporter's version | `main` | Outcome |
| --- | --- | --- |
| fails | fails | Proceed to a fix |
| fails | passes | **Already fixed on main**: name the commit if it can be found, and stop |
| passes | — | **Cannot reproduce**: report what was run, and stop |
| no test can be written from the report | — | **Underspecified**: name the missing fact, and stop |

This is the procedure every serious issue-fixing agent converged on. SWE-agent's default
procedure writes a reproduction script first. Agentless keeps only tests that fail on the
unchanged code. Filtering fixes through a generated reproduction test doubled precision in
arXiv 2406.12952.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugfix-reproduce-1 | Test Before Code | Proposed | No source change is made before a test exists that encodes the report's expected-versus-actual. | |
| req-dev-bugfix-reproduce-2 | Two Baselines | Proposed | The test is run at the reporter's named commits and at `main`, and both results are recorded. | |
| req-dev-bugfix-reproduce-3 | Exits Are Named | Proposed | Already-fixed, cannot-reproduce and underspecified each end the run with that name and the evidence for it. | The X3 done-test is the proceed outcome on a real report |

### A Human Pushes
----
RID: `req-dev-bugfix-handback`

Status: `Proposed`

The skill proposes a plan and waits for the human before changing code. It keeps the diff small,
and the reproduction test lands with the fix. It hands back:

- a local branch;
- the test failing before the fix and passing after, as command output;
- the result of the repository's own lane (`scripts/test` for tap; the plugin's CI command for a plugin);
- a draft PR body.

The PR body carries:

- the linked-issue trailer (`Closes: <owner>/<repo>#<n>`);
- a conventional title;
- an `Assisted-by:` line naming the agent;
- a "what I did not verify" section.

It never pushes, opens a pull request or comments on the issue, and it never writes a
`Signed-off-by`. The sign-off and the push are the human's, after their own review. That is what
`CONTRIBUTING.md` already requires of every contribution, and it is the gate that every issue-to-PR
product, from GitHub Copilot to OpenHands, keeps in front of the merge. A reporter pushes from their
own fork. A maintainer pushes a branch.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugfix-handback-1 | Plan Before Code | Proposed | The skill presents its plan and waits for the human's go before editing source. | |
| req-dev-bugfix-handback-2 | Before And After Evidence | Proposed | The hand-back includes the reproduction test's failing output without the fix and passing output with it. | |
| req-dev-bugfix-handback-3 | Never Pushes Or Signs | Proposed | The skill performs no `git push`, no `gh pr create`, no issue comment, and writes no `Signed-off-by`. | |

## Development

Prior art was surveyed on 2026-10-02 (tap#927), in two passes with each claim labelled as fetched,
search-only or inferred.

- **Bug reporters:**
  - Docker Desktop and Claude Code's `/feedback`: a private channel for the payload, with only an ID in the public issue.
  - `sos clean` and Elastic's support diagnostics: consistent value replacement.
  - npm's `bugs` field and VS Code's extension routing: the component declares where its bugs go.
  - reprex and pytest's contributing guide: minimal reproduction, ideally as a failing test.
  - Firefox's crash reporter: nothing sent automatically.
- **Fixing agents:**
  - SWE-agent, Agentless, OpenHands, the GitHub Copilot coding agent, Jules and the Claude Code GitHub Action.
  - The SWE-bench critiques: solution leakage, and weak tests that pass wrong fixes.
  - AI-contribution policies, including the Linux kernel's `Assisted-by:` trailer and Fedora's rule that AI never makes the final accept decision.
- **Injection incidents:**
  - Invariant Labs' GitHub MCP toxic-agent flow, Clinejection, and the Amazon Q extension.
  - The mitigations in use: quarantined extraction, author-only comment reading, no egress, and a human gate.

Two rulings shaped the design (George, 2026-10-02). First, there is no private upload channel:
reports are public issues built from synthetic data, and security bugs go to private vulnerability
reporting. Second, the human stays in the loop: the fix skill never pushes.

The schema-driven classification is the design's distinguishing feature. It exists because TAP
mandates field descriptions, and George pointed out that a generic reporter has to guess where TAP
can read.

## Future

- **`review-a-fix`**, the third skill. It must treat the diff itself as untrusted, because the Amazon Q extension compromise arrived through a merged pull request, and it must never be the merge decision.
- **Issue forms for plugin repositories**, generated once for the fleet. Today none of the 24 has one, and neither does the org `.github` repository.
- **A gitleaks pass on new issue bodies**, as an Action, for the reports that do not come through the skill.
- **A session-wide injection hook** (a `PreToolUse`/`PostToolUse` classifier on everything a session reads), ruled 2026-10-02 to wait until a locally run model is evaluated (for example, the open-weights AgentJev-0.6B). A hosted classifier would send private session content to a third party.
- **Agent sandboxes beyond this skill.** Every session that reads issue or PR text has the same exposure `req-dev-bugfix-isolation` closes for one skill.
