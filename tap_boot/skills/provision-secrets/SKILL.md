---
name: provision-secrets
description: Guide an operator from "this boot profile declares secrets" to "every required secret present, kind-matched, and alive" — enumerate needs offline from the profile's required_secrets declaration, check current state via the boot record and envelope metadata, route each gap to its kind's canonical minting docs, place the envelope safely, and verify through the boot preflight. Use when a boot/preflight reports a missing or dead secret, before first boot of a credentialed profile (e.g. samsite), or when someone asks "what credentials does this need?" NOT for wiring a NEW secret kind into the system — that is /manage-secret.
allowed-tools: Read Grep Glob Bash(scripts/dc *) Bash(scripts/*) Bash(docker *) Bash(git *) Bash(ls *) Bash(cat boot/*) Bash(python3 *) Bash(grep *) Bash(mkdir *) Bash(chmod *) Bash(tail *)
argument-hint: [boot-profile]  (default: the session's TAP_BOOT_PROFILE from .env.local)
---

# Provision the Secrets a Boot Profile Requires

> **Skill source-of-truth.** Canonical location: `tap_boot/skills/provision-secrets/SKILL.md`. `.claude/skills/…` is a wiring symlink (`scripts/wire-skills.sh`). Edit the canonical.

A profile declares what it needs in **two** machine-readable places, and this skill is the named consumer of both:

1. **`required_secrets`** (`req-boot-required-secrets`, `spec-tap-boot-v0.md`) — what POPULATION needs: the secrets `fire-collector` steps resolve at run time.
2. **`install.plugins[].source.credential`** (`req-tap-plugin-arch-source-secret-5/-6`) — what INSTALL needs: the PAT that pulls a private plugin repo. Naming the key IS the declaration that it is required. These are *not* `required_secrets` entries and never appear in that table, so a profile can declare zero required secrets and still be unbootable without a credential — that asymmetry is why this step reads both.

Both are machine-enforced, and the enforcement tells you which KIND of gap you have. For population secrets the boot preflight runs two lanes (`req-boot-obs-preflight-6`): **offline** (envelope present, kind matches — a *provisioning* gap: mint it) and **live** (the collector's self-test — a *liveness* gap: rotate it). Install credentials have only the offline lane (`req-tap-plugin-arch-source-secret-7`) — an install either finds a usable envelope or it does not, and the pull itself is the liveness proof. Your job is to walk the operator across whichever gap the evidence shows, without ever seeing a secret value.

**Division of labor with `/manage-secret`:** that skill *authors* — a new secret kind, a new consumer, scanner/redaction wiring (developer-facing). This skill *provisions* — supplies values for already-declared requirements (operator-facing). If the work turns into "TAP doesn't have a kind/consumer for this yet," switch skills.

## Redaction discipline (read first, non-negotiable)

- **Never print, echo, or paste a secret value into the conversation** — not the `data` block of an envelope, not a token "just to check it." When inspecting envelopes, read **identity fields only** (`scope`, `key`, `kind`, `description`, `metadata`); a one-liner that cannot leak: `python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print({k: d[k] for k in ('scope','key','kind','description') if k in d})" <path>`.
- The operator types values into their own editor, never into chat. You write envelope **skeletons** with `"<PASTE-VALUE-HERE>"` placeholders; they fill them in.
- `~/tap-secrets` is **shared host state** symlinked into every session — editing an envelope mutates all live sessions at once. Say so before any edit; for red-testing or experiments, point `TAP_SECRETS_ROOT` at a private scratch dir instead.

## Step 0 — Enumerate the requirements (offline, from the declaration)

Read the profile — `boot/<profile>.boot.json` (repo-local) or the staged record — and present **two** tables. No container, no network needed (`req-boot-required-secrets-6`).

**Population secrets.** For each `required_secrets` entry: its `scope:key`, `kind`, the least-privilege `note`, and which enabled steps consume it (`secrets` refs).

**Install credentials.** For each ENABLED git install entry carrying a `credential`: the key, the slugs that share it, and the repo URLs they pull. The machine answer — presence, both lookup rules, kind, token — is one command, offline, host-runnable, no venv (`req-tap-plugin-arch-source-secret-7`):

```
python3 -m tap.install_credentials --profile <id> --boot-dir <worktree>/boot     # exit 3 ⇒ unsatisfiable
```

Run it before minting anything: its verdict names every unsatisfiable credential at once, and its message is the worklist.

**Ask the public-repo question BEFORE provisioning an install credential.** A `credential` on a source whose repo is *public* is unsatisfiable for no reason, and minting a PAT to satisfy it is the wrong fix — it papers over a record defect and mints a credential nobody needed. Records travel and outlive their claims about other repos (a repo opened up, or an org migration that left the URL behind). Check:

```
GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0 git ls-remote <url> <rev>
```

If that resolves, the fix is to **drop the `credential` key from the record** (in the plugin repo that ships it, then re-release) — not to provision. Say this plainly and stop; do not mint.

A profile with no `required_secrets`, no fire-collector steps, and no declared install credential needs nothing — say so and stop. Auth-section secrets (e.g. an OIDC client secret) are outside these declarations by design; auth's own boot validation covers them.

## Step 1 — Establish current state (evidence, not guesswork)

Best evidence first:

1. **The boot record** — `<worktree>/logs/boot/latest.boot-record.json`. Its preflight entries answer both lanes per ref/collector: `{"type": "preflight", "key": "<scope>:<key>", "status": ...}` for the offline checks, collector-keyed entries (with `failing_checks`) for the live lane. The abort block's `missing_secrets` (ref/kind/note/problem) is the exact worklist.
2. **No record yet** (never booted): check envelopes directly under `$TAP_SECRETS_ROOT` (`<scope>/<key>.secret.json`) — presence, and `kind` via the identity-fields one-liner above. This predicts the offline lane; only a boot proves the live lane.
3. **For install credentials there is no boot record to read** — they are resolved before one exists (host-side during spawn; in-container at the head of pre-boot). `python3 -m tap.install_credentials` from Step 0 IS the evidence, and it is authoritative for both resolvers: an install envelope must satisfy the container's identity rule (`scope` `tap_plugins.source` + `key`) AND the host tools' filename rule (`<key>.secret.json`), because the host resolver runs before any venv exists and cannot reach the registry (`req-tap-plugin-arch-source-secret-9`). Getting one right and the other wrong is a real failure mode the check names explicitly — an envelope that satisfies only the filename rule passes spawn's staging and then aborts pre-boot minutes later.

Classify each requirement: **present + alive** (done), **missing/kind-mismatched** (provisioning gap → Step 2), **present but dead** (liveness gap — a 401/403 in the live lane's `failing_checks` → Step 2, framed as *rotate/re-mint*, and the old value is revoked provider-side, not merely misplaced).

## Step 2 — Route each gap to its kind's canonical guidance

**Do not restate minting steps here — they live with the kind's consumer and would only drift.** Route:

- `github_pat` → the samsite plugin README ("Place the GitHub credential") and `github_core`'s collector secret schema (`tap_plugin/github_core/.../secret.py` documents the exact `data` fields). Least-privilege posture rides the declaration's `note` (read-only Metadata + Contents + Actions, scoped repos).
- `aws_static_access_key` / `aws_assumed_role` → the samsite plugin README (Steps 1–2) and `aws_core`'s handoff kit (`tap_plugin/aws_core/collectors/boto3_collector/handoff/`) for the cross-account variant. Region scope lives on the envelope and is mandatory.
- Any other kind → its consuming plugin's README + secret schema module (the kind is consumer-owned, `req-tap-cares-secrets-consumer-kinds`). If no consumer documents it, that's an authoring gap → `/manage-secret`.

Walk the operator through minting **conversationally** (which console, which scopes to tick, what expiry), reading from those sources — the human does the clicking; remind them about expiry ("set one you'll outlive, or calendar the rotation — an expired token aborts the next boot at preflight").

## Step 3 — Place the envelope

Write the skeleton at `$TAP_SECRETS_ROOT/<scope>/<key>.secret.json` (create the scope dir if needed) with `scope`/`key`/`kind` exactly as declared, a human `description`, and placeholder `data` matching the kind's schema. For an **install credential** the identity is fixed by the install system, not the plugin: `scope` is `tap_plugins.source` (the install system owns it — a plugin must never resolve the credential that installs its siblings), `key` is the record's `credential` value, `kind` is `github_pat`, `data` is `{"token": ...}` (plus optional `host`/`username` for GHE) — and the **filename must be `<key>.secret.json`**, which the host-side resolver matches on. Then:

- Operator fills the value(s) in their editor. `chmod 600` the file.
- Never commit it (the leak-guard would catch it; don't make it try). Never place fixtures with a real-looking name — `.secret.example.json` for templates.
- Repeat the shared-state warning if the target is the `~/tap-secrets` symlink.

## Step 4 — Verify through the machinery, not by hand

The secrets loader is **load-once (restart-to-rotate)**: a new or changed envelope is invisible until the web container restarts. So:

```bash
scripts/dc restart web
# wait for readiness, then:
scripts/dc exec web uv run python manage.py boot --profile <profile>
```

For an **install credential**, verify offline first — it needs no container and no restart, because the host tools read the store directly:

```bash
python3 -m tap.install_credentials --profile <profile> --boot-dir <worktree>/boot   # exit 0 ⇒ satisfiable
```

Then let the real install prove it (a boot performs the pull). The rest of this step is the population lane.

The preflight is the verifier: the offline lane confirms presence + kind, the live lane proves the credential works — one output, both answers, and the boot record persists the verdict. Green means fully provisioned *and* alive; don't hand-craft curl checks when the self-test already encodes the right probe.

## Step 5 — If it still fails

- Live-lane failure after a fresh mint → `/diagnose-failed-session-spawn`'s credential signature splits credential-dead vs target-moved (e.g. the envelope's `repos`/target list is stale even though the token is good).
- Offline-lane failure after placing the file → kind typo (envelope `kind` vs declared), wrong path (`scope`/`key` must match the filename convention), or the restart was skipped.
- An install credential still unsatisfiable after placing the file → run `python3 -m tap.install_credentials` and read WHICH rule it names: `identity` (filename right, `scope`/`key` wrong — spawn would pass and pre-boot would abort) vs `filename` (identity right, file misnamed — spawn's own staging fails). Both must hold.
- The need itself looks wrong (profile demands a secret this deployment shouldn't have) → the profile is config-as-code: disabling the consuming step drops the requirement (the coherence rules then demand removing the entry) — an edit for the operator to make deliberately, not a waiver to talk them around.
