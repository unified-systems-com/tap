# TAP Baked Instances

## Philosophy

A TAP instance should be ready the moment someone launches it. Today every launch builds itself
from nothing: it installs its plugins from git, builds about 2,100 tables, and runs every population
step. The rampart-20x-playground Codespace (`rampart-20x-playground-tap`) shows the cost. Measured on
a real Codespace on 2026-11-21, with tap 0.4.2 and the schema already built from the models, it served
its site 403 s after creation:

| Phase | Time |
| --- | ---: |
| Machine, clone and image pull, before the web container starts | 170 s |
| Installing 15 plugins from git | 68 s |
| Crypto-BOM gate | 12 s |
| Schema (`migrate_from_models` is 32 s of it) | 59 s |
| 11 population steps | 90 s |

Every launch repeats work whose result is the same each time. Population imports static JSON with
fixed batch and entity ids. The schema is a function of the plugin set. The crypto-BOM verdict is a
function of the image's contents. None of it depends on who launched the instance or where. The
first impression matters most for a demo: a visitor who waits seven minutes is entitled to doubt the
rest. And for an operator replacing a compromised instance, rebuild time is time spent exposed.

This spec moves that work from launch time to build time. It names two halves, and keeps them apart
the way every system that does this well keeps them apart:

- **Bake**, once, in CI. It produces two artifacts: a **product image** with the record's plugins
  already installed, and a **seed**, the database and plugin data of an instance that has finished
  booting. Neither artifact holds a secret or anything specific to one instance.
- **Personalize**, at the first start of each instance, on whatever host it runs. It mints that
  instance's secrets and identity, loads the seed into an empty database, and lets boot skip
  everything the seed already holds.

Four convictions shape the requirements below.

**Nothing instance-specific is baked.** A value made at bake time is shared by every instance made
from the artifact. AWS Lambda SnapStart documents this for restored snapshots ("content generated
during initialization might not be unique"). Windows sysprep and cloud-init exist for the same
reason. So the bake mints no secret, and a launch never trusts a secret it did not mint itself.

**A seed is not a backup restore.** [`spec-tap-backup.md`](spec-tap-backup.md) keeps restoring an
instance's own data a deliberate human act, and this spec does not weaken that rule. A seed is a
reviewed, pinned artifact that every new instance starts from. That makes it closer to an image than
to a backup, and its boot is a third mode beside restore and clone.

**Both roads always work.** A seed that fails any check is set aside, loudly, and the instance boots
the full way, as it does today. The fast road is an optimisation. It is never the only way up, and it
never leaves an instance half-built.

**One mechanism, every host.** The same two artifacts start a Codespace, a local session stack and a
hosted instance on AWS. Only how the artifacts reach the host differs, so nothing in bake or
personalize names a product.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Launch In Seconds | A baked instance serves its site within a measured budget; the playground Codespace's is under 2 minutes, from creation to the site answering. |
| 2. | Nothing Shared Between Instances | No secret, credential, session or person crosses from the bake into an instance, and every instance mints its own identity. |
| 3. | Proven Artifacts | The image and the seed are attested in CI, keyed to exactly what built them, and checked before an instance trusts them. |
| 4. | Always A Way Up | Any refused or failed seed falls back to the full boot, recorded and visible, never silently. |
| 5. | Any Product, Any Host | Bake and personalize take a boot record as input and name no product; Codespaces, local spawns and hosted launches use the same artifacts. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-bake-shape | [Bake, Then Personalize](#bake-then-personalize) | Proposed | Two halves, one name each; where a seed sits beside export, backup and frozen containers |
| req-tap-bake-product-image | [The Product Image](#the-product-image) | Proposed | `FROM tap-web@digest`, the record's plugins installed from a verified wheelhouse at bake time |
| req-tap-bake-baked-venv | [A Baked Environment Survives Boot](#a-baked-environment-survives-boot) | Proposed | The entrypoint neither wipes nor prunes it, and makes no network call to re-check it |
| req-tap-bake-seed | [The Seed](#the-seed) | Proposed | A full-backup archive of a booted CI instance, with a fixed set of subtractions |
| req-tap-bake-seed-key | [The Seed Key](#the-seed-key) | Proposed | Record digest, image digest and Postgres major; a seed loads only where all three match |
| req-tap-bake-attest | [Attested Artifacts](#attested-artifacts) | Proposed | CI attests both; the deploy config pins the seed by digest |
| req-tap-bake-seed-boot | [Seed Boot](#seed-boot) | Proposed | Third boot-from-archive mode; clone identity; automatic only when pinned; falls back loudly |
| req-tap-bake-personalize | [Personalize At First Start](#personalize-at-first-start) | Proposed | Secrets from a CSPRNG inside the stack, keyed on an instance identity, never in a prebuild |
| req-tap-bake-crypto-bom | [The Crypto Verdict Travels With The Image](#the-crypto-verdict-travels-with-the-image) | Proposed | Computed at bake, bound to the image digest; any change at boot rescans |
| req-tap-bake-hosts | [One Mechanism, Every Host](#one-mechanism-every-host) | Proposed | Codespaces, `spawn-session.sh`, hosted Postgres; fleets by copy-on-write clone |
| req-tap-bake-launch-budget | [The Launch Is Timed](#the-launch-is-timed) | Proposed | Each phase timed in the run record; the playground budget is proven on a real Codespace |

### Bake, Then Personalize
----
RID: `req-tap-bake-shape`

Status: `Proposed`

This spec uses these names and no others:

- **Bake**: the CI job that turns a boot record and a tap image digest into a product image and a
  seed.
- **Product image**: the tap-web image plus the record's plugins
  ([`req-tap-bake-product-image`](#the-product-image)).
- **Seed**: the archive of a freshly booted instance that new instances start from
  ([`req-tap-bake-seed`](#the-seed)).
- **Seed boot**: a boot that loads a seed into an empty database
  ([`req-tap-bake-seed-boot`](#seed-boot)).
- **Personalize**: the first-start step that gives one instance its own secrets and identity
  ([`req-tap-bake-personalize`](#personalize-at-first-start)).
- **Baked instance**: an instance started from a product image and a seed.

[`req-tap-backup-tiers`](spec-tap-backup.md#three-tiers-one-name-each) names three ways to carry an
instance: export, full backup and frozen containers. A seed uses the full-backup archive format, so
its reader, its integrity checks and its manifest are the backup spec's. It is a third mode of
booting from an archive, beside restore and clone, and not a fourth tier. What differs is its
purpose: a restore brings one instance back, and a clone forks one instance once. A seed is made to
be started from many times, by people who never saw the instance it was taken from.

The bake runs the normal boot to produce the seed. There is no second population path, and nothing
written for the bake that boot does not already do. A seed is therefore exactly what a full boot of
the record produces, minus the subtractions [`req-tap-bake-seed`](#the-seed) names.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-shape-1 | Same Boot, Earlier | Proposed | The bake produces its seed by running `manage.py boot` on the record, with no step that a full boot of the record does not also run. | A seed can only hold what a real boot writes |
| req-tap-bake-shape-2 | No Product Named | Proposed | The bake job, the seed boot and personalize take the record and the image digest as inputs, and no product name, slug or repository appears in their code. | Enforced by a test over those modules |
| req-tap-bake-shape-3 | Archive Format Shared | Proposed | A seed validates against the full-backup manifest schema, and is read only through the backup spec's checked reader ([`req-tap-backup-safe-read`](spec-tap-backup.md#safe-archive-reading)). | |

### The Product Image
----
RID: `req-tap-bake-product-image`

Status: `Proposed`

A product image is built `FROM ghcr.io/unified-systems-com/tap-web@<digest>`, never from a tag, with
the record's plugins installed at build time. Plugins come from a wheelhouse the bake builds from
each plugin's pinned commit. Pre-boot already supports the wheelhouse source, offline and
digest-verified. The bake writes the boot record it was built from into the image, at the path
pre-boot reads, together with its digest.

Nothing about the image is product-specific apart from its record and the plugins that record
names. A product publishes its image under its own name, attested
([`req-tap-bake-attest`](#attested-artifacts)), and its deploy config pins it by digest.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-product-image-1 | Pinned Base | Proposed | The product image's `FROM` line names tap-web by digest; a tag-only base is refused by the bake. | |
| req-tap-bake-product-image-2 | Plugins Match The Record | Proposed | Every plugin in the record is installed in the image at its pinned commit, and nothing else is; the bake fails otherwise. | |
| req-tap-bake-product-image-3 | Record Travels With It | Proposed | The image holds the record and its digest; pre-boot in that image reports every plugin as already satisfied and installs nothing. | |

### A Baked Environment Survives Boot
----
RID: `req-tap-bake-baked-venv`

Status: `Proposed`

Today's entrypoint undoes a baked environment in three ways:

- It empties the venv and uv cache whenever the cache volume's image stamp is missing or different.
- It runs `uv sync --all-packages`, an exact sync, which removes packages pre-boot installed outside
  the lock.
- Pre-boot looks up each git plugin's tag over the network on every boot, even when the plugin is
  already satisfied.

In a product image, the venv the image ships is the environment: the image's stamp is written at
build time, the sync leaves the record's plugins in place, and the tag check happens once, at bake,
where its result is recorded. A volume that holds a *different* image's venv is still cleared, as
today. That rule exists because a stale venv cannot be vouched for, and it still holds.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-baked-venv-1 | Not Wiped | Proposed | Starting a product image on fresh volumes leaves its installed plugins in place; a volume stamped by another image is still cleared. | |
| req-tap-bake-baked-venv-2 | Not Pruned | Proposed | After the entrypoint's sync step, every plugin the record names is still importable. | |
| req-tap-bake-baked-venv-3 | No Network To Start | Proposed | A product image boots to serving with outbound network denied, when its record's population needs none. | Proves the tag lookup moved to bake |

### The Seed
----
RID: `req-tap-bake-seed`

Status: `Proposed`

A seed is a full-backup archive ([`spec-tap-backup.md`](spec-tap-backup.md)) taken by the bake from an
instance it has just booted from the record, inside CI, on the product image. Its database is a
`pg_dump -Fc` like every backup's, never a Postgres data directory. A dump restores into a cluster that
already holds the new instance's own role passwords. It is not tied to one Postgres build. And it is
the only form a managed database such as RDS or Aurora can load. (Ruled 2026-11-21: Q11 in the
make-it-fast session.)

Forensic-by-default ([`req-tap-backup-forensic-default`](spec-tap-backup.md#forensic-by-default))
still holds: a seed is a complete archive minus subtractions that are named and recorded in its
manifest, with `by: seed`. The seed's subtractions are fixed, not chosen per bake:

| Removed | Why |
| --- | --- |
| Every human account, external identity and passkey | A seed has no people; the first owner signs in to the new instance |
| Sessions | They belong to logins on the bake instance |
| Task-queue executions, claims and process rows | They belong to the bake's workers |
| Collection jobs, and each schedule's last-fired and enabled-at times | The new instance's schedules start from its own first start |
| The cache table's rows | Derived, and keyed to the bake's state |
| Secret values and the secrets inventory | No secret is ever in a seed |
| Run records and file logs | They describe the bake, not the instance |

The built-in actors, groups and capabilities stay, because `sync_auth` writes the same ones on every
instance.

A seed carries the plugin data directories
([`spec-tap-plugin-data-directory.md`](../tap_plugins/specs/spec-tap-plugin-data-directory.md)) as well
as the database, including directories declared as caches. A seed exists to save the launch from
fetching and rebuilding, so a cache the population filled is part of what it saves. The manifest
records each directory's declared durability.

The bake refuses to write a seed that still holds anything the table removes. Checking the result,
rather than trusting the steps that removed things, is the same rule the backup spec applies to its
secrets leak gate.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-seed-1 | A Dump, Not A Data Directory | Proposed | The seed's database member is a `pg_dump -Fc` archive; no Postgres data directory is ever written into a seed or an image. | Ruled Q11 |
| req-tap-bake-seed-2 | Subtractions Are Fixed And Recorded | Proposed | Every seed's manifest lists each subtraction in the table as `omitted`, `by: seed`, and no other subtraction. | |
| req-tap-bake-seed-3 | Checked, Not Trusted | Proposed | A bake whose instance still holds a human account, session, queue execution, secret value or run record after subtraction refuses to write the seed and names what it found. | Seeded by a test that leaves one of each behind |
| req-tap-bake-seed-4 | Plugin Data Included | Proposed | Every plugin data directory on the bake instance, caches included, is in the seed, with its declared durability in the manifest. | |
| req-tap-bake-seed-5 | Built-ins Kept | Proposed | After a seed boot, the built-in actors, groups and capabilities equal those of a full boot of the same record. | |

### The Seed Key
----
RID: `req-tap-bake-seed-key`

Status: `Proposed`

A seed is valid for one combination only, and its manifest records it:

- the canonical digest of the boot record (`tap/boot_records.py`),
- the digest of the product image it was baked on,
- the Postgres major version of the bake's database.

A seed boot loads a seed only when all three match the instance being started. Matching image
digests is stricter than the backup spec's version gate, and simpler: the image fixes the TAP
version, every plugin's commit and every migration head together. A mismatch is not an error to
override. It means the seed was made for something else, and the instance boots the full way
([`req-tap-bake-seed-boot`](#seed-boot)).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-seed-key-1 | Key Recorded | Proposed | Every seed's manifest carries the record digest, the image digest and the Postgres major version it was baked with. | |
| req-tap-bake-seed-key-2 | Any Mismatch Declines | Proposed | Changing any one of the three makes seed boot decline that seed, naming which part differed, and boot the full way. | Three cases, one per part |
| req-tap-bake-seed-key-3 | No Override | Proposed | No flag or setting makes a seed boot load a seed whose key does not match. | `--force` belongs to restore, not here |

### Attested Artifacts
----
RID: `req-tap-bake-attest`

Status: `Proposed`

The bake publishes the product image and the seed with signed build provenance (GitHub artifact
attestations, as `publish-images.yml` already does for tap-web and tap-db). The seed is published as
an OCI artifact beside the image, so the same registry, the same digests and the same verification
apply to both.

Each artifact's trust anchor is a digest pinned in the deploy config: the compose file for a
Codespace or a session stack, the task definition for a hosted launch. Pinning a digest is a reviewed
change to that config. That pin is the human decision that lets a seed load without a person present
([`req-tap-bake-seed-boot`](#seed-boot)), in the same way the backup spec treats a supplied archive
digest as its anchor ([`req-tap-backup-integrity`](spec-tap-backup.md#member-hashes)). An artifact
reached by tag alone is never loaded.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-attest-1 | Both Attested | Proposed | Every bake publishes provenance for the product image and the seed; `gh attestation verify` succeeds for both against the producing repository. | |
| req-tap-bake-attest-2 | Digest Or Nothing | Proposed | A seed boot given a seed reference with no digest declines it and boots the full way. | |
| req-tap-bake-attest-3 | Wrong Bytes Decline | Proposed | A seed whose fetched bytes do not match the pinned digest is declined before any member is read. | |

### Seed Boot
----
RID: `req-tap-bake-seed-boot`

Status: `Proposed`

Seed boot is the third boot-from-archive mode (`--as-seed`), beside
[restore](spec-tap-backup.md#restore) and [clone](spec-tap-backup.md#clone). It takes the clone's
identity rules, because every instance started from a seed is a new instance:

| | Restore | Clone | Seed |
| --- | --- | --- | --- |
| Started by | A human | A human | The deploy config's pinned seed, at first start |
| Grid id | Kept | New UUIDv7 | New UUIDv7 |
| Lineage | — | `cloned_from` in the run record and a lineage batch | `seeded_from` (seed digest, record digest, time) in the run record and a lineage batch |
| Entity ids | Kept | Kept | Kept |
| `SECRET_KEY` | Restored when available | Always new | Always new, minted by personalize |
| Users and passkeys | Kept | Kept | None; the seed holds none |
| Collector schedules | As captured | Paused | As the record declares |

Schedules run as the record declares, unlike a clone's, because a seed holds no credentials. Two
instances started from one seed are no more duplicates than two instances booted from one record.

Seed boot runs only when the database is **pristine**, as the backup spec defines the word. A
database that already holds the instance, such as a Codespace being restarted, is not a first start:
it boots normally, and the seed is not consulted.

The order, every refusal before any load:

1. Fetch the pinned seed and check its digest ([`req-tap-bake-attest`](#attested-artifacts)).
2. Read it through the checked reader, and check its key ([`req-tap-bake-seed-key`](#the-seed-key)).
3. Check that the database is pristine.
4. Load the dump. Because the target is pristine, the load may run in parallel jobs. A load that
   fails part-way is discarded by dropping and recreating the database before falling back, so it
   stays all-or-nothing ([`req-tap-backup-restore-7`](spec-tap-backup.md#restore)) without needing a
   single transaction.
5. Restore the plugin data directories.
6. Mint the new grid id and write the lineage batch.
7. Run the rest of boot. It is idempotent against the seeded data
   ([`req-boot-idempotent`](spec-tap-boot-v0.md#idempotent-re-apply)), so seeding, vocabulary and
   every population step the seed already holds are skipped.

A population step that re-acts on every boot instead of seeding once, such as `fire-collector`, is
recorded by the bake as already applied. The seed boot then skips it, and a later boot behaves as
that step always does.

**Any refusal or failure falls back to the full boot**: the instance installs, builds its schema and
populates exactly as it does today. The fallback writes a `TAP-WARN` line naming the step that
declined and why, and the run record carries the same reason. A fallback never happens silently, and
it never stops an instance from coming up.

[`req-boot-snapshot-4`](spec-tap-boot-v0.md#pre-migrate-snapshot) and
[`req-tap-backup-restore`](spec-tap-backup.md#restore) keep a restore a human act. A seed boot does not
contradict them, because it restores nothing of the instance's own. It is the first build of a new
instance from a reviewed, pinned artifact.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-seed-boot-1 | New Identity | Proposed | After a seed boot the grid id differs from the bake's, and a lineage batch names the seed digest and the record digest. | |
| req-tap-bake-seed-boot-2 | Pristine Only | Proposed | Given a database holding any user-defined object, boot does not consult the seed and boots normally. | A restart is not a first start |
| req-tap-bake-seed-boot-3 | Same Instance Either Road | Proposed | A seed boot and a full boot of the same record produce the same Gryphon counts by entity type, the same schema (`tap.schema_parity`) and the same recorded migrations. | The end-to-end parity test |
| req-tap-bake-seed-boot-4 | Fallback Is Loud And Complete | Proposed | For each refusal in steps 1 to 4, the instance boots the full way, serves, and its run record and log name the declining step and the reason. | One case per step |
| req-tap-bake-seed-boot-5 | No Half-Seeded Instance | Proposed | A load killed part-way leaves no seeded objects, and the full boot that follows succeeds. | |
| req-tap-bake-seed-boot-6 | Seeded Steps Not Repeated | Proposed | On a seed boot no population step the seed records as applied runs again, `fire-collector` steps included. | |

### Personalize At First Start
----
RID: `req-tap-bake-personalize`

Status: `Proposed`

Personalize gives one instance what must be its own. It runs inside the stack, at the first start of
the instance, before the seed boot. Today the playground's database passwords come from a host-side
`initializeCommand`, and its `SECRET_KEY` from a host file written once. Both are made outside the
container, and a Codespaces prebuild may snapshot either. So personalize makes them inside.

What it mints, each from a CSPRNG (`secrets`):

- `SECRET_KEY`.
- The `tap` database role's password and the `tap_gryphon_ro` search role's password.
- The grid id, through seed boot ([`req-tap-bake-seed-boot`](#seed-boot)).

What it derives from the host: the instance owner and every hostname-dependent value, as
[`req-tap-serving-codespace-5`](spec-tap-serving.md#the-one-click-codespace-is-the-first-deployment)
already does in a Codespace.

**Keyed on the instance's identity.** Personalize stores what it minted on a volume private to the
stack, together with the instance identity it minted them for. On every start it compares that stored
identity with the host's: `CODESPACE_NAME` in a Codespace, the instance id from the metadata service
on a cloud host, a generated id for a local stack. When they differ, or nothing is stored, it mints
everything again and re-keys the database roles with `ALTER ROLE`. This is cloud-init's instance-id
rule. It means a secret captured by a prebuild, an image layer or a copied volume is replaced at the
first start of every instance that inherited it, instead of being shared.

Personalize is idempotent. On a restart of the same instance it changes nothing.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-personalize-1 | Minted Inside | Proposed | In a baked instance, `SECRET_KEY` and both role passwords are created by the stack at first start; no host-side command and no file in the image or repository supplies them. | |
| req-tap-bake-personalize-2 | Two Instances Share Nothing | Proposed | Two instances started from the same image, seed and prebuilt volumes have different `SECRET_KEY`s, role passwords and grid ids. | The prebuild case, simulated by copying volumes |
| req-tap-bake-personalize-3 | Inherited Secrets Replaced | Proposed | Starting with stored secrets minted for a different instance identity re-mints them all, and the old role passwords stop working. | |
| req-tap-bake-personalize-4 | Restart Changes Nothing | Proposed | A second start of the same instance leaves every minted value as it was. | |

### The Crypto Verdict Travels With The Image
----
RID: `req-tap-bake-crypto-bom`

Status: `Proposed`

The crypto-BOM system gate
([`req-fips-crypto-bom-system-gate`](spec-fips.md#boot-time-system-gate)) reads every ELF file in the
venv and `/usr/bin`, and parses every core and plugin source file. Its verdict depends only on those
bytes. In a product image the bake runs the gate, and the image carries the verdict bound to its own
digest and to the venv's stamp.

At boot, when the venv is still the one the image shipped (its stamp matches, and pre-boot installed
nothing), the entrypoint checks the binding instead of rescanning. Anything installed at boot
invalidates the binding, and the full gate runs as today. The gate's refusal rule is unchanged: an
unwaived non-validated provider still stops the instance. Only the time at which the bytes are read
moves.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-crypto-bom-1 | Verdict Baked | Proposed | A product image carries a crypto-BOM verdict naming the image digest and venv stamp it was computed over. | |
| req-tap-bake-crypto-bom-2 | Unchanged Means Checked | Proposed | Booting an unchanged product image checks the binding and does not rescan. | |
| req-tap-bake-crypto-bom-3 | Changed Means Rescanned | Proposed | Installing anything at boot, or a stamp that differs, runs the full gate, which still refuses an unwaived non-validated provider. | |

### One Mechanism, Every Host
----
RID: `req-tap-bake-hosts`

Status: `Proposed`

The artifacts are the same everywhere. Only how they reach the host differs:

- **Codespaces.** Compose names the product image and tap-db with `image:` and digests, never
  `build:`. A prebuild only pulls images (`onCreateCommand`). It makes no secret and starts no
  database. Personalize and the seed boot run at the Codespace's own first start, so a prebuild
  speeds up the pull and shares nothing. Turning prebuilds on is a repository setting that spends
  Actions minutes and storage, so a maintainer makes that call.
- **Local session stacks.** `scripts/spawn-session.sh` accepts a seed reference for a profile that
  has one, and starts from it in place of a full boot.
- **Hosted (AWS and similar).** The product image goes to the host's registry. A one-shot task runs
  personalize and the seed boot against the managed database, with `pg_restore --no-owner`, because
  the managed database's own roles own the objects. To start many instances, a copy-on-write clone of
  one seeded database (Aurora cloning, or `CREATE DATABASE … TEMPLATE` on one host) is followed at
  once by personalize, which re-keys every credential the clone inherited.

Replacing a compromised instance is then the same act as launching one: a new instance from a known,
attested seed, with fresh secrets, in the time a launch takes.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-hosts-1 | Prebuild Makes No Secret | Proposed | A Codespace configuration using this mechanism generates no secret in `initializeCommand`, `onCreateCommand` or `updateContentCommand`. | Enforced by a test over the devcontainer config |
| req-tap-bake-hosts-2 | Spawn Takes A Seed | Proposed | `spawn-session.sh` started with a seed reference serves without running population, and its run record names the seed. | |
| req-tap-bake-hosts-3 | Managed Database Loads | Proposed | A seed boot against a database whose objects must be owned by a role other than the dump's completes with `--no-owner`, and the instance serves. | |
| req-tap-bake-hosts-4 | Clones Re-Keyed | Proposed | An instance started from a copy-on-write clone of a seeded database holds none of the source's role passwords after personalize. | |

### The Launch Is Timed
----
RID: `req-tap-bake-launch-budget`

Status: `Proposed`

A speed claim holds only if it is measured, so every launch measures itself. The run record carries
the duration of each phase from container start: environment, personalize, seed fetch and check,
load, the rest of boot, and first response. It also records which road the instance took, seed or
full.

A product that ships a baked instance states its launch budget in its own spec and proves it on the
real host. The playground's budget is 2 minutes from Codespace creation to the site answering
(target ruled 2026-11-21, Q10 in the make-it-fast session). The 2026-11-21 estimate is 60 to 100 s:

| Phase | Today | Baked (estimate) |
| --- | ---: | ---: |
| Machine and image pull | 170 s | 30 to 60 s, prebuilt |
| Plugin install | 68 s | about 5 s |
| Crypto gate | 12 s | about 1 s |
| Schema and population | 149 s | 10 to 15 s (a 15-plugin schema dump restores in 5 s on 12 cores) |
| Personalize | — | about 5 s |
| Django start-up and first response | inside the schema phase | 10 to 20 s |

Two of those figures are not measured yet: what a prebuild saves for a compose-based devcontainer,
and Django start-up with about 2,000 models.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-launch-budget-1 | Phases Recorded | Proposed | Every run record of a baked instance carries each phase's duration and the road taken. | |
| req-tap-bake-launch-budget-2 | Playground Under Two Minutes | Proposed | A fresh rampart-20x-playground Codespace, created from the repository's default branch, answers on its forwarded port within 120 s of creation, measured on a real Codespace and recorded with the run. | The X1 target |

#### Future

- **A data-directory fast path.** Shipping a Postgres data directory would save the load, an
  estimated 10 s. It was ruled out for now (Q11) because it bakes in role passwords and is tied to one
  Postgres build. Revisit it only if a measured launch misses its budget because of the load.
- **Memory snapshots** (Firecracker or CRIU, as Fly.io's suspend and resume does). They could remove
  Django start-up too, but they bring the uniqueness problems this spec avoids, and Fly does not
  guarantee a snapshot survives. Both roads would still be needed.
- **Seed freshness.** The playground's mock data carries absolute dates, so a seed baked once looks
  older every day. A scheduled re-bake keeps it current at no launch-time cost.
