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

Most of that work produces the same result on every launch. Population imports static JSON with
fixed batch and entity ids. The schema is a function of the plugin set. The crypto-BOM scan is a
function of the image's bytes. None of that depends on who launched the instance or where. The first
impression matters most for a demo: a visitor who waits seven minutes is entitled to doubt the rest.
And for an operator replacing a compromised instance, rebuild time is time spent exposed.

This spec moves that work from launch time to build time. It describes one lifecycle, the same on
every host:

**build artifacts → initialize an installation once → start serving processes cheaply → upgrade
deliberately.**

- **Build**, once, in CI. It produces a **product image**: an immutable environment with the record's
  plugins already installed. It also produces a **seed**: the database, plugin data and stored files
  of an instance that has just finished the bakeable part of its boot. Neither artifact holds a
  secret or anything that belongs to one installation.
- **Initialize**, once per logical installation, by a single serialized initializer. It loads the
  seed and **activates** the result as a new installation with its own identity and secrets. Then it
  runs whatever part of boot belongs after activation.
- **Serve.** Serving processes check that the installation is initialized and start Django. They
  never mint identity, load data or migrate, so a replica or a replacement host starts in the time
  Django takes to start.
- **Upgrade**, deliberately, through the initializer, as today's migrate path does.

Five convictions shape the requirements below.

**Nothing installation-specific is baked.** A value made at build time is shared by everything made
from the artifact. AWS Lambda SnapStart documents this for restored snapshots ("content generated
during initialization might not be unique"). Windows sysprep and cloud-init exist for the same
reason. So the build mints no secret, and an installation never trusts a secret it did not mint.

**Identity belongs to the installation, not the machine.** A Codespace is one host and one
installation. A hosted TAP behind several replicas is one installation on many hosts, and a host
replaced after a failure is still the same installation. Hosts come and go; an installation's grid
id, secrets and roles stay until someone deliberately changes them.

**A seed is not a backup restore.** [`spec-tap-backup.md`](spec-tap-backup.md) keeps restoring an
instance's own data a deliberate human act, and this spec does not weaken that rule. A seed is a
reviewed, pinned artifact that new installations start from. It is closer to an image than to a
backup.

**Both roads always work, and neither leaves debris.** A seed that fails any check is set aside,
loudly, and the installation is initialized the full way, as today. An initialization interrupted at
any point resumes or starts over cleanly, across every store it writes. It never leaves an
installation whose database says one thing and whose files say another.

**One lifecycle, every host.** The same artifacts and the same initializer serve a Codespace, a local
session stack, a hosted installation on AWS, and replicas behind a load balancer. Only how the
artifacts reach the host, and where the installation keeps its secrets, differ. Nothing in build,
initialize or serve names a product.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Launch In Seconds | A baked installation serves within a measured budget, and the playground Codespace's budget is under 2 minutes from creation, once the measurements in [`req-tap-bake-launch-budget`](#the-launch-is-timed) show it is reachable. |
| 2. | Nothing Shared Between Installations | No secret, credential, session or person crosses from the build into an installation, and every installation has its own identity and roles. |
| 3. | Proven Artifacts | The image and the seed are attested in CI, keyed to exactly what built them, and checked before an installation trusts them. |
| 4. | Always A Way Up | A refused seed falls back to the full initialization, and an interrupted one resumes or restarts cleanly; both are recorded and visible. |
| 5. | Any Product, Any Host, Any Scale | Build and initialize take a boot record as input and name no product; one installation may have many serving processes. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-bake-lifecycle | [Build, Initialize Once, Serve](#build-initialize-once-serve) | Proposed | The lifecycle and its names; where a seed sits beside export, backup and frozen containers |
| req-tap-bake-product-image | [The Product Image](#the-product-image) | In Development | `FROM tap-web@digest`; a manifest ties each source commit to its wheel digest and installed distribution |
| req-tap-bake-immutable-env | [The Deployed Environment Is The Image's](#the-deployed-environment-is-the-images) | In Development | Deployments run the image's venv directly, with no venv volume; development keeps today's |
| req-tap-bake-bakeable | [What May Be Baked](#what-may-be-baked) | Proposed | Each population step is bakeable or post-activation; completion is recorded in the database and read before preflight |
| req-tap-bake-seed | [The Seed](#the-seed) | Proposed | Database dump, plugin data and file store from a CI instance, with fixed recorded subtractions |
| req-tap-bake-seed-key | [The Seed Key](#the-seed-key) | Proposed | Record digest, image digest and Postgres major; a seed loads only where all three match |
| req-tap-bake-attest | [Attested Artifacts](#attested-artifacts) | In Development | Detached attestations bound to final digests; the deploy config pins the seed |
| req-tap-bake-initializer | [One Initializer Per Installation](#one-initializer-per-installation) | In Development | Serialized, staged, with durable progress; interruption at any phase resumes or restarts cleanly |
| req-tap-bake-activate | [Activating A New Installation](#activating-a-new-installation) | In Development | Separate from loading: new grid id, lineage, secrets and per-installation roles, for a seed load or a clone |
| req-tap-bake-installation-identity | [Identity Belongs To The Installation](#identity-belongs-to-the-installation) | In Development | Secrets live in the installation's store; replicas and replacement hosts consume them, never rotate them |
| req-tap-bake-crypto-bom | [The Crypto Verdict Travels With The Image](#the-crypto-verdict-travels-with-the-image) | Proposed | Scan at build, attested against the final image digest and the policy inputs; runtime self-check kept |
| req-tap-bake-startup | [Django Starts Once](#django-starts-once) | Proposed | One initializer process instead of several; import cost profiled; preloading decided deliberately |
| req-tap-bake-hosts | [One Lifecycle, Every Host](#one-lifecycle-every-host) | Proposed | Codespaces, `spawn-session.sh`, dedicated managed Postgres, shared clusters, replicas |
| req-tap-bake-launch-budget | [The Launch Is Timed](#the-launch-is-timed) | Proposed | Every phase timed; the Codespaces infrastructure phase is measured before the seed is built |

### Build, Initialize Once, Serve
----
RID: `req-tap-bake-lifecycle`

Status: `Proposed`

This spec uses these names and no others:

- **Build** (or bake): the CI job that turns a boot record and a tap image digest into a product image
  and a seed.
- **Product image**: the tap-web image plus the record's plugins and its manifest
  ([`req-tap-bake-product-image`](#the-product-image)).
- **Seed**: the archive of a freshly built instance that new installations start from
  ([`req-tap-bake-seed`](#the-seed)).
- **Installation**: one logical TAP instance. It has one grid id, one set of secrets and its own
  database roles, and any number of hosts serving it over its lifetime.
- **Initializer**: the single process that takes an installation from empty to ready
  ([`req-tap-bake-initializer`](#one-initializer-per-installation)). It has three parts:
  - **Load**: placing the seed's contents into the installation's empty stores.
  - **Activate**: making the loaded or cloned state a new installation
    ([`req-tap-bake-activate`](#activating-a-new-installation)).
  - **Finish**: the post-activation part of boot.
- **Serving process**: a gunicorn worker, queue worker or similar. It reads the installation's state
  and never changes its identity.

[`req-tap-backup-tiers`](spec-tap-backup.md#three-tiers-one-name-each) names three ways to carry an
instance: export, full backup and frozen containers. A seed uses the full-backup archive format, so
it shares that tier's manifest, integrity rules and leak gate. Its boot is a third mode beside
restore and clone, not a fourth tier. The backup spec's archive reader, manifest and restore are
still Proposed, so this spec depends on building them. The shared part built first is the narrowest
one a seed needs: the checked reader, the manifest schema, the database member, and the plugin-data
and file-store members. Restore and clone can come later.

The build runs the normal boot to produce the seed, stopping where
[`req-tap-bake-bakeable`](#what-may-be-baked) says the bakeable part ends. No population path exists
only for the build, and the build does nothing a real boot would not.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-lifecycle-1 | Same Boot, Earlier | Proposed | The build produces its seed by running `manage.py boot` on the record, through the bakeable steps only, with no step a full boot of the record does not also run. | A seed can only hold what a real boot writes |
| req-tap-bake-lifecycle-2 | No Product Named | Proposed | The build job, the initializer and the serving start-up take the record and the image digest as inputs, and no product name, slug or repository appears in their code. | Enforced by a test over those modules |
| req-tap-bake-lifecycle-3 | Archive Format Shared | Proposed | A seed validates against the full-backup manifest schema, and is read only through the backup spec's checked reader ([`req-tap-backup-safe-read`](spec-tap-backup.md#safe-archive-reading)). | That reader is built as part of this work |
| req-tap-bake-lifecycle-4 | Serving Never Initializes | Proposed | A serving process started against an uninitialized installation waits or exits, naming the initializer; it never loads, activates or migrates. | |

### The Product Image
----
RID: `req-tap-bake-product-image`

Status: `In Development`

A product image is built `FROM ghcr.io/unified-systems-com/tap-web@<digest>`, never from a tag. The
build makes a wheel from each plugin's pinned commit and resolves the whole dependency closure. It
installs all of it into the image's environment.

The image carries an **install manifest** that ties every plugin, and every distribution in the
closure, together as **source commit → wheel digest → installed distribution and version**. The image
also carries the boot record it was built from, and the record's digest.

Pre-boot today decides a git plugin is satisfied from the PEP 610 `direct_url.json` VCS commit of a
git install (`_installed_git_rev` in `tap/preboot.py`). A plugin installed from a wheel carries no
VCS metadata, so that check would reinstall correct code. In a product image, pre-boot decides
satisfaction from the install manifest instead. It checks each installed distribution's version and
`RECORD` hash against its manifest entry, and the manifest entry's commit against the record's pin.
The existing wheelhouse digest check (`_verify_wheelhouse_digest`) covers one wheel's bytes against
one coordinate. The manifest extends that to the closure.

Nothing about the image is product-specific apart from its record and the plugins that record
names. A product publishes its image under its own name, attested
([`req-tap-bake-attest`](#attested-artifacts)), and its deploy config pins it by digest.

**As built (tap#1322).**

- **Recipe.** `docker/product-image.Dockerfile` is shipped inside tap-web at
  `/app/docker/product-image.Dockerfile`. A product's build reads it from the base it builds on,
  so the recipe and the builder always come from the same release.
- **Bake stage.** It runs `docker/bake-product-image.sh` as the image's unprivileged user, in
  four steps:
  1. Verify the wheel-cache seed.
  2. Run `uv sync --frozen --all-packages`.
  3. Run `python -m tap.product_image build`, which fetches each plugin at its pinned commit and
     tag, builds a wheel, compiles the closure with hashes against the installed core, and
     installs both with `--no-deps`.
  4. Run pre-boot in product-image mode, so a record the image cannot satisfy fails the build.
- **What start checks.** Pre-boot checks every file of every record plugin against its RECORD and
  the manifest. The core, workspace and closure distributions are recorded too, but start does not
  hash them; they are protected by being root-owned in the image and by the entrypoint refusing any
  mount over `/app`, `/app/.venv` or `/app/tap-product`.
- **Final stage.** It copies the venv, the manifest and the record in, owned by root.
- **Publishing.** `.github/workflows/bake-product-image.yml` is a reusable workflow. It builds
  amd64 and arm64, tags the index `in-<inputs digest>` and `sha-<caller commit>`, and attests it.
- **Measured locally, 2026-11-22.** Product image against tap-web 0.4.5, both booting the
  playground's 15-plugin record on a fresh database on a 12-core host:
  - Start to listening: 92.9 s against 136.1 s. The environment phase fell from about 45 s to
    about 3 s.
  - `manage.py boot`: 57.6 s against 73.9 s.
  - The image's own build took 51 s, and it adds 346 MB to the base.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-product-image-1 | Pinned Base | Implemented | The product image's `FROM` line names tap-web by digest; a tag-only base is refused by the build. | `tap/product_image.py` `require_digest_ref`, run by the build and again by the reusable workflow |
| req-tap-bake-product-image-2 | Manifest Covers The Closure | Implemented | Every installed distribution in the image appears in the install manifest with its source commit (for plugins), wheel digest and version, and the build fails if any is missing or extra. | Core digests from `uv.lock`, the plugin closure's from a hashed `uv pip compile`, each plugin's wheel sha256 and commit; tap#1322 |
| req-tap-bake-product-image-3 | Satisfied By Manifest | Implemented | Pre-boot in a product image reports every record plugin satisfied from the manifest and installs nothing; changing one installed file's bytes makes it report that distribution unsatisfied. | The wheel-has-no-VCS-metadata gap; checked per file against RECORD, whose own digest is in the manifest |

### The Deployed Environment Is The Image's
----
RID: `req-tap-bake-immutable-env`

Status: `In Development`

A deployed product image runs the environment it ships, and its processes call that environment's
executables directly (`/app/.venv/bin/python`, `gunicorn`). No venv volume is mounted over it, and
`uv sync` and plugin installs don't run at start. This is uv's own recommended pattern for deploying
in containers.

Today's compose stack mounts a named, writable venv volume over `/app/.venv` (`docker-compose.yml`),
and the entrypoint keeps that volume honest at every start:

- it clears the volume when it was stamped by another image;
- it runs `uv sync --all-packages`, an exact sync that would remove packages installed outside the
  lock;
- pre-boot looks up each git plugin's tag over the network, even when the plugin is satisfied.

That machinery is right for development, where the source tree is bind-mounted and plugins change
under a running stack, and it stays there. A deployment profile turns all of it off. Each tag lookup
then happens once, at build time, and its result is recorded in the manifest.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-immutable-env-1 | No Venv Volume, Read-Only Root | Proposed | A deployment compose file or task definition for a product image mounts no volume at `/app/.venv` and no bind mount over application source, and runs the container with a read-only root filesystem; writable paths are named volumes or tmpfs. | Enforced by a test over the shipped deploy configs |
| req-tap-bake-immutable-env-2 | Nothing Installed At Start | Implemented | A deployed product image starts to serving without running `uv sync` or any package install. | Entrypoint product-image mode: no seed, clear or `uv sync`, `UV_NO_SYNC`, a venv mount refused; measured locally 2026-11-22, environment phase about 3 s against about 45 s |
| req-tap-bake-immutable-env-3 | No Network To Start | Proposed | A deployed product image starts to serving with outbound network denied, when its record's post-activation steps need none. | Proves the tag lookup moved to build |
| req-tap-bake-immutable-env-4 | Development Unchanged | Implemented | A session stack started by `spawn-session.sh` without a product image keeps the venv volume, the stamp check and the sync exactly as before. | The mode switches on the baked manifest alone, which no development tree has |

### What May Be Baked
----
RID: `req-tap-bake-bakeable`

Status: `Proposed`

The playground's population is the same on every launch, but TAP boot in general is not. A record can
fire collectors that use external credentials and observe one installation's world. Baking that
output would either hand one installation's observations to every other, or mark collection done for
an installation that never collected. So each population step in a record is one of two kinds:

- **Bakeable**: its result depends only on the record and the installed plugins. Seed-plugin GRIFT
  imports, vocabulary and schedule creation are bakeable.
- **Post-activation**: it observes, uses credentials, or reaches the network. It runs in the
  installation's Finish step, never in the build. `fire-collector` is post-activation unless its step
  declares `bakeable: true` and its collector declares itself local and credential-free. The
  playground's `fedramp_20x_vdr:vdr_max` qualifies on both counts.

A step's completion is recorded **in the database**, as a row the seed carries: the step's identity
within the record, the record digest, and when it completed. Run records don't serve, because the
seed drops them. Boot reads these rows **before** it resolves, preflights or parses anything for a
step. A completed bakeable step then costs one query: no collector preflight, no bundle read and no
GRIFT parse. Today's GRIFT idempotence prevents duplicate writes but still repeats the reading and
the preflight; this removes them.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-bakeable-1 | Every Step Classified | Proposed | Boot refuses a record used for a build if any population step's kind cannot be determined, naming the step. | |
| req-tap-bake-bakeable-2 | Observation Never Baked | Proposed | A build of a record with a credentialed or networked `fire-collector` step produces a seed with no output from that step, and that step runs in the installation's Finish. | |
| req-tap-bake-bakeable-3 | Completion Read First | Proposed | On a seeded installation, no completed bakeable step runs a collector preflight, opens a bundle file or parses GRIFT. | Asserted by instrumenting those three calls |
| req-tap-bake-bakeable-4 | Completion Survives The Seed | Proposed | Step-completion rows are in the database member of every seed, and are not removed by the seed's subtractions. | |

### The Seed
----
RID: `req-tap-bake-seed`

Status: `Proposed`

A seed is a full-backup archive ([`spec-tap-backup.md`](spec-tap-backup.md)) that the build takes from
an instance it has just taken through the bakeable steps, inside CI, on the product image. It holds
three stores:

- **The database**, as a `pg_dump -Fc`, never a Postgres data directory. A dump loads into a cluster
  that already holds the installation's own roles, is not tied to one Postgres build, and is the only
  form a managed database such as RDS or Aurora can load. (Ruled 2026-11-21: Q11 in the make-it-fast
  session.)
- **The plugin data directories**
  ([`spec-tap-plugin-data-directory.md`](../tap_plugins/specs/spec-tap-plugin-data-directory.md)),
  caches included, with each one's declared durability in the manifest. A cache the population
  filled is part of what a seed saves the launch from fetching.
- **The file store** ([`spec-tap-file-store.md`](spec-tap-file-store.md)): the OCFL storage root that
  holds the bytes of every file entity. Graph rows without their files would look valid and be
  broken, and neither schema parity nor entity counts would notice. Until the seed can carry the file
  store, the build **refuses** a record whose bakeable steps store any file, naming the step.

Forensic-by-default ([`req-tap-backup-forensic-default`](spec-tap-backup.md#forensic-by-default))
still holds: a seed is a complete archive minus subtractions that are named and recorded in its
manifest, with `by: seed`. The subtractions are fixed, not chosen per build:

| Removed | Why |
| --- | --- |
| Every human account, external identity and passkey | A seed has no people; the first owner signs in to the new installation |
| Sessions | They belong to logins on the build instance |
| Task-queue executions, claims and process rows | They belong to the build's workers |
| Collection jobs, and each schedule's last-fired and enabled-at times | The installation's schedules start from its own activation |
| The cache table's rows | Derived, and keyed to the build's state |
| Secret values and the secrets inventory | No secret is ever in a seed |
| Run records and file logs | They describe the build, not the installation |

The built-in actors, groups and capabilities stay, because `sync_auth` writes the same ones on every
instance. The step-completion rows stay ([`req-tap-bake-bakeable`](#what-may-be-baked)).

The build then checks the result rather than trusting the steps that removed things. A seed that
still holds anything in the table is refused, and so is any member the backup spec's archive-wide
credential leak gate flags, plugin data and file store included.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-seed-1 | A Dump, Not A Data Directory | Proposed | The seed's database member is a `pg_dump -Fc` archive; no Postgres data directory is ever written into a seed or an image. | Ruled Q11 |
| req-tap-bake-seed-2 | Subtractions Are Fixed And Recorded | Proposed | Every seed's manifest lists each subtraction in the table as `omitted`, `by: seed`, and no other subtraction. | |
| req-tap-bake-seed-3 | Checked, Not Trusted | Proposed | A build whose instance still holds a human account, session, queue execution, secret value or run record after subtraction, or whose archive the leak gate flags, writes no seed and names what it found. | Seeded by a test that leaves one of each behind |
| req-tap-bake-seed-4 | Every Store Carried | Proposed | A seed holds the database, every plugin data directory and the file store of its build instance, each listed in the manifest. | |
| req-tap-bake-seed-5 | No Files Without Their Store | Proposed | Until the file-store member is built, a build whose bakeable steps hold any file entity refuses and names the step. | |
| req-tap-bake-seed-6 | Built-ins Kept | Proposed | After a seeded initialization, the built-in actors, groups and capabilities equal those of a full boot of the same record. | |

### The Seed Key
----
RID: `req-tap-bake-seed-key`

Status: `Proposed`

A seed is valid for one combination only, and its manifest records it:

- the canonical digest of the boot record (`tap/boot_records.py`),
- the digest of the product image it was built on,
- the Postgres major version of the build's database.

The initializer loads a seed only when all three match the installation being initialized. Matching
image digests is stricter than the backup spec's version gate, and simpler: the image fixes the TAP
version, every plugin's commit and every migration head together. A mismatch is not an error to
override. It means the seed was made for something else, and the installation is initialized the
full way.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-seed-key-1 | Key Recorded | Proposed | Every seed's manifest carries the record digest, the image digest and the Postgres major version it was built with. | |
| req-tap-bake-seed-key-2 | Any Mismatch Declines | Proposed | Changing any one of the three makes the initializer decline that seed, naming which part differed, and initialize the full way. | Three cases, one per part |
| req-tap-bake-seed-key-3 | No Override | Proposed | No flag or setting makes the initializer load a seed whose key does not match. | `--force` belongs to restore, not here |

### Attested Artifacts
----
RID: `req-tap-bake-attest`

Status: `In Development`

The build publishes the product image and the seed with signed build provenance: GitHub artifact
attestations, as `publish-images.yml` already does for tap-web and tap-db. The seed is published as an
OCI artifact beside the image, so the same registry, the same digests and the same verification
apply to both.

An image cannot contain its own final digest, because writing the digest in would change it. So
anything that must name the image's digest, such as the crypto verdict
([`req-tap-bake-crypto-bom`](#the-crypto-verdict-travels-with-the-image)), is a **detached**
attestation whose subject is the finished image. The same holds for the seed key's image digest: the
seed names the image, and the image does not name its seed.

Verification constrains **who** signed, not only which repository. Several workflows in a repository
can hold `id-token: write` (tap has four), and any of them could request an attestation. So an artifact
is accepted only when its attestation was issued by the one build workflow named for it
(`--signer-workflow`), from a protected ref: the default branch or a release tag. An attestation from
any other workflow or ref is treated as none.

Each artifact's trust anchor is a digest pinned in the deploy config: the compose file for a
Codespace or a session stack, the task definition or manifest for a hosted installation. Pinning a
digest is a reviewed change to that config. That pin is the human decision that lets a seed load
without a person present, in the same way the backup spec treats a supplied archive digest as its
anchor ([`req-tap-backup-integrity`](spec-tap-backup.md#member-hashes)). An artifact reached by tag
alone is never loaded.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-attest-1 | Both Attested By The Build | Proposed | Every build publishes provenance for the product image and the seed, and verification requires the named build workflow as signer and a protected source ref; an attestation for the same digest from another workflow or an unprotected ref fails verification. | |
| req-tap-bake-attest-2 | Detached, Not Embedded | Proposed | No file inside a product image claims to state that image's own digest; every image-digest binding is an attestation on the finished image. | |
| req-tap-bake-attest-3 | Digest Or Nothing | Proposed | An initializer given a seed reference with no digest declines it and initializes the full way. | |
| req-tap-bake-attest-4 | Wrong Bytes Decline | Proposed | A seed whose fetched bytes do not match the pinned digest is declined before any member is read. | |

### One Initializer Per Installation
----
RID: `req-tap-bake-initializer`

Status: `In Development`

One initializer takes an installation from empty to ready. It is the only thing that loads, activates
or migrates, and only one runs per installation at a time. A second initializer started meanwhile (a
second replica, or a restarted container) waits rather than racing it. Per-pod init containers don't
provide that on their own, because each pod would run its own.

**The lock lives outside the database it protects.** The initializer holds a session advisory lock,
keyed on the installation's database name, on a connection to the cluster's maintenance database
(`postgres`, which every cluster and managed service provides). It holds that lock for its whole run.
Dropping and recreating the installation's database, which recovering a failed load requires, cannot
happen while a session is connected to it, and closing that session would release a lock held there.
A lock held in the maintenance database survives the target being replaced.

**Progress is durable, and recorded before each phase starts as well as after it ends.** The
initializer writes its progress to the installation's state store, beside its secrets
([`req-tap-bake-installation-identity`](#identity-belongs-to-the-installation)). The record lives
there, not in the database, because the database is the thing a failed load discards. Each phase is
written as `started` before its first write and `done` after its last, for `load`, `files`,
`activate` and `finish`. A copy of the record goes into the database once activation completes, so
serving processes can check readiness without reading the state store. Every write that crosses
stores is staged:

1. **Load the database** into the empty database. Because the target is pristine, the load may run in
   parallel jobs. A load that fails part-way is discarded by dropping and recreating the database, so
   it stays all-or-nothing ([`req-tap-backup-restore-7`](spec-tap-backup.md#restore)) without a single
   transaction.
2. **Stage the files.** Plugin data and the file store are unpacked into staging directories beside
   their final roots, verified against the manifest's hashes, and only then renamed into place. A
   rename within one filesystem is atomic, so each root holds either nothing from the seed or all of
   it. The roots can sit on different volumes, so renaming them all is not one atomic step. Each root
   therefore commits separately:
   - The staging directory carries a marker, `.tap-seed`, naming the seed digest and the root.
   - The progress record names each root as `done` after its rename.
   - A restart in `files` treats any root not marked `done` that holds a `.tap-seed` marker as a
     partial result of this load. It empties that root and stages it again. A root whose contents
     carry no marker is not the seed's, so the initializer refuses rather than delete it.
3. **Activate** ([`req-tap-bake-activate`](#activating-a-new-installation)).
4. **Finish**: the post-activation steps and the rest of boot, which is idempotent against seeded
   data ([`req-boot-idempotent`](spec-tap-boot-v0.md#idempotent-re-apply)).

A restarted initializer reads the progress record and resumes after the last phase marked `done`.
A phase marked `started` but not `done` was interrupted: its partial writes are discarded and it
runs again. It never runs Finish against stores that disagree about what was loaded.

Before anything else the initializer classifies the stores, and each class has exactly one road:

| The stores hold | Road |
| --- | --- |
| Nothing (pristine, as the backup spec defines the word) | Seed load, or the full initialization if the seed is declined |
| A declared clone not yet activated | Activation, then Finish |
| Whatever the progress record names as `started` but not `done` | Discard that phase's partial writes and repeat it: for `load`, drop and recreate the database, then load again; for `files`, remove the staging directories, then stage again ([`req-tap-bake-initializer-2`](#one-initializer-per-installation)) |
| An activated installation, or a TAP installation made by a boot before this initializer existed | Finish only, which is today's boot of an existing installation |
| Anything else: objects but no TAP schema, or a partial TAP schema with no progress record naming a phase in flight | **Refuse, writing nothing**, and name what was found |

The seed is consulted only in the first row. A Codespace being restarted is in the fourth row and goes
straight to Finish.

**Any refusal of the seed itself falls back to the full initialization of the pristine stores**:
pre-boot, schema and every population step, as today. A refusal is a bad digest, a key mismatch or a
refusal from the checked reader. A non-pristine target is never a reason to fall back: it is classified
above, and an unknown one is refused rather than initialized. The fallback writes a `TAP-WARN` line naming what declined and why,
and the run record carries the same reason. A fallback is never silent, and it never stops an
installation from coming up.

[`req-boot-snapshot-4`](spec-tap-boot-v0.md#pre-migrate-snapshot) and
[`req-tap-backup-restore`](spec-tap-backup.md#restore) keep a restore a human act. Seeding does not
contradict them, because it restores nothing of the installation's own. It is the first build of a
new installation from a reviewed, pinned artifact.

**As built, first slice (tap#1328).** `tap/initialize.py` is settings-free. The entrypoint runs it
first, in a product image whose deploy config sets `TAP_INSTALLATION_DIR` to a mounted volume.

- **State store.** The volume holds `identity.json`, mode 0600: the secret key, the owner and search
  role passwords, the grid id, an activation id, a status and per-phase progress. The image prepares
  the mount point as `nonroot`, mode 0700, so a fresh named volume takes that owner and mode.
- **Classification.** The roads built so far are activate (an empty database with no identity),
  resume (a pending identity) and Finish (an active identity whose stamp matches the database).
  Everything else is refused, including a TAP database with no identity: adopting a database made
  without the initializer is not built yet. Activation stamps the database with its activation id,
  as a database comment, so a volume and a database from different installations are told apart.
- **The lock.** It covers activation, the entrypoint's schema steps (`tap.initialize locked --`)
  and Finish, so a second start waits rather than migrating, booting or issuing alongside the first.
- **Finish.** `tap.initialize finish` runs `manage.py boot`, then records `finish: done`; a failed
  boot is fatal. On the first activation only, it records `issuing`, then prints a one-time
  `enroll_admin` link, so a crash can never issue a second one. Where an instance owner is named, as
  in a Codespace, it records `owner` and issues no link.
- **Not built yet.** The seed rows, clone activation and per-installation role names.
- **Measured locally, 2026-11-22.** The playground's 15-plugin record, with no seed, on a compose file
  carrying only a bootstrap password. From `compose up` to HTTP 302, with one admin link printed: 107.6
  s on Docker and 113.5 s on rootless Podman, on a shared 12-core host.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-initializer-1 | One At A Time | In Development | Two initializers started together against one installation complete as one: one does the work, the other waits and then finds it done, including while the first drops and recreates the installation's database. | The lock is in the maintenance database; Two concurrent `tap.initialize run`s on one installation: one activated, one waited and took Finish (tap#1328); the drop-and-recreate case waits for the seed |
| req-tap-bake-initializer-8 | In-Flight Recorded First | Proposed | Killing the initializer after `pg_restore` has created some tables but before it finished, then restarting it, drops and reloads the database instead of refusing it, because the progress record names `load` as started. | The crash the classification would otherwise refuse |
| req-tap-bake-initializer-2 | Interrupted Anywhere | Proposed | Killing the initializer during each phase in turn (load, file staging, activation, Finish), then restarting it, yields an installation equal to an uninterrupted one. | One case per phase; the parity check of -4 |
| req-tap-bake-initializer-9 | Roots Commit Separately | Proposed | Killing the initializer after the first of several file roots is renamed into place, then restarting it, leaves every root holding exactly the seed's contents once; a root holding files without a `.tap-seed` marker is refused, not emptied. | |
| req-tap-bake-initializer-3 | Files Atomic | Proposed | After an interruption during file staging, each file root holds either nothing from the seed or all of it, verified against the manifest. | |
| req-tap-bake-initializer-4 | Same Installation Either Road | Proposed | A seeded and a full initialization of the same record produce the same Gryphon counts by entity type, the same schema (`tap.schema_parity`), the same recorded migrations, and the same file-store inventory and plugin-data hashes. | |
| req-tap-bake-initializer-5 | Fallback Is Loud And Complete | Proposed | For each seed refusal named above, the pristine installation initializes the full way and serves, and its run record and log name what declined and why. | One case per refusal |
| req-tap-bake-initializer-7 | Unknown Stores Refused | Implemented | Given a database holding an unrelated table, or a partial TAP schema with no progress row, the initializer exits non-zero naming what it found, and no migration, load or population write occurs. | `tap.initialize.classify`; on a real database an unrelated table was refused and the state volume left empty |
| req-tap-bake-initializer-6 | Restart Skips To Finish | Implemented | Starting an already-initialized installation runs neither load nor activation, and leaves its identity unchanged. | A restart took the Finish road with the same grid id and printed no second admin link |

### Activating A New Installation
----
RID: `req-tap-bake-activate`

Status: `In Development`

Loading state and activating a new installation are separate steps. A seed load ends with an
unactivated installation, and so does a copy-on-write clone of an activated one: a clone holds its
source's grid id, lineage and role grants until it is activated. Activation is the one step that makes
the state somebody's. It applies to both:

| | Restore | Clone (backup spec) | Activation |
| --- | --- | --- | --- |
| Started by | A human | A human | The initializer, for a pinned seed or a declared clone |
| Grid id | Kept | New UUIDv7 | New UUIDv7 |
| Lineage | — | `cloned_from` in the run record and a lineage batch | `seeded_from` or `cloned_from` (source digest or grid id, record digest, time) in the run record and a lineage batch |
| Entity ids | Kept | Kept | Kept |
| `SECRET_KEY` | Restored when available | Always new | Always new |
| Database roles | As captured | As captured | The installation's own, created or re-keyed for it |
| Users and passkeys | Kept | Kept | Seed: none. Clone: kept only when the operator declares the clone keeps people |
| Collector schedules | As captured | Paused | As the record declares for a seed; paused for a clone |

The installation's state records activation, with the grid id it minted. The initializer never
activates an installation twice.

**Activation is recoverable because it mints first and writes second.** Activation touches several
stores that commit independently: the grid id and lineage in the database, the role passwords in the
cluster, and the secrets in the secret store. So it never mints a value at the moment it writes one:

1. It mints every value at once (grid id, `SECRET_KEY`, role passwords, an activation id) and writes
   them to the installation's state store as `pending`, before anything else changes. From then on
   the state store is the source of truth for those values.
2. It applies each one idempotently from the stored value. Role passwords are set with `ALTER ROLE`
   to the stored password, and setting the same password again changes nothing. The grid id and the
   lineage batch are written insert-if-absent, keyed on the activation id. Secrets are copied to the
   secret store as the stored value.
3. It marks the values `active` and the phase `done`.

A restart that finds `activate: started` re-reads the pending values and re-applies them. It never
mints again, so an interruption between any two writes cannot leave a second password, a second grid
id or a duplicate lineage batch. A clone is declared, by the operator or the hosting tool that made
it, through the installation's initialization input. Its stores are not pristine, so declaring it is
how the initializer knows to activate it rather than treat it as initialized.

**Roles belong to the installation.** Postgres roles are cluster-wide. Several installations in one
cluster therefore never share the fixed `tap` and `tap_gryphon_ro` role names, because re-keying one
installation's role would lock out its siblings. Each installation gets roles named for it, and
ownership is reassigned to them. A cluster that holds one installation, such as a Codespace's or a
dedicated RDS instance, may keep the plain names.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-activate-1 | New Identity | Proposed | After activation the grid id differs from the seed's or the clone source's, and a lineage batch names the source. | |
| req-tap-bake-activate-2 | Clones Activate | Proposed | A declared copy-on-write clone of an activated installation is activated by the initializer even though its stores are not pristine, and afterwards shares no grid id, secret or role password with its source. | |
| req-tap-bake-activate-3 | Once Only | Implemented | Re-running the initializer on an activated installation changes neither its grid id nor its secrets. |  |
| req-tap-bake-activate-5 | Interrupted Activation Reuses Its Values | In Development | Killing the initializer after each activation write in turn (role password, grid id, lineage, secret store), then restarting it, yields one grid id, one lineage batch, and role passwords and secrets that match the state store, with no value minted twice. | One case per write; The owner re-key is applied from the stored value and resumed without minting; the grid id, lineage and secret-store writes arrive with the seed |
| req-tap-bake-activate-4 | Siblings Unaffected | Proposed | Activating an installation in a cluster that hosts another leaves the other's roles, passwords and objects untouched. | |

### Identity Belongs To The Installation
----
RID: `req-tap-bake-installation-identity`

Status: `In Development`

Activation mints the installation's secrets, each from a CSPRNG (`secrets`), and stores them in the
**installation's secret store**:

- `SECRET_KEY`;
- the installation's database role passwords (the owning role, and the search role
  [`req-boot-search-role`](spec-tap-boot-v0.md) re-keys on every boot);
- the grid id, through activation.

Where the store lives depends on the host:

- a volume private to the stack, for Compose and Codespaces;
- the platform's secret manager, for hosted installations (AWS Secrets Manager, Kubernetes Secrets);
- [`TAP_SECRETS_ROOT`](spec-tap-boot-v0.md) where an installation already keeps its secrets.

Every serving process, on every host, reads the secrets from that store. A replica joining the
installation, or a host replacing a failed one, consumes the existing secrets. It never rotates them,
and never mints a grid id. Rotation is a deliberate operator act, not a side effect of a new machine.

A host identity (`CODESPACE_NAME`, an EC2 instance id, a pod name) is therefore never the trigger for
minting. In a Codespace, host and installation coincide, so the Codespace's own first start is its
initialization. What keeps a prebuild from sharing secrets is that a prebuild does no
initialization: it pulls images and creates no installation state
([`req-tap-bake-hosts`](#one-lifecycle-every-host)).

Hostname-dependent values (`ALLOWED_HOSTS`, CSRF origins, `TAP_BASE_URL`) are not identity. They are
derived on each host at each start, as
[`req-tap-serving-codespace-5`](spec-tap-serving.md#the-one-click-codespace-is-the-first-deployment)
does in a Codespace today.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-installation-identity-1 | Minted By Activation | Implemented | `SECRET_KEY` and the role passwords of an activated installation were created by its activation; no host-side command, image layer or repository file supplies them. | The deploy compose file carries only a bootstrap password, refused after the first start's re-key |
| req-tap-bake-installation-identity-2 | Two Installations Share Nothing | Implemented | Two installations initialized from the same image and seed have different `SECRET_KEY`s, role passwords and grid ids. |  |
| req-tap-bake-installation-identity-3 | Replicas Consume | Proposed | Starting a second serving host against an initialized installation changes no secret, role password or grid id, and both hosts serve the same sessions. | |
| req-tap-bake-installation-identity-4 | No Host Trigger | Implemented | Changing the host identity of an initialized installation (a new container, a new hostname, a new `CODESPACE_NAME`) causes no minting. | The initializer reads no host identity; a new container consumed the stored identity |

### The Crypto Verdict Travels With The Image
----
RID: `req-tap-bake-crypto-bom`

Status: `Proposed`

The crypto-BOM system gate
([`req-fips-crypto-bom-system-gate`](spec-fips.md#boot-time-system-gate)) reads every ELF file in the
venv and `/usr/bin`, and parses every core and plugin source file. Its static scan depends on those
bytes and on the waiver policy in the boot record, so the build runs it there. The verdict is a
detached attestation on the finished image ([`req-tap-bake-attest`](#attested-artifacts)), and it
names its inputs: the image digest, the install manifest's digest, and the digest of the record's
waiver policy.

**The scan reads the finished image, not a stage of its build.** The build pushes the image, then
starts a container from the **pushed digest** and runs the gate inside it, then attests the result
against that same digest. Nothing is built or pushed after the scan. Any layer added later produces
a different digest, which the attestation does not name, so the verdict cannot be carried onto bytes
it never read.

At start, a deployed product image ([`req-tap-bake-immutable-env`](#the-deployed-environment-is-the-images))
accepts the attested verdict instead of rescanning only when all of these hold:

- the running image's digest is the attested one;
- **nothing is mounted over any path the scan reads or the interpreter imports from**, by any mount
  type (bind, named volume or tmpfs). That covers the venv, `/usr/bin`, `/usr/lib`, the application
  source and every plugin's source. A deployment declares its writable paths (data directories,
  the file store, logs, `/tmp`), and the initializer refuses the attested verdict if any mount's
  destination is on, under or above a scanned path. A read-only root alone is not enough, because a
  mount replaces what is under it;
- the container's root filesystem is **read-only** (`read_only: true` in compose,
  `readOnlyRootFilesystem` in Kubernetes, `readonlyRootFilesystem` in ECS). An image digest
  authenticates the layers, not a container's writable upper layer, so without this the venv and
  source could change after the container was created;
- the record's waiver policy hashes to the attested digest.

Anything else runs the full gate as today: a development stack, a bind-mounted tree, a changed
waiver, or a verdict that does not verify. A writable venv's stamp is not evidence that the scanned
bytes are unchanged, so it never qualifies.

Two things do not move. The `tap.fips` self-check still runs on every start, because it observes the
live provider state, which no build-time scan can stand in for. And the gate's refusal rule is
unchanged: an unwaived non-validated provider still stops the instance.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-crypto-bom-1 | Verdict Attested | Proposed | Every product image build publishes a crypto-BOM verdict attestation naming the image digest, manifest digest and waiver-policy digest. | |
| req-tap-bake-crypto-bom-2 | Verified Inputs Only | Proposed | A deployed product image whose digest and waiver policy match the attested verdict, with a read-only root and no mount of any type on, under or above a scanned path, skips the rescan. Changing either digest, any such mount (a bind over `/usr/bin`, or a named volume over source included), or a writable root runs the full gate. | The mount check reads `/proc/self/mountinfo`, not the deploy config |
| req-tap-bake-crypto-bom-3 | Self-Check Kept | Proposed | The `tap.fips` self-check runs on every start of every image, attested verdict or not. | |
| req-tap-bake-crypto-bom-5 | Scanned By Digest | Proposed | The build's gate runs in a container started from the image's pushed digest, and the attestation names that digest. An image with any layer added after the scan does not verify against the verdict, and its start runs the full gate. | |
| req-tap-bake-crypto-bom-4 | Refusal Unchanged | Proposed | A product image containing an unwaived non-validated provider fails its build's gate, and if forced past the build, still refuses to serve at start. | |

### Django Starts Once
----
RID: `req-tap-bake-startup`

Status: `Proposed`

A seed saves the schema and the population. It does not save building about 2,000 model classes and
Django's registries, and today's entrypoint pays for that several times over. `createcachetable`, the
schema-mode resolution, `migrate`, the queue supervisor, `boot` and the gunicorn workers each start
their own Django process, one after another. gunicorn runs with `preload_app = False`, and its
configuration notes that a cold import can take tens of seconds (`docker/gunicorn.conf.py`).

So start-up is the next cost after the seed, and it is measured and reduced like the others:

- The initializer runs as **one** Django process. Cache table, schema or load, activation and Finish
  all run in it, instead of one process per step.
- Model import and registration are **profiled** (`python -X importtime`, and timing of
  `apps.populate()`) on the playground record. The profile is recorded with the launch timings.
- The product image ships **compiled bytecode** for its whole environment, so no worker compiles
  sources at start.
- **Preloading** the app in gunicorn's master is decided deliberately, not adopted as a tweak. It
  saves an import per worker, but conflicts with development's code reload and needs every
  import-time side effect checked for safety under fork. It may be on for deployed product images and
  stays off for development.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-startup-1 | One Initializer Process | Proposed | On a deployed product image, the initializer's steps run in a single Python process. | |
| req-tap-bake-startup-2 | Import Cost Recorded | Proposed | The launch timings for a product include the measured Django set-up time for its record, from a profile taken on the target machine class. | |
| req-tap-bake-startup-3 | Bytecode Shipped | Proposed | A product image's environment contains compiled bytecode for every installed module, and starting it writes no `.pyc` file. | |
| req-tap-bake-startup-4 | Preload Decided | Proposed | `preload_app` is set explicitly per image kind, with the fork-safety review recorded for any image that turns it on. | |

### One Lifecycle, Every Host
----
RID: `req-tap-bake-hosts`

Status: `Proposed`

The artifacts and the initializer are the same everywhere. What differs is how the artifacts arrive,
where the secret store lives, and how many hosts serve:

| Host | Initializer | Secret store | Notes |
| --- | --- | --- | --- |
| Codespaces, isolated Compose | The web container's start, once per Codespace | A stack-private volume | A prebuild only pulls images, makes no secret and creates no installation state. Turning prebuilds on is a maintainer's call, because it spends Actions minutes and storage. |
| Local session stacks | `spawn-session.sh`, given a seed reference | The session's secrets root | Development keeps its venv volume ([`req-tap-bake-immutable-env-4`](#the-deployed-environment-is-the-images)) |
| Dedicated managed Postgres (RDS, Aurora) | A one-shot task, then the serving service | The platform's secret manager | `pg_restore --no-owner`, so the managed instance's roles own the objects. Test the managed roles' privileges and the restore's job count against the instance class. |
| Several installations in one cluster | One task per installation | Per installation | Distinct roles per installation ([`req-tap-bake-activate`](#activating-a-new-installation)). For many installations quickly, a template database (`CREATE DATABASE … TEMPLATE`) or Aurora clone per installation, each then declared and activated. |
| Replicas, ECS or Kubernetes, scale to zero | One job per installation, serialized by its advisory lock | The platform's secret manager | Serving pods only read state and secrets. Start-up time is Django's ([`req-tap-bake-startup`](#django-starts-once)). |

Replacing a compromised installation is then the same act as launching one: a new installation from a
known, attested seed, with fresh secrets and roles, in the time a launch takes.

**A Codespace on the initializer's road.** A Codespace whose compose file runs a product image with
`TAP_INSTALLATION_DIR` is an installation like any other, with three Codespace-specific rules in the
entrypoint:

- **The Codespace derivation runs before the initializer.** It needs the Codespace's name, which a
  prebuild never has; it waits, runs out and aborts the container, so a prebuild never reaches the
  initializer and mints nothing that every Codespace made from it would share. The derivation reads
  no Django setting, so running it first costs nothing.
- **The secret key is the initializer's.** The derivation still writes the hostname values and the
  instance owner, but `scripts/codespace-env --no-secret-key` leaves `SECRET_KEY` out and creates no
  key file in the workspace.
- **Boot runs once.** Finish boots the installation under its lock, so the Codespace's own boot step
  stands aside when the installation was initialized.

The instance owner is the first admin, granted on their first sign-in
([`req-tap-serving-codespace-7`](spec-tap-serving.md)), so Finish issues no passkey enrolment link
when `TAP_AUTH_INSTANCE_OWNER` names one: a JSON object with a numeric `user_id`, the shape the
derivation writes. An owner it could not resolve leaves the value empty, and an empty, `{}` or
malformed value names nobody, so the link is issued as on any other host. The compose file then carries only a bootstrap database
password and no generated secret, so the devcontainer's `initializeCommand` generates none either.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-hosts-1 | Prebuild Initializes Nothing | Proposed | A Codespace configuration using this lifecycle generates no secret and starts no database in `initializeCommand`, `onCreateCommand` or `updateContentCommand`. | Enforced by a test over the devcontainer config |
| req-tap-bake-hosts-2 | Spawn Takes A Seed | Proposed | `spawn-session.sh` started with a seed reference serves without running bakeable population, and its run record names the seed. | |
| req-tap-bake-hosts-3 | Managed Database Loads | Proposed | An initialization against a database whose objects must be owned by a role other than the dump's completes with `--no-owner`, and the installation serves. | |
| req-tap-bake-hosts-4 | Replica Start Is Serving Only | Proposed | A second serving host started against an initialized installation reaches serving without taking the initializer lock or writing installation state. | |
| req-tap-bake-hosts-5 | A Codespace Mints At Its Own Start | In Development | In the entrypoint, the Codespace derivation precedes the initializer and aborts when no Codespace name arrives; for an installation it passes `--no-secret-key`, so the key is the initializer's; the Codespace boot step does not run for an initialized installation; and Finish issues no enrolment link when an instance owner is named. | The order and the flags are read from the entrypoint; the derivation and Finish are run in tests |

### The Launch Is Timed
----
RID: `req-tap-bake-launch-budget`

Status: `Proposed`

A speed claim holds only if it is measured, so every launch measures itself. The run record carries
the duration of each phase from container start: environment, initializer lock, seed fetch and check,
load, file staging, activation, Finish, Django set-up and first response. It also records which road
the installation took, seeded or full.

**The infrastructure phase is the budget's hinge.** The plugin, crypto, schema and population phases
add up to 229 s of the playground's 403 s. Removing all of them still leaves 174 s, mostly the 170 s
before the web container starts. So a 2-minute Codespace depends on cutting the infrastructure
phase, and that is measured first, before the seed is built. A spike on a real Codespace, on the
playground's machine size, records:

- creation to container start with and without a prebuild, and on a prebuild miss;
- image download and extraction time for the product image;
- first usable page.

GitHub documents what a prebuild runs (the `onCreateCommand` and `updateContentCommand` lifecycle
steps) but not whether images pulled during it, or compose volumes, survive into a codespace. Only a
real codespace can answer that.

A product that ships a baked installation states its launch budget in its own spec and proves it on
the real host. The playground's target is 2 minutes from Codespace creation to the site answering
(ruled 2026-11-21, Q10 in the make-it-fast session). The spike either confirms it is reachable or
reports how far it misses, before anyone commits to it as a budget. The 2026-11-21 estimate, which the
spike replaces:

| Phase | Today | Baked (estimate) |
| --- | ---: | ---: |
| Machine and image pull | 170 s | 30 to 60 s if a prebuild caches the images; unproven |
| Plugin install | 68 s | 0 |
| Crypto gate | 12 s | about 1 s (the self-check only) |
| Schema and population | 149 s | 10 to 15 s (a 15-plugin schema dump restored in 5 s on 12 cores; not a 4-core measurement) |
| Activation | — | about 5 s |
| Django set-up and first response | inside the schema phase | 10 to 20 s, unmeasured at 2,000 models |

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-bake-launch-budget-1 | Phases Recorded | Proposed | Every run record of a baked installation carries each phase's duration and the road taken. | |
| req-tap-bake-launch-budget-2 | Infrastructure Measured First | Proposed | Before the seed is built, a real-Codespace spike records creation-to-container-start with a prebuild hit, a miss and none, plus image pull and extraction, on the playground's machine size. | |
| req-tap-bake-launch-budget-3 | Playground Under Two Minutes | Proposed | A fresh rampart-20x-playground Codespace, created from the repository's default branch, answers on its forwarded port within 120 s of creation, measured on a real Codespace and recorded with the run. | The X1 target; confirmed or revised by -2 |

#### Future

- **A data-directory fast path.** Shipping a Postgres data directory would save the load, an
  estimated 10 s. It was ruled out for now (Q11) because it bakes in role passwords and is tied to one
  Postgres build. Revisit it only if a measured launch misses its budget because of the load.
- **Other storage engines.** A desktop TAP on SQLite fits the same lifecycle: build, initialize once,
  serve. A Postgres dump does not fit it. Seed loaders are therefore storage-specific behind the
  common initializer, and the manifest names which loader a seed needs.
- **Memory snapshots** (Firecracker or CRIU, as Fly.io's suspend and resume does). These could remove
  Django start-up too, but they bring back the uniqueness problems this spec avoids, and Fly does not
  guarantee a snapshot survives. Both roads would still be needed.
- **Seed freshness.** The playground's mock data carries absolute dates, so a seed built once looks
  older every day. A scheduled rebuild keeps it current at no launch-time cost.

#### Development

The first draft (PR# 1283 - tap, `25bdaa70`) drew seven findings in a Codex review on 2026-11-21. Each
finding, how it was checked, and its answer are recorded on the pull request
(issuecomment-7063973771). This history explains why the design is shaped as it is; it is not a
substitute for reviewing it. This revision makes these changes:

- It keyed minting on the host's identity (cloud-init's rule). That rotates secrets whenever a
  replica or replacement host appears, so minting now belongs to activation, and identity to the
  installation.
- It had no single owner for initialization. The initializer is now serialized by an advisory lock,
  with durable progress and staged files.
- It put new identity inside the seed load. A database clone, which is never pristine, could not
  have been activated, so loading and activation are now separate steps.
- It used fixed role names. Postgres roles are cluster-wide, so roles are now per installation in a
  shared cluster.
- It left out the file store, so stored files are now carried, or refused until they can be.
- It bound the crypto verdict to a writable venv stamp and to an image digest embedded in the image.
  The first is no evidence and the second is impossible, so the verdict is now a detached
  attestation over verified inputs.
- It assumed every population step was bakeable. Steps are now classified, and completion is read
  before preflight.
- It treated the Codespace target as reachable, but even with every TAP phase removed 174 s would
  remain. The infrastructure phase is now measured before the seed is built.
- It relied on PEP 610 VCS metadata that a wheel install does not carry, so the install manifest
  replaces it.
- It ignored Django start-up, which is now its own requirement.
- Round 2 of the review (`7026c51e`) found three more gaps, and this revision closes them:
  - An image digest does not cover a container's writable layer, so skipping the crypto rescan now
    also requires a read-only root filesystem.
  - A non-pristine target had been listed as a reason to fall back to full initialization, which
    would have initialized an unknown database. Stores are now classified first, and unknown ones are
    refused.
  - Verifying an attestation against the repository alone admits any workflow that can mint one, so
    verification now pins the signer workflow and a protected ref.
- Round 5 (`fa5b6245`) found three recovery gaps, and this revision closes them. The scan could
  read an intermediate stage, so it now reads a container started from the pushed digest.
  Activation could mint twice across a crash, so it now mints everything first, into the state
  store, and applies from there. A crash partway through renaming several file roots had no defined
  cleanup, so each root now commits separately, with a marker that identifies the seed's own partial
  writes.
- Round 4 (`b0cb33e1`) found that the read-only root still allowed a mount of any type over a
  scanned path. The skip now also requires that no mount sits on, under or above a scanned path. The
  FIPS spec's pointer no longer restates the conditions, so the two cannot drift apart.
- Round 3 (`af974155`) found that the lock and recovery contradicted each other. A lock held on the
  installation's database can't survive dropping that database, and a crash mid-load left a partial
  schema with no progress row, which the classification would have refused. The lock now lives in the
  maintenance database, and progress is recorded in the state store before each phase starts.
