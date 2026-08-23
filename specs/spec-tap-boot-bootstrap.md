# TAP Boot Bootstrap Specification

## Philosophy

`spec-tap-boot-v0.md` took a TAP instance from a fresh database to a populated,
self-describing instance by applying **one boot profile in fixed phases**. It answered
*"given a profile, stand the instance up."* It did not answer the question that comes
*before* that one: **where does the profile itself come from, and how does a single
gesture pick which one?**

Today a profile is a file the operator already has on disk (`boot/<id>.boot.json`, or a
plugin-owned `--boot-file` path). That is **single-file boot**: you must already possess
the recipe. The chicken-and-egg is unmissable once plugins live in their own repos — if
`samsite.boot.json` ships *inside* the samsite plugin, and the boot profile is what says
*which plugins to install*, then the profile is trapped inside an artifact you have not
installed yet. You cannot read the recipe until you have the ingredient the recipe tells
you to fetch.

This spec closes that gap with **single-command boot**: one pointer, resolved through the
source machinery TAP already has, fetches the boot record out of a versioned plugin
artifact and stands the instance up from it.

> One pointer names a plugin artifact, a version, and a boot record inside it. The
> bootloader fetches the record, stages it as the active profile, and proceeds. The
> instance unrolls from a single line. Config-as-code, extended one level up: the
> *location of the config* is itself config.

This is **netboot** for TAP, and we build on that lineage deliberately (Prior Art below):
a machine with no operating system holds one pointer (PXE's `next-server`+`filename`,
Ignition's config URL, a Nix flake ref), fetches a recipe, and converges. The irreducible
stage-0 is *"know where to look"*; everything else is downloaded. TAP's irreducible
stage-0 is one pointer string.

Two forces make this worth building **now**, ahead of the lights-out deployment that will
eventually require it:

- **Dogfood-until-load-bearing.** The same command is the daily-driver spawn *and* the
  eventual zero-touch field standup. Building it now means it is exercised every day until
  the moment a customer's lights-out environment depends on it — battle-hardened before it
  is critical, not guessed at when it is.
- **It replaces a harder question.** The alternative — "where do we store boot profiles
  when we need them, and how do we version them" — is *more* machinery, not less. A pointer
  into a versioned artifact makes the storage-and-versioning question dissolve: the record
  lives in the plugin, versioned with it, fetched on demand.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | One Command | A single `tap boot --from <pointer>` stands an instance up from nothing but the pointer. |
| 2. | Records Ride The Artifact | Boot records ship *inside* the plugin package, so bootstrap is source-type-agnostic (git, index, wheelhouse all work identically). |
| 3. | Precise Selection | The pointer names package + version + record; a plugin may ship many records (instance flavors) and the pointer picks exactly one. |
| 4. | Versioned Honestly | A record carries its own version, decoupled from the plugin's code tag; content changes are guarded, never silent. |
| 5. | Fail Closed | Ambiguous or unverifiable selection is a loud error, never a silent default. |

## v0 Scope (spec-first, code deferred)

This spec is **authored ahead of its implementation** (the callsite-identity / SARIF-Phase-0
pattern): the design is locked here so the standardization decisions do not drift while
the pieces land incrementally. The **near-term buildable floor** is (1) *records ride the
artifact* (`req-boot-bootstrap-records-in-package`), (2) a **referrer-held content digest** with
its non-circular guard (`req-boot-bootstrap-record-version`), and (3) the manifest↔files coherence
guard (`req-boot-bootstrap-discovery`) — all cheap, foundational, worth laying while the surface
is being defined (`spec-security-posture.md` `req-sec-cheap-edges`). Crucially, a record carries
**no version of its own** (its version is the plugin's, single-sourced) — this is what dissolves
the stamp-circularity documented in `req-boot-bootstrap-record-version`. Signing
(`req-boot-bootstrap-signing`) is explicitly **backlog**, demand-gated on the first
non-George user (see the strategy note in `plan/road-rampart.md`).

The pilot is **`gryphon_playground`**: it already owns a plugin-local profile, it is
low-stakes, and it immediately exercises multi-record selection — a `playground` flavor
(muck around: seed the Gridkin corpus, no workers) and a `soak` flavor. **Locked pilot decisions:**
`soak` ships as a real second record (same install as `playground`) but is **reserved** for the
fuzz-campaign task loop, which is driven out-of-band by `scripts/gryphon-fuzz-campaign` today and
wired to boot population later — the record exercises selection now without asserting unbuilt
runtime behavior. gryphon ships **no `default.boot.json`**: a bare pointer fails closed naming
`playground` and `soak` (`req-boot-bootstrap-default-record-2`), exercising the fail-closed default
path — a cheap security edge — from day one. `samsite` (the demo) completed the migration to the
in-package `boot/` convention (`req-boot-bootstrap-samsite-rehome`): its record ships in
`tap-plugin-samsite` and the core copy is deleted — the in-package location is the canonical home
for every future plugin-shipped boot record.

## Prior Art

The pointer, the version model, and the fetch are each a well-trodden pattern; we assemble
them rather than invent.

- **Netboot family (PXE / iPXE / cloud-init / Ignition).** A machine with no OS holds one
  pointer and fetches its recipe: PXE's DHCP hands `next-server` + `filename`; Ignition
  takes a single config URL before PID 1 and converges on first boot. The irreducible
  stage-0 is *know where to look*; the rest is downloaded. TAP's single pointer is the same
  irreducible stage-0.
- **Nix flake reference + fragment.** `github:org/repo/v1.0#nixosConfigurations.foo` selects
  a **named output** from a **versioned** flake with a `#fragment`. This is the pointer
  grammar TAP adopts directly: `<source-ref>#<record>`. Nix also fails loud when no
  `default` output exists rather than guessing — the model for `req-boot-bootstrap-default-record`.
- **Content-addressing, and where the hash lives — the config-inside-a-versioned-artifact case.**
  Keyed to *our* narrow problem (a config that ships inside an already-versioned package), the prior
  art is unanimous on one invariant: **a thing never contains its own hash; the hash of X lives in
  whatever refers to X, one layer up.** Python **wheels** carry a `RECORD` file that hashes every file
  *except itself* (`…/RECORD,,` — a blank self-entry) and delegate `RECORD`'s own integrity upward to
  the signature. **OCI** points a mutable **tag** at an immutable content **digest**, and references
  the config blob *by digest from the manifest* — "changing content changes the digest, which changes
  the parent reference." Signed JAR `MANIFEST.MF`, Debian `Release`→`Packages`→`.deb`, and npm/Cargo/Nix
  locks all store the child's hash in the parent. The reason this shape is universal: **a content hash
  is a fixed point** (it depends only on the bytes, not on the metadata being written), whereas a
  **git-derived version is not** — so hashing content and storing it in a referrer *converges*, while
  stamping a derived version into the file it describes is circular. This is exactly the model
  `req-boot-bootstrap-record-version` adopts: digest in the referrer, version = the plugin's.
- **GitOps app-of-apps (`flux bootstrap`, `argocd-autopilot`).** The bootstrap config
  references the very repo/app that manages it — the self-reference that resolves the
  chicken-and-egg. TAP's boot record names its own plugin in its install list
  (`req-boot-bootstrap-stage0`).
- **Kustomize overlays / compose profiles / Spring profiles.** One artifact, many named
  instance shapes selected at launch. This is the "a plugin ships multiple boot records"
  model (`req-boot-bootstrap-records-in-package`): a record *is* an instance flavor.
- **Sigstore keyless signing / PyPI attestations (PEP 740).** OIDC workflow identity →
  short-lived Fulcio cert → sign → Rekor transparency log; no long-lived keys. The signing
  ladder (`req-boot-bootstrap-signing`) builds on this, not on GPG keyrings.

## Relationship To Other Specs

- **Extends `spec-tap-boot-v0.md`.** That spec owns the profile *shape* and the phase
  application (`req-boot-profile`, `req-boot-phases`, `req-boot-population`). This spec owns
  *resolving and fetching* the profile from a pointer, one level above. `--from` is a
  superset of `--boot-file` (`req-boot-bootstrap-command`): a local path still works; a
  remote `pkg@ver#record` is the new capability. The pre-boot stage (`req-boot-preboot`) is
  where stage-0 fetch runs — before Django, settings-free.
- **Consumes `spec-tap-plugin-architecture.md`'s source machinery.** The pointer's `<source-ref>`
  resolves through the existing source-type strategies (`req-tap-plugin-arch-sources`: git /
  index / wheelhouse); bootstrap is **another consumer of the source registry, not a new
  fetch path**. That is why records-ride-the-artifact matters: a record shipped as package
  data is reachable by *every* source type identically.
- **Supersedes the location half of `req-tap-plugin-arch-layout-6`.** That requirement put a
  plugin's standalone-test profile at the plugin **root** (`plugins/<slug>/<slug>.boot.json`,
  outside the importable package). Correct for a monorepo; wrong for bootstrap, because a
  root-level file does **not** ship in the wheel and so cannot be fetched from an index or
  wheelhouse install. `req-boot-bootstrap-records-in-package` moves records *into* the
  package (`tap_plugin/<slug>/boot/`) so they ride the artifact.
- **Sits under `spec-security-posture.md`.** The pointer is a **supply-chain root of trust** —
  the whole instance unrolls from it. The hash-floor / sigstore / TUF ladder
  (`req-boot-bootstrap-signing`) is the honest-risk register for that surface: cheap edge
  now, expensive edges named and demand-gated.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-boot-bootstrap-command | [Single-Command Boot](#single-command-boot) | Proposed | `tap boot --from <pointer>` fetches + stages + boots; `--from` subsumes `--boot-file` (local path, or remote `pkg@ver#record`) |
| req-boot-bootstrap-records-in-package | [Records Ride The Artifact](#records-ride-the-artifact) | Proposed | Boot records live at `tap_plugin/<slug>/boot/<name>.boot.json` as package data; shippable records in-package, harness profiles stay repo-local; supersedes the location of `req-tap-plugin-arch-layout-6` |
| req-boot-bootstrap-samsite-rehome | [Samsite Profile Re-Home](#samsite-profile-re-home) | Implemented | **Executed 2026-08-09 (unified session).** The record ships in `tap-plugin-samsite` (`tap_plugin/samsite/boot/samsite.boot.json`, enumerated with its sha256; doc-rot description rewritten; `required_secrets` rides the record; gate coverage re-homed into the plugin's shipped suite), the core copy is deleted, spawn examples and docs point at the pointer, and the CodeBuild samsite lane stage-0 pointer-fetches the record |
| req-boot-bootstrap-pointer-grammar | [Pointer Grammar](#pointer-grammar) | Proposed | `<source-ref>#<record>[@<digest>]` (Nix-flake fragment + OCI reference); three orthogonal axes — carrier version (`@ver`/`@+ver`), record selector (`#record`), record digest (`@algo:hex`, a fail-closed guard); simple cells built, ranges + digest reserved |
| req-boot-bootstrap-default-record | [Default Record Is Explicit](#default-record-is-explicit) | Proposed | No `#` → `boot/default.boot.json` if present, else loud error naming available records; never "first"/"latest" |
| req-boot-bootstrap-record-version | [Record Integrity + Version](#record-integrity--version) | Proposed | **Near-term build.** Record carries **no version of its own** (version = the plugin's, single-sourced — dissolves the stamp-circularity); integrity = a content `sha256` in the **referrer** (`tap-plugin.toml`), never in the record; non-circular guard; install entries pin *or* float; `targets_major` compat + monotonic counter explicitly reserved/rejected |
| req-boot-bootstrap-install-commit-pin | [Commit-Pinned Install Entries](#commit-pinned-install-entries) | Proposed | **Backlog — enforce sooner or later.** Install entries pin mutable git *tags* today; an optional `commit` field alongside `rev` lets preboot fail closed on a re-pointed tag (the tj-actions attack shape). Advisory first, mandatory for from-git standups when the container/plugin-image dev refactor lands ([doc-dev-compose-tier-handoff](../docs/misc/doc-dev-compose-tier-handoff.md)) |
| req-boot-bootstrap-stage0 | [Stage-0 Fetch Without Import](#stage-0-fetch-without-import) | Proposed | Extract only `boot/<record>.boot.json` from the artifact without installing/importing the package; the record self-references its own plugin (app-of-apps) |
| req-boot-bootstrap-discovery | [Record Discovery](#record-discovery) | Proposed | `tap-plugin.toml` enumerates records (name + description + content `sha256`; no per-record version); `tap boot --list <pointer>` and spawn tab-completion read it; a CI guard reconciles the toml against `boot/*.boot.json` |
| req-boot-bootstrap-signing | [Supply-Chain Integrity Ladder](#supply-chain-integrity-ladder) | Proposed | **Backlog, surfaced sooner-than-usual.** Hash (near-term) → Sigstore keyless attestation → TUF channel security; verify primitives are a `tap/`-level helper (`sigstore` uv-installed), NOT the `sigstore_core` plugin; trigger = first non-George user |

---

### Single-Command Boot
----
RID: `req-boot-bootstrap-command`
Status: `Proposed`

One command stands an instance up from nothing but a pointer.

#### Implementation

- The bootloader gains `--from <pointer>`, a **superset** of `--boot-file`. `--from` accepts:
  - a **local path** (today's `--boot-file` behavior — a file already on disk, including a
    repo-local harness profile like `boot/core_dev.boot.json`);
  - a **remote pointer** (`req-boot-bootstrap-pointer-grammar`) resolved through the source
    machinery — the new capability.
  The single flag dispatches on the shape of its argument, matching the mainstream polymorphic
  form (`nix run <installable>`, `pip install <arg>` — path, URL, or name). `--boot-file` is
  retained as a deprecated alias, not a second mechanism.
- The pointer may be supplied as `--from`, or as the `TAP_BOOT_FROM` boot-variable
  (`req-boot-variable-resolution` ladder: flag > env > default). One env var is the entire
  lights-out stage-0 configuration — the DHCP-option / cloud-init-user-data equivalent.
- Remote resolution runs in the **pre-boot stage** (`req-boot-preboot`), before `migrate` and
  before Django reads settings: stage-0 fetch (`req-boot-bootstrap-stage0`) produces the boot
  record on disk, which the rest of pre-boot and `manage.py boot` then consume exactly as a
  local profile. Nothing downstream of staging knows the profile came from a pointer.
- The command is the canonical standup for **both** dev (spawn) and customer field deployment —
  the one-path doctrine (`req-boot-app`) extended to the profile's origin.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-bootstrap-command-1 | From Flag | Proposed | `--from <pointer>` resolves a local path or a remote pointer; dispatch is on argument shape. | |
| req-boot-bootstrap-command-2 | Boot-File Subsumed | Proposed | `--boot-file` becomes a deprecated alias of `--from`; one code path. | |
| req-boot-bootstrap-command-3 | Env Stage-0 | Proposed | `TAP_BOOT_FROM` supplies the pointer via the boot-variable ladder; one env var is the whole lights-out stage-0 config. | |
| req-boot-bootstrap-command-4 | Resolves In Pre-Boot | Proposed | Remote resolution runs in the settings-free pre-boot stage; downstream boot treats the staged record as a local profile. | |

---

### Records Ride The Artifact
----
RID: `req-boot-bootstrap-records-in-package`
Status: `Proposed`

Boot records ship **inside** the importable plugin package, as package data, so bootstrap is
source-type-agnostic.

#### Implementation

- A plugin's boot records live at **`tap_plugin/<slug>/boot/<name>.boot.json`** — inside the
  importable package, declared as package data (the same treatment `grift/` and
  `tap-plugin.toml` already get). They therefore **ship in the wheel** and travel with the
  versioned artifact.
- **This is the load-bearing reason for the location.** A record must be reachable by *every*
  source type — git, the future index, and the wheelhouse. A record at the plugin **root**
  (the old `req-tap-plugin-arch-layout-6` location) is outside `tap_plugin/<slug>/` and does **not**
  ship in the wheel, so it can only be fetched over git — breaking bootstrap from an index or an
  airgapped wheelhouse. In-package placement makes the fetch identical across all source types
  (`req-tap-plugin-arch-sources`).
- **Version coherence for free.** The record you get is exactly the one that shipped in that
  package version — the recipe and the code it installs are pinned together by construction
  (see `req-boot-bootstrap-record-version` for the record's *own* version axis).
- **A record is an instance flavor.** A plugin MAY ship several records in its `boot/` dir, each
  a full instance recipe (install + population + behavior). The pilot: `gryphon_playground`'s
  `boot/playground.boot.json` (seed the Gridkin corpus, no workers — muck around) and
  `boot/soak.boot.json` (same install; **reserved** for the fuzz-campaign task loop, which is driven
  out-of-band by `scripts/gryphon-fuzz-campaign` today and wired to boot population later — it
  exercises multi-record selection now without asserting unbuilt runtime behavior). Same package, same
  version, different flavor — the Kustomize-overlay / compose-profile shape.
- **Two record classes, two homes:**
  - **Shippable / solution-set records** (samsite demo, gryphon flavors) live **in-package**,
    per this requirement — they travel to deployments.
  - **Harness / dev records** (`core`, `core_dev`, `test_all`) stay **repo-local** under `boot/`
    — they are monorepo-dev/test infrastructure, install-everything-editable, and never shipped.
    `--from` still resolves them by local path.
- **Migration.** `req-tap-plugin-arch-layout-6`'s `plugins/<slug>/<slug>.boot.json` moves to
  `plugins/<slug>/tap_plugin/<slug>/boot/<name>.boot.json`. The gryphon pilot moves
  `gryphon_playground.boot.json` → `tap_plugin/gryphon_playground/boot/playground.boot.json`
  and adds `boot/soak.boot.json`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-bootstrap-records-in-package-1 | In-Package Location | Proposed | Boot records live at `tap_plugin/<slug>/boot/<name>.boot.json`, declared as package data, shipping in the wheel. | |
| req-boot-bootstrap-records-in-package-2 | Source-Type-Agnostic | Proposed | Because records ride the wheel, the same pointer resolves identically over git, index, and wheelhouse. | Supersedes the plugin-root location of `req-tap-plugin-arch-layout-6` |
| req-boot-bootstrap-records-in-package-3 | Multiple Records Per Plugin | Proposed | A plugin may ship several records (instance flavors) in one `boot/` dir; selection is per `req-boot-bootstrap-pointer-grammar`. | Pilot: gryphon `playground` vs `soak` |
| req-boot-bootstrap-records-in-package-4 | Shippable vs Harness | Proposed | Shippable records are in-package; harness profiles (`core`/`core_dev`/`test_all`) stay repo-local under `boot/` and resolve by local path. | |

---

### Samsite Profile Re-Home
----
RID: `req-boot-bootstrap-samsite-rehome`
Status: `Implemented`

The motivating example finally executes its own spec: `boot/samsite.boot.json` moves into `tap-plugin-samsite` as an in-package boot record (`tap_plugin/samsite/boot/samsite.boot.json`, `req-boot-bootstrap-records-in-package`) and the core-repo copy is **deleted**. This spec's opening argument was written about exactly this file — "the profile is trapped inside an artifact you have not installed yet" — yet the pointer flow was proven on `gryphon_playground`'s records while samsite's profile stayed put as the transitional daily-driver copy.

#### Status Details

**Executed 2026-08-09 (unified session), same-night as the unblocking analysis (nightly session).** The record ships in `tap-plugin-samsite` at `tap_plugin/samsite/boot/samsite.boot.json`, enumerated in `tap-plugin.toml` `[[boot.records]]` with its canonical sha256; the doc-rot description was rewritten in the move, `required_secrets` rides the record, and the samsite self-pin advanced to the release that carries the record (tag cut after the commit, so the record is self-consistent). Gate coverage re-homed as `tap_plugin/samsite/tests/test_boot_record_resolves.py` (digest bijection + schema + cold-resolve incl. collector keys + app-of-apps assert). Core deleted `boot/samsite.boot.json`, narrowed its shipped-profile asserts, repointed spawn's help examples at the pointer form, and the CodeBuild samsite lane stage-0 pointer-fetches the record before boot. Known residuals, named not hidden: ~~the `--dev-plugins`/`--from` interplay is unchanged~~ (closed 2026-08-09, same day: `--from` now composes with `--dev-plugins` — the staged record becomes the workspace base; see `req-dev-workspace-spawn-6` in `spec-dev-plugin-workspace.md`), and `tap.plugin_release`'s `--boot-dir` sweep no longer sees samsite's pins — a substrate release does not auto-bump the in-package record; the bump lands at the samsite plugin's own next release. Live-session migration note: a session whose `.env.local` carries `TAP_BOOT_PROFILE=samsite` keeps running, but its next re-boot must first stage the record (`python3 -m tap.boot_pointer '<plugin-ref>#samsite' --out boot`) or respawn via `--from` — the repo-local file it used to resolve is gone.

#### Implementation (the ordered actions)

1. **Record ships in the plugin.** Add the profile to `tap-plugin-samsite` as `tap_plugin/samsite/boot/samsite.boot.json` (package data, enumerated in `tap-plugin.toml` with its content `sha256` per `req-boot-bootstrap-discovery`/`-record-version`). In the same move, fix the doc-rot: rewrite the stale "evict-last / editable from the monorepo" description, reconcile description-vs-install-list drift, and keep `required_secrets` — the declaration rides the artifact, so the provisioning flow reads it wherever the record lives (`req-boot-required-secrets-6`). Release as the next plugin version; the record needs no version of its own.
2. **Spawn shorthand becomes a pointer.** `scripts/spawn-session.sh <name> samsite` resolves from repo-local `boot/` and stops working the moment the file is deleted. The replacement is the existing pointer flow: `spawn --from git+https://github.com/unified-systems-com/tap-plugin-samsite@<ver>#samsite`. **No alias machinery** — a pointer-shortcut table in spawn is demand-gated future, not part of this move. Doc/skill updates ride the same change: README's samsite pointer, the samsite plugin README's boot instructions, the `get-started` skill's profile-choices step (samsite becomes "the full demo, booted via a pointer"), CLAUDE.md's dev-commands note if it names the profile.
3. **Gate coverage re-homes — the protection must not silently vanish.** The dev-validation shipped-profiles axis (`boot --check` over `boot/*.boot.json`, locked by `tap_boot/tests/test_shipped_profiles_resolve.py`) mechanically stops covering samsite when the file is deleted — and that axis caught a real break in this exact file (the stale module-path collector keys after the collector-identity refactor). The equivalent check moves to the plugin: a test in the plugin's shipped suite (`tap_plugin/samsite/tests/`) that stage-0-loads its own record and cold-resolves it (schema + coherence rules + collector keys against the plugin's registry surface), running in the plugin repo's CI against core-main (the two-mains model). The honest gap is named, not hidden: core's gate no longer sees the samsite profile; the plugin CI owns it. Update the `spec-dev-validation.md` Validation Map row for the shipped-profiles axis (narrowed set) and add the plugin-side row **in the same change as the guard**, per Map discipline.
4. **Samsite CodeBuild lane repoints.** The per-product-line `samsite` lane currently exercises the in-tree profile. It fetches the record via the same pointer (one copy, no lane-local fork). Effort deliberately minimal: the lane is already slated for deprecation with the `180731181784` account retirement — pointer-fetch keeps it honest until then without investing in machinery it won't outlive.
5. **Core-side follow-through.** Delete `boot/samsite.boot.json`; `profile_ids()` / `installable_profile_ids()` and the focused-session install-awareness shrink mechanically (samsite's plugin set is no longer demanded by any repo-local profile — `test_all` keeps installing the samsite *plugins* as the test union, which is a different, unaffected file). Sweep repo references to the profile id (`spec-dev-multisession`'s spawn examples, this spec's own prose, memory files at next touch).
6. **Companion item, explicitly out of scope here:** the `artifact_manifest.json` override gap (samsite plugin README, Known Limitation) — pointing samsite at *your* deployment still requires an editable checkout because the compliance collector's manifest has no per-install override. The re-home does not fix that (records are per-deployment config-as-code; the manifest is package data), and the adopter arc needs it fixed regardless of where the profile lives. Tracked in the samsite plugin's own roadmap, referenced here only because every conversation about "adopters boot samsite" trips over both.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-bootstrap-samsite-rehome-1 | Record In The Plugin | Implemented | `tap_plugin/samsite/boot/samsite.boot.json` ships as package data, enumerated in `tap-plugin.toml` with content hash; description doc-rot fixed in the move; `required_secrets` rides the record. | |
| req-boot-bootstrap-samsite-rehome-2 | Core Copy Deleted | Implemented | `boot/samsite.boot.json` is removed from the core repo; no repo-local reference to the profile id survives except historical prose. | |
| req-boot-bootstrap-samsite-rehome-3 | Pointer Is The Path | Implemented | The documented (README/skills) way to boot samsite is `spawn --from <plugin-ref>#samsite`; no spawn alias machinery is added. | |
| req-boot-bootstrap-samsite-rehome-4 | Gate Coverage Re-Homed | Implemented | The plugin's shipped suite cold-resolves its own record (schema + coherence + collector keys) in plugin CI; the Validation Map reflects both the narrowed core axis and the new plugin-side row in the same change as the guard. | The stale-collector-key class stays caught. |
| req-boot-bootstrap-samsite-rehome-5 | CI Lane Pointer-Fetches | Implemented | The samsite CodeBuild lane fetches the record via pointer — no lane-local copy. | Minimal effort; lane is deprecation-slated. |

#### Future

- A `spawn` pointer-shortcut table (named aliases for frequently-used remote records) if the long `--from` form proves to be real day-to-day friction — demand-gated, not assumed.

### Pointer Grammar
----
RID: `req-boot-bootstrap-pointer-grammar`
Status: `Proposed`

A single-line pointer names package + version + record.

#### Implementation

- The grammar is the **Nix-flake fragment + OCI reference**: `<source-ref>#<record>[@<digest>]`, a
  cross-product of **three orthogonal selection axes**:
  1. **Carrier version** — on the `<source-ref>`, *before* the `#`: which artifact the record is read
     *out of*. `@<version>` pins (`@v0.1.0`), `@+<version>` is a floor (`@+v0.1.0` = "≥ this"), absent
     = latest. Resolved by the **existing** source machinery (`req-tap-plugin-arch-sources`) to a versioned
     artifact; it carries source type + locator + version exactly as an `install` entry's `source`
     does. Credentials resolve from `TAP_SECRETS_ROOT`, never in the pointer
     (`req-tap-plugin-arch-sources-4`).
  2. **Record selector** — the `#<record>`: selects `boot/<record>.boot.json` from inside that
     artifact. Absent = the default record (`req-boot-bootstrap-default-record`, fail-closed).
  3. **Record digest** — `@<algo>:<hex>` *after* the record: a fail-closed **integrity guard** on the
     fetched record's content (`req-boot-bootstrap-record-version`). Absent = accept whatever the
     carrier ships.
- **`@` is position-disambiguated**, OCI-style (`repo:tag@sha256:…`): before the `#` it is a
  **version-or-range** (`@v0.1.0`, `@+v0.1.0`); after the record it is a **digest**, recognized by its
  `<algo>:` marker (`@sha256:…`). The `#` separates the two, so one sigil serves both unambiguously.
- **The digest is a GUARD, not a search key.** `foo#soak@sha256:abc` with an unpinned carrier means
  *"fetch soak from the latest artifact; its content MUST be `abc`, else **fail closed**"* — it does
  **not** search versions for the artifact whose `soak` is `abc` (that reverse lookup is deliberately
  out of scope). This is OCI's `image:latest@sha256:abc`. To pin a *specific historical* recipe, pin
  the carrier too (`foo@v0.1.0#soak`).
- **Carrier ≠ installed — by design.** The carrier version says which artifact the *recipe* is read
  from; what code the instance actually *installs* is decided **inside** the record's `install` entries
  (each pin/float per `req-boot-bootstrap-record-version`), including the app-of-apps self-reference
  (`req-boot-bootstrap-stage0-3`). So a digest-pinned pointer freezes the **recipe**; the recipe
  decides how much of the **system** is frozen — install entries that pin → reproducible system;
  install entries that float → frozen boot process over evolving code. The two coordinates are
  intentionally decoupled.
- **Three independent, individually-pinnable coordinates** — do not conflate them:
  1. the **carrier** version (which artifact carries the record) — in `<source-ref>`;
  2. the **record digest** (which exact recipe bytes) — the `@<algo>:<hex>` guard;
  3. the **per-plugin install** versions (what code the recipe installs) — inside the record's
     `install` entries.
- Example (simple, pilot): `git+https://github.com/unified-systems-com/tap-plugin-gryphon-playground@v0.1.0#soak`
  → the `soak` record from the v0.1.0 gryphon artifact.
- The pointer is a **locator, not a full profile**: it identifies + verifies the record; the record
  declares the install set and population. The reproducibility surface (pinned plugin versions) lives
  in the record where it is reviewable.
- **Scope — grammar now, resolver incrementally.** The full grammar is specified here so it does not
  drift, but the pilot resolver implements only the three simple cells — `@<version>#<record>`,
  `#<record>` (latest carrier), and bare `<source-ref>` (default record). **Floor ranges (`@+`) and the
  digest guard (`@<algo>:<hex>`) are reserved grammar**, demand-gated: range resolution is its own
  complexity (npm/Cargo semver ranges) with no pre-launch demand, and the digest guard lands when
  fail-closed recipe pinning is actually wanted.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-bootstrap-pointer-grammar-1 | Fragment Selects Record | Proposed | `#<record>` selects `boot/<record>.boot.json` from the resolved artifact. | |
| req-boot-bootstrap-pointer-grammar-2 | Source-Ref Reuses Machinery | Proposed | `<source-ref>` resolves through `req-tap-plugin-arch-sources` (git/index/wheelhouse); bootstrap adds no new fetch path. | |
| req-boot-bootstrap-pointer-grammar-3 | No Secrets In Pointer | Proposed | The pointer carries only a locator + version + record + digest; credentials resolve from `TAP_SECRETS_ROOT`. | Mirrors `req-tap-plugin-arch-sources-4` |
| req-boot-bootstrap-pointer-grammar-4 | Three Selection Axes | Proposed | Carrier version (`@ver`/`@+ver`, before `#`), record selector (`#record`), and record digest (`@algo:hex`, after) are orthogonal and separately optional; carrier ≠ installed. | |
| req-boot-bootstrap-pointer-grammar-5 | Digest Is A Guard | Proposed | The record digest fail-closes on mismatch against the fetched record; it is a verification guard, not a version-search key. | OCI `image@sha256` |
| req-boot-bootstrap-pointer-grammar-6 | Simple Cells First | Proposed | The pilot resolver implements `@ver#record`, `#record`, and bare (default); floor ranges (`@+`) and the digest guard are reserved grammar, demand-gated. | |

---

### Default Record Is Explicit
----
RID: `req-boot-bootstrap-default-record`
Status: `Proposed`

Selecting a record without a `#` resolves to a named default or fails loud — never a guess.

#### Implementation

- A pointer with no `#<record>` resolves to **`boot/default.boot.json`** if it exists.
- If there is no `default.boot.json`, resolution **fails loud**, naming the records that *are*
  available (`req-boot-bootstrap-discovery` supplies the list). It does **not** pick "the first
  one" or "the only one."
- **Prior art dictates this.** Nix flakes look for an explicitly-named `default` output and
  error if absent — the careful pattern. Docker's implicit `:latest` default is the
  widely-regretted counterexample: it drifts silently and reads as "the newest" when it means
  "whatever was tagged latest." Fail-closed-on-ambiguity is also the security posture
  (`req-sec-cheap-edges`: over-restriction relaxes cheaply; a silent wrong-flavor boot is
  expensive).
- The single-record convenience case is served by *naming* the default record `default.boot.json`,
  not by inferring it — an explicit authoring choice, visible in the `boot/` dir.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-bootstrap-default-record-1 | Named Default | Proposed | No `#` resolves to `boot/default.boot.json` when present. | |
| req-boot-bootstrap-default-record-2 | Fail Closed On Ambiguity | Proposed | Absent a `default.boot.json`, resolution errors and names the available records; never "first"/"latest". | |

---

### Record Integrity + Version
----
RID: `req-boot-bootstrap-record-version`
Status: `In Development`

A boot record's **integrity** is a content digest held **one layer up** in the referrer, never
inside the record; its **version** is the plugin's, not a copy. **This is the near-term buildable
floor of the spec** — cheap, foundational, non-circular.

#### The circularity this avoids (why it is shaped this way)

An earlier design gave the record its own SemVer `version` stamped inside the file. That is a
**circular trap**: a plugin's version is derived from git state (hatch-vcs: a tag is `0.1.0`, a dev
commit is `0.1.1.dev4+g<sha>`), so stamping the version into a tracked file changes the tree → changes
the commit → changes the version → the stamp is stale. It never converges. This is the same
derived-vs-declared drift that bit the uuid5 seed ids: a value derived from state must come from its
derivation, never be hand-copied into that state.

Every package manager avoids this the same way, and the prior art keyed to *our* case — a config
**inside** an already-versioned artifact — is unanimous (see Prior Art):

- **A thing never contains its own hash.** The hash of X lives in whatever *refers to* X, one layer
  up. Python wheels: `RECORD` hashes every file **except itself** (`…/RECORD,,`) and delegates its own
  integrity upward to the signature. OCI: the config blob is referenced **by digest from the
  manifest**; a mutable **tag** points at an immutable **digest**.
- **A content hash is a fixed point; a git-derived version is not.** `sha256(record)` depends only on
  the record's bytes — not on the metadata being written, not on the commit sha — so writing it into a
  sibling file does not invalidate it; it converges in one step. That is *why* the ecosystem hashes
  content and stores it in a referrer instead of stamping a version into the file.

#### Implementation

- **Version = the plugin's version. The record carries none of its own.** A record's version is the
  version of the artifact it ships inside (hatch-vcs / git tag), single-sourced and never copied.
  Selection uses it as a mutable pointer, OCI-tag-style; exact-instance pinning uses the digest below,
  OCI-digest-style. The "same recipe, newer code" decoupling (a record version that floats free of the
  code tag) is a real capability with **no current demand signal** — demand-gated backlog, triggered
  when records are pinned in production (first non-George user, alongside signing).
- **Integrity = a content digest in the referrer.** Each record's `sha256` (over the canonicalized
  record — sorted keys, fixed separators, so cosmetic reformatting does not count) is declared **one
  layer up**, in the package `tap-plugin.toml`'s `[[boot.records]]` table (the same table that
  enumerates records for `req-boot-bootstrap-discovery`), never inside the record file. The digest is
  **regenerated through its derivation** by `scripts/boot-record-hash --refresh`, never hand-typed.
  The derivation sweeps both plugin layouts — in-tree `plugins/*/` and plugin-workspace dev checkouts
  at `_dev-plugins/*/` (`spec-dev-plugin-workspace.md`) — so a fork author editing their checkout's
  in-package record (the adopter cutover flow: repoint the record at your own repos, refresh, release)
  can actually run the mandatory tool; `--root <path>` serves any other layout.
- **Two integrity layers, two jobs.** (a) The shipped wheel already hashes every boot record in its
  standard `RECORD` file, free at build time — post-build / transit / at-rest integrity. (b) The
  `tap-plugin.toml` digest is the **source-side declared baseline** (catches unintended edits in the
  monorepo/editable world where there is no wheel) **and the substrate a signature attests**
  (`req-boot-bootstrap-signing` signs over the digest). Different layers, no conflict.
- **The guard is non-circular and needs no git baseline.** CI recomputes each record's canonical
  digest and asserts it equals the declared `sha256` in the toml; a mismatch fails the build ("the
  playground record changed — rerun `scripts/boot-record-hash`"). The digest *is* the tripwire; there
  is no version to couple it to.
- **Per-entry pin or float — unchanged.** Reproducible-vs-fresh is resolved in the record's `install`
  entries, each of which pins (`rev: v0.1.0`, byte-reproducible) or floats (`rev: main`/range,
  auto-fix). The digest freezes the *recipe*; the install entries decide how much of the *system* is
  frozen (see `req-boot-bootstrap-pointer-grammar`, carrier ≠ installed).

#### Compatibility fidelity (demand-gated backlog — reserved seat)

There is a **good** form of "a version in the profile" that is *not* a copied derived fact: a
hand-authored **compatibility target** — "this record is written against plugin **major** N" — like
Kubernetes `apiVersion`, Terraform `required_version`, Helm `Chart.yaml`, `package.json` engines. It is
authored *intent*, changes only on a breaking major (not every release), and so has neither the drift
nor the circularity of a copied version. The acceptance gate would flag when
`plugin.major > record.targets_major` ("you jumped to v2; your record still targets v1 — review it").
This is **reserved, not built**: gryphon is `v0.1.0` and nothing reaches v2 before launch. A monotonic
"revision counter" is explicitly **not** adopted — it is redundant with the digest (which already
answers "did it change") and the compatibility target (which answers "is it still compatible").

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-bootstrap-record-version-1 | Version Is The Plugin's | Proposed | A record carries no version of its own; its version is the artifact's (hatch-vcs/git tag), single-sourced, never copied into the record. | Kills the stamp-circularity |
| req-boot-bootstrap-record-version-2 | Digest In The Referrer | Proposed | Each record's canonical `sha256` is declared in the package `tap-plugin.toml` `[[boot.records]]` table (one layer up), never inside the record; refreshed via `scripts/boot-record-hash`. | **Near-term buildable floor** |
| req-boot-bootstrap-record-version-3 | Non-Circular Guard | Proposed | CI recomputes each record's canonical digest and fails on mismatch with the declared value; no git baseline, no version coupling. | |
| req-boot-bootstrap-record-version-4 | Per-Entry Pin Or Float | Proposed | Each install entry pins (`rev: v0.1.0`) or floats (`rev: main`/range); the digest freezes the recipe, the entries decide how much of the system is frozen. | |
| req-boot-bootstrap-record-version-5 | Compatibility Target Reserved | Proposed | A hand-authored `targets_major` compat declaration (apiVersion-style intent) + an acceptance-gate check are reserved, demand-gated; a monotonic revision counter is explicitly rejected as redundant. | Not built pre-launch |

---

### Commit-Pinned Install Entries

RID: `req-boot-bootstrap-install-commit-pin`
Status: `Proposed`

The one lane in the pinning story where "pin" still means "mutable ref" (identified
2026-08-10). Every other surface is content-addressed: Python deps carry per-artifact
sha256 in `uv.lock`, container images pin digests, GitHub Actions pin commit SHAs, and the
boot **record** itself is sha256-verified through the pointer. But the record's *install
entries* pin version **tags** (`"rev": "v0.2.2"`), and `tap/preboot.py` installs whatever
that tag points to at install time — a re-pointed tag on a plugin repo delivers arbitrary
code into the venv. This is structurally the March-2025 `tj-actions/changed-files` attack
shape. Mitigations today: the plugin repos are org-controlled and the immutable-tag
discipline is policy — but policy is not proof.

#### Implementation

- Records gain an optional `"commit": "<40-hex>"` field on each git install entry,
  alongside `rev`. When present, preboot verifies the resolved commit matches and **fails
  closed** on mismatch (the idempotence probe in `_installed_git_rev` already reads the
  installed `commit_id` — the comparison point exists).
- `release-plugin.sh` knows the commit at tag time; it stamps the field into any record it
  touches for free. Hand-authored records may omit it (advisory tier).
- **Enforcement ratchet:** advisory now → mandatory for from-git standups (`--from`
  pointer boots, the compose/runtime tier) when the build/dev refactor toward containers
  and plugin-contained docker images lands — that tier installs from records fetched over
  the network with no developer eyeballs in the loop, which is exactly when a mutable ref
  is most dangerous. See [doc-dev-compose-tier-handoff](../docs/misc/doc-dev-compose-tier-handoff.md).
- This is rung 1.5 of the [Supply-Chain Integrity Ladder](#supply-chain-integrity-ladder):
  above the record's own content hash, below Sigstore attestation (which additionally
  proves *who built* the artifact; the commit pin only proves *which content*).

#### Acceptance Criteria

- A record entry with `commit` present + a tag re-pointed to a different commit ⇒ preboot
  aborts before any install, naming the plugin, the expected commit, and the resolved one.
- A record entry without `commit` behaves as today (advisory tier; the gap is named, not
  silently closed).
- `release-plugin.sh` emits `commit` on every git install entry it writes.

### Stage-0 Fetch Without Import
----
RID: `req-boot-bootstrap-stage0`
Status: `Proposed`

Stage-0 extracts only the boot record from the artifact, without installing or importing the
package.

#### Implementation

- Stage-0 resolves `<source-ref>` to the artifact and **extracts only `boot/<record>.boot.json`** —
  it does **not** `pip install` or import the bootstrap plugin at this point. Concretely: download
  the wheel (or sparse-fetch the path) and read the file out of it, rather than installing a
  package whose sibling-imports are not yet satisfiable (the bootstrap plugin may `import
  tap_plugin.<sibling>` at module load, and those siblings are exactly what the record has not
  installed yet). Reading bytes out of an artifact triggers none of that.
- This keeps stage-0 the **minimal, settings-free, Django-free** fetcher that pre-boot already is
  (`req-boot-preboot-1`), and preserves the "abort before any mutation" guarantee: a bad pointer
  fails before `migrate`, DB untouched.
- **Self-reference resolves the chicken-and-egg (app-of-apps).** The staged record names its own
  plugin in its `install` list, so the bootstrap plugin is then installed *properly* (pinned,
  registered, migrated) as part of the normal install stage — not left as a stage-0 peek. This is
  the GitOps `flux bootstrap` / `argocd-autopilot` shape: the config that manages the instance
  includes itself.
- The extracted record is written to the pre-boot working area and consumed as an ordinary local
  profile from that point on; `req-boot-preboot` / `req-boot-install-section` / `req-boot-population`
  are unchanged downstream.

**Credential handling: shared mechanism, reduced validation, explicit boundary.** Stage-0 runs on
the *host* under bare `python3` (during `spawn-session`, before the container exists), so it cannot
import the jsonschema-backed install-system module (`tap/plugin_source_auth.py` →
`tap.runtime_secrets` → `tap.jsonfiles` → `import jsonschema`, venv-only). That boundary is real,
and it governs exactly one thing — *validation depth* — not the credential mechanism:

- **The `GIT_ASKPASS` handoff is not reimplemented.** The askpass script, its owner-only
  (`0700`) temp-file lifecycle, `GIT_TERMINAL_PROMPT=0`, and the git runner live in the
  stdlib-only leaf `tap/git_invocation.py`, imported by BOTH stage-0 and the install system. Two
  byte-identical copies previously existed (2026-08 code-clone sweep, finding S1) on the
  never-leak-the-token surface, where a hardening applied to one would silently miss the other.
  The leaf must remain stdlib-only or the host tools break at spawn time — asserted by test.
- **Stage-0 DOES check the envelope `kind`** (`github_pat`) before reading `data.token`. This
  costs no jsonschema, and without it any envelope carrying a `token` field would have its secret
  handed to whatever git host the pointer names — credential confusion (material for service A
  transmitted to service B). The host boundary never excused this check.
- **Stage-0 does NOT validate the `data` block against the source schema** — that needs
  jsonschema. A right-kind/wrong-shape envelope is caught downstream instead: the clone itself
  fails loud on a bad token, and the in-container install path re-resolves and fully validates the
  record's own per-entry credentials (`req-tap-plugin-arch-source-secret`). This is the named,
  bounded reduction (`req-sec-honest-risk`), not an omission.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-bootstrap-stage0-1 | Extract Not Install | Proposed | Stage-0 reads `boot/<record>.boot.json` out of the artifact without installing/importing the package. | |
| req-boot-bootstrap-stage0-2 | Settings-Free + Abort-Safe | Proposed | Stage-0 stays Django-free and runs before `migrate`; a bad pointer aborts with the DB untouched. | Extends `req-boot-preboot-4` |
| req-boot-bootstrap-stage0-3 | Self-Reference | Proposed | The staged record names its own plugin in `install`, so the bootstrap plugin is properly installed in the normal stage (app-of-apps). | |
| req-boot-bootstrap-stage0-4 | Shared Credential Mechanism | Implemented | The `GIT_ASKPASS` handoff and git runner come from the stdlib-only `tap/git_invocation.py` leaf, shared with the install system — never a second copy. The leaf's stdlib-only property is asserted by test (host tools run under bare `python3`). | Closes code-clone sweep S1. |
| req-boot-bootstrap-stage0-5 | Kind Checked Before Token Use | Implemented | Stage-0 refuses an envelope whose `kind` is not `github_pat` before reading `data.token`, so a credential for another service is never transmitted to the git host. | No jsonschema needed; the boundary is no excuse. |
| req-boot-bootstrap-stage0-6 | Schema Validation Deferred, Named | Implemented | Stage-0 does not validate the `data` block against the source schema (jsonschema is venv-only); the clone failing loud plus the in-container install path's full validation are the named downstream backstops. | `req-sec-honest-risk` — bounded, documented. |

---

### Record Discovery
----
RID: `req-boot-bootstrap-discovery`
Status: `Proposed`

A plugin's available boot records are enumerable cheaply, without a full artifact fetch.

#### Implementation

- **`tap-plugin.toml` enumerates the records** the plugin ships in a `[[boot.records]]` table: for
  each, its `name` (the `#<record>` selector), a one-line `description` of the flavor, and its content
  `sha256` (`req-boot-bootstrap-record-version` — the referrer-held integrity digest lives here, not in
  the record). **No per-record version is stored** — a record's version is the plugin's, single-sourced.
  The `boot/*.boot.json` files remain the runtime source of truth; the manifest is the **index** of them
  (the entry-points / flake-`show` / compose-`--profiles` shape). Each record's own `description` field
  (`json-structures-require-descriptions`) is the long form; the manifest carries the short label so
  listing does not require reading every record.
- **`tap boot --list <source-ref>`** fetches only the manifest (one small file, source-type-agnostic)
  and prints the available records + descriptions — the netboot menu.
- **Tab completion falls out of the grammar.** Because the pointer is enumerable at each coordinate
  — package → version → record — `spawn-session` (and `tap boot`) can complete each `<TAB>`:
  package names from the known plugin set, versions from the source's tags/index, and record names
  from the manifest (with descriptions shown inline). Completing a record requires only the manifest
  read, not a wheel download. This is a concrete near-term payoff of standardizing the grammar, not
  a hypothetical.
- **A CI guard reconciles the manifest against the filesystem:** every record enumerated in
  `tap-plugin.toml` has a matching `boot/<name>.boot.json`, and every `boot/*.boot.json` is
  enumerated (fail closed both directions). This is the same cheap coherence-guard shape as the
  existing plugin conformance checks — it keeps the listing honest.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-bootstrap-discovery-1 | Manifest Enumerates Records | Proposed | `tap-plugin.toml` `[[boot.records]]` lists each shipped record's name + description + content `sha256` (no per-record version); `boot/*.boot.json` stays the runtime truth. | |
| req-boot-bootstrap-discovery-2 | List Command | Proposed | `tap boot --list <source-ref>` fetches only the manifest and prints available records + descriptions. | |
| req-boot-bootstrap-discovery-3 | Tab Completion | Proposed | Package / version / record complete from known sets + the manifest; record completion needs no wheel download. | `spawn-session` + `tap boot` |
| req-boot-bootstrap-discovery-4 | Manifest ↔ Files Guard | Proposed | A CI check fails closed if the manifest's record list and `boot/*.boot.json` disagree in either direction. | |

---

### Supply-Chain Integrity Ladder
----
RID: `req-boot-bootstrap-signing`
Status: `Proposed`

The pointer is a supply-chain root of trust; the instance unrolls from it. Integrity is a
**ladder** — a cheap floor now, expensive rungs named and demand-gated.

#### Implementation

> **Backlog — but surfaced sooner than the usual demand-gate.** The **trigger is the first
> non-George user** playing with the system: at that point we want to offer the most secure
> plugin/boot experience possible, to set the bar high from the start. See the strategy note in
> `plan/road-rampart.md`. Named here so the surface is designed for it, not retrofitted.

- **What signing buys, and what it does not.** A signature gives **integrity** (not tampered) +
  **authenticity** (who built it) — and **nothing else**. Not confidentiality, and crucially **not
  a judgment of intent**: a correctly-signed malicious plugin verifies perfectly. Signing binds an
  artifact to an identity; trusting the identity is a separate decision. This bounds the whole
  ladder honestly.
- **The three rungs:**

  | Rung | Cost | When |
  | --- | --- | --- |
  | **Content hash** in the record / a wheelhouse `sha256` manifest | ~free | **now** — this is `req-boot-bootstrap-record-version`'s guard; catches accidental drift + naive tampering |
  | **Sigstore keyless attestation** (wheel + boot record) | low — reuses the `gh` OIDC identity + a small `tap/` helper | **first non-George user** |
  | **TUF-style channel security** (rollback / freshness / threshold keys) | high | only when an untrusted mirror/index is in the path |

- **Sigstore keyless, specifically.** No long-lived keys. The GitHub Actions release workflow gets
  an OIDC token ("I am the release job of `unified-systems-com/tap-plugin-<slug>`"), sends an ephemeral public
  key + that token to Fulcio (Sigstore's CA), and receives a ~10-minute cert **binding the workflow
  identity to the key**. It signs the artifact's digest, producing a PEP-740-style in-toto
  attestation that ties *this artifact's name + hash* to *that identity*, logged in the Rekor
  transparency log; the ephemeral key is discarded. Verification checks: signature valid, cert
  identity == the expected release workflow, present in Rekor. Key custody: none, ever. This fits
  TAP because plugins are already published via `gh` — the same OIDC identity the release path
  already has.
- **Layering — the verifier is `tap/`-level, NOT the `sigstore_core` plugin.** Plugin-install/boot
  verification runs **before and beneath** any plugin exists; making the verifier depend on a
  plugin being installed to verify plugins is a chicken-and-egg layering violation and cuts against
  the no-sideways-`tap_*`-dependency rule (`avoid-tap-app-interdependencies`). The verify primitives
  therefore live at **`tap/` level** — a `tap/plugin_verify.py`-shaped helper next to
  `plugin_source_auth.py` and `runtime_secrets` — with the `sigstore` library **uv-installed as a
  boot dependency**, not by reusing `sigstore_core`'s code (that plugin is *domain data on the grid*;
  this is *infrastructure*). Same shape as the source-auth helper: settings-free, app-neutral,
  import-safe.
- **Highest-value target is the record, not only the wheel.** Because the pointer is the root, the
  **boot record** (the recipe) is as worth signing as the plugin code (the ingredients). Sign both.
- **Where it matters most.** The git+PAT install already trusts the *transport* (TLS to GitHub + the
  token) — authenticity of the *channel*, not the *artifact*. Signing is transport-independent, so
  it matters exactly where the channel guarantee disappears: **wheelhouse / airgapped / third-party
  index** installs, where a wheel arrives with no trusted-host TLS behind it. This shares the
  deferred-signing edge already named in `req-tap-plugin-arch-sources-6` / `req-tap-plugin-arch-versioning-5`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-bootstrap-signing-1 | Hash Floor Now | Proposed | The content hash of `req-boot-bootstrap-record-version` is the near-term integrity floor; wheelhouse `sha256` manifest shares it. | |
| req-boot-bootstrap-signing-2 | Sigstore Keyless | Proposed | Wheel + boot record signed via Sigstore keyless (OIDC → Fulcio → Rekor); no long-lived keys; verify checks identity + inclusion. | Trigger: first non-George user |
| req-boot-bootstrap-signing-3 | Verifier Is tap/-Level | Proposed | Verify primitives live in `tap/` (e.g. `tap/plugin_verify.py`) with `sigstore` uv-installed; NOT the `sigstore_core` plugin (layering: infra below plugins). | |
| req-boot-bootstrap-signing-4 | Sign The Record Too | Proposed | The boot record (the recipe / supply-chain root) is signed alongside the plugin code (the ingredients). | |
| req-boot-bootstrap-signing-5 | TUF Named Not Built | Proposed | TUF-style channel security (rollback/freshness/threshold) is the far rung, built only when an untrusted mirror is in the path. | |
