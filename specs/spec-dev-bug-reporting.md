# Bug Reporting And Fix Proposals From Outside — `submit-a-bug` And `submit-a-fix`

## Philosophy

People now run TAP who have never spoken to us: they found the repository, booted it, customised it
and kept going. When something breaks for them, the report they can write without help is a
paragraph and a stack trace. The report we need to fix it is a diagnosis: which component, which
code path, what the failing shape looks like, and a scenario that triggers it. This spec makes the
difference between the two the job of the agent already running in their install, with two repo
skills: **`submit-a-bug`** investigates and files; **`submit-a-fix`** reads a report and works toward
a fix. A third skill, `review-a-fix`, is deliberately not in this spec.

Three facts shape everything below.

**The agent in the install already has what it needs to find out what is going on.** TAP carries its
own context: specs with requirement IDs, traceability from each requirement to the code that claims
it, skills for every routine job, a boot record naming every installed component and its commit,
structured logs, and a grid that can be read with Gryphon. An agent working in a session uses all of
that today to diagnose a failure, without being told how. So `submit-a-bug` does not interview the
reporter and it does not forbid the agent from looking. The reporter describes the behaviour; the
agent does what it would do for any failure (reads the code, the logs, the boot record, the specs
and our existing issues, queries the grid), reaches a root cause or a set of theories, invents a
scenario that should trigger it, and writes the report. The skill is **light guardrails**, not a
procedure: what the agent must not do to the running instance while it looks, and what must not
leave the instance in what it files. Ruled by George, 2026-11-11, replacing the version-0 design
(a reporter interview with no instance reads, ruled 2026-10-25) as dead on arrival.

**The reporter's data is sensitive, and the destination is public.** TAP is pointed at cloud
accounts, identity providers and source forges. A report drafted from the reporter's real graph
carries their account IDs, hostnames, org and repository names, and email addresses. It would
publish them to a public tracker where an edit does not remove them, because GitHub keeps a public
edit history for issue bodies and comments. Nothing on GitHub blocks that send: push protection
does not cover issue bodies, and secret scanning alerts only after the fact. The documented failure
is not a leaked token but leaked *names* (anthropics/claude-code#29121, where an agent drafted a
public bug report full of a user's private org names, repository URLs and paths). The same holds
for the shape of their build: which plugins they run, at which versions, on which platform, is
information about their system that a public issue has no business carrying. So the agent reads
freely and locally, and the report carries **shapes, reasoning and invented data**, plus the version
of the one component that has the bug. The reporter consents to the exact bytes before anything is
sent, and a tripwire built from the instance's own values stands in front of the send.

**A bug report is text a stranger wrote, and the fixing agent will read it.** Any agent that reads
untrusted text, holds credentials and can reach the network can be steered into leaking what those
credentials reach (Simon Willison's "lethal trifecta"). Agents have been: a malicious public issue
made an agent with GitHub access leak private-repository data into a public pull request (Invariant
Labs, 2025), and an injected issue title in Cline's triage workflow led to stolen publish tokens and
a malicious release ("Clinejection"). Filtering clever text is best effort, even by its vendors'
own account. What holds is structure: once `submit-a-fix` has read a report, it holds no
credentials and has no network, and a human pushes whatever it produced. The same discipline
applies the moment `submit-a-bug` reads one of our existing issues during its investigation.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | The Reporter Describes, The Agent Diagnoses | The only input a reporter must give is a description of the behaviour in their own words; the agent gathers everything else. |
| 2. | Looking Changes Nothing | The investigation reads the running instance and leaves it exactly as it found it. |
| 3. | Reports Carry A Diagnosis | A report names the component, the code path and a root cause with its evidence, or ranked theories each with the evidence for it, plus an invented scenario and sample data a maintainer can start from. |
| 4. | Nothing From The Instance Leaves | A report carries no value read from the instance and nothing about the reporter's build beyond the version of the component that has the bug; what is sent is shown byte for byte and sent only on an explicit yes to that exact content. |
| 5. | Reports Reach The Right Place | A bug lands in the repository that owns the failing code, and a vulnerability never lands in a public issue. |
| 6. | Fixes Start From A Failing Test | A proposed fix exists only alongside a test that fails without it and passes with it, on the reporter's version and on `main`. |
| 7. | Stranger-Written Text Never Steers The Agent | Whatever an issue says, the agent reading it cannot be made to send data anywhere, run what the issue names, or push anything. |

## Version 1

Version 1 replaces version 0 in full (George, 2026-11-11). The rulings:

- the reporter's description is the input, and the agent's own investigation is the method: code,
  logs, configuration, the boot record, specs, our existing issue reports, and the grid, read-only;
- the agent reports a root cause where it finds one, otherwise its theories, each with the method
  behind the evidence named;
- the report carries a scenario and sample data the agent invented that could trigger the failure;
- the report is machine-parseable and holds no sensitive information from the running instance;
- the TAP version is reported only when the bug is in core, and a plugin's version only when the bug
  is in that plugin; anything else about the build is disclosure and stays home.

What version 0 had and version 1 drops: the step-by-step reporter interview, hand-written answers,
the environment allowlist (host OS, Docker and Compose versions, every plugin's version), the rule
that the skill reads no instance data, the reporter re-running the failure as the evidence, and
schema-driven field classification. What carries over unchanged: the private route for anything that
might be a vulnerability, the owning-repository rule, the tripwire, the hash-bound consent, the single
send attempt, the one-JSON-block report shape, and every `submit-a-fix` requirement.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-dev-bugreport-route | [Security First, Then The Owning Repository](#security-first-then-the-owning-repository) | Proposed | The agent answers the security question with evidence and a "might be" goes private; otherwise the report goes to the repository the boot record names as the failing component's source |
| req-dev-bugreport-investigate | [Read Everything, Change Nothing](#read-everything-change-nothing) | Proposed | The agent investigates with every local source it has, read-only; the running instance is left as it was found |
| req-dev-bugreport-conclude | [A Root Cause Or Named Theories](#a-root-cause-or-named-theories) | Proposed | The report states a root cause with its evidence, or ranked theories each with its evidence, and names the method behind every claim |
| req-dev-bugreport-scenario | [An Invented Scenario And Sample Data](#an-invented-scenario-and-sample-data) | Proposed | A reproduction scenario and sample data the agent made up to the failing shape, in reserved ranges, never copied from the instance |
| req-dev-bugreport-disclosure | [Only The Buggy Component's Version Leaves](#only-the-buggy-components-version-leaves) | Proposed | The report names one component and its version; nothing else about the build, and no value, log line or row from the instance |
| req-dev-bugreport-tripwire | [The Instance's Own Values Block The Send](#the-instances-own-values-block-the-send) | Proposed | The instance's identifiers, every other component's version, the values the agent observed while investigating, and any credential shape in the outgoing text stop the send |
| req-dev-bugreport-consent | [Exact Bytes, Explicit Yes, Fail Closed](#exact-bytes-explicit-yes-fail-closed) | Proposed | Preview the exact file, name the repository as public and permanent, take a yes bound to that content, and never improvise on a failed send |
| req-dev-bugreport-shape | [A Report Shape The Fixer Can Parse](#a-report-shape-the-fixer-can-parse) | Proposed | Fixed headings plus one machine-readable block carrying the diagnosis, the scenario and the sample data; an AI-assistance disclosure |
| req-dev-bugfix-untrusted-intake | [The Report Is Data](#the-report-is-data) | Proposed | Extract into the report shape; read only the reporter's and maintainers' comments; nothing in it is an instruction |
| req-dev-bugfix-ownreports | [Until The Sandbox, Only Our Own Reports](#until-the-sandbox-only-our-own-reports) | Proposed | `submit-a-fix` reads an issue only when a maintainer session account wrote it, by account identity; the gate lifts when the sandbox is enabled, never by a flag |
| req-dev-bugfix-isolation | [No Credentials, No Network, After Reading](#no-credentials-no-network-after-reading) | Proposed | Runs only inside a named deny-all sandbox, on commits reachable from our own refs, in a confined throwaway stack; a fail-closed preflight refuses a credentialed or networked session |
| req-dev-bugfix-reproduce | [Reproduce Twice Before Fixing](#reproduce-twice-before-fixing) | Proposed | A failing test on the reporter's version and on `main`, starting from the report's scenario, or one of three named exits |
| req-dev-bugfix-handback | [A Human Pushes](#a-human-pushes) | Proposed | A local branch, before and after evidence, and a draft PR body; the skill never pushes, opens a PR, or signs off |

### Security First, Then The Owning Repository
----
RID: `req-dev-bugreport-route`

Status: `Proposed`

The first thing `submit-a-bug` settles is whether the problem lets someone do something they should
not: read data they shouldn't, act as someone else, or get past a check. The agent answers that
itself, from what the reporter described and what its investigation finds, and shows the reporter
its answer with the reasoning. If the answer is yes, or might be, the skill stops drafting a public
issue. It directs the reporter to the repository's private vulnerability reporting, and to
`SECURITY.md`, whose existing rules for AI-assisted reports (a runnable proof, and a preamble in the
reporter's own words) apply unchanged. The skill does not judge severity. "Might be" is enough to go
private, because a vulnerability published as a public issue cannot be unpublished. The reporter can
overrule toward private, never toward public.

Otherwise the report goes to the repository that owns the failing code. The owner is read from the
install, not guessed. The boot record names every installed plugin's source as
`install.plugins[].source.url`, with the `rev` and `commit` it was installed at. A failure inside a
plugin goes to that URL. A failure in core goes to `unified-systems-com/tap`. A failure the
investigation cannot attribute also goes to tap, which is what tap's issue-template `config.yml`
already tells people, and the report says that attribution is open. A source URL outside
`unified-systems-com` is a third-party plugin: the skill says so, names that repository, and does not
file into ours on its behalf.

Our existing issues and pull requests are part of the investigation (`req-dev-bugreport-investigate`),
so the duplicate search is no longer a separate titles-only step: the agent has read what is already
filed in the target repository and says in the report which issues it considers related and why. What
remains outbound before consent is the search query itself, so it is built only from TAP's own
vocabulary (a plugin slug that is ours, an error class or message template with its values removed, a
model or field name from the published schema) and passes the tripwire before it leaves.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugreport-route-1 | Possible Vulnerability Goes Private | Proposed | When the agent's answer to the security question is yes or might be, the skill produces no public issue draft and names the private vulnerability reporting URL for the target repository. | |
| req-dev-bugreport-route-2 | Owner From The Boot Record | Proposed | For a failure in an installed plugin, the target repository is the `install.plugins[].source.url` of that plugin in the running instance's boot record, not a name the agent infers. | |
| req-dev-bugreport-route-3 | Third-Party Plugins Are Not Ours To File | Proposed | A source URL outside `unified-systems-com` is reported to the reporter as a third-party repository; the skill does not open an issue in a `unified-systems-com` repository for it. | |
| req-dev-bugreport-route-4 | The Search Query Is Checked Before It Leaves | Proposed | The issue-search query passes the tripwire before it is sent; a query containing a planted instance value is blocked. | |
| req-dev-bugreport-route-5 | Related Issues Are Named | Proposed | The report lists the existing issues the agent judged related, by number, with one line each on why. | |

### Read Everything, Change Nothing
----
RID: `req-dev-bugreport-investigate`

Status: `Proposed`

The investigation is the agent's own, and it uses every local source it has:

- the code of core and of every installed plugin, at the commits the boot record names;
- the structured logs of the web, worker and database containers;
- the boot record and the resolved configuration, read for which components are installed and how
  they are wired, never for credentials (the secrets store and `.env*` files are not read);
- the specs, their requirement IDs and the traceability fragments that point from a requirement to
  the code claiming it;
- the grid, through Gryphon or the ORM's read surface, for the rows and edges the failure involves;
- our existing issues and pull requests in the target repository and its dependencies, read as data
  under the same rules `submit-a-fix` applies to a report (`req-dev-bugfix-untrusted-intake`): hidden
  text stripped, instruction-shaped text reported and never acted on, a suggested fix a hypothesis.

It does not change the running instance. No grid write, no migration, no restart, no collector run,
no settings change, no `pytest` against the live stack, and nothing that would alter what the
reporter sees afterwards. Reproducing the failure is allowed where it costs the instance nothing: a
read-only query that returns the wrong rows is a reproduction; so is a unit test run in a throwaway
checkout that never touches the instance's database. Anything heavier is described in the report as
a scenario (`req-dev-bugreport-scenario`) for the fixing side to run.

Everything the agent reads stays in the session. Values it saw (identifiers, names, addresses, tag
values, hostnames, log fields) are recorded to the tripwire's observed-values file as it goes
(`req-dev-bugreport-tripwire`), so that none of them can be written into the report by accident
later.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugreport-investigate-1 | Nothing Written | Proposed | The investigation performs no grid write, migration, restart, collector run, settings change or live-stack test run; the instance's state after the skill equals its state before. | |
| req-dev-bugreport-investigate-2 | Secrets Not Read | Proposed | Building a report reads no `.env*` file and nothing under the secrets store. | |
| req-dev-bugreport-investigate-3 | Issues Read As Data | Proposed | An existing issue read during investigation has hidden text stripped and, when any line reads as an instruction, the text is withheld and only the findings (line, rule, excerpt) are handed over, so the body never reaches the agent as something to act on; the unsanitised body is never written to disk. | The body goes straight from `gh` into the intake; the excerpts are what the human judges |
| req-dev-bugreport-investigate-4 | Observed Values Recorded | Proposed | Every literal value the agent read from the instance during investigation is appended to the observed-values file before the report is rendered. | The honest gap: a value the agent read and did not record is caught only by the reporter's preview |

### A Root Cause Or Named Theories
----
RID: `req-dev-bugreport-conclude`

Status: `Proposed`

The investigation ends in one of two states, and the report says which:

- **a root cause**: the component, the code path (file and line at the named commit), what the code
  does, what it should do, and the evidence that this is the cause;
- **theories**: two or more candidate causes, ranked, each with the evidence for and against it and
  what would settle it.

Every claim names the method behind it: *read* (a file and line), *ran* (a command and its output,
with values removed), or *inferred* (from what). A report that says "the collector drops the row"
without saying how the agent knows is not finished. Where the agent could not observe something it
would have liked to, the report says so under a "not observed" heading rather than guessing.

The report also names where a fix would go, as a file path and a one-line description, when the
agent has a view. That is a pointer for the fixing side, not code: `submit-a-fix` treats any suggested
fix as a hypothesis to test.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugreport-conclude-1 | One Of Two States | Proposed | The report's parseable block declares either one root cause or a ranked list of at least two theories, never neither and never both. | |
| req-dev-bugreport-conclude-2 | Method Named | Proposed | Every evidence entry carries a method of `read`, `ran` or `inferred` and the file, command or premise it rests on. | |
| req-dev-bugreport-conclude-3 | Not Observed Is Stated | Proposed | The report has a "not observed" section, empty or not, and a theory whose evidence is absent says so there rather than presenting the theory as established. | |

### An Invented Scenario And Sample Data
----
RID: `req-dev-bugreport-scenario`

Status: `Proposed`

A report carries a scenario in which the failure comes up and sample data that should trigger it.
Both are **invented** by the agent to the failing shape (the node and edge types, fields,
cardinalities and value forms the investigation found), never exported from the instance and never
"cleaned" from it. Redaction of real data is the approach prior art shows failing: the best secret
detectors compared in one 2023 study caught 52–88% of secrets (arXiv 2307.00714), and the names that
leak most are not secret-shaped at all.

Sample values come from ranges reserved for documentation: IPs from RFC 5737, domains under RFC 2606
(`example.com`, `.test`, `.invalid`), the AWS account ID `123456789012` from AWS's documentation,
and names such as `example-org` and `user-1@example.com`. Where a bug depends on two fields matching,
the invented values match the same way. Where the shape is grid data, the sample is a GRIFT document,
so the fixing side can load it into a fresh instance through the importer
(`req-grid-import-grift-preflight` validates the whole file before anything is written). Where the
shape is an input, a request or a configuration, the sample is that input with invented values.

The report states whether the agent tried the scenario and what happened, and it tries only where
trying leaves the instance untouched (`req-dev-bugreport-investigate`). A scenario the agent did not
try is sent as untried, in those words; it is never labelled reproduced.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugreport-scenario-1 | Scenario Present | Proposed | Every report's parseable block carries a scenario (steps) and sample data of the failing shape, or states in a fixed field why no sample data applies. | |
| req-dev-bugreport-scenario-2 | Reserved Ranges Only | Proposed | Every IP, domain, AWS account ID and email address in the sample data falls in the documentation-reserved ranges named above; the render step refuses one that does not. | |
| req-dev-bugreport-scenario-3 | Tried Or Untried, Said | Proposed | The report states whether the scenario was tried and the result, and a scenario that was not tried is never labelled reproduced. | |

### Only The Buggy Component's Version Leaves
----
RID: `req-dev-bugreport-disclosure`

Status: `Proposed`

A report names **one** component as the one with the bug, and that component's version:

- for core, the TAP version (and the commit, when run from a checkout);
- for a plugin that is ours, its slug, `rev` and `commit` from the boot record.

Nothing else about the build is in the report. Not the other plugins installed, their versions or
their count; not the boot profile; not the host OS, architecture, Docker or Compose versions; not how
TAP is run. Each of those says something about the reporter's system that the public tracker has no
need of, and together they describe the build. When the agent's evidence genuinely rests on one of
them (a failure that only happens on one platform, an interaction with a second plugin), the report
may name that one fact, the reasoning that needs it sits beside it, and the reporter sees it in the
preview like everything else.

No value from the instance is in the report: no log line verbatim, no row, no identifier, no
hostname, no path under the reporter's home. A log line's *template* (the message with its values
removed) and a row's *shape* are what the report carries. The only instance-generated text allowed is
the output of a command the agent ran as evidence, with its values removed, and it passes the tripwire
like everything else. The tripwire is a detector, not a licence.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugreport-disclosure-1 | One Component, One Version | Proposed | The parseable block names exactly one component and its version, and the render step refuses a block that names a version for any other component. | |
| req-dev-bugreport-disclosure-2 | No Build Facts By Default | Proposed | A report contains no boot profile, host OS, architecture, Docker or Compose version unless the block carries that fact beside a stated reason it is evidence. | |
| req-dev-bugreport-disclosure-3 | No Instance Text | Proposed | The report contains no log line, row, dump or export from the instance; command output present as evidence has its values removed and passes the tripwire. | |

### The Instance's Own Values Block The Send
----
RID: `req-dev-bugreport-tripwire`

Status: `Proposed`

Before the preview, the skill builds a **deny list from the reporter's own instance**:

- the instance's own hostnames;
- the local username and home path;
- every installed plugin's `rev` and `commit`, except the one component the report names, and for
  plugins sourced outside `unified-systems-com` also every repository owner, repository name and
  slug;
- every value in the **observed-values file**, which the agent appends to as it investigates
  (`req-dev-bugreport-investigate`): identifiers, names, addresses, email addresses, URLs, tag
  values, hostnames and log fields it read from the instance.

The outgoing text, and the search query, are checked against that list and against
`tap/credential_patterns.py`, the scanner the repository's own guards use. Any hit blocks the send
and names the match, with its line, to the reporter. A clean pass means only that the deny list
found nothing, and the skill says so in exactly those words: it is a tripwire, not a guarantee. The
deny list and the observed-values file are never written into the report, the repository, or
anywhere outside the session, and they are deleted when the skill ends.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugreport-tripwire-1 | Planted Value Is Caught | Proposed | A value on the deny list (an instance hostname, the local username or home path, a third-party plugin's name) planted into the draft blocks the send and is named with its line. | |
| req-dev-bugreport-tripwire-2 | Planted Credential Is Caught | Proposed | A string matching a `CREDENTIAL_PATTERNS` shape planted into the draft blocks the send. | |
| req-dev-bugreport-tripwire-3 | Clean Is Not Called Safe | Proposed | On a pass, the skill reports "no match against your instance's values" and does not call the report safe. | |
| req-dev-bugreport-tripwire-4 | Other Components' Versions Are Caught | Proposed | The `rev` or `commit` of any installed plugin other than the named component, planted into the draft, blocks the send. | |
| req-dev-bugreport-tripwire-5 | Observed Values Are Caught | Proposed | A value appended to the observed-values file during investigation, planted into the draft, blocks the send. | |
| req-dev-bugreport-tripwire-6 | Nothing Local Leaves | Proposed | Neither the deny list nor the observed-values file appears in the report or in any file outside `.bug-reports/`, and both are removed when the skill ends. | |

### Exact Bytes, Explicit Yes, Fail Closed
----
RID: `req-dev-bugreport-consent`

Status: `Proposed`

The report is written to a local file, and that file is what gets sent. The skill shows the
reporter:

- the file's path;
- its full contents;
- the target repository by name, with the words "public" and "permanent";
- the one component and version the report discloses, and any build fact carried as evidence.

It asks for a typed yes. The yes is bound to a hash of that file's contents. Any change, by the
reporter or the agent, produces a new preview and needs a new yes. This is the reporter's one job
besides describing the bug, and the skill says so: the agent wrote the report, the reporter is the
one who knows what in it would identify them.

**The yes is the reporter's act, so the mechanism makes it one the agent cannot perform.** The
phrase is deterministic and the agent sees it in the preview, so a consent command that accepted
the phrase as an argument would let the agent preview, copy, consent and send on its own. Instead
the consent command runs on the host, takes the phrase only from a terminal (input that is a pipe,
a file or an agent's shell is refused, and nothing is recorded), and writes the record outside the
worktree, in a directory the container cannot see and the agent's granted tools cannot write. The
send checks for a record naming exactly the bytes about to go. With `scripts/dc exec` granted for
investigation, no in-process gate is unforgeable by an agent that sets out to forge it; this one
removes the direct route and leaves the skill's rule, which the agent does not run `consent`, as
the remainder.

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
| req-dev-bugreport-consent-5 | Typed At A Terminal, Recorded Outside The Worktree | Proposed | The consent command refuses input that is not a terminal and takes no phrase as an argument; a yes typed at a terminal is recorded outside the worktree, and the send refuses a file with no record for exactly its bytes. | The agent sees the phrase and still cannot record it |
| req-dev-bugreport-consent-6 | Send Re-Runs What Render Checks | Proposed | A report whose block carries what render refuses (a security answer other than no, a conclusion that is not one of its two states, sample data outside the reserved ranges) is refused at check, preview and send, so a block edited after rendering cannot reach GitHub. | |
| req-dev-bugreport-consent-7 | One Yes, One Send, From A Snapshot | Proposed | The send copies the verified bytes outside the worktree, re-hashes the copies against the manifest the verification produced, sends from the copies, and spends the consent record whether the send succeeds or fails; a file that changed between verification and the copy, or a second send on the same yes, is refused. | Closes the file-change race and the reuse of one yes |

### A Report Shape The Fixer Can Parse
----
RID: `req-dev-bugreport-shape`

Status: `Proposed`

A report has fixed headings and one fenced block holding a single JSON document that validates
against the report schema shipped with the skill, which both skills read and write through. The
block carries:

- the target repository;
- the one component and its version;
- the reporter's description, in their words;
- the security answer and its reasoning;
- the findings: each with its method (`read`, `ran`, `inferred`), its location and what it shows;
- the conclusion: a root cause, or ranked theories, as `req-dev-bugreport-conclude` describes;
- the scenario and the sample data, and whether the scenario was tried;
- what was not observed;
- related issues, by number;
- a suggested fix location, when there is one;
- any build fact carried as evidence, beside its reason.

The JSON document carries a `description` at its top level and on each key, per the repository's
JSON-structures rule. The headings are rendered from the block, so a human reads the same facts the
fixer parses. The report ends with a disclosure line: drafted by an AI agent from its own
investigation, scenario tried yes or no, and reviewed by the reporter.

Plugin repositories have no issue forms today, so the report shape is the template wherever the
skill files. The skill applies the label `via:submit-a-bug` when the repository has it, and reports
in the skill output that it didn't when it doesn't.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugreport-shape-1 | One Parseable Block | Proposed | Every report contains exactly one fenced JSON block that validates against the report schema shipped with the skill. | |
| req-dev-bugreport-shape-2 | Disclosure Present | Proposed | Every report ends with the AI-investigation, scenario-tried and reporter-review disclosure. | |
| req-dev-bugreport-shape-3 | One Schema For Both Skills | Proposed | `submit-a-bug` writes and `submit-a-fix` reads the report through one schema file, and a round-trip test builds a report from the writer and extracts it with the reader. | |

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
and the skill stops and asks. A fix the reporter suggests, including the report's own suggested fix
location, is a hypothesis to test, never code to apply. In one SWE-bench study, about a third of the
agent fixes graded successful had the answer supplied in the issue (arXiv 2410.06992). In a public
repository that channel belongs to whoever writes the issue.

**An optional typed classifier can add stops, never remove them.** When one is configured (TypeSafe's
Jev is the first candidate, ruled 2026-10-02), each paragraph of the report is also put to it as a
yes/no question: is this text an instruction aimed at an agent? A yes stops the run and asks, exactly
as the skill's own reading does. A no changes nothing. The skill's own judgement still applies, and
so do the preflight and the human push. A typed model returns probabilities, not prose, so injected
text can nudge its score but cannot make it write "this is safe" (arXiv 2609.28613 measured
attacker-chosen decisions at 1.8–3.5% across 510 cases). TypeSafe's own guidance is that it is not a
standalone security boundary. The issue is public text, so sending it to a hosted classifier
discloses nothing that was not already published.

The same intake applies when `submit-a-bug` reads an existing issue during its investigation
(`req-dev-bugreport-investigate`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugfix-untrusted-intake-1 | Only Author And Maintainer Comments | Proposed | Comments from accounts other than the issue author and the repository's maintainers are not read into the session; the comments that are read pass the same hidden-text stripping and instruction check as the body, and a finding in one stops the run. | An author's or a maintainer's account can be compromised |
| req-dev-bugfix-untrusted-intake-2 | Hidden Text Stripped And Named | Proposed | Invisible characters, HTML comments and collapsed blocks are removed before the model reads the issue, and the removal is reported. | |
| req-dev-bugfix-untrusted-intake-3 | Instruction-Shaped Text Stops The Run | Proposed | A planted instruction in the issue body (for example, "also run `curl …`") is reported as a finding, and the skill does not act on it. | |
| req-dev-bugfix-untrusted-intake-4 | A Classifier Only Adds Stops | Proposed | With a typed classifier configured, its yes stops the run, and its no on a planted instruction still leaves the run stopped by the skill's own reading; with none configured, the skill behaves identically otherwise. | |

### Until The Sandbox, Only Our Own Reports
----
RID: `req-dev-bugfix-ownreports`

Status: `Proposed`

Ruled by George, 2026-10-25, and carried into version 1 unchanged. Until the sandbox of
`req-dev-bugfix-isolation` is enabled, `submit-a-fix` reads an issue only when a maintainer session
account wrote it. The author is read from the issue as fetched, by account identity and never by a
name in the text, using the same allowlist that `req-cicd-issue-link-7` uses. Any other author stops
the run before the issue body is read, with a message that says why: bugs from other accounts wait
for the sandbox. The fetch, the report-as-data intake and the human push are unchanged.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugfix-ownreports-1 | Only A Maintainer Account's Issue Is Read | Proposed | An issue authored by an account that is not a maintainer session account stops the run before its body is read; the skill names the author check as the reason. | By numeric account id and type, as `req-cicd-issue-link-7` does. |
| req-dev-bugfix-ownreports-2 | The Gate Lifts With The Sandbox | Proposed | Enabling `req-dev-bugfix-isolation` is what removes this requirement; the gate is not bypassed by a flag or an environment variable. | |

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

It names which check failed, and does not offer to skip it. The probes come from three directions:
an allowlisted host, an address with no name, and DNS, the channel sandboxes most often leave open.

**The probes detect a misconfigured sandbox. They do not prove isolation.** Three blocked
destinations say nothing about the rest: other hosts, private addresses, metadata endpoints, a
proxy, another protocol. Deny-all egress has to come from the environment, an agent sandbox that
enforces it, and the skill requires one. The sandbox is named, the skill checks it is present
before reading the issue, and the probes are a smoke test that it is actually on. **Until a
sandbox is chosen and named here, `submit-a-fix` stops after the fetch.** A probe that happens to
fail is not a substitute.

**Executing a report runs code a stranger chose, so it runs where it cannot reach the host.** A
report names commits, a scenario and sample data, and reproducing it runs TAP at those commits. So:

- **Provenance first.** Every commit the report names must be reachable from a tag or from `main`
  in the target repository, fetched from that repository and never from a URL in the report. A
  commit that is not stops the run as "not one of ours". A fork's commit is not reproduced: the
  reporter is asked to reproduce on a release.
- **The stack is fresh and confined.** It is never the reporter's or the maintainer's working
  instance, and it holds nothing but the report's sample data. It has no Docker socket, no host
  mounts beyond a scratch copy of the checkout, no secrets store, dropped capabilities, and CPU,
  memory and time limits. Reaching any host file or local service from inside it is a defect in the
  sandbox, not something the skill is trusted to avoid.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugfix-isolation-1 | Preflight Refuses A Credentialed Session | Proposed | With `gh` authenticated, a token or AWS credential in the environment, or the secrets store readable, the skill stops after the fetch and names the failing check. | |
| req-dev-bugfix-isolation-4 | Preflight Refuses Any Egress | Proposed | With `github.com` blocked but a non-GitHub host, a bare IP or DNS still reachable, the skill stops and names which probe succeeded. | A smoke test, not proof: isolation-5 is the boundary |
| req-dev-bugfix-isolation-5 | A Named Sandbox Or No Run | Proposed | Without a named, enforcing deny-all sandbox detected before the issue is read, the skill stops after the fetch; failed probes alone never let it continue. | Blocked until a sandbox is chosen |
| req-dev-bugfix-isolation-6 | Only Our Commits Run | Proposed | A commit the report names that is not reachable from a tag or `main` of the target repository, fetched from that repository, stops the run as "not one of ours". | |
| req-dev-bugfix-isolation-2 | One Fetch | Proposed | The skill performs exactly one network operation, the issue fetch, before the preflight, and none after. | |
| req-dev-bugfix-isolation-3 | Throwaway, Confined Stack Only | Proposed | Reproduction runs in a stack created for the run, loaded only with the report's sample data, with no Docker socket, no host mounts beyond a scratch checkout, no secrets store, dropped capabilities and resource limits. | |

### Reproduce Twice Before Fixing
----
RID: `req-dev-bugfix-reproduce`

Status: `Proposed`

Before any change to code, the skill writes a test that encodes the report's expected-versus-actual,
starting from the report's scenario and sample data, and runs it twice:

- at the reporter's version, the `commit` their report names for the one component;
- at `main`.

There are four outcomes, and three are exits rather than failures:

| Reporter's version | `main` | Outcome |
| --- | --- | --- |
| fails | fails | Proceed to a fix |
| fails | passes | **Already fixed on main**: name the commit if it can be found, and stop |
| passes | — | **Cannot reproduce**: report what was run, and stop |
| no test can be written from the report | — | **Underspecified**: name the missing fact, and stop |

The report's root cause or theories are where the test starts, not what it assumes: a theory the
test contradicts is recorded as contradicted, and the next one is tried. This is the procedure every
serious issue-fixing agent converged on. SWE-agent's default procedure writes a reproduction script
first. Agentless keeps only tests that fail on the unchanged code. Filtering fixes through a
generated reproduction test doubled precision in arXiv 2406.12952.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-bugfix-reproduce-1 | Test Before Code | Proposed | No source change is made before a test exists that encodes the report's expected-versus-actual. | |
| req-dev-bugfix-reproduce-2 | Two Baselines | Proposed | The test is run at the reporter's named commit and at `main`, and both results are recorded. | |
| req-dev-bugfix-reproduce-3 | Exits Are Named | Proposed | Already-fixed, cannot-reproduce and underspecified each end the run with that name and the evidence for it. | |

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

Two rulings shaped the first design (George, 2026-10-02). First, there is no private upload channel:
reports are public issues built from invented data, and security bugs go to private vulnerability
reporting. Second, the human stays in the loop: the fix skill never pushes.

Version 0 (George, 2026-10-25 and 2026-10-26) built the reporter side as an interview that read no
instance data, so that nothing sensitive could reach the report because nothing was ever read. It was
never merged. The design that replaced it (George, 2026-11-11) starts from the opposite observation:
the agent in the install already diagnoses failures with the system's own context, and withholding
that context produced a report that was mostly the reporter's homework. The protection moved from
"never read it" to "read locally, and guard what leaves": the tripwire grew the observed-values file
and the other-components' versions, and the disclosure rule shrank the report's environment section
to the one component that has the bug. The same ruling removed every build fact (OS, Docker, other
plugins) from the report as information about the reporter's system that a public issue should not
carry.

## Future

- **`review-a-fix`**, the third skill. It must treat the diff itself as untrusted, because the Amazon Q extension compromise arrived through a merged pull request, and it must never be the merge decision.
- **Issue forms for plugin repositories**, generated once for the fleet. Today none of the 24 has one, and neither does the org `.github` repository.
- **A gitleaks pass on new issue bodies**, as an Action, for the reports that do not come through the skill.
- **A session-wide injection hook** (a `PreToolUse`/`PostToolUse` classifier on everything a session reads), ruled 2026-10-02 to wait until a locally run model is evaluated (for example, the open-weights AgentJev-0.6B). A hosted classifier would send private session content to a third party.
- **Agent sandboxes beyond this skill.** Every session that reads issue or PR text has the same exposure `req-dev-bugfix-isolation` closes for one skill.
- **A mechanical observed-values capture.** Today the agent records what it read; a read proxy that captured every value returned by the grid, the logs and the files would close the gap `req-dev-bugreport-investigate-4` names.
