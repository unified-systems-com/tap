---
name: manage-secret
description: Review and wire a TAP secret — a new secret kind, a new credential for a plugin/collector/connector, or any change to how a credential is stored, resolved, scoped or detected. Use whenever the work involves an API token, password, private key, client secret, or any material that must not enter source control — including when merely DISCUSSING whether something needs a credential, before code exists.
allowed-tools: Read Write Edit Bash(scripts/dc *) Bash(grep *) Bash(find *) Bash(ls *) Bash(git *) Glob Grep
argument-hint: [consumer] [what the secret authenticates to]
---

# Wire a TAP Secret

> **Authoring, not provisioning.** This skill wires a secret INTO the system — a new
> kind, a new consumer, scanner/redaction/necessity plumbing (developer-facing). If the
> kind and consumer already exist and the task is "supply the value a boot profile
> declares" (mint + place + verify), that is `/provision-secrets` (operator-facing,
> reads the profile's `required_secrets` declaration).

A credential is entering (or changing inside) the system. Secrets are the one surface where a
mistake is **not recoverable by editing** — once material reaches a commit it is disclosed for
the life of the repository, and the only remedy is rotation plus history rewriting. So this runs
as a review, not a wiring task: decide first, write second.

Trigger this even when no code exists yet. "Does this connector need a token?" is already the
right moment — the cheapest fix to a badly-scoped credential is choosing a different one.

## Best practices for TAP

The shared list is [AGENTS.md § Best practices for TAP](../../../AGENTS.md#best-practices-for-tap). For this skill, lead with:

- **Name the evidence behind every claim** (12): read, grepped, ran or inferred, with the file:line, output or commit.
- **Treat specs as canon** (13): read the spec first and change it with the code.


## Authoritative Sources

Read before writing; do not work from memory.

- **[`tap_cares/specs/spec-tap-cares-secrets.md`](../../specs/spec-tap-cares-secrets.md)** — the
  contract. Envelope shape, scoping, kinds, rotation, and the three leak surfaces.
- **[`tap/runtime_secrets.py`](../../../tap/runtime_secrets.py)** — envelope parsing, size
  ceiling, and the envelope leak scan.
- **[`tap/credential_patterns.py`](../../../tap/credential_patterns.py)** — the credential-shape
  scanner. **You will probably need to edit this** (Step 5).
- **[`tap/plugin_source_auth.py`](../../../tap/plugin_source_auth.py)** — the worked example of a
  well-formed credential end to end: declaration, kind, data schema, `GIT_ASKPASS` handoff,
  redacted `__repr__`.
- **[`tap/secret_sources.py`](../../../tap/secret_sources.py)** — the pluggable source seam
  (disk today, AWS Secrets Manager in CI) and its distribution allow-list.

## Step 0: Core or Plugin? Answer This First

Secret *material* never lives in the repository on either side — that is
`req-tap-cares-secrets-scope`, and three guards enforce it. But the *consumer* matters enormously,
and the default is not symmetric:

- **A plugin/collector/connector secret is the routine case.** Scope is the plugin slug. This is
  where nearly all new kinds arrive, and where external plugin authors will add them from August.
- **A core secret is rare and must justify itself.** Core consumes only a handful today — the
  OIDC client that authenticates every user, and the install-system PAT that installs every
  plugin. Those are the highest-blast-radius credentials in the system precisely because
  everything depends on them.

So: if the proposed consumer is core, **challenge it before proceeding.** Ask what breaks if the
credential belongs to a plugin instead. Add a core secret only when the consumer genuinely is core
infrastructure (auth, boot, the install system), never merely because core is convenient. Record
the justification in the spec section you write in Step 8 — a future reader must be able to see
that the question was asked.

## Step 1: Classify — New Kind, or New Instance?

| Situation | What it costs |
| --- | --- |
| **New instance of an existing `kind`** (another `github_pat`, another OIDC client) | Steps 2–4 and 8. No schema, no scanner change. |
| **New `kind`** (a shape nothing else uses) | All steps. You are extending the type system. |

Check honestly before claiming "new" — `grep -rn '"kind"' --include='*.schema.json'` and read
`tap/plugin_source_auth.py`'s `GITHUB_PAT_KIND` note on why the *same* kind name can carry a
*different* data schema per consumer. Reusing a kind whose data shape does not actually fit is
worse than adding one.

## Step 2: Scope and Key

- **Scope names who CONSUMES the secret, never who issues it**
  (`req-tap-cares-secrets-consumer-scoping`). A GitHub token used by the install system is
  `tap_plugins.source`, not `github`. A GitHub token used by the `github_core` collector is
  `github_core`. The provider is carried by `kind`, not by scope.
- **Install-system credentials live in `tap_plugins.source`** and belong to the install system,
  never to a plugin. A plugin resolving that scope trips the cross-scope `CONCERN` tripwire
  (`req-tap-cares-secrets-cross-scope-concern`) — that is detection working, not a false alarm.
- **Filename `<key>.secret.json` must match the envelope's `key`**
  (`req-tap-cares-secrets-files-5`). Directories are organizational only and carry no meaning.

## Step 3: Envelope and Data Schema

Every secret is `scope` + `key` + `kind` + `description` + `data`. For a **new kind**, write a JSON
Schema for the `data` block, owned by the **consuming** spec, not by `tap_cares`
(`req-tap-cares-secrets-consumer-kinds`). Model it on
[`tap/schemas/github_pat_source_secret.schema.json`](../../../tap/schemas/github_pat_source_secret.schema.json).

Per the project's JSON-structure rule, **every field carries a description** — the top-level object
and each property. These descriptions are read by humans triaging an incident and by AI helpers
reasoning about the system; an undescribed field is a field nobody can safely change later.

State the **least-privilege** shape in the schema description: which scopes, which repos, read vs
write. `github_pat_source_secret.schema.json` says "Fine-grained, Contents: Read-only, scoped to
the plugin repos" — that sentence is what makes an over-scoped token reviewable.

## Step 4: Necessity Is a Health Probe, Not a Flag

Whether a secret is *required* is per-consumer conditional logic owned by a health probe
(`req-tap-cares-secrets-conditional-validation`), not a static declaration on the file. Do not add
a "required" boolean to the envelope. Write the probe that answers "is this consumer configured
such that it needs this credential right now?"

The parallel in the install path is the `credential` key itself: a git source that declares one is
private and must resolve it; a source with no `credential` is public and never raises. **The
declaration IS the requirement.**

## Step 5: Teach the Scanner Its Shape — or Declare It Undetectable

This is the step that decays if skipped, and the reason this skill exists.

Ask: **does this credential have a recognizable wire format?** An issuer-assigned prefix plus a
length floor — `github_pat_`, `AKIA`, `xox[baprs]-`, PEM armor.

- **If yes** — add a `CredentialPattern` to `CREDENTIAL_PATTERNS` in
  [`tap/credential_patterns.py`](../../../tap/credential_patterns.py), with a `description` saying
  what it detects, plus tests in `tap/tests/test_credential_patterns.py`: one asserting the shape
  is caught, and one asserting a near-miss (prose naming the kind, a truncated value) is **not**.
  Assemble test tokens by concatenation rather than as literals — the test file is inside the tree
  the guard walks, so a literal would fail the guard it is testing.
  The guard, the pre-commit hook and the CI gate all pick it up at once; there is nothing else to wire.
- **If no** — a password, a bare random string, anything without a distinguishing prefix — **say
  so explicitly** in the spec section. Record that this kind is pattern-undetectable and rests on
  the envelope layer plus `.gitignore`. Do **not** reach for an entropy rule: measured on this
  repository, entropy heuristics produced 21 findings and 21 false positives with zero true
  positives, which is why they are disabled in the gate profile.

Silence is the failure mode here. An undetectable kind that nobody wrote down looks exactly like a
covered one.

## Step 6: Redaction

The value must not reach logs, tracebacks, run records, or CI output
(`req-tap-cares-secrets-redaction`). Concretely:

- Any dataclass or object holding the material defines `__repr__` **omitting it** — see
  `GitCredential` in `tap/plugin_source_auth.py`.
- Never interpolate a credential into a URL. In the install path this is load-bearing: a token in
  a git URL lands in the venv's `direct_url.json`. Pass it out-of-band (`GIT_ASKPASS`, an env
  overlay, a header).
- Failure messages name the **scope:key**, never the value.

## Step 7: Where the Value Comes From

Disk is the default (the mounted `*.secret.json` store). If this credential must also work in CI
or a deployed environment, it routes through the source seam (`tap/secret_sources.py`) — the
envelope stays on disk and only the opaque value moves. Adding a *new* source provider means a
slim, allow-listed distribution plus a deliberate one-line widening of
`_ALLOWED_SOURCE_DISTRIBUTIONS`; "any installed distribution can register a credential source" is
the hijack surface that list closes.

Note the bootstrap rule: a source provider authenticates via **ambient cloud IAM**, never via a
TAP secret, so there is no resolution recursion.

## Step 8: Spec, Tests, Verify

1. **Spec section** in the consuming spec: what the credential is, who consumes it, its least-
   privilege shape, its rotation story, whether it is pattern-detectable, and — if core — why it
   is core's.
2. **Tests** for the schema and any new pattern.
3. **Run the guards:**
   ```
   scripts/dc exec -T web uv run pytest tap/tests/test_guards.py tap/tests/test_credential_patterns.py -q
   ```
4. **Confirm the real secret is ignored:** `git status --short` must not list your
   `*.secret.json`. If it does, stop — `.gitignore` is not covering it.

## Gotchas

- **`~/tap-secrets` is shared host state.** It is symlinked into every session worktree, so
  editing a `*.secret.json` mutates every live session at once. Check siblings before editing. For
  an experiment, point `TAP_SECRETS_ROOT` at a private directory instead.
- **A guard passing is not proof it ran.** A scan that reads nothing exits clean. If you add
  detection, plant a positive control and watch it fail before trusting a green.
- **The pre-commit hook is bypassable and is not the authority** — the CI guards are. It also does
  not run the envelope-*content* scan (that needs `jsonschema`, absent on a bare host). Do not
  treat a passing hook as full coverage.
- **Rotation is restart-to-rotate in v0.** There is no atomic reload; changing a value requires a
  restart. Say so wherever a runbook implies otherwise.
- **Going public is one-way.** If the consuming repository may ever become public, a credential in
  its history is disclosed permanently — the tree being clean says nothing about the commits.
  See `req-tap-cares-secrets-history-audit`.

## Definition of Done

- [ ] Core-vs-plugin decided, and a core secret's justification written down
- [ ] Scope names the consumer; filename matches `key`
- [ ] `data` JSON Schema exists, every field described, least privilege stated
- [ ] Necessity expressed as a health probe, not a flag
- [ ] Pattern added to `CREDENTIAL_PATTERNS` **or** undetectability recorded in the spec
- [ ] Redaction verified: `__repr__`, no credential in any URL, errors name `scope:key` only
- [ ] Spec section written; guards green; `git status` clean of secret files
