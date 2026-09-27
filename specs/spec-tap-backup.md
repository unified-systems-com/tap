# TAP Full Backup

## Philosophy

This spec owns the **full backup**: an off-grid copy of everything needed to boot an identical TAP
instance, taken by one command and checked by another. It fills a gap that canon already names.
[`spec-tap-serving.md`](spec-tap-serving.md) makes a deployment crash-safe "enough for a backup to
mean something" and says that "producing and testing backups is a separate spec and a separate
claim." This is that spec.

There are three ways to carry a TAP instance somewhere else, and they answer different questions:

| Tier | Carries | Verb | Version-bound? |
| --- | --- | --- | --- |
| **Export** (GRIFT, `export_grift`) | Grid nodes and edges, re-stamped as one new captured batch | *Merge* this data into another grid | No: GRIFT is the portable interchange format ([`req-grift-format`](../tap_grid/specs/spec-grift-v0.md)) |
| **Full backup** (this spec) | The whole database, the boot profile, the instance's identity, plugins that cannot be downloaded again, file logs | *Replace* an instance with this one, or start a clone of it | Yes: the same TAP and plugin versions |
| **Frozen containers** (future) | Images plus volume snapshots | *Resurrect* the machine | Yes, down to the Postgres data-file format |

The export is deliberately partial. `Batch` is `INTERNAL_ONLY` (`tap_grid/models.py:1315`), so an
export re-stamps everything it carries into a single captured batch, and it carries no users, no
history, no source batches and no plugin code. That is correct for merging data between grids and
wrong for getting an instance back. The full backup is the tier that keeps all of it.

Four convictions shape the requirements below.

**Forensic by default; flags only subtract.** The default archive is the most complete copy the
tool can make. An operator removes things on purpose, by name, and the removal is written into the
archive. A component added to TAP later is included by default until someone decides otherwise,
because a forgotten inclusion is recoverable and a forgotten exclusion is discovered during the
restore that needed it.

**Every gap is declared.** A backup that is silently missing something is worse than one that is
openly missing it, because nobody looks for what the record says is present. Each component
therefore carries one of four states in the manifest: included, omitted (and by whom), not captured
(and why), or none exists. Absence is never silent.

**Verified means restored.** Reading a dump's table of contents proves the header parses, not that
the data loads. A backup is called restorable only after it has been loaded into a scratch database
and its row counts compared.

**A backup tool must work when the instance does not.** Backups are taken most urgently when
something is already wrong. The tool therefore needs only a database URL and the file tree. It does
not need a healthy boot, loaded plugins or Django settings.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Complete Copy | One command captures everything needed to boot an identical instance: database, boot profile, identity, non-downloadable plugins, and file logs. |
| 2. | Declared Contents | The archive states what it contains, what was left out and why, and who took it for what reason, so a reader a year later can trust it without guessing. |
| 3. | Proven Restorable | A backup can be checked end to end, from member hashes through an actual restore into a scratch database. |
| 4. | Secrets Stay Controlled | Secret values leave the machine only when asked for, and then only under password encryption. |
| 5. | Restore Or Clone | An archive boots back into the same instance, or into a clone with its own identity, and the operator chooses which. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-backup-tiers | [Three Tiers, One Name Each](#three-tiers-one-name-each) | Proposed | Export merges, backup replaces, frozen containers resurrect |
| req-tap-backup-forensic-default | [Forensic By Default](#forensic-by-default) | Proposed | Everything in; `--skip` subtracts by component name |
| req-tap-backup-command | [The Command](#the-command) | Proposed | Settings-free `tap/backup.py`; `manage.py backup` wrapper in `tap_boot` |
| req-tap-backup-manifest | [The Manifest](#the-manifest) | Proposed | Acquisition, instance, contents; `--reason` mandatory |
| req-tap-backup-integrity | [Member Hashes](#member-hashes) | Proposed | `SHA256SUMS` detects corruption; an out-of-band archive digest is the trust anchor |
| req-tap-backup-safe-read | [Safe Archive Reading](#safe-archive-reading) | Proposed | One checked reader: no traversal, links, duplicates or unknown paths |
| req-tap-backup-database | [The Database](#the-database) | Proposed | `pg_dump -Fc` through the primitive shared with `req-boot-snapshot` |
| req-tap-backup-boot | [Boot Profile And Identity](#boot-profile-and-identity) | Proposed | Profile, run records, non-secret instance env |
| req-tap-backup-plugins | [Plugins That Cannot Be Downloaded](#plugins-that-cannot-be-downloaded) | Proposed | Classify every plugin; vendor source for what a pin cannot reproduce; never execute plugin code |
| req-tap-backup-secrets | [Secrets](#secrets) | Proposed | Inventory by default; values only with `--include-secrets` |
| req-tap-backup-secrets-encryption | [Secret Encryption](#secret-encryption) | Proposed | AES-256-GCM, PBKDF2-HMAC-SHA256, through the FIPS OpenSSL |
| req-tap-backup-logs | [File Logs](#file-logs) | Proposed | Everything under `logs/` |
| req-tap-backup-app-logs | [Application Logs](#application-logs) | Proposed | Backlog: consider gathering stderr logs; not critical path |
| req-tap-backup-consistency | [Consistency Point](#consistency-point) | Proposed | One database snapshot; files after it, timestamped |
| req-tap-backup-verify | [Verify](#verify) | Proposed | Hashes and manifest always; `--restore` into a scratch DB |
| req-tap-backup-restore | [Restore](#restore) | Proposed | A boot from the archive, same identity, same-version gate |
| req-tap-backup-clone | [Clone](#clone) | Proposed | A boot from the archive with a new identity and recorded lineage |
| req-tap-backup-periodic | [Scheduled Backups](#scheduled-backups) | Proposed | Backlog: recurring task plus retention |

### Three Tiers, One Name Each
----
RID: `req-tap-backup-tiers`  

Status: `Proposed`

TAP has three mechanisms for carrying an instance, and each has one name and one job. Documentation,
commands and code use these names and do not blur them:

- **Export**: GRIFT, merged *into* a grid. Portable across versions and grids. Partial by design.
- **Full backup**: this spec. Replaces an instance *with* the archived one, or seeds a clone of it.
  Requires matching versions. Complete by design.
- **Frozen containers**: images plus volume snapshots. Not specified yet; the
  copy-on-write volume snapshot that [`req-boot-snapshot`](spec-tap-boot-v0.md#pre-migrate-snapshot)
  names as its scale upgrade path belongs to this tier.

A full backup never substitutes for an export, or the reverse. When an operator needs to move data
across a version boundary, the answer is a GRIFT export, not a forced restore.

The term **boot profile** means the `boot/*.boot.json` recipe. The term **run record** means the
per-run log written by `tap_boot/record.py` under `logs/boot/`
([`req-boot-obs-record`](spec-tap-boot-observability.md)). Canon currently uses "boot record" for
both; this spec uses the two distinct names.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-tiers-1 | Distinct Commands | Proposed | The backup command and the export command are separate entry points; neither accepts the other's output. | |
| req-tap-backup-tiers-2 | Mismatch Points To Export | Proposed | A restore refused for a version mismatch names the GRIFT export as the cross-version route in its error. | |

### Forensic By Default
----
RID: `req-tap-backup-forensic-default`  

Status: `Proposed`

With no flags, `create` captures every component in this spec: the database, boot profile and
identity, plugins that cannot be downloaded again, and file logs. Secret material is the one
component that is omitted by default ([`req-tap-backup-secrets`](#secrets)); the manifest records
that omission like any other.

Flags only remove things. They name components, not paths:

| Flag | Removes |
| --- | --- |
| `--skip db` | The database dump |
| `--skip local-plugins` | Vendored source, wheels and forensics for plugins that cannot be downloaded again |
| `--skip logs` | The file logs under `logs/`, including run records |
| `--exclude-history` | Table data for history tables (schema still dumped) |
| `--exclude-transient` | Table data for sessions and task-queue state (schema still dumped) |

The boot profile, the manifest and the member hashes cannot be skipped. Without them the archive
cannot be read or restored.

Two flags *add* beyond the default, because the default is sized for "boot an identical instance on
a connected machine":

- `--vendor-all`: also bundle source for plugins that *can* be downloaded, for an air-gapped restore.
- `--include-secrets`: include secret values, encrypted ([`req-tap-backup-secrets-encryption`](#secret-encryption)).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-forensic-default-1 | Default Is Complete | Proposed | `create` with no flags produces an archive whose manifest marks every capturable component `included`. The only other states allowed are those this spec names: secret material `omitted` by default; `db-roles` and `app-logs` `not-captured`; a component this instance has none of `none-exists`. | |
| req-tap-backup-forensic-default-2 | Skips Are Recorded | Proposed | Each `--skip`/`--exclude-*` flag produces an `omitted` entry with `by: request` for its component. | |
| req-tap-backup-forensic-default-3 | New Components Default In | Proposed | The component registry has no default-off state except secret material; a component added without a decision is included. | Enforced by a test over the registry |
| req-tap-backup-forensic-default-4 | Unskippable Core | Proposed | `--skip` of the manifest, hashes or boot profile is refused with a message naming why. | |

### The Command
----
RID: `req-tap-backup-command`  

Status: `Proposed`

The implementation lives in `tap/backup.py` as a **settings-free primitive**, the same shape as the
pre-migrate snapshot ([`req-boot-snapshot-6`](spec-tap-boot-v0.md#pre-migrate-snapshot)). It runs as
`python -m tap.backup <create|verify|inspect>` and needs only `DATABASE_URL`, the file tree, and
(for plugin classification) the installed environment's distribution metadata. It does not call
`django.setup()`, import plugins, or require a completed boot.

`manage.py backup` in `tap_boot` is a thin wrapper for operators used to management commands.
`tap_boot` owns it because restore and clone are boot sources ([`req-tap-backup-restore`](#restore)).
No new Django app is added.

The default output directory is `.tap-backups/` at the repository root, overridable with
`--output` or `TAP_BACKUP_DIR`. It is gitignored, like `.tap-snapshots/`. The directory is created
with mode `0700` and the archive written with mode `0600`, because the archive holds user records
and passkey registrations even when it holds no secrets.

The archive is one uncompressed POSIX tar named
`tap-backup-<grid_id>-<UTC stamp>.tar`. The database dump inside is already compressed by
`pg_dump -Fc`; compressing the tar again buys little and makes streaming verification harder.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-command-1 | Runs Without Django | Proposed | `python -m tap.backup create` succeeds in an environment where `django.setup()` would fail (plugin import error), given a reachable database. | |
| req-tap-backup-command-2 | Wrapper Is Thin | Proposed | `manage.py backup` delegates to `tap.backup` with the same arguments and adds no behaviour. | |
| req-tap-backup-command-3 | Private By Mode | Proposed | The output directory is `0700` and the archive `0600` on creation. | |
| req-tap-backup-command-4 | Ignored By Git | Proposed | `.tap-backups/` is in `.gitignore`. | |

### The Manifest
----
RID: `req-tap-backup-manifest`  

Status: `Proposed`

`MANIFEST.json` is the first member of the archive and has three blocks, described by a JSON Schema
at `tap/schemas/backup-manifest.schema.json` with a description on every field.

- **`acquisition`**: who, when, where, with what, and why. It holds `reason` (from `--reason`,
  mandatory), `operator` (from git config or the environment, and marked unverified because both
  are locally mutable), `host`, the tool's TAP version and commit, `started_at`, `db_snapshot_at`,
  `finished_at`, and the exact command line. This block follows the forensic imaging practice of
  recording examiner, acquisition time, tool and notes.
- **`instance`**: the facts a restore gates on. It holds `grid_id`, the active boot profile id, TAP
  version and commit, whether the TAP tree was dirty, the Postgres server version, the migration
  head per Django app (read from `django_migrations`), the row count of every table (with
  `data_excluded: true` on tables whose data an exclusion flag left out), and the
  plugin inventory summary ([`req-tap-backup-plugins`](#plugins-that-cannot-be-downloaded)).
- **`contents`**: one entry per component, each in exactly one of four states:

| State | Meaning | Extra fields |
| --- | --- | --- |
| `included` | Present in the archive | `members` (the paths) |
| `omitted` | Deliberately left out | `by`: `default` or `request` |
| `not-captured` | Wanted, but the tool cannot reach it | `why` |
| `none-exists` | This instance has none of it | — |

`--reason` is mandatory for the same reason batch labels are
([`req-grid-service-batch-label-required`](../tap_grid/specs/spec-grid-service-batch.md)): an archive
with no stated purpose cannot be triaged later.

The `contents` block uses the same declare-then-check shape as the GRIFT contents declaration and the
`[fips]` block. What the manifest declares, `verify` checks against the tar.

Two components are always declared even though they are not captured, so that their absence is
visible: `db-roles` (`not-captured`: cluster-level, and boot re-provisions the roles it needs) and
`media` (`none-exists` today; a future upload feature must change this entry or `verify` fails).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-manifest-1 | Schema Valid | Proposed | Every manifest `create` writes validates against `backup-manifest.schema.json`. | |
| req-tap-backup-manifest-2 | Reason Required | Proposed | `create` without a non-blank `--reason` exits non-zero before touching the database. | |
| req-tap-backup-manifest-3 | Four States Only | Proposed | Every component in the registry appears in `contents` with exactly one of the four states. | |
| req-tap-backup-manifest-4 | Migration Heads | Proposed | `instance.migrations` equals the latest applied migration per app in the dumped database. | |

### Member Hashes
----
RID: `req-tap-backup-integrity`  

Status: `Proposed`

`SHA256SUMS` lists the SHA-256 of every other member, in `sha256sum` format so standard tools can
check it. `MANIFEST.json` is listed. The model is Postgres's `backup_manifest`, which hashes every
file and hashes itself.

Membership is exact: `verify` fails if a member is missing, if a member is present but not listed,
or if a hash differs.

**Member hashes detect corruption, not tampering.** Anyone who can rewrite the archive can rewrite
`SHA256SUMS` to match. Authenticity therefore rests on a **trust anchor held outside the archive**:
the SHA-256 of `SHA256SUMS`, called the *archive digest*. `create` prints it as its last line and
writes it to a sidecar file `<archive>.digest` beside the tar, so an operator can store it
separately (a password manager, a ticket, a second medium). `verify --expected-digest <hex>`
checks the archive against it, and restore and clone require it
([`req-tap-backup-restore`](#restore)). The sidecar travelling next to the archive is a
convenience for corruption checks only; it carries no more trust than the archive does.

A detached signature over `SHA256SUMS` is Future, and would replace the out-of-band digest as the
trust anchor once a signing key has a home.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-integrity-1 | Every Member Hashed | Proposed | `SHA256SUMS` lists every member except itself, and `sha256sum -c` passes on an extracted archive. | |
| req-tap-backup-integrity-2 | Corruption Detected | Proposed | Changing one byte of any member, without updating `SHA256SUMS`, makes `verify` fail and name that member. | |
| req-tap-backup-integrity-4 | Anchor Detects Rewrite | Proposed | An archive whose member and `SHA256SUMS` were both rewritten passes `verify` alone and fails `verify --expected-digest` with the original digest. | Proves hashes alone are not authenticity |
| req-tap-backup-integrity-5 | Digest Emitted | Proposed | `create` prints the archive digest and writes `<archive>.digest`; both equal the SHA-256 of the archived `SHA256SUMS`. | |
| req-tap-backup-integrity-3 | Extra Member Detected | Proposed | A member added to the tar after `create` makes `verify` fail. | |

#### Future
Detached signature over `SHA256SUMS` through the FIPS OpenSSL, once a signing key has a home.

### Safe Archive Reading
----
RID: `req-tap-backup-safe-read`  

Status: `Proposed`

Every read of an archive (`verify`, `inspect`, restore, clone) goes through one checked reader that
refuses, before extracting anything:

- absolute member paths, and any path containing a `..` segment;
- duplicate member names;
- symbolic links, hard links, device files, FIFOs, and anything else that is not a regular file or
  a directory;
- member paths outside the layout in [Archive Layout](#archive-layout).

Extraction happens only into a fresh staging directory created with mode `0700`, and every
extracted path is checked to resolve inside it. `tarfile.extractall` without these checks is never
used. Refusals name the offending member.

The same rules apply **recursively** to every archive nested inside the backup: plugin source tars,
installed-file tars and copied wheels (zip). Restore opens a nested archive only through the checked
reader, before any install tool sees it. The archive digest proves these bytes are the ones that
were captured; it does not make them safe to unpack.

`create` holds the same line when it builds nested archives. A source tar contains only regular
files whose resolved path lies inside the plugin's source root; symbolic links are recorded by name
in the forensics and never followed. An installed-file tar contains only `RECORD` entries that
resolve inside the distribution's install root; an entry pointing elsewhere aborts `create` and
names the plugin.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-safe-read-1 | Traversal Refused | Proposed | An archive with a member named `../x` or `/x` is refused by `verify` and restore, naming the member, with nothing written outside the staging directory. | |
| req-tap-backup-safe-read-2 | Links Refused | Proposed | An archive containing a symlink or hard link member is refused. | |
| req-tap-backup-safe-read-3 | Duplicates Refused | Proposed | An archive with two members of the same name is refused. | |
| req-tap-backup-safe-read-4 | Unknown Paths Refused | Proposed | A member outside the documented layout is refused. | |
| req-tap-backup-safe-read-5 | Nested Archives Checked | Proposed | A plugin source tar or wheel inside an otherwise valid backup that holds a `..` path, an absolute path, a link or a duplicate is refused by restore before any install tool runs. | |
| req-tap-backup-safe-read-6 | Capture Stays In Root | Proposed | A plugin tree containing a symlink to a file outside its root, or a `RECORD` entry resolving outside the install root, never puts that outside file in the archive; the `RECORD` case aborts `create`. | |

### The Database
----
RID: `req-tap-backup-database`  

Status: `Proposed`

The database is captured with `pg_dump --format=custom` into `db/tap.dump`, with the output of
`pg_restore --list` beside it as `db/toc.txt` for inspection without Postgres tools.

The dump and its table-of-contents check are **one function shared with the pre-migrate snapshot**
(`_take_snapshot()`, `tap/preboot.py:1241`, [`req-boot-snapshot`](spec-tap-boot-v0.md#pre-migrate-snapshot)).
The implementation extracts that function's dump-and-list core into a primitive both callers use, so
connection handling, `PGPASSWORD` treatment and failure reporting cannot drift apart.

A logical dump is the right tool for this tier: it is MVCC-consistent without an application lock,
covers the one database TAP uses, and loads into the same or a newer Postgres. Physical base
backups (`pg_basebackup`) copy the whole cluster, are tied to one Postgres major version, and belong
to the frozen-containers tier.

Cluster roles are not dumped. The owning role comes from the database image's initialisation, and
boot re-provisions the search role and its grants after migrate
([`req-boot-search-role`](spec-tap-boot-v0.md)). The manifest declares `db-roles` as
`not-captured` with that reason.

The migration heads and row counts in the manifest must describe the same data the dump holds. The
tool opens a `REPEATABLE READ` transaction, exports its snapshot (`pg_export_snapshot()`), reads the
heads and counts inside it, and passes the snapshot to `pg_dump --snapshot`. Counts taken outside
the dump's snapshot would make `verify --restore` fail on any instance that was being written to.

`--exclude-history` and `--exclude-transient` map to `pg_dump --exclude-table-data` over the history
tables and over session and task-queue tables respectively. The schema is always dumped, so a
restore still migrates cleanly.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-database-1 | Shared Primitive | Proposed | The backup and the pre-migrate snapshot call the same dump function; there is one `pg_dump` invocation site in `tap/`. | |
| req-tap-backup-database-2 | Whole Database | Proposed | With no exclusions, every table in the database appears as `TABLE DATA` in `db/toc.txt`. | |
| req-tap-backup-database-3 | Exclusions Keep Schema | Proposed | With `--exclude-history`, history tables appear in the TOC as tables with no `TABLE DATA` entry. | |

### Boot Profile And Identity
----
RID: `req-tap-backup-boot`  

Status: `Proposed`

`boot/profile.boot.json` is the active boot profile, resolved from `TAP_BOOT_PROFILE` exactly as the
entrypoint resolves it. A derived development profile (`boot/<base>__dev.boot.json`) is captured too
when it exists, under `boot/derived/`, because a derived profile's plugin sources are what the
instance actually runs.

Run records under `logs/boot/` are captured under `boot/runs/` as part of the logs component.

`env/instance.json` records the non-secret instance settings a restore needs: `TAP_GRID_ID`,
`TAP_BOOT_PROFILE`, the session label if any, and the boot-variable overrides present in the
environment (`TAP_BOOT_*`). `SECRET_KEY` and database passwords are secret values and follow
[`req-tap-backup-secrets`](#secrets).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-boot-1 | Active Profile Captured | Proposed | The captured profile is byte-identical to the file boot would load for the current `TAP_BOOT_PROFILE`. | |
| req-tap-backup-boot-2 | No Secret In Env File | Proposed | `env/instance.json` never contains `SECRET_KEY`, a password, or any value the credential-pattern scanner flags. | |

### Plugins That Cannot Be Downloaded
----
RID: `req-tap-backup-plugins`  

Status: `Proposed`

Every installed plugin is classified from its PEP 610 `direct_url.json`, the same metadata
`tap_plugins/report.py:39` already reads. The question for each is: *could a fresh machine get these
exact bytes from the profile's pin alone?*

| Installed as | Profile source | Downloadable? | Archive carries |
| --- | --- | --- | --- |
| git, 40-hex commit pinned, matches installed | `git` + `commit` | Yes | Pin only (source too with `--vendor-all`) |
| git, no commit pin | `git` + `rev` | Pin by commit: a tag can move, so the inventory records the commit the install resolved to (`direct_url.json` `commit_id`) | That commit as the pin (source too with `--vendor-all`) |
| local wheel | `wheelhouse` | No | The wheel file, copied, and checked against the profile's `sha256` when one is declared |
| editable checkout | `editable` | No | Source tar of the working tree, plus forensics |
| path install | `path` | No | Source tar of the source path, plus forensics |
| no `direct_url.json` | — | No | The installed files listed in the distribution's `RECORD`, as a tar, flagged in the manifest |

`plugins/inventory.json` lists every plugin with its slug, distribution name, version, provenance
class, commit where known, and the downloadable verdict with its reason.

**The backup never executes plugin code.** It does not build, import or install anything. Building
a wheel would run the plugin's build backend and hooks, which is working-tree code with the backup's
environment (including `DATABASE_URL`) in reach, before any scan could look at the output. So the
archive carries **source**, and restore builds it. A source tar holds the files git tracks
(`git ls-files`), with their content as it is in the working tree, so uncommitted edits are
included; for a path install that is not a git checkout, every regular file under the source path
except `.git/`, virtual environments and `__pycache__/`. `--vendor-all` fetches each pinned
plugin's source at its commit (`git archive` over the pinned URL, with the install system's
credential when the source declares one) and stores it the same way; this is the one network step
in `create`, and it runs no fetched code. Restore then installs every vendored source through the
normal install path, which runs the build backend at a point where that code is about to run anyway
and where the archive has already been checked against its trust anchor
([`req-tap-backup-restore`](#restore)).

**Forensics** for an editable or path plugin that is a git checkout: `HEAD`, the remote URL with
any user-info (`user:token@`) stripped, `git status --porcelain`, and `git diff HEAD` (tracked
changes) under `plugins/forensics/<slug>/`. Untracked files are listed by name only and never
copied.

Plugin artifacts are the default component most likely to carry stray secret material, since they
come from arbitrary working trees. They pass the archive-wide leak gate
([`req-tap-backup-secrets`](#secrets)), which for a plugin reads every file of its source tar or
installed-file tar, every member of a copied wheel (from the zip, as data, never installed), and its
diff. A hit also suggests `--skip local-plugins` or cleaning the tree.

This is the first code in TAP that asks whether an editable plugin's tree is dirty. The dirty check
belongs in `tap_plugins`, where the plugin report can use it too, rather than inside the backup.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-plugins-1 | Every Plugin Classified | Proposed | `inventory.json` has one entry per installed TAP plugin distribution, each with a provenance class and a downloadable verdict. | |
| req-tap-backup-plugins-2 | Non-Downloadable Vendored | Proposed | Every plugin with verdict "no" has a source tar, wheel file or installed-file tar in the archive, and restoring from it installs the same version. | |
| req-tap-backup-plugins-3 | Dirty Tree Recorded | Proposed | An editable plugin with an uncommitted change has a non-empty `diff.patch` and is marked dirty in the inventory. | |
| req-tap-backup-plugins-4 | Pinned Not Vendored | Proposed | Without `--vendor-all`, a clean commit-pinned git plugin contributes no source. | |
| req-tap-backup-plugins-7 | No Plugin Code Runs | Proposed | `create` runs no build backend, hook or plugin import: a plugin whose build hook writes a marker file leaves no marker after `create`. | |
| req-tap-backup-plugins-5 | Remote Credentials Stripped | Proposed | A remote URL of the form `https://user:token@host/path` is recorded as `https://host/path`. | |
| req-tap-backup-plugins-6 | Fail Closed On Credentials | Proposed | A plugin whose diff, captured source, installed-file tar or copied wheel contains a scanner-detectable credential or a `*.secret.json` makes `create` exit non-zero with no archive written, naming the plugin and file but not the value. | Includes a wheelhouse wheel carrying `example.secret.json` |

### Secrets
----
RID: `req-tap-backup-secrets`  

Status: `Proposed`

TAP secrets are plaintext `*.secret.json` envelopes under `TAP_SECRETS_ROOT`
([`req-tap-cares-secrets-scope`](../tap_cares/specs/spec-tap-cares-secrets.md)), and their
encryption at rest is Backlog
([`req-tap-cares-secrets-future-encryption`](../tap_cares/specs/spec-tap-cares-secrets.md)). A
backup that copies them by default would create a portable plaintext copy of every credential, in a
file whose purpose is to leave the machine. GitLab excludes `gitlab-secrets.json` from its backups
for this reason, and Vault keeps its unseal keys apart from its snapshots.

So the default is an **inventory**, and values are opt-in:

- `secrets/inventory.json` (always, unless the secrets component is skipped): each envelope's
  `scope`, `key` and `kind`, its path relative to the secrets root, and its file mode; and for the
  boot profile's `required_secrets` ([`req-boot-required-secrets`](spec-tap-boot-v0.md)), whether
  each is present. The inventory **never hashes a secret value**. A plain hash of a low-entropy
  password can be brute-forced, so a hash would leak the value.
- `secrets/material.enc` (only with `--include-secrets`): the envelopes, `SECRET_KEY`, and the
  database passwords from the environment, encrypted per
  [`req-tap-backup-secrets-encryption`](#secret-encryption). `--include-secrets` without a password
  is refused.
- **Never included**, flag or not: `.dev-credentials` (a development admin password in plaintext).
  The manifest declares it `omitted` with `by: default` and a note that no flag includes it.

**The leak gate is archive-wide.** Every file the tool adds to the archive is scanned before it is
added, except the two members whose contents the tool itself produces from controlled sources: the
database dump and the encrypted secrets file. That covers boot profiles, run records, the instance
settings file, file logs, and every plugin artifact
([`req-tap-backup-plugins`](#plugins-that-cannot-be-downloaded)). The scan uses the repository's
credential-pattern scanner and also looks for secret-store file names (`*.secret.json` and the
store's other file families). Files are read as data; nothing is executed. A hit aborts `create`
with no archive written, and names the component and file, never the matched value. The scanner
catches known credential shapes, not every secret, and the manifest says so rather than implying
the scan is a guarantee. The database dump is not scanned: it is compressed, and the database holds
no secret-store material by contract ([`req-tap-cares-secrets-scope`](../tap_cares/specs/spec-tap-cares-secrets.md)).

The tool follows the secrets redaction rules
([`req-tap-cares-secrets-redaction`](../tap_cares/specs/spec-tap-cares-secrets.md)): errors and log
lines name `scope:key`, never a value, and no value reaches the manifest, the inventory or stdout.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-secrets-1 | Values Omitted By Default | Proposed | With no secrets flag, no member of the archive contains any value read from the secrets store or the environment's secret settings; the credential-pattern scanner over the extracted archive finds nothing. | Plugin artifacts are covered by `req-tap-backup-plugins-6` |
| req-tap-backup-secrets-2 | Inventory Complete | Proposed | Every `*.secret.json` under the secrets root appears in `inventory.json` by `scope:key:kind`. | |
| req-tap-backup-secrets-3 | No Value Hashes | Proposed | `inventory.json` has no field derived from a secret value. | |
| req-tap-backup-secrets-4 | Password Required | Proposed | `--include-secrets` with no password source exits non-zero before writing anything. | |
| req-tap-backup-secrets-5 | Dev Credentials Never | Proposed | `.dev-credentials` is absent from every archive, including with `--include-secrets`. | |
| req-tap-backup-secrets-6 | Archive-Wide Leak Gate | Proposed | A scanner-detectable credential or a `*.secret.json` placed in any scanned component (a file under `logs/`, a boot profile, a plugin artifact) makes `create` exit non-zero with no archive written, naming the component and file but not the value. | |

### Secret Encryption
----
RID: `req-tap-backup-secrets-encryption`  

Status: `Proposed`

`secrets/material.enc` is password-encrypted as follows:

| Part | Choice | Why |
| --- | --- | --- |
| Cipher | AES-256-GCM, 96-bit random nonce | FIPS-approved and authenticated: a tampered or truncated file fails to decrypt instead of producing garbage. `openssl enc` is not used because it has no authenticated mode. |
| Key derivation | PBKDF2-HMAC-SHA256, 600,000 iterations, 16-byte random salt | PBKDF2 is the FIPS-approved password-based KDF (NIST SP 800-132). The iteration count is OWASP's current floor for SHA-256. Argon2id and scrypt resist GPU attack better but are not FIPS-approved and would be flagged under [`req-fips-crypto-bom-source`](spec-fips.md). |
| Library | `cryptography` (`PBKDF2HMAC`, `AESGCM`) | Already a dependency, built from source against the system OpenSSL and its FIPS provider (`pyproject.toml:176`), and an OpenSSL-routed module under the FIPS crypto guard. |
| Format | A JSON header (format id, KDF name, iterations, salt, nonce), a newline, then the ciphertext; the header bytes are the GCM associated data | Self-describing, so iterations can rise without breaking old archives; editing the header breaks decryption. |
| Password input | Interactive prompt, `--secrets-password-file PATH`, or `TAP_BACKUP_SECRETS_PASSWORD` | Never a command-line argument: arguments show in `ps` and shell history, and the manifest records the command line. |

The plaintext inside is a tar of the envelopes plus a small JSON document holding the environment
secrets. It is built in memory, never written to disk unencrypted.

This spec includes, in its Implementation section once built, a stand-alone decryption recipe of a
few lines of Python using only `cryptography`, so recovering secrets does not depend on a working
TAP install.

Only the secrets component is encrypted. The rest of the archive stays readable, so an investigator
can inspect what an instance held without a password. Whole-archive encryption is Future and would
reuse the same primitive.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-secrets-encryption-1 | Round Trip | Proposed | `material.enc` decrypts with the right password to the exact envelopes and environment secrets captured. | |
| req-tap-backup-secrets-encryption-2 | Wrong Password Fails | Proposed | A wrong password fails with an authentication error and produces no partial output. | |
| req-tap-backup-secrets-encryption-3 | Header Bound | Proposed | Changing any header byte (such as the iteration count) makes decryption fail. | |
| req-tap-backup-secrets-encryption-4 | Parameters Recorded | Proposed | The header records KDF, iterations, salt and nonce, and iterations are at least 600,000. | |
| req-tap-backup-secrets-encryption-5 | No Plaintext On Disk | Proposed | No file containing secret plaintext is created during `create`, including in temporary directories. | |
| req-tap-backup-secrets-encryption-6 | Standalone Recipe | Proposed | The documented recipe decrypts a real `material.enc` in an environment with only `cryptography` installed. | |

### File Logs
----
RID: `req-tap-backup-logs`  

Status: `Proposed`

Everything under the instance's `logs/` directory is captured under `logs/` in the archive, except
that run records go under `boot/runs/` ([`req-tap-backup-boot`](#boot-profile-and-identity)). Today
that is the spawn log and the boot run records. Their writers are secret-free by contract, but the
directory is writable and anything can be dropped into it, so every log file passes the
archive-wide leak gate ([`req-tap-backup-secrets`](#secrets)) before it is added. `--skip logs`
removes them.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-logs-1 | Logs Captured | Proposed | Every regular file under `logs/` at capture time is present in the archive with its relative path preserved. | |

### Application Logs
----
RID: `req-tap-backup-app-logs`  

Status: `Proposed`

Backlog, not on the critical path (ruled 2026-09-25). Application logs go only to stderr
(`tap/logging.py:283`), so they live in the container runtime's log store, which the backup tool,
running inside the container, cannot read. Until this requirement is taken up, the manifest declares
`app-logs` as `not-captured` with the reason "stderr only; no file sink".

The likely route is the file or JSON sink proposed in
[`req-tap-logging-format-6`](spec-tap-logging.md): once logs land in a file under `logs/`,
[`req-tap-backup-logs`](#file-logs) captures them with no further work. A host-side wrapper that
collects the container runtime's logs was considered and not preferred, because it would be a
second entry point that drifts from the first.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-app-logs-1 | Declared Until Captured | Proposed | While application logs are not captured, every manifest declares `app-logs` as `not-captured` with a reason. | Holds from phase 1 |

### Consistency Point
----
RID: `req-tap-backup-consistency`  

Status: `Proposed`

The database dump is one MVCC snapshot; `acquisition.db_snapshot_at` records when it was taken. File
components are captured after the dump and each carries its capture time in the manifest. The
database and the file tree are therefore not captured atomically together, and the manifest says so
rather than implying otherwise.

`--quiesce` pauses the task workers for the duration of the capture and resumes them afterwards,
for operators who want no background writes during the backup. Whether the pause succeeded, and for
how long it held, is recorded in the manifest. A failure to resume is reported loudly and does not
leave the workers paused.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-consistency-1 | Snapshot Time Recorded | Proposed | `db_snapshot_at` is set, and falls between `started_at` and `finished_at`. | |
| req-tap-backup-consistency-2 | Quiesce Resumes | Proposed | After `--quiesce`, workers are running again whether `create` succeeded or failed. | |

### Verify
----
RID: `req-tap-backup-verify`  

Status: `Proposed`

`verify <archive>` always checks:

1. `SHA256SUMS` against every member, with exact membership ([`req-tap-backup-integrity`](#member-hashes)).
2. `MANIFEST.json` against its schema, and every `included` component's members are present.
3. `pg_restore --list` succeeds on `db/tap.dump`.

All reading goes through the checked reader ([`req-tap-backup-safe-read`](#safe-archive-reading)).
With `--expected-digest <hex>`, `verify` also checks the archive digest against the trust anchor
([`req-tap-backup-integrity`](#member-hashes)); without it, a pass means "not corrupted", not "not
tampered with", and the output says which of the two was checked.

`verify --restore` also loads the dump into a scratch database (`tap_backup_verify_<random>`) on the
configured server, compares per-table row counts against the manifest's expected counts, and drops
the scratch database whether the check passed or failed. This is the only check this spec calls
*restorable*.

Loading a dump executes the SQL inside it, so `verify --restore` is gated exactly like restore: it
requires `--expected-digest` (or an explicit, recorded `--trust-unanchored`) and checks the anchor
before `pg_restore` runs. The load uses `pg_restore --no-owner --no-privileges --exit-on-error --single-transaction`, so object ownership
and grants in the dump are not applied.

For a table whose data was excluded (`--exclude-history`, `--exclude-transient`), the manifest
records both the source row count and `data_excluded: true`, and the expected restored count is
zero. The comparison uses the expected count, so a backup taken with exclusions verifies cleanly and
the source count is still on record.

Reading the table of contents (step 3) proves the dump's header parses. It does not prove the data
loads. [`req-boot-snapshot-3`](spec-tap-boot-v0.md#pre-migrate-snapshot) currently describes the same
table-of-contents check as verifying the snapshot "restorable"; that wording overstates what it checks,
and is corrected in a separate change.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-verify-1 | Hash And Manifest | Proposed | `verify` fails on any integrity or manifest-membership violation and names it. | |
| req-tap-backup-verify-2 | Real Restore | Proposed | `verify --restore` loads the dump into a scratch database and passes only if every table's row count matches its expected count: the source count, or zero for a table marked `data_excluded`. | |
| req-tap-backup-verify-5 | Anchor Before Load | Proposed | `verify --restore` without `--expected-digest` or `--trust-unanchored` refuses before invoking `pg_restore`; with a wrong digest it refuses the same way. | Loading a dump executes its SQL |
| req-tap-backup-verify-6 | Exclusions Verify | Proposed | A backup taken with `--exclude-history` passes `verify --restore`, and its manifest still carries the source row count of each excluded table. | |
| req-tap-backup-verify-3 | Scratch Cleaned | Proposed | The scratch database does not exist after `verify --restore` returns, on success or failure. | |
| req-tap-backup-verify-4 | Truncation Caught | Proposed | A dump with its data section truncated passes `pg_restore --list` and fails `verify --restore`. | The case that separates the two checks |

### Restore
----
RID: `req-tap-backup-restore`  

Status: `Proposed`

Restore is a **boot from the archive**, started by a human, never triggered automatically
([`req-boot-snapshot-4`](spec-tap-boot-v0.md#pre-migrate-snapshot)). The operator runs boot with a
`restore_from` source naming the archive and the mode `--as-restore`. Pre-boot then:

1. Runs `verify --expected-digest` with the archive digest the operator supplies
   ([`req-tap-backup-integrity`](#member-hashes)), through the checked reader
   ([`req-tap-backup-safe-read`](#safe-archive-reading)). Without a digest, restore refuses unless
   the operator passes `--trust-unanchored`, which is recorded in the run record.
2. Refuses unless the target database is **pristine**: no user-defined tables, views, sequences,
   functions, triggers, types or extensions beyond those the database image creates at
   initialisation. Having no rows is not enough, because an empty table, a function or a trigger
   left in place would take part in the load. It never restores over live data.
3. Checks the **version gate**: TAP version, each plugin's version and commit, each app's migration
   head, and the Postgres major version against the manifest. A mismatch refuses, names every
   difference, and points to the GRIFT export as the cross-version route. `--force` overrides and
   is recorded in the run record.
4. Installs vendored plugins from the archive (building vendored source through the normal install
   path), and pinned plugins from their pins.
5. Loads the dump with `pg_restore --no-owner --no-privileges --exit-on-error --single-transaction`
   in place of running migrate on an empty database, so a load that fails part-way leaves nothing
   behind. It then runs the normal remainder
   of boot (role provisioning, seeding checks, health), which is idempotent against restored data
   ([`req-boot-idempotent`](spec-tap-boot-v0.md)).
6. Restores `TAP_GRID_ID` from the manifest, and `SECRET_KEY` from the secrets file when it was
   included and a password is supplied.
7. Clears sessions and claimed task-queue executions from the restored data, because they point at
   logins and workers that no longer exist, and lists how many of each it cleared in the run record.

Every refusal (steps 1 to 3) happens before anything from the archive is installed or loaded:
vendored plugins are code, and building them runs it. The digest proves the archive is the one
that was taken; it does not make the plugins' build hooks harmless, so nothing is built until every
check that could still refuse has passed.

Passkey registrations are restored with the users. They authenticate only when the restored
instance is served on the same host name, because a passkey is bound to its relying-party ID. The
restore report states the host name the backup was taken on.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-restore-1 | Identical Identity | Proposed | After a restore, the instance's grid id equals the manifest's `grid_id`. | |
| req-tap-backup-restore-6 | Anchor Before Code | Proposed | A restore or clone given no archive digest, and not `--trust-unanchored`, refuses before installing any vendored plugin or loading the dump; a wrong digest refuses the same way. | |
| req-tap-backup-restore-2 | Version Gate | Proposed | A restore with any version mismatch refuses without `--force` and names each mismatch. | |
| req-tap-backup-restore-3 | Pristine Target Only | Proposed | A restore refuses, before any vendored plugin is installed or built, into a database holding any user-defined object beyond the image's initial set, including an empty table or a lone function. | |
| req-tap-backup-restore-7 | All Or Nothing Load | Proposed | A dump that fails part-way through the load leaves the target database with no restored objects. | |
| req-tap-backup-restore-4 | Transient State Cleared | Proposed | After restore, the session table and claimed-execution table are empty, and the run record states how many rows were cleared. | |
| req-tap-backup-restore-5 | Round Trip | Proposed | Back up an instance, restore into a fresh one, and every Gryphon count by entity type (live and retired) matches. | The end-to-end acceptance test |

### Clone
----
RID: `req-tap-backup-clone`  

Status: `Proposed`

`--as-clone` boots from the archive as a **new instance** that shares the original's history. It
runs the same steps as restore, except:

| | Restore | Clone |
| --- | --- | --- |
| Grid id | Kept | New UUIDv7 |
| Lineage | — | `cloned_from` (source grid id, archive `SHA256SUMS` digest, time) in the run record, and a lineage batch written on the new grid through the service layer |
| Entity ids | Kept | Kept |
| `SECRET_KEY` | Restored when available | Always newly generated |
| Collector schedules | As captured | Paused |
| Sessions, claimed jobs | Cleared | Cleared |
| Users and passkeys | Kept | Kept |

Entity ids are kept because a clone is a fork: both instances hold the same objects as of the
backup, and a later GRIFT exchange between them correctly treats a shared id as the same object.

Schedules start paused because a clone usually holds the same collector credentials. Two instances
polling the same APIs would double the load on those APIs and write the same world into two grids.
The operator resumes schedules deliberately.

Neither mode is the default. Boot from an archive with neither `--as-restore` nor `--as-clone`
refuses and asks for one, so an operator cannot create a second live instance with the original's
identity by accident.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-clone-1 | New Identity | Proposed | After a clone, the grid id differs from the manifest's, and a lineage batch naming the source grid id exists on the grid. | |
| req-tap-backup-clone-2 | Fresh Secret Key | Proposed | The clone's `SECRET_KEY` differs from the source's even when the secrets file was included. | |
| req-tap-backup-clone-3 | Schedules Paused | Proposed | Every collector schedule on the clone is paused after boot. | |
| req-tap-backup-clone-4 | Mode Required | Proposed | A boot from an archive with no mode refuses. | |

### Scheduled Backups
----
RID: `req-tap-backup-periodic`  

Status: `Proposed`

Backlog. A recurring task runs `create` on a schedule with a configured reason prefix, and a
retention policy removes old archives. This is the "periodic system" that
[`req-boot-snapshot-6`](spec-tap-boot-v0.md#pre-migrate-snapshot) shaped its primitive for. The
schedule is on the grid like every other TAP schedule. Scheduled runs never include secret values,
because a scheduled run has no one to type the password.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-backup-periodic-1 | No Scheduled Secrets | Proposed | A scheduled backup cannot be configured with `--include-secrets`. | |

## Archive Layout

```text
tap-backup-<grid_id>-<UTC stamp>.tar
├── MANIFEST.json                acquisition · instance · contents
├── SHA256SUMS                   every other member
├── db/
│   ├── tap.dump                 pg_dump --format=custom
│   └── toc.txt                  pg_restore --list
├── boot/
│   ├── profile.boot.json        active boot profile
│   ├── derived/<name>.boot.json derived dev profile, when present
│   └── runs/*.boot-record.json  run records (logs component)
├── env/instance.json            non-secret instance settings
├── plugins/
│   ├── inventory.json           every plugin, provenance, downloadable verdict
│   ├── source/<slug>.tar        editable/path trees (pinned too with --vendor-all)
│   ├── wheels/*.whl             wheelhouse wheels, copied
│   ├── installed/<slug>.tar     RECORD files, when provenance is unknown
│   └── forensics/<slug>/        HEAD · remote · status.txt · diff.patch
├── secrets/
│   ├── inventory.json           scope:key:kind, presence; never values
│   └── material.enc             only with --include-secrets
└── logs/                        file logs
```

Beside the archive, not inside it: `<archive>.digest`, the SHA-256 of the archived `SHA256SUMS`.

## Build Order

| Phase | Delivers | Requirements |
| --- | --- | --- |
| 1 | The database floor: `create` with database, boot profile, identity, manifest, hashes and archive digest; `verify` without `--restore`, through the checked reader; the shared dump primitive | `-tiers`, `-forensic-default`, `-command`, `-manifest`, `-integrity`, `-safe-read`, `-database`, `-boot`, `-app-logs` |
| 2 | Plugins, file logs, secret inventory, password-encrypted secrets | `-plugins`, `-logs`, `-secrets`, `-secrets-encryption`, `-consistency` |
| 3 | `verify --restore`; restore and clone as boot sources | `-verify`, `-restore`, `-clone` |
| 4 | Scheduled backups and retention | `-periodic` |

Frozen containers (images plus volume snapshots) are a separate, later spec.

## Prior Art

| System | What this spec takes | What it does not |
| --- | --- | --- |
| GitLab `gitlab-backup create` | Component skip list recorded in the archive's metadata; restore only to the same version; secrets file kept out of the backup | No checksums; encryption only at the object store |
| Gitea `gitea dump` | Logs included by default; per-component skip flags | Secret key inside the dump; service must stop; no restore command |
| Sentry self-hosted | A separate export and backup, each named for what it is; encrypted export | Only export and raw volume copies are supported, with no middle tier |
| Discourse | Same-version restore; an explicit switch before a restore may run | Plugins redeclared, not backed up |
| Nextcloud | Quiescing; the server announcing after a restore that it went back in time | No single command |
| Vault and Consul snapshots | Keys held apart from data; read-back check after writing; restore in isolation | — |
| Velero | Exclude beats include; freeze hooks recorded with their results | Cluster-scale machinery |
| Postgres `pg_dump` / `pg_basebackup` | `pg_dump -Fc` for this tier; `backup_manifest` as the model for member hashes | `pg_basebackup` belongs to frozen containers |
| EWF/E01, AFF4 forensic images | The acquisition record (examiner, time, tool, notes) and per-member digests | The imaging formats themselves |
| django-dbbackup | Command naming | No manifest; no version gate |
