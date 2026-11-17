# File Store Specification

## Philosophy

The grid holds facts as nodes and edges. Some things TAP must keep are not facts but documents: a
software bill of materials, a compliance file a provider publishes each day, the exact bytes a
collector received. They are read whole or not at all, they are often large, and putting them in
database fields grows the database and its history for content nobody queries by field. Issue# 1035 -
tap recorded the gap: a node can hold fields, but nothing lets a node refer to a file that lives
outside the database and lets a user download it.

This specification is that capability: one byte store in core, on its own mounted volume, that keeps
whole files and gives them back with their integrity checked. A file kept here is on-grid. It has a
node that names it and carries its digest, so it can be found, related to other things, downloaded by
a person with the right capability, and followed through its history.

Four decisions give the store its shape.

- **One store.** Every part of TAP that needs to keep a document uses this one. A separate store for
  collector evidence was designed earlier and is superseded by this specification (ruled 2026-11-16).
- **Kept, not edited.** Bytes are written once. A changed file is a new version beside the old one,
  never an overwrite, and nothing is deleted in this release. That is what makes a digest check
  meaningful and history possible.
- **A standard on disk.** The store's directory is an Oxford Common File Layout (OCFL) storage root.
  OCFL was written so that stored content "can be fully understood in the absence of original
  software" and a repository can be rebuilt from its storage root "without additional information
  resources". A person or a third-party OCFL tool pointed at the volume, with no TAP running and no
  database, can tell what every file is, verify it, and see its versions. The maintainer's ruling:
  inside the directory TAP is sub-grid and conforms to OCFL, and does not try to outsmart it.
- **Thin interface, one backend.** Core talks to the store through a small interface of whole-file
  operations. The only backend built is the local filesystem. The interface exists so another
  backend can be contributed later without changing callers; none is planned.

What core knows about a stored file is deliberately little: an identifier, a name, where it sits in
TAP's own tree of directories, bytes, a digest, a size and a version. Core owns the grid's types for
those, `tap_file` and `tap_directory`, so holding a file never depends on a plugin (ruled
2026-11-17). What a file *means* (that it is an SBOM, that it is valid, who published it) belongs to
the plugin that understands the format and lives on that plugin's own node.

### Prior Art

Surveyed 2026-11-13 and 2026-11-16 by research agents; each line says what was read in those surveys
and what was recalled. Inspiration only: no code was taken.

| Project | Mechanism | What this specification takes | What does not fit |
| --- | --- | --- | --- |
| Oxford Common File Layout 1.1 (read) | An object is a directory holding a conformance marker, an `inventory.json` listing each file's digest, stored path and logical name per version, a sidecar digest of the inventory, and `v1`, `v2`… directories whose `content` holds only bytes new in that version. Naming of object directories is left to registered layout extensions. Purging is not supported. | The on-disk format, whole. | Multi-file objects are allowed by OCFL and not used here. |
| Git LFS, OCI distribution, restic, git-annex (read) | Bytes named by an algorithm-tagged digest; stream to a temporary file on the same filesystem while hashing, then move into place; verify before publishing; git-annex keeps the file extension in the stored name because hash-only names "can confuse some programs". | Hash while streaming; stage on the same filesystem; rename into place; a recognisable stored filename. | Deduplication across objects and chunking: not worth their cost at this scale. |
| Rails Active Storage (read) | Splits the bytes (blob) from what they are attached to; warns never to purge inside a database transaction. | Bytes are durable before the row that names them commits; a row is removed before its bytes. | Its MD5 checksum, which is not a FIPS-approved digest. |
| Django storage API and security guidance (read) | A narrow store interface; the framework's own guidance that no framework-level fix exists for hostile uploaded content served inline, and that it should be served as an attachment or from another origin. | A narrow interface; downloads are always attachments. | A human path as the identity of a stored file. |
| OWASP File Upload Cheat Sheet (read) | Server-generated stored names; length and character limits on any kept user-supplied name; store outside the web root; hand out identifiers through an application handler; enforce size limits. | All of it, for the write path and the download route. | Extension allow-lists: the writers in this release are programs, not browsers. |
| Paperless-ngx, Nextcloud, Seafile (read) | A report-only checker that lists rows without files, files without rows and checksum mismatches. | The report-only check, from the first release. | Human-browsable trees that people edit by hand, which those projects must then reconcile. |
| Vendor storage SDKs and multi-backend libraries (read, 2026-11-16) | No multi-backend library is at once current, organisation-owned and free of its own cryptography; the vendors' own SDKs are. An S3-style store cannot rename atomically or append. | The interface promises only whole-file operations every object store can do, so a backend wrapping a vendor SDK stays thin. | Building any remote backend now. |

One gap the surveys found and this specification does not close: no mature system has garbage
collection whose reachability includes version history and tombstones. This release keeps everything,
which postpones that problem instead of solving it.

## Goals

|    |                   |                                                                                         |
| :---: | ---            | ---                                                                                     |
| 1. | Refer And Fetch    | A node can refer to a stored file, and a permitted user or program can get the bytes back |
| 2. | Provably Unchanged | Bytes are write-once, named by SHA-256, and verified before they are released            |
| 3. | Understandable Cold | The volume alone, with no grid, says what every file is and proves it                   |
| 4. | Accounted For      | Every operation is gated by a capability and logged, reads included                      |
| 5. | Replaceable Engine | Callers depend on a small interface, not on the local filesystem                         |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-files-scope | [Scope](#scope) | Proposed | One on-grid byte store in core; what it knows and what it leaves to plugins |
| req-tap-files-root | [The Root](#the-root) | Proposed | One setting, one mounted local volume, separate from plugin data |
| req-tap-files-mount-gate | [Mount Gate And Initialisation](#mount-gate-and-initialisation) | Proposed | Boot refuses an unmounted root; an empty root is initialised; unknown content is never adopted |
| req-tap-files-ocfl | [On-Disk Format](#on-disk-format) | Proposed | A conformant OCFL 1.1 storage root, one object per stored file |
| req-tap-files-naming | [Object And File Naming](#object-and-file-naming) | Proposed | Object directory from the identifier alone; stored filename carries name, identifier, version and digest |
| req-tap-files-immutable | [Immutability And Versions](#immutability-and-versions) | Proposed | Write-once bytes; a change is a new version; nothing is deleted |
| req-tap-files-interface | [Store Interface](#store-interface) | Proposed | Whole-file operations behind a backend protocol; local filesystem is the only backend |
| req-tap-files-write | [Write Path](#write-path) | Proposed | Stream, hash, limit, stage, verify, move into place; recovery after a crash |
| req-tap-files-read | [Read Path](#read-path) | Proposed | Verify the digest before releasing any byte |
| req-tap-files-capabilities | [Capabilities](#capabilities) | Proposed | `files.create`, `files.read`, `files.update`, `files.delete` in the core registry |
| req-tap-files-gateway | [Service Gateway](#service-gateway) | Proposed | The gated operations programs call; the identifier a file node shares with its object |
| req-tap-files-node | [The Grid File](#the-grid-file) | Proposed | `tap_file`, a core type: every held file's node, found again by its directory and name |
| req-tap-files-directory | [Directories](#directories) | Proposed | `tap_directory`, a core type: one parent, containment edges to its files and directories |
| req-tap-files-format-record | [Format Records](#format-records) | Proposed | `FILE_CONTENTS` joins a file to the one node, of a plugin's type, that says what its bytes are |
| req-tap-files-hold | [Holding A File](#holding-a-file) | Proposed | The one helper that stores bytes and shapes the nodes, bytes first; what changes when a file changes |
| req-tap-files-logging | [Operation Logging](#operation-logging) | Proposed | One structured record per operation, reads and refusals included |
| req-tap-files-download | [Download Route](#download-route) | Proposed | A logged-in user with `files.read` downloads a file as an attachment |
| req-tap-files-check | [Report-Only Check](#report-only-check) | Proposed | A command that validates the store and lists where it and the grid's file nodes disagree, both ways |
| req-tap-files-health | [Health Probe](#health-probe) | Proposed | A probe that reports the root as usable or not |
| req-tap-files-history | [History Stays Possible](#history-stays-possible) | Proposed | Nothing in this release prevents reading any earlier version |
| req-tap-files-size-limit | [File Size Limit](#file-size-limit) | Backlog | A ceiling on the size of one stored file |
| req-tap-files-retention | [Deletion And Retention](#deletion-and-retention) | Backlog | Removing content, retention periods, and what a tombstone means for bytes |
| req-tap-files-backends | [Other Backends](#other-backends) | Backlog | How a contributed backend is discovered and what it must guarantee |
| req-tap-files-upload | [Browser Upload](#browser-upload) | Backlog | A person adding a file through the web interface |
| req-tap-files-slices | [Reading Inside Files](#reading-inside-files) | Backlog | Searching stored files and returning addressed parts of them |
| req-tap-files-version-download | [Downloading An Earlier Version](#downloading-an-earlier-version) | Backlog | A browser surface for a version the node's history once recorded |
| req-tap-files-dimensions | [Dimensions For Files And Directories](#dimensions-for-files-and-directories) | Backlog | Which dimensions held files and directories should carry |
| req-tap-files-nongoals | [v0 Non-Goals](#v0-non-goals) | Proposed | What this specification deliberately does not do |

### Scope
----
RID: `req-tap-files-scope`

Status: `Proposed`

The file store keeps whole files for the grid. It is a core capability: any app or plugin may use it
through the service gateway (`req-tap-files-gateway`), and no plugin is required for it to work.

**What the store knows about a file.** An identifier, the name it is known by, its bytes, their
SHA-256 digest and size, its versions, and who wrote each version and when.

**What core represents on the grid.** Every held file is a `tap_file` and every folder of held files
a `tap_directory`, both core types owned by this app (`req-tap-files-node`,
`req-tap-files-directory`; ruled 2026-11-17). An instance with no plugin installed can hold, find and
serve files.

**What the store does not know.** A file's format, what is inside it, whether it is valid, or what it
describes. A file's meaning belongs to the plugin that understands its format, on a format record of
that plugin's own type, joined to the file by `FILE_CONTENTS` (`req-tap-files-format-record`). The
store imports no plugin.

**The join between grid and store.** A stored file's identifier is the entity identifier of its
`tap_file`, written as a URN (`req-tap-files-naming`). The node carries the file's name, path, size,
digest and file version; the store holds the bytes under the same identifier. The node's path is
logical and is not how either side finds the other.

**Not for working data.** A database updated in place, a version-control clone or a cache of fetched
datasets is a plugin data directory (`tap_plugins/specs/spec-tap-plugin-data-directory.md`), which is
sub-grid and has a different volume.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-scope-1 | Core Imports No Plugin | Proposed | The file store's code, its node types and its helper import nothing from any plugin package, and work in an instance with zero plugins installed. | Covered by the lean-boot gate once built. |
| req-tap-files-scope-2 | One Store | Proposed | Exactly one module reads or writes under the file store root; a guard test finds no other reference to the root setting outside it. | The same guard the superseded evidence design proposed. |
| req-tap-files-scope-3 | Format-Blind | Proposed | No store operation branches on a file's extension, declared type or content. | |

### The Root
----
RID: `req-tap-files-root`

Status: `Proposed`

The store lives under one root named by one core setting.

- **Setting, and what it means to be enabled** (ruled 2026-11-16). `settings.TAP_FILES_ROOT`,
  projected from the environment variable `TAP_FILES_ROOT` in `tap/settings.py`, with **no default**.
  Unset or empty means the file store is not enabled on this instance. Set means the operator has
  provided a volume for it, and from then on that volume must be usable. Every consumer reads the
  setting; the variable is read nowhere else. The rule is the one the secrets root arrived at
  (`req-tap-cares-secrets-root-resolution`), and the plugin data root works the same way.
- **An instance without the store.** The store is optional for an instance. Where it is not
  enabled, every gateway operation fails with one clear error, `FileStoreNotEnabled`, the download
  route answers not found, and nothing else in TAP is affected. A plugin that cannot work without the
  store says so (`req-tap-files-mount-gate`).
- **Its own volume.** The compose files in this repository enable the store: they mount a named volume
  in every service that runs store code and set the variable to its path. It is a different volume from the plugin data volume (ruled 2026-11-16). Separate roots let a
  backup treat the two differently, and let an operator give each its own disk or quota.
- **Shared capacity is an accepted limitation** (ruled 2026-11-16). Two named volumes are two
  directories, and by default they sit on the same disk and share its free space. On the shipped
  compose files a plugin cache that fills the disk does stop a file being stored. An operator who
  needs that not to happen mounts the two roots on separately sized storage; this specification
  does not require it and the mount gate does not test for it.
- **Layout under the root.** Core owns everything under the root:

  | Path | Holds |
  | --- | --- |
  | `ocfl/` | The OCFL storage root. Nothing but OCFL content is ever placed in it. |
  | `staging/` | Files being written, before they are moved into `ocfl/`. Same filesystem, so the move is atomic. |
  | `quarantine/` | Incomplete or invalid content moved aside by recovery, never deleted. |
  | `locks/` | Per-object lock files. |

  Staging, quarantine and locks sit beside the OCFL root and not inside it because OCFL forbids
  anything but objects and its own extensions under a storage root.
- **Local filesystem.** The local backend requires a filesystem with atomic rename and working file
  locks. An operator who wants other storage may mount it at the root on the host; whether it meets
  those two properties is theirs to establish, and the health probe reports the filesystem type.
- **Image.** The image creates the root path owned by the runtime user, so a new empty named volume
  starts with usable ownership.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-root-1 | One Setting, No Default | Proposed | `TAP_FILES_ROOT` is read from the environment in `tap/settings.py` only; with the variable unset the setting is empty and no path literal stands in for it. | Guard-pinned. |
| req-tap-files-root-2 | Repository Compose Enables It | Proposed | Every compose file in this repository that defines a service running store code mounts a named volume and sets the variable to that mount path; that volume is not the plugin data volume. | |
| req-tap-files-root-5 | Not Enabled Is One Clear Error | Proposed | With the variable unset, each gateway operation raises `FileStoreNotEnabled` and touches no path, and the download route answers not found. | |
| req-tap-files-root-3 | Nothing Foreign Under The OCFL Root | Proposed | After any sequence of store operations, including interrupted ones, `ocfl/` contains only the storage-root marker, the layout declaration, the extensions directory and object hierarchy, with no empty directory. | OCFL section 4.1. |
| req-tap-files-root-4 | Roots Do Not Overlap | Proposed | When both are set, the mount gate fails if the file store root and the plugin data root are the same path or one contains the other. | |

### Mount Gate And Initialisation
----
RID: `req-tap-files-mount-gate`

Status: `Proposed`

**Gate** (ruled 2026-11-16). The store is optional, a plugin declares when it needs it, and boot
fails only when a need cannot be met or a configured volume is broken.

|  | No installed plugin requires the store | An installed plugin requires the store |
| --- | --- | --- |
| **Store not enabled** | Boots. Store operations fail with `FileStoreNotEnabled`. | Boot aborts, naming the plugin. |
| **Store enabled and usable** | Boots. | Boots. |
| **Store enabled but not usable** | Boot aborts. | Boot aborts. |

- **How a plugin says it requires the store.** One optional table in `tap-plugin.toml`:

  ```toml
  [file_store]
  required = true
  ```

  `file_store` joins the manifest's allowed top-level keys; `required` is a boolean and is the only
  key; unknown keys are rejected. A plugin that uses the store when it is there and works without it
  declares nothing. Because unknown top-level keys are rejected by older cores, a plugin that
  declares the table raises its `requires_tap` floor to the first core release that carries the
  store.
- **What "usable" means.** The path exists and is a directory and not a symbolic link; it is on a
  different device from the container's root filesystem; and a real write, `fsync`, rename and remove
  succeeds in `staging/`. The test is one function, shared with the health probe, and is the same
  test the plugin data directory uses (`req-tap-plugin-datadir-mount-gate`); the two share an
  implementation, not a copy.
- **An abort** is a standup abort (`req-boot-abort-signal`) in the `boot` domain naming the root, the
  failed check and, where one caused it, the plugin.

The failure being prevented is the one Docker does nothing to signal: an operator configured a
volume, it is not mounted, the path exists inside the container's own disk, files are written there,
and they are gone when the container is recreated. A configured store is therefore never optional,
whoever is installed.

**Initialisation.** When the store is enabled and the gate has passed:

- A root that is completely empty is initialised: the four directories are created, and `ocfl/`
  receives the OCFL storage-root marker `0=ocfl_1.1`, an `ocfl_layout.json` naming the layout
  extension, and that extension's configuration under `extensions/`.
- A root that holds a valid OCFL storage root with the expected layout is used as it is.
- A root that is not empty and is not that is refused with a standup abort. Core never adopts
  content it did not create and never initialises over existing files.

**Recovery.** After initialisation, boot runs the recovery sweep described in `req-tap-files-write`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-mount-gate-1 | Unmounted Configured Root Aborts | Proposed | With the setting naming a path on the same device as `/`, boot exits non-zero after one `ABORT` record whose reason says the root is not a mounted volume, whether or not any plugin requires the store. | |
| req-tap-files-mount-gate-6 | Required But Not Enabled Aborts | Proposed | With the setting unset and an installed plugin declaring `[file_store] required = true`, boot aborts and the reason names that plugin. | |
| req-tap-files-mount-gate-7 | Not Enabled, Not Required, Boots | Proposed | With the setting unset and no installed plugin requiring the store, boot succeeds and creates nothing. | |
| req-tap-files-mount-gate-8 | Manifest Table Strict | Proposed | A `[file_store]` table with a non-boolean `required` or any other key fails the manifest load. | |
| req-tap-files-mount-gate-2 | Empty Root Initialised | Proposed | Booting against an empty mounted root leaves a storage root that a conformant OCFL validator accepts as a valid, empty storage root. | |
| req-tap-files-mount-gate-3 | Foreign Content Refused | Proposed | Booting against a mounted root that contains a file and no storage-root marker aborts and changes nothing under the root. | |
| req-tap-files-mount-gate-4 | Idempotent | Proposed | A second boot against an initialised root changes no file under `ocfl/`. | |
| req-tap-files-mount-gate-5 | Shared Mount Test | Proposed | The file store and the plugin data directory obtain their mount verdicts from one implementation of the test. | |

### On-Disk Format
----
RID: `req-tap-files-ocfl`

Status: `Proposed`

`ocfl/` is a conformant OCFL 1.1 storage root, and each stored file is one OCFL object (ruled
2026-11-16). Conformant means a third-party OCFL validator reports no errors against it.

An object's directory holds exactly what OCFL allows:

```
<object directory>/
  0=ocfl_object_1.1            the object conformance marker
  inventory.json               identifier, digests, stored paths, logical names, versions
  inventory.json.sha256        the digest of inventory.json
  v1/
    inventory.json             the inventory as of v1
    inventory.json.sha256
    content/
      <stored filename>        the bytes
  v2/ ...                      present only if the file has a second version
```

Choices this specification makes where OCFL leaves one:

- **Digest algorithm: `sha256`.** OCFL permits `sha256` and recommends `sha512`, so a strict
  validator reports a warning, not an error. SHA-256 is the digest used everywhere else in TAP, it is
  FIPS-approved, and one digest across the grid, the filename and the disk is worth the warning
  (ruled 2026-11-16). Hashing uses the interpreter's `hashlib`, which resolves to the image's
  validated OpenSSL provider; the store adds no cryptographic provider.
- **Version inventories.** Each version directory carries its own inventory and sidecar, as OCFL
  recommends, and the root inventory equals the newest version's. The store relies on this copy: it
  is what recovery completes or restores a root inventory from (`req-tap-files-write`).
- **Every version has a directory.** A version that stores no new bytes (a rename) still has its
  `vN` directory, holding its inventory and sidecar and no `content` directory, which is the shape
  OCFL gives for a version that adds no content.
- **One file per version.** Each version's state maps exactly one digest to exactly one logical path.
  OCFL allows more; the store does not use it.
- **Version entries.** Each version records `created` (the time of the write, with zone), `user.name`
  (the acting actor's stable key, never an email address) and `message` (the operation, and the
  caller's short reason when one was given).
- **No fixity block, no zero-padded version numbers**, and the default content directory name
  `content`.
- **No links.** The store creates no symbolic or hard link under the root, as OCFL requires.

Every inventory the store writes validates against a JSON Schema for the OCFL inventory, authored
for this project from the specification's text and shipped with the code, and every inventory the
store reads is validated against it before it is trusted.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-ocfl-1 | Validator Finds No Errors | Proposed | After creating objects, adding versions and renaming, a conformant OCFL 1.1 validator run over `ocfl/` reports zero errors. | Run in CI against at least one independent validator; which one is a build-time choice needing dependency approval if it is not a standalone tool. |
| req-tap-files-ocfl-2 | Only Expected Warnings | Proposed | The same run reports no warning other than the ones this section accepts by name: the SHA-512 recommendation. | A new warning is a finding. |
| req-tap-files-ocfl-3 | Sidecar Matches | Proposed | For every inventory file in the store, the adjacent sidecar holds the SHA-256 of that inventory's bytes. | |
| req-tap-files-ocfl-4 | Inventory Schema | Proposed | Every inventory written validates against the shipped schema; an inventory on disk that fails it makes the object unreadable through the store and is reported by the check. | |
| req-tap-files-ocfl-5 | Readable Cold | Proposed | Given only a copy of `ocfl/`, a script using nothing but the standard library can list every object's identifier, logical name, versions and digests, and verify every content file. | The test of Goal 3. |

### Object And File Naming
----
RID: `req-tap-files-naming`

Status: `Proposed`

**The object identifier** is the URN form of the UUID of the node that represents the file:
`urn:uuid:` followed by the UUID in its canonical lower-case hyphenated form. OCFL says an identifier
should be a URI, and this is one (ruled 2026-11-16: follow the standard).

**The object directory is derived from the identifier alone** (ruled 2026-11-16). OCFL requires "a
deterministic mapping from an object identifier to a unique storage path"; a name and a digest can
both change, so neither may take part.

**The tree is for programs, not people** (ruled 2026-11-16). Only TAP, OCFL libraries and automated
tools read the directory tree, so the layout is chosen for what suits them: the layout the most tools
understand, an even spread of objects whatever order they arrive in, and the identifier recoverable
from a path. That is the OCFL community layout extension `0003-hash-and-id-n-tuple-storage-layout`,
used with its defaults:

| Parameter | Value | Effect |
| --- | --- | --- |
| `digestAlgorithm` | `sha256` | The identifier is hashed with SHA-256, the digest used everywhere else in the store. |
| `tupleSize` | `3` | Each level of the hierarchy is three characters of the hash. |
| `numberOfTuples` | `3` | Three levels. |

The last level is the identifier itself, percent-encoded as the extension specifies, because a colon
is not safe in a directory name on every filesystem:

```
urn:uuid:01a1e3b1-25c0-7d4a-9b1c-2f6e5a7b8c9d
ocfl/568/a1f/6b7/urn%3auuid%3a01a1e3b1-25c0-7d4a-9b1c-2f6e5a7b8c9d/
```

Why this layout and not another published one:

- **It is the most widely read.** Of six maintained OCFL tools surveyed on 2026-11-16, all six read
  this layout; the plain hashed layout (`0004`) is read by five and the prefix-omitting layout
  (`0007`) by four.
- **It spreads evenly by construction.** The levels come from a hash, so a collector that stores a
  thousand files in one run does not put them in one directory, and the spread does not depend on
  the form of the identifier.
- **A path gives the identifier back.** In `0004` the last level is the hash, and the only way to
  learn which object a directory holds is to open its inventory. Here a tool walking the tree reads
  identifiers from paths.

The layout's configuration is written once, at initialisation, to
`ocfl/extensions/0003-hash-and-id-n-tuple-storage-layout/config.json`, and `ocfl_layout.json` names
the extension, so another OCFL tool learns the layout from the store itself.

**The stored filename** carries four things, so a file copied out of the store still says what it is:

```
<stem>+<identifier>+v<N>+<sha256>.<extension>
vdr-2026-11-16+0192f3a1-7c2e-7d4a-9b1c-2f6e5a7b8c9d+v1+9f86d0…0f00a08.json
```

- `<stem>` and `<extension>` are derived from the logical name at the time of that version. The stem
  keeps ASCII letters, ASCII digits, `.`, `_` and `-`, replaces every other character with `_`,
  drops leading dots, and is cut to 100 characters. The extension is the logical name's final
  suffix when it is 1 to 16 ASCII letters or digits, and is otherwise omitted along with its dot.
  Both are ASCII so that the name has a fixed byte budget: at most 100 + 1 + 36 + 2 + 1 + 64 + 1 +
  16 = 221 bytes plus the digits of the version, well inside the 255-byte limit common filesystems
  place on one name. A stem that kept other letters would not fit: a hundred two-byte letters alone
  take 200 bytes.
- `<identifier>` is the bare UUID, without the `urn:uuid:` prefix, because a colon is not safe in a
  file name on every filesystem.
- `v<N>` is the OCFL version in whose directory the file sits. It is OCFL's number, not any counter
  from the grid (ruled 2026-11-16), so the name and the path always agree.
- `<sha256>` is the full digest of the bytes, lower-case hex. It is not truncated, so a file can be
  checked against its own name with `sha256sum` and nothing else.
- The parts are joined by `+`. The identifier, the version and the digest have fixed shapes, so the
  name is taken apart from the right even when the stem contains a `+`.

OCFL places no rule on content file names beyond forbidding empty, `.` and `..` path elements, so
this name is conformant.

**The logical name** is the name the file is known by, recorded per version in the inventory. It is
supplied by the caller and is kept exactly, subject to being one path element: no `/`, no control
character, not `.` or `..`, not empty, at most 255 bytes of UTF-8. A name that fails is refused; the
store does not silently repair a logical name.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-naming-1 | Directory From Identifier Only | Proposed | Two objects with the same logical name and identical bytes live in different directories, and renaming or re-versioning an object never moves its directory. | |
| req-tap-files-naming-2 | Layout Matches The Extension | Proposed | The store maps the extension's own published example identifier `object-01` to `3c0/ff4/240/object-01`, and maps `urn:uuid:01a1e3b1-25c0-7d4a-9b1c-2f6e5a7b8c9d` to `568/a1f/6b7/urn%3auuid%3a01a1e3b1-25c0-7d4a-9b1c-2f6e5a7b8c9d`. | The extension's example is the conformance test for the algorithm. |
| req-tap-files-naming-7 | Layout Declared In The Store | Proposed | An initialised store's `ocfl_layout.json` names the `0003` extension and its `config.json` carries the three parameters above. | |
| req-tap-files-naming-6 | Identifier Is A URN | Proposed | Every object's inventory `id` is `urn:uuid:` followed by a canonical lower-case UUID, and equals the URN of the entity identifier it was stored under. | |
| req-tap-files-naming-3 | Name Carries All Four | Proposed | Every content file's name parses from the right into a digest equal to the SHA-256 of its bytes, a version equal to its version directory, and an identifier equal to its object's. | |
| req-tap-files-naming-4 | Hostile Names Are Safe | Proposed | Logical names containing `../`, a leading dot, a NUL, a newline, a `+`, a 300-character stem and a reserved device name each either produce a stored filename inside the object's own `content` directory or are refused; none writes anywhere else. | |
| req-tap-files-naming-8 | Stored Name Fits One Path Element | Proposed | For the logical names `"é" * 100 + ".json"`, `"a" * 255` and a 100-character stem with a 16-character extension, the stored filename is ASCII, at most 255 bytes, and the write succeeds; the logical name is still kept exactly. | Raised by the AI review on PR# 1213 - tap. |
| req-tap-files-naming-5 | Logical Name Kept Exactly | Proposed | A valid logical name containing spaces and non-ASCII letters is returned unchanged by a read and appears unchanged in the inventory. | |

### Immutability And Versions
----
RID: `req-tap-files-immutable`

Status: `Proposed`

Stored bytes are write-once (ruled 2026-11-16).

- **Create** makes an object at version 1.
- **A new version** stores new bytes for an existing object. The earlier version's directory is not
  touched.
- **A rename** records a new logical name. It is a new OCFL version that stores no new bytes: the
  inventory gains a version whose state maps the existing digest to the new name. The new version's
  directory is created and holds that version's inventory and sidecar; it has no `content`
  directory, because no content file is written.
- **Nothing is deleted.** There is no operation that removes an object, a version or a content file
  (`req-tap-files-retention`).
- **Content is placed read-only.** A content file has mode `0444` when it is moved into place, and
  no code path opens one for writing afterwards (ruled 2026-11-17; the read path relies on it,
  `req-tap-files-read`).

The **file version** is OCFL's version number for the object. It counts changes to the file's bytes
or name and nothing else. It is deliberately not the grid's per-node edit counter, which rises on
every change to a node including ones that have nothing to do with the file. The node that represents
the file carries the file version as a field so the grid, the directory and the filename state one
number; keeping that field current is the job of whoever writes the node, using the value the store
returns.

A version is identified by its number. Writers state the version they believe is current when adding
a version or renaming, and the store refuses when it is not, the same optimistic rule the grid uses
for nodes (`req-grid-service-batch-occ`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-immutable-1 | Earlier Versions Untouched | Proposed | After adding a version, every file under the earlier version directories is byte-identical and has an unchanged modification time. | |
| req-tap-files-immutable-2 | Rename Stores No Bytes | Proposed | A rename raises the head version by one, adds no content file, and leaves the digest unchanged. The new version's directory exists, holds an inventory and its sidecar, and has no `content` directory. | |
| req-tap-files-immutable-3 | No Delete Operation | Proposed | The backend protocol and the service gateway expose no operation that removes an object, a version or content, and no code path under the store unlinks a file inside `ocfl/`. | Recovery moves incomplete content to quarantine; it does not unlink. |
| req-tap-files-immutable-4 | Stale Writer Refused | Proposed | Adding a version or renaming with an expected version that is not the head is refused with a conflict error carrying both numbers, and changes nothing. | |
| req-tap-files-immutable-5 | Create Is Put-If-Absent | Proposed | Creating an object whose identifier already exists is refused and the existing object is unchanged. | |
| req-tap-files-immutable-6 | Content Is Read-Only | Proposed | After a create and after a new version, every content file under `ocfl/` has mode `0444`, and no code path under the store opens a content file for writing once it is placed. | |

### Store Interface
----
RID: `req-tap-files-interface`

Status: `Proposed`

Callers reach the store through a backend protocol of whole-file operations (ruled 2026-11-16: a
thin abstraction, local filesystem the only target).

| Operation | Does |
| --- | --- |
| `create(identifier, name, stream, actor, reason)` | Stores a new object at version 1. Returns the digest, size and version. |
| `add_version(identifier, expected_version, name, stream, actor, reason)` | Stores new bytes as the next version. |
| `rename(identifier, expected_version, name, actor, reason)` | Records a new logical name as the next version. |
| `open(identifier, version=None)` | Returns the logical name, digest, size, version and a readable stream of verified bytes. |
| `stat(identifier)` | Returns the head version and, for each version, its name, digest, size, time and actor. Reads no content. |
| `exists(identifier)` | Says whether an object exists. |
| `identifiers()` | Iterates every object identifier in the store. |
| `verify(identifier, deep)` | Checks an object's structure and, when `deep`, re-hashes its content. |

The protocol promises nothing a plain object store cannot do: no partial write, no append, no
in-place edit, no rename of stored bytes, no directory listing by name, no lock a caller can hold.
That restraint is what keeps a future backend thin.

The backend is chosen by a setting whose only accepted value in this release is the local one. OCFL
is the local backend's on-disk format; it is not part of the protocol, and another backend would
keep the protocol's guarantees its own way.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-interface-1 | Callers Use The Protocol | Proposed | Outside the local backend's module, no code opens, lists or stats a path under the file store root. | |
| req-tap-files-interface-2 | A Second Backend Satisfies The Tests | Proposed | The store's behavioural tests run against the protocol, and an in-memory backend written for the tests passes the same suite as the local backend. | The proof the interface is the contract. |
| req-tap-files-interface-3 | Unknown Backend Refused | Proposed | A backend setting other than the local value fails at startup with an error naming the accepted value. | |

### Write Path
----
RID: `req-tap-files-write`

Status: `Proposed`

A write never leaves a partly written file where a reader can find it.

1. **Take the object's lock.** A lock file per identifier under `locks/`, held for the whole write.
   The lock is an exclusive `flock` (`fcntl.flock`, never the POSIX record locks of `fcntl.lockf`,
   which a process loses on closing any descriptor for the file), and a lock file is never deleted.
   Writers do not wait indefinitely; a write that cannot take the lock within a short bound fails
   with a busy error.
2. **Stream to staging while hashing.** Bytes are copied in bounded chunks into a new directory under
   `staging/`, with the SHA-256 computed as they pass. The whole file is never held in memory, so the
   store has no built-in limit on a file's size (`req-tap-files-size-limit`). A write that runs out
   of disk fails like any other failed write: nothing is moved into place and the staging directory
   is removed.
3. **Check the caller's digest, when given.** A caller that knows the digest it expects passes it,
   and a mismatch refuses the write. A collector that has verified a document elsewhere uses this to
   prove the store kept the same bytes.
4. **Build the complete result in staging.** For a create, the whole object directory. For a new
   version or a rename, the version directory, which carries the new inventory and its sidecar. The
   staging directory's name begins with the object's encoded identifier, so anything that finds it
   later knows which object's lock governs it.
5. **Make it durable.** `fsync` each staged file and each staged directory.
6. **Move into place.**
   - A create renames the staged object directory to its place under `ocfl/`, creating the hashed
     parent levels first. The rename is atomic, so the object either exists whole or not at all.
   - A new version or a rename moves the staged version directory into the object. It then replaces
     the root inventory with a copy of the new version's inventory, by an atomic rename of a
     temporary file. **That rename is the commit point**: before it the object is at its old head,
     after it at its new one. Last, it replaces the root sidecar the same way.
   - After each rename the directory that received the entry is itself `fsync`ed, and for a create
     so is each parent level that was made. A rename is not durable until its directory is.
7. **Log, release the lock, return** the digest, size and version.

The root inventory is replaced after the version directory is in place because an object whose root
inventory does not mention a version directory is recoverable, and one whose inventory names content
that is not there is not.

**Order against the grid.** Bytes are stored before the node that names them is written, and a
caller whose grid write then fails is left with stored bytes no node records: a whole object after a
create, or a version above the one the node names after a new version or rename. That is the safe
direction: nothing points at bytes that are not there. Three rules keep it safe.

- The node is the authority for which version is current. A reader acting for a node asks for the
  version the node records and does not take the store's head on trust (`req-tap-files-download`).
- A stored version no node records is kept, like everything else, and is not an error in the store.
  The check reports a whole object with no node, and a head that is ahead of its node
  (`req-tap-files-check`).
- A caller that retries reads the store's head with `stat` first. It does not repeat its earlier
  expected version, which the store would now refuse for good. If the head already holds the bytes
  it means to store, it uses that version and writes nothing; otherwise it adds its version after
  the head. Its grid write names the node version it expects, so the grid refuses a second writer
  the same way the store does.

**Recovery.** Recovery puts right what an interrupted write left behind. It runs for every object at
boot, on demand through `manage.py files recover`, and for one object at the start of any write to
it. It is the only thing besides a write that changes anything under the root, and the check never
runs it (`req-tap-files-check`).

Recovery never assumes it is alone. Services boot separately, so one process can be recovering while
another is writing. For each object it touches, recovery takes that object's lock without waiting,
skips the object when the lock is held, and looks again at the object's state after taking the lock
and before changing anything. A staging directory is examined under the lock of the object its name
gives. A writer holds its lock for the whole write and the lock dies with its process, so a staging
directory whose lock is free belongs to no one.

Under the lock, recovery:

- moves an unowned staging directory to `quarantine/`, with a note saying what it was and when it
  was found;
- **completes or restores the root inventory pair** when the root inventory does not match its
  sidecar. If the root inventory's bytes equal the inventory in one of the object's version
  directories, and that version inventory matches its own sidecar and validates, the root sidecar
  is rewritten from that version's: the commit had happened and is finished. Otherwise both root
  files are restored from the highest version directory whose inventory matches its sidecar and
  validates, and an integrity finding is logged. Where no version directory qualifies, nothing is
  changed and the object is reported invalid. This is the only case in which recovery writes an
  inventory, and it only ever copies one the store had already written and can verify;
- moves a version directory numbered above the head in the (now matching) root inventory to
  `quarantine/`: the write was interrupted before its commit point;
- removes a hashed parent directory under `ocfl/` left empty by a create that did not finish, this
  being the one place the store removes a directory, and only an empty one.

Recovery never authors an inventory and never removes content.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-write-1 | Bytes Exact | Proposed | The stored content file's bytes equal the bytes supplied, and the returned digest equals their SHA-256. | |
| req-tap-files-write-2 | Disk Full Fails Cleanly | Proposed | A write that fails because the volume is full raises an error, leaves nothing under `ocfl/` for that write, and leaves `staging/` empty. | |
| req-tap-files-write-3 | Declared Digest Checked | Proposed | A create given an expected digest that does not match is refused and stores nothing. | |
| req-tap-files-write-4 | Interrupted Create Leaves No Object | Proposed | A create killed at any step before the final rename leaves no object for its identifier, and after the next boot `ocfl/` validates and the remains are in `quarantine/`. | Test by injecting a failure at each step. |
| req-tap-files-write-5 | Interrupted Version Leaves The Old Head | Proposed | An `add_version` killed at any step before the commit point leaves the object readable at its previous head with its previous bytes, and after the next boot the object validates. | |
| req-tap-files-write-6 | One Writer Per Object | Proposed | Two concurrent creates for one identifier yield exactly one success; two concurrent `add_version` calls with the same expected version yield one success and one conflict. | Across processes, not only threads. |
| req-tap-files-write-7 | Constant Memory | Proposed | Writing a file many times larger than the chunk size does not raise the process's memory use by more than a small multiple of the chunk size. | |
| req-tap-files-write-8 | Recovery Removes No Content | Proposed | After recovery, every content file that existed under `ocfl/` before it still exists and is unchanged, under `ocfl/` or under `quarantine/`. | |
| req-tap-files-write-9 | Every Interruption Point Recovers | Proposed | An `add_version` and a rename are each killed after every single step of the move into place, including between the root inventory's replacement and the root sidecar's. After recovery the object validates, is readable, and is at the old head when the kill came before the commit point and at the new head when it came after. | The case the first draft could not recover from. |
| req-tap-files-write-10 | Root Pair Restored From A Version | Proposed | With the root sidecar altered, recovery rewrites it from the matching version directory and the object reads again; with the root inventory altered, recovery restores both files from the highest valid version directory and logs a finding; with no valid version inventory it changes nothing and the object is reported invalid. | |
| req-tap-files-write-11 | Recovery Spares A Live Write | Proposed | With a writer in another process holding an object's lock, mid-write, recovery run at each step of that write moves nothing of that object's, and the write then completes and reads back correctly. | Covers the staging directory and the version directory placed before its commit point. |
| req-tap-files-write-12 | Destination Directories Synced | Proposed | Each rename into `ocfl/` is followed by an `fsync` of the directory that received the entry, and a create also syncs each parent level it made. | Asserted by recording the calls in a test. |
| req-tap-files-write-13 | Retry After A Failed Grid Write | Proposed | After a stored version whose grid write was refused, repeating the write with the earlier expected version is a conflict; `stat` then shows the head, and a retry that offers the same bytes is told the version that already holds them and stores nothing new. | |

### Read Path
----
RID: `req-tap-files-read`

Status: `Proposed`

No byte leaves the store unverified. `open` reads the object's root inventory, checks the inventory
against its sidecar, locates the requested version's content file, computes the SHA-256 of the whole
file, compares it with the inventory's digest, and only then returns a stream.

A reader takes no lock in the ordinary case. A root inventory that does not match its sidecar may be
a write caught between its last two renames, so before calling it a failure the reader takes the
object's lock, waiting no longer than a writer would, and reads the pair again. A mismatch that is
still there is real. A reader repairs nothing; repair is recovery's (`req-tap-files-write`).

Verification completes before the first byte is released. A stream that verifies as it goes cannot
take back what it has already sent, and a caller that has received half a corrupted file has no way
to know. The cost is reading the file twice.

The stream released is the one that was verified (ruled 2026-11-17). `open` opens the content file
once, computes the digest through that descriptor, seeks it back to the start and returns it; it
never opens the path a second time. Content files are placed read-only (`req-tap-files-immutable`)
and nothing opens one for writing afterwards. The bytes delivered are therefore the bytes verified,
unless a process with write access to the volume changes the file in place while the read is in
flight. Such a process is outside this store's threat model: it could as easily rewrite a content
file and its inventory together, and what catches tampering at rest is the digest recorded on the
file's node, which the download route compares (`req-tap-files-download`). The read guarantee is
against corruption, an interrupted write and tampering at rest, not against a hostile writer on the
volume during a read.

A failure is one error, `FileIntegrityError`, whatever the cause: the content does not match its
digest, the inventory does not match its sidecar, the inventory is not valid, or the content file is
missing. The error carries the identifier, the version and the kind of failure, and never any of the
content. Each failure is logged as an integrity finding and emits the reserved `CONCERN` signal
(`req-tap-logging-concern-signal`), because a stored document that no longer matches its digest is a
security-relevant event.

A read of an object or version that does not exist is a not-found error, distinct from an integrity
error.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-read-1 | Altered Content Refused | Proposed | With one byte of a content file changed on disk, `open` raises `FileIntegrityError` and returns no stream. | |
| req-tap-files-read-2 | Altered Inventory Refused | Proposed | With the root inventory edited and its sidecar left alone, `open` raises the same error. | |
| req-tap-files-read-3 | Missing Content Is Integrity, Missing Object Is Not Found | Proposed | A deleted content file yields `FileIntegrityError`; an unknown identifier yields the not-found error. | |
| req-tap-files-read-4 | Verified Before First Byte | Proposed | For a file whose last byte is corrupt, no byte is delivered to the caller before the error. | |
| req-tap-files-read-5 | Any Version Readable | Proposed | After two further versions are added, `open` with version 1 returns version 1's bytes and name. | |
| req-tap-files-read-7 | No False Alarm During A Write | Proposed | Reads of an object issued continuously while another process adds versions to it never raise `FileIntegrityError` and never emit `CONCERN`. | |
| req-tap-files-read-6 | Finding Raised | Proposed | Each integrity failure produces one log record and one `CONCERN` record naming the identifier and the failure kind. | |
| req-tap-files-read-8 | The Verified Descriptor Is Delivered | Proposed | `open` opens the content file exactly once, and the stream it returns is that same descriptor, positioned at the first byte. | Asserted by recording the opens in a test. Ruled 2026-11-17 in answer to the AI review on PR# 1213 - tap. |

### Capabilities
----
RID: `req-tap-files-capabilities`

Status: `Proposed`

Four capabilities join the core registry (`tap_auth/tap_auth.capabilities.json`,
`req-tap-auth-capabilities`), each with a description and a risk (ruled 2026-11-16: create, read,
update and delete, with nothing finer).

| Capability | Risk | Gates |
| --- | :---: | --- |
| `files.create` | medium | Storing a new file. |
| `files.read` | medium | Getting a stored file's bytes. Seeing the node that represents a file needs only `grid.read`; getting the bytes needs this as well. |
| `files.update` | medium | Adding a version to a stored file, or renaming it. |
| `files.delete` | high | Reserved. No operation in this release requires it, because nothing is deleted (`req-tap-files-retention`). It is registered now so the vocabulary is complete and grants do not need revisiting when deletion arrives. |

Reading bytes is separated from reading the grid on purpose. A stored document can be more sensitive
than the fact that it exists, and an actor that may browse the graph should not thereby be able to
pull every document off the instance.

There is no access control finer than these four in this release: an actor with `files.read` can
read any stored file whose node it can see.

Grants follow the registry's existing rules, and no capability implies another:

- `tap_admin` holds every capability, as it does today.
- `tap_viewer` receives `files.read` (ruled 2026-11-16). A person who can see the grid can download
  any stored file whose node they can see. There is no narrower download role in this release.
- The collector program actor receives `files.create`, `files.update` and `files.read`. One program
  actor runs every collector today, so this grant is global: any installed collector can store a
  file. That is accepted for this release (ruled 2026-11-16) and is the same interim position the
  actor's delete grant is in. Scoping it to the collectors that declare they need it is designed
  separately and does not block the store: Issue# 1205 - tap, under the epic Issue# 1204 - tap.
- The bootloader and scheduler actors receive none. Initialising the store at boot happens below the
  gateway and needs no capability.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-capabilities-1 | Registered With Descriptions | Proposed | The four capabilities are present in the registry file with a description and a risk, and the file validates against its schema. | |
| req-tap-files-capabilities-2 | Grid Read Is Not Enough | Proposed | An actor holding `grid.read` and not `files.read` can read a file's node and is refused its bytes. | |
| req-tap-files-capabilities-5 | Collector Actor Can Write | Proposed | The collector program actor holds `files.create`, `files.update` and `files.read`, and the roles file's description of that grant names it as global and interim. | Per-collector scoping: Issue# 1205 - tap. |
| req-tap-files-capabilities-4 | Viewer Can Read | Proposed | The `tap_viewer` role holds `files.read` and none of the other three. | |
| req-tap-files-capabilities-3 | No Implication | Proposed | Holding `files.update` does not permit a create, and holding `files.create` does not permit a read. | |

### Service Gateway
----
RID: `req-tap-files-gateway`

Status: `Proposed`

Programs use the store through a gateway of gated operations, following the guarded service boundary
(`req-service-boundary-model`): every exported operation carries its capability check, and the
backend sits below the gate where callers cannot reach it.

| Gateway operation | Capability | Backend operation |
| --- | --- | --- |
| `store_file` | `files.create` | `create` |
| `add_file_version` | `files.update` | `add_version` |
| `rename_file` | `files.update` | `rename` |
| `open_file` | `files.read` | `open` |
| `file_info` | `files.read` | `stat` |
| `file_exists` | `files.read` | `exists` |

The acting actor is taken from the caller context, as it is for grid operations, and is what the
store records as the writer of a version. A caller cannot name a different actor.

**Who mints the identifier.** The caller, and in practice the holding helper
(`req-tap-files-hold`), which mints the `tap_file`'s entity identifier, stores the bytes under it,
and returns the node envelopes carrying the returned digest, size and file version for the caller's
batch. The gateway itself does not create or change any node: the store is format-blind, and writing
nodes is the job of the service layer the caller already uses.

**Writers in this release are programs** (ruled 2026-11-16): collectors and other processes running
inside the instance, through this gateway. That covers a file fetched from an outside source, a
file TAP produced itself, and the raw responses a collector records from a source it talks to, which
are stored as files here and not kept in a plugin's own directory (ruled 2026-11-16). There is no path by which a browser adds a file
(`req-tap-files-upload`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-gateway-1 | Every Export Gated | Proposed | Every name the gateway exports is an operation carrying a capability requirement; the boundary guard finds none ungated. | `req-service-boundary-contract-surface`. |
| req-tap-files-gateway-2 | Refused Without The Capability | Proposed | Each gateway operation called by an actor without its capability raises the standard capability error and performs no backend call. | |
| req-tap-files-gateway-3 | Actor From Context | Proposed | The writer recorded in a version's inventory entry is the caller context's actor, and no gateway operation accepts an actor argument. | |
| req-tap-files-gateway-4 | No Grid Write | Proposed | No gateway operation creates, changes or deletes a node or an edge. | |

### The Grid File
----
RID: `req-tap-files-node`

Status: `Proposed`

A file TAP holds is represented on the grid by a node of a core type, `tap_file`, owned by this app
(ruled 2026-11-17). It is TAP-native in the way `layout` and `dimension` are: core declares and
registers it, so an instance with no plugin installed can hold, find and serve files. No plugin is
needed for a file to exist on the grid, and none is consulted when one is read.

**A `tap_file` is a held file.** Its bytes are in this store under the node's entity identifier,
and every `tap_file` has them. A file that a collector merely observed on a host is a different
thing: it belongs to whichever plugin describes hosts, which may link it to a `tap_file` when TAP
also holds a copy (What This Settles Elsewhere). Nothing here represents a file TAP does not hold.

| Field | Meaning |
| --- | --- |
| `name` | The file's logical name, exactly as the store records it (`req-tap-files-naming`). |
| `path` | Where the file sits in TAP's own tree of directories: its directory's `path`, a `/`, and its `name`. A file in no directory has the path `/` followed by its name. |
| `media_type` | The media type the writer declared, as an IANA media type string, or null. Recorded as declared; nothing inspects the bytes to confirm it. It is what the download route sends. |
| `size_bytes` | The size of the bytes, as the store returned it. |
| `sha256` | The SHA-256 of the bytes, 64 lower-case hex characters, as the store returned it. |
| `file_version` | The version of the file in this store, an integer from 1. It is the store's own number, which counts changes to the bytes or the name. It is not the grid's per-node edit counter, which rises on every change to the node. |

**Identity is the directory and the name** (ruled 2026-11-17). `NATURAL_KEY = ("path",)`, and the
path is composed of the containing directory's path and the file's name, so two files may share a
name only in different directories. A path starts with `/`, uses `/` as its separator, and has no
empty, `.` or `..` element, no trailing separator and no control character. It is logical: it says
where the file sits on the grid and never appears on disk, where the store lays files out by
identifier (`req-tap-files-naming`). Moving or renaming a file changes its path while its entity
identifier, and so its stored object, stays the same: the same node, found from then on by its new
path.

**No body.** The node holds no bytes and no parsed copy of them. What the bytes mean is recorded on
a format record (`req-tap-files-format-record`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-node-1 | Core Type, No Plugin | Proposed | `tap_file` is declared and registered by `tap_files`, and in an instance with no plugin installed a file can be stored, its node written and the file downloaded. | Covered by the lean-boot gate once built. |
| req-tap-files-node-2 | Fields Declared | Proposed | `tap_file` declares `name`, `path`, `media_type`, `size_bytes`, `sha256` and `file_version` in its field schemas; `media_type` may be null and the others may not. | |
| req-tap-files-node-3 | Digest And Version Shape | Proposed | A `sha256` that is not 64 lower-case hex characters, a negative `size_bytes`, and a `file_version` below 1 are each refused. | |
| req-tap-files-node-4 | Found Again By Path | Proposed | Writing a file twice with the same path resolves to one node; one name in two directories is two nodes. | |
| req-tap-files-node-5 | Path Shape | Proposed | A path that does not start with `/`, or has an empty, `.` or `..` element, a trailing separator or a control character, is refused. | |
| req-tap-files-node-6 | No Body | Proposed | No field holds the file's bytes or a parsed copy, and a write carrying one is refused. | |

### Directories
----
RID: `req-tap-files-directory`

Status: `Proposed`

A `tap_directory` is a named container of held files and of other directories, a core type owned by
this app like `tap_file` (ruled 2026-11-17).

- **Fields.** `name`, and `path`: the parent directory's path, a `/` and the name, or `/` and the
  name for a directory at the top. `NATURAL_KEY = ("path",)`, with the path shape of
  `req-tap-files-node`.
- **Edges.** `CONTAINS_TAP_DIRECTORY`, from a directory to a directory inside it, and
  `CONTAINS_TAP_FILE`, from a directory to a file inside it. Both are containment: `tap_directory`
  lists them in `CONTAINMENT_EDGES`, so retiring a directory retires what it holds. Both declare
  the plain identity and no properties.
- **One parent.** A directory has at most one parent, and a file sits in at most one directory. If
  one file must appear in two places, that is a future link node, not a second parent.
- **Path and edges agree.** The path is what identity is declared on; the edges are what a
  traversal follows. The helper that holds files (`req-tap-files-hold`) writes both and keeps them in
  step.
- **No cycles.** A directory cannot contain itself, directly or through its descendants.

A file need not sit in a directory. One with no `CONTAINS_TAP_FILE` edge is at the top.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-directory-1 | Type And Edges Declared | Proposed | `tap_directory`, `CONTAINS_TAP_DIRECTORY` and `CONTAINS_TAP_FILE` are declared by `tap_files`, and both edges are in the directory's `CONTAINMENT_EDGES`. | |
| req-tap-files-directory-2 | One Parent | Proposed | A second `CONTAINS_TAP_DIRECTORY` edge into one directory, and a second `CONTAINS_TAP_FILE` edge into one file, are refused. | |
| req-tap-files-directory-3 | Wrong Ends Refused | Proposed | `CONTAINS_TAP_FILE` from anything but a `tap_directory` or into anything but a `tap_file`, and `CONTAINS_TAP_DIRECTORY` between anything but two directories, are refused. | |
| req-tap-files-directory-4 | Retirement Cascades | Proposed | Tombstoning a directory tombstones the directories and files it contains, and their bytes stay in the store. | The store deletes nothing (`req-tap-files-immutable`). |
| req-tap-files-directory-5 | No Cycle | Proposed | An edge that would make a directory its own ancestor is refused. | |
| req-tap-files-directory-6 | Paths Follow Edges | Proposed | For every file and directory written through the helper, the stored path equals the path composed from its chain of containment edges. | |

### Format Records
----
RID: `req-tap-files-format-record`

Status: `Proposed`

A `tap_file` is generic: a name, a place, a size, a digest. What its bytes are (an SBOM, a
compliance report, a configuration export) is recorded on a second node, a format record, of a type
owned by whichever plugin understands that format. Core declares the join and nothing about the
formats.

- **The edge.** `FILE_CONTENTS`, declared by `tap_files`, from a `tap_file` to its format record.
  Its source is `tap_file`; its targets are left open, so a plugin points it at a type of its own
  without core knowing that type. It declares the plain identity and no properties.
- **At most one per file.** A file whose format nobody knows has none and is still a complete,
  downloadable file.
- **Validity lives on the format record.** Whether a file is well-formed, and why not, are facts
  about what a parser found, so they belong to the format record and never to the `tap_file`. A file
  that fails validation is still stored and still has its record, marked invalid, as evidence that
  the source served it. Whether a document was signed is a separate fact from whether it parsed;
  both are the format record's own fields, defined by the plugin that owns it.
- **A format record describes bytes, not a file.** Where a record is identified by the digest of its
  bytes, two files holding the same bytes share one record, and a record is never changed to follow
  a file. When a file's bytes are replaced, the file's `FILE_CONTENTS` edge moves to the record for
  its new bytes; the old record stays.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-format-record-1 | Edge Declared, Targets Open | Proposed | `FILE_CONTENTS` is declared by `tap_files` with `tap_file` as its only source and no target restriction; an edge from any other type is refused. | |
| req-tap-files-format-record-2 | One Per File | Proposed | A second `FILE_CONTENTS` edge out of one file is refused. | |
| req-tap-files-format-record-3 | Shared Record Survives A Replacement | Proposed | Two files hold the same bytes and share one format record of a test type. One file's bytes are then replaced. The original record is unchanged and still joined to the other file; the replaced file has one `FILE_CONTENTS` edge, to the record for its new bytes. | |

### Holding A File
----
RID: `req-tap-files-hold`

Status: `Proposed`

One helper in `tap_files` is how a program holds a file: it stores the bytes through the gateway and
shapes the nodes that represent them, so every caller gets the order right and none writes store
plumbing.

**The order, which is the point.**

1. Mint the `tap_file`'s entity identifier.
2. Store the bytes under it (`store_file`, which needs `files.create`). The store returns the digest,
   the size and the file version.
3. Return node and edge envelopes for the caller's own batch: the `tap_file` with the returned facts,
   its `CONTAINS_TAP_FILE` edge and any directories on its path that do not yet exist, and the
   `FILE_CONTENTS` edge when the caller supplies a format record.

The helper writes no grid node itself. A collector submits the envelopes in its own GRIFT batch with
everything else it found, so the file, its format record and the facts parsed from it land or fail
together. Bytes go first: if the batch then fails, the store holds an object no node points at,
which the check reports and which harms nothing (`req-tap-files-write`, "Order against the grid").

**When a file changes.** The same file with new bytes is the same node. The helper stores a new
version under the same identifier (`add_file_version`, which needs `files.update`) and returns a
patch setting `sha256`, `size_bytes` and `file_version`, naming the node version it expects so the
grid refuses a second writer. The caller's batch moves the `FILE_CONTENTS` edge to the record for the
new bytes. A renamed or moved file is likewise one node: the helper records the new name in the store
(`rename_file`) and patches `name`, `path`, `file_version` and its containment edge. The grid's history
keeps each earlier state, so the digest and version a file had at any past moment can be read from
history and the store still returns those bytes (`req-tap-files-history`).

**Retrying after a refused batch.** A refused batch leaves the store one version ahead of the node.
The node still names the current version, and downloads follow the node. On the next attempt the
helper reads the store's head first: if the head already holds the bytes it was given, it uses that
version and stores nothing; otherwise it stores after the head. A version skipped this way stays in
the store, recorded by no node.

**What is normally a new file.** A source that publishes a new document each day is producing new
files, not new versions of one, and each gets its own node. Versions are for the case where the thing
that was one file is replaced.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-hold-1 | Bytes Before Nodes | Proposed | When the helper returns, the store already holds the object; with the store refusing the write, the helper raises and returns no envelope. | |
| req-tap-files-hold-2 | Facts From The Store | Proposed | The returned `tap_file` envelope's `sha256`, `size_bytes` and `file_version` are exactly what the store returned, never values the caller passed. | |
| req-tap-files-hold-3 | Identifier Shared | Proposed | The `tap_file` envelope's entity identifier is the identifier the bytes were stored under. | |
| req-tap-files-hold-4 | No Grid Write | Proposed | The helper performs no grid write; the nodes exist only after the caller's batch commits. | |
| req-tap-files-hold-5 | New Version Updates The Same Node | Proposed | Holding new bytes for an existing file leaves one node whose `file_version` is one higher and whose earlier `sha256` is in its history, and the store returns the earlier bytes for the earlier version. | |
| req-tap-files-hold-6 | Capability Needed | Proposed | A caller without `files.create` is refused by the gateway, and the helper passes that refusal through unchanged. | |
| req-tap-files-hold-7 | Refused Batch Then Retry | Proposed | The helper stores a new version and the caller's batch is refused. The node still records the earlier version and digest, and a download returns the earlier bytes. A retry with the same bytes stores nothing and returns a patch naming the version already held; a retry with different bytes stores one version after the head. After the retried batch commits, the node, the store and the download agree. | |
| req-tap-files-hold-8 | Directories Made As Needed | Proposed | Holding a file at a path whose directories do not exist returns envelopes for each missing directory and its containment edge; holding a second file in the same directory returns none for it. | |

### Operation Logging
----
RID: `req-tap-files-logging`

Status: `Proposed`

Every gateway operation and every download produces one structured log record (ruled 2026-11-16:
the interface is specified with strong logging). The record is a structured message object
(`req-tap-logging-message-object`) with a reserved `message_code` for file operations and the
object identifier as its entity reference.

`message_data` carries: the operation; the object identifier; the version acted on; the digest and
size where the operation has them; the acting actor's stable key; the outcome (done, refused, failed);
for a refusal or failure, the reason class; and for a download, the route by which it was requested.

- **Reads are logged.** Who took a copy of which document, and when, is the question an auditor asks
  of a document store.
- **Refusals are logged.** A capability refusal, a size refusal, a conflict and an integrity failure
  each leave a record.
- **Never the content.** No record carries file bytes, and a logical name is recorded as a name and
  never interpreted.
- **Not a grid write.** Logging does not create nodes (`req-tap-logging-no-grid-mutation`). Whether
  file operations should also appear on the grid as run records is left for later; the log is the
  record in this release.

Each log call carries a site token as every committed log call does (`req-tap-logging-site-ids`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-logging-1 | One Record Per Operation | Proposed | Each gateway operation and each download emits exactly one record with the reserved code, whether it succeeds, is refused or fails. | |
| req-tap-files-logging-2 | Read Names The Reader | Proposed | A successful read's record carries the reader's actor key, the identifier, the version and the digest. | |
| req-tap-files-logging-3 | Refusal Recorded | Proposed | A read refused for lack of `files.read` produces a record with outcome refused and the actor's key. | |
| req-tap-files-logging-4 | No Content In Logs | Proposed | Storing and reading a file whose bytes contain a marker string leaves that string in no log record at any level. | |

### Download Route
----
RID: `req-tap-files-download`

Status: `Proposed`

A logged-in user downloads a stored file from the browser (ruled 2026-11-16).

- **Route.** `GET /files/<identifier>/download`, with no query parameters. The
  `/files` prefix is declared reserved by the owning app in the same change
  (`req-tap-auth-app-4`). `HEAD` is answered with the same headers and no body.
- **Which version.** The route serves the version the node records in its `file_version` field,
  and only that version, and before sending anything compares the store's digest and size for
  that version with the node's `sha256` and `size_bytes`. A disagreement is an integrity failure.
  The store's head is not consulted: a version stored ahead of a failed grid write is not the
  file's current content until a node says so. A node with no `file_version` field is refused
  rather than served the head (ruled 2026-11-17): falling back to the head would serve exactly the
  unrecorded bytes this rule exists to keep out. The identifier must be that of a live `tap_file`
  (`req-tap-files-node`); the route reads that node's fields and no other type's. There is no way to ask this route for another version (ruled 2026-11-17):
  a stored version no node records may hold bytes whose grid write was refused, including one
  below the node's version after a retry, and the node is the only authority for what a file's
  content is. Earlier versions stay readable by programs through the service layer; a browser
  surface for them is `req-tap-files-version-download`.
- **Who may.** The request must come from an authenticated user; the route is behind the login wall
  and is not exempted from it. The user must hold `files.read`, and must be able to read the node
  whose identifier this is, which must exist and be live. A file whose node is tombstoned is not
  downloadable through this route, though its bytes remain in the store.
- **What is sent.** The verified bytes (`req-tap-files-read`), with:
  - `Content-Disposition: attachment` carrying the logical name, encoded as RFC 6266 describes, so
    the file is saved and never rendered in the page's origin;
  - `Content-Type` set to the media type recorded on the file's node (ruled 2026-11-16), and
    `X-Content-Type-Options: nosniff`, so the browser uses the stated type and does not guess
    another. The value is the `tap_file`'s `media_type`, used only when it is a well-formed media
    type of plain token characters; when the field is null, empty or malformed, the type sent is
    `application/octet-stream`;
  - `Content-Length`, and an `ETag` that is the digest;
  - cache headers that keep the response out of shared caches.
- **What is refused, and how.** No session: the login wall's ordinary response. No capability, or a
  node the user cannot read: a refusal that does not reveal whether the file exists. Unknown
  identifier: not found. A node whose `file_version` names an object or a version the store does
  not hold: not found, as the read reports it (`req-tap-files-read`); a node can arrive without its
  bytes, by GRIFT for one. Integrity failure: a server error that names no detail, with the finding
  logged. A node with no `file_version`: a server error that names the missing field and sends no
  bytes, with the finding logged; the node is malformed, and no request can make it right.

The files served here may have been written by a third party and fetched by a collector. Serving
every one as an attachment is what makes that safe to do from the instance's own origin: whatever
type is stated, the browser saves the file and never renders it as part of TAP. The recorded type
makes the saved file open in the right program; it is not what the safety rests on.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-download-1 | Bytes And Digest | Proposed | A permitted user receives bytes whose SHA-256 equals the `ETag` and the digest on the file's node. | Closes the done-test of Issue# 1035 - tap. |
| req-tap-files-download-2 | Always An Attachment | Proposed | Every successful response carries `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`, for a file recorded as `text/html` as for any other. | |
| req-tap-files-download-9 | Recorded Type Sent, Safely | Proposed | The `Content-Type` equals the node's `media_type` when that is a well-formed media type, and is `application/octet-stream` when the field is absent, empty, or contains a space, a control character, a newline or a semicolon. | The last cases are header injection attempts. |
| req-tap-files-download-3 | Login Required | Proposed | An unauthenticated request receives the login wall's response and no bytes, and the route is absent from the login-exempt prefixes. | |
| req-tap-files-download-4 | Capability Required | Proposed | A logged-in user without `files.read` is refused, and the response is the same whether or not the identifier exists. | |
| req-tap-files-download-5 | Tombstoned Not Served | Proposed | After the file's node is tombstoned, the route refuses and the object is still present in the store. | |
| req-tap-files-download-6 | Hostile Name Safe In Header | Proposed | A logical name containing a quote, a newline, a semicolon and non-ASCII letters produces one well-formed `Content-Disposition` header and no additional header. | Header injection. |
| req-tap-files-download-7 | Prefix Reserved | Proposed | `/files` is in the reserved URL prefixes, and the reserved-prefix test passes. | |
| req-tap-files-download-10 | The Node's Version Is Served | Proposed | With version 2 stored and the node still recording version 1, a download with no `version` returns version 1's bytes with an `ETag` equal to the node's `sha256`; after the node is updated to version 2 it returns version 2's. | The stored-then-refused case. |
| req-tap-files-download-12 | No Version Chosen By The Caller | Proposed | With version 2 stored after a refused grid write and the node at version 3, a request carrying `?version=2`, or any other query parameter, returns version 3's bytes or is refused; no request to the route returns version 2's bytes, and none returns version 3's before the node records it. | Ruled 2026-11-17 in answer to the AI review on PR# 1213 - tap. |
| req-tap-files-download-13 | No Recorded Version Is Refused | Proposed | With versions 1 and 2 stored and the node's `file_version` field removed, a download returns a server error naming `file_version`, sends no file bytes, and logs a finding; it does not return version 2's bytes. | Ruled 2026-11-17 in answer to the AI review on PR# 1213 - tap. |
| req-tap-files-download-14 | Recorded Version Not Stored Is Not Found | Proposed | With the node recording version 3 and the store holding versions 1 and 2, and again with the store holding no object for the identifier, the route answers not found, sends no file bytes, and serves no other version. | Raised by the AI review on PR# 1218 - tap. |
| req-tap-files-download-11 | Node And Store Must Agree | Proposed | With the node's `sha256` or `size_bytes` differing from the store's for the node's version, the route returns a server error with no bytes and logs an integrity finding. | |
| req-tap-files-download-8 | Changed File Fails Visibly | Proposed | With the content altered on disk the route returns a server error with no file bytes, and an integrity finding is logged. | The integrity half of the Issue# 1035 - tap done-test. |

### Report-Only Check
----
RID: `req-tap-files-check`

Status: `Proposed`

`manage.py files check` examines the store and reports. It changes nothing at all: it writes no
file, moves nothing and takes no lock, so it is safe to run against a store in use. Recovery is a
separate step (`req-tap-files-write`). An object caught mid-write may be reported as it is seen; a
finding that a second run does not repeat was a write in progress.

It reports:

- **Invalid objects.** An object whose structure, inventory, sidecar or naming does not satisfy this
  specification. With `--deep`, also any content file whose bytes do not match its digest.
- **Objects with no live node.** An object whose identifier is not the identifier of a live
  `tap_file`. Stored bytes nothing on the grid points at: the result of a write whose grid half
  failed, or of a node tombstoned after its file was stored.
- **Nodes the store disagrees with.** Because `tap_file` is core's own type (`req-tap-files-node`),
  core finds the reverse case too: a live `tap_file` whose object the store does not have; one whose
  `file_version` is ahead of the store's head; one whose `sha256` or `size_bytes` differs from the
  store's for its version; and, as a notice and not a fault, one whose store head is ahead of its
  `file_version`, a version stored whose grid write did not follow.
- **Interrupted writes.** Staging directories, version directories above an object's head and root
  inventory pairs that do not match, each of which recovery would act on.
- **What recovery found.** The contents of `quarantine/`, with what each item was.
- **Totals.** Objects, versions, bytes.

Output is a human table by default and JSON with a published schema on request. The exit status is
non-zero when anything was found, so the command can gate a script.

The check exists from the first release because every system surveyed that shipped without one later
told its users to write their own.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-check-1 | Clean Store Is Clean | Proposed | Against a store of valid objects each with a live node, the check reports nothing and exits zero. | |
| req-tap-files-check-2 | Finds An Orphan Object | Proposed | An object with no matching live entity is listed by identifier. | |
| req-tap-files-check-3 | Deep Finds A Changed Byte | Proposed | With one content byte changed, the check without `--deep` may pass and with `--deep` names the object and version. | |
| req-tap-files-check-4 | Changes Nothing | Proposed | After the check runs against a store with findings, including a staging directory and a version directory above its head, every file and directory under the root is unchanged and in place. | |
| req-tap-files-check-6 | Reports What Recovery Would Do | Proposed | A leftover staging directory, a version directory above the head and a mismatched root pair are each listed, and none is moved or repaired. | |
| req-tap-files-check-7 | Finds A Node With No Bytes | Proposed | A live `tap_file` whose object is absent from the store is listed by identifier and path. | |
| req-tap-files-check-8 | Finds A Disagreement | Proposed | A live `tap_file` whose `sha256` differs from the store's digest for its version is listed with both values, and one whose `file_version` is ahead of the store's head is listed. | |
| req-tap-files-check-9 | A Head Ahead Is A Notice | Proposed | A store head one version ahead of its `tap_file` is listed as a notice, and alone does not make the exit status non-zero. | The node's own version is intact. |
| req-tap-files-check-5 | Seeded Defect Fails | Proposed | The check's own test seeds a defect of each reported class and asserts each is reported, so a passing check is not vacuous. | |

### Health Probe
----
RID: `req-tap-files-health`

Status: `Proposed`

One health probe reports the store. Where the store is not enabled it reports healthy and says so, unless an installed plugin requires it, in which case it is unhealthy. Where the store is enabled it reports it as usable or not: the mount test's verdict and reason, the
presence and validity of the storage-root marker and layout declaration, the filesystem type, and
free bytes and free inodes on the volume. It reads no object and walks nothing, and it does not touch
the database, so it answers truthfully when the database is down.

A non-empty `quarantine/` does not make the probe unhealthy; its item count is reported in the
probe's context so an operator sees it.

The probe and the boot gate are validation surfaces, so the implementing change adds their rows to
the Validation Map (`req-dev-validation-map`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-health-1 | Unmounted Is Unhealthy | Proposed | With the store enabled and its test failing, the probe is unhealthy and its detail carries the reason. | |
| req-tap-files-health-4 | Not Enabled Is Healthy | Proposed | With the store not enabled and no installed plugin requiring it, the probe is healthy and its context says the store is not enabled. | |
| req-tap-files-health-2 | Missing Marker Is Unhealthy | Proposed | With the storage-root marker removed from an initialised root, the probe is unhealthy. | |
| req-tap-files-health-3 | Quarantine Is Reported, Not Failed | Proposed | With one item in `quarantine/` the probe is healthy and its context gives the count. | |

### History Stays Possible
----
RID: `req-tap-files-history`

Status: `Proposed`

The maintainer's requirement is that this release leaves the door open for history tracking. Two
mechanisms carry it, and neither is new.

- **On disk**, OCFL keeps every version of an object, with who made it and when, and any version can
  be read by number.
- **On the grid**, the node that represents a file changes when the file does, and the grid's
  existing history system records each earlier state, including the digest and file version it had.

So the history of a file is already recoverable: a node's history says which file version was current
at any past moment, and the store returns that version's bytes. What is left for later is a surface
that presents it.

This requirement exists to name the two things that would close the door, so a later change does not
do either by accident: overwriting stored bytes in place, and removing earlier versions when a new one
is written.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-history-1 | Every Version Named In The Inventory | Proposed | After any number of versions and renames, the root inventory lists every version with its time, actor, logical name and digest. | |
| req-tap-files-history-2 | Past Bytes Retrievable | Proposed | Given a digest and file version taken from a `tap_file`'s history entry, the store returns bytes with that digest. | |

### File Size Limit
----
RID: `req-tap-files-size-limit`

Status: `Backlog`

This release puts no ceiling on the size of a stored file (ruled 2026-11-16: no case calls for one
yet, and choosing a number now is premature). What is recorded for when one is wanted:

- **What a ceiling is for.** Stopping a runaway or hostile source from filling the volume. It is not
  for policing ordinary files, so it belongs above everything legitimately stored. The largest
  datasets any current plugin handles are a little over 1 GB.
- **Two levels were sketched.** An instance-wide ceiling an operator sets, and a tighter limit a
  caller passes with a write because it knows roughly how big the thing it is fetching should be. The
  lower applies, and a caller cannot raise the instance ceiling.
- **Enforced as bytes arrive**, not after, so an oversized stream is abandoned without being stored.
- **What it interacts with.** Verification reads a file twice before releasing it
  (`req-tap-files-read`), so a ceiling also bounds read cost; and what actually prevents a full disk
  in the systems surveyed is a floor on free space for the whole volume, which is a separate idea.

### Deletion And Retention
----
RID: `req-tap-files-retention`

Status: `Backlog`

This release keeps every object and every version (ruled 2026-11-16). The questions deletion will
have to settle, recorded here so they are not rediscovered:

- **What a tombstone means for bytes.** A tombstoned node's file stays in the store and stops being
  downloadable. Whether bytes may ever be removed while the grid's history still refers to them is
  the hard part, and no surveyed system has garbage collection that respects version history and
  tombstones together.
- **OCFL does not support purging.** Its guidance is to create a new object without the content and
  delete the original, optionally leaving a placeholder. A deletion design has to say how that looks
  from the grid.
- **Replaceable files need it first.** A large dataset refreshed often cannot be kept forever. That
  kind of content stays in a plugin data directory until deletion exists here.
- **Retention and legal hold** are separate from deletion and from each other: a period before which
  content may not be removed, and a hold with no expiry.
- **Order.** A row is removed before its bytes, never the reverse, and never inside the same
  database transaction.

### Other Backends
----
RID: `req-tap-files-backends`

Status: `Backlog`

No backend other than the local filesystem is planned (ruled 2026-11-16). An operator who wants other
storage can mount it at the root on the host. For a contributor who wants to build one:

- **Shape.** A separate, optional package that wraps the storage vendor's own SDK behind the backend
  protocol and declares its own dependencies and FIPS posture. A survey on 2026-11-16 found no
  multi-backend library that is at once current, owned by an organisation and free of its own
  cryptographic provider, and found that the vendors' own SDKs are. Core gains no dependency.
- **Discovery.** By an entry-point group, as secret sources are (`req-tap-plugin-depres-sources`).
- **What a backend must guarantee.** Everything the behavioural test suite of
  `req-tap-files-interface` checks: put-if-absent, verified reads, no partial object visible, every
  version retrievable. An object store offers put-if-absent and server-side digest checks unevenly, so
  a backend tests for them and falls back to check-then-write, which is safe when no two writers
  share an identifier.
- **What stays local.** Plugin data directories are never remote.

### Browser Upload
----
RID: `req-tap-files-upload`

Status: `Backlog`

A person adding a file through the web interface is the second release (ruled 2026-11-16: "let's get
them to disk first"). It brings the hostile-content surface this release avoids by having only
programs write: enforcing the size ceiling on the request body before it is buffered, cross-site
request forgery protection on the route, a decision about which roles hold `files.create`, and
abandoned partial uploads. The write path of `req-tap-files-write` is already the right one for it.

### Reading Inside Files
----
RID: `req-tap-files-slices`

Status: `Backlog`

Searching stored files and returning parts of them, to answer questions and to give an AI reader
context. Two properties of this release are chosen so that it stays cheap:

- A stored version's bytes never change, so a position inside one (a line range, a byte range, a
  page, a row) addressed together with the digest is exact forever.
- Text extracted from a file, and any index over it, is derived data keyed by the digest and the
  version of whatever produced it. It is superseded when either changes and never invalidated.

Partial download by HTTP range is part of this and is not in this release.

### Downloading An Earlier Version
----
RID: `req-tap-files-version-download`

Status: `Backlog`

A person downloading a version of a file other than the current one. This release serves only the
version the file's node records (`req-tap-files-download`), ruled 2026-11-17, because the store
holds versions no node ever recorded: bytes stored before a grid write that was then refused, which
can sit above the node's version or, after a retry, below it.

What this needs, and why it is not in this release: a requested version is served only if the
node's grid history once recorded that file version with that digest. Checking it means reading a
node's history from core without knowing the node's type, and whether the service layer offers
that read is not yet known. The data to answer it already exists (`req-tap-files-history`): the
grid keeps each earlier state of the node, and the store keeps every version.

### Dimensions For Files And Directories
----
RID: `req-tap-files-dimensions`

Status: `Backlog`

`tap_file`, `tap_directory` and their edges carry whatever dimensions core's vocabulary requires of
every core type, and nothing more is declared now. There will be dimensions worth having for held
files, and it is not yet known which. What any must respect: identity never rests on a dimension
(`req-grid-entity-natural-key`), and a dimension added after files exist means re-stamping them.

### v0 Non-Goals
----
RID: `req-tap-files-nongoals`

Status: `Proposed`

- **No deletion, retention or garbage collection.** `req-tap-files-retention`.
- **No limit on the size of a file.** `req-tap-files-size-limit`.
- **No browser upload.** `req-tap-files-upload`.
- **No backend but the local filesystem.** `req-tap-files-backends`.
- **No reading inside files and no HTTP range.** `req-tap-files-slices`.
- **No browser download of an earlier version.** `req-tap-files-version-download`.
- **No format records.** What a file's bytes are, and whether they are valid, is recorded on a
  format record of a type owned by the plugin that understands the format
  (`req-tap-files-format-record`); core declares no such type.
- **No knowledge of formats.** No type detection, no parsing, no validation of content.
- **No deduplication.** Two files with identical bytes are stored twice. That is the price of a store
  in which every object is self-describing, and the formats this was designed for are small.
- **No access control per file.** The four capabilities are the whole model.
- **No encryption at rest by the store.** An operator who needs it encrypts the volume.
- **No virus scanning or content rewriting.**
- **No moving files between grids.** GRIFT carries a file's node, with its digest and size, and not
  its bytes; how bytes follow is a Backlog requirement of the GRIFT specification
  (`req-grift-stored-files`).
- **No backup or restore.** The volume is self-describing and a copy of it is a complete copy of the
  store; declaring it in the backup manifest is the backup specification's work.
- **No multi-file objects.**

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-nongoals-1 | Non-Goals Are Listed | Proposed | This section names each deliberate omission, and each that has a planned home names the requirement that holds it. | |

## Open Decisions

None. Every choice this specification makes has been ruled on.

Ruled 2026-11-16 and now in the requirements above: the store is a new core app, named `tap_files`;
the store is optional and enabled by its setting being set, with no default path; this repository's
compose files enable it; the object identifier is a `urn:uuid:` URN; the directory tree is for programs and uses the
`0003` hash-and-identifier layout; a download carries the media
type recorded on the node and is always an attachment; there is no file size limit in this release;
the names `TAP_FILES_ROOT`, `files.*`, `/files` and `manage.py files`; the collector actor's grant is global for now, with per-collector scoping
tracked in Issue# 1205 - tap.

Ruled 2026-11-17 and now in the requirements above: a read delivers the descriptor it verified,
content files are placed read-only, and a process with write access to the volume during a read is
outside the threat model (`req-tap-files-read`, `req-tap-files-immutable`); the download route
serves only the node's version, and refuses a node that records none (`req-tap-files-download`);
a stored filename is ASCII and fits one path element (`req-tap-files-naming`).

Ruled 2026-11-17 and now in the requirements above, superseding the design session's decisions D8,
D9 and D10 where they disagree: the grid's representation of a held file is core's own, `tap_file`
and `tap_directory` with their edges in `tap_files`, so storing files never depends on a plugin
(`req-tap-files-node`, `req-tap-files-directory`); a file is found again by its directory and its
name, written as one logical path, with no path scope; the join to a plugin's format record,
`FILE_CONTENTS`, and the holding helper are core's (`req-tap-files-format-record`,
`req-tap-files-hold`); and the check reports file nodes the store disagrees with
(`req-tap-files-check`).

## What This Settles Elsewhere

- **Issue# 1035 - tap.** Its done-test is met by `req-tap-files-gateway`, `req-tap-files-download`,
  `req-tap-files-read` and `req-tap-files-node`: the `tap_file` is the node that carries the reference.
- **computing-core-tap.** Its `file` stays what it was before this design, a file observed on a host,
  and gains no content facts, scope or held-file helper; the file and directory requirements drafted
  on its `spec/file-and-directory-nodes` branch move here and are withdrawn there. When TAP holds a copy
  of a file it observed, computing-core links its `file` to the `tap_file` by an edge it declares
  itself (ruled 2026-11-17), since core cannot name a plugin's type. Its `sbom_document` is a format
  record joined by `FILE_CONTENTS`, and its parse-outcome fields stay in its own specification.
- **`specs/spec-cicd-sbom.md`.** `req-cicd-sbom-20-7` and `req-cicd-sbom-24-2` name this store as where
  SBOM revisions are kept; `req-cicd-sbom-20-8` (a restore keeps the files) remains open until the
  backup specification declares the volume.
- **Issue# 456 - tap.** Settled for this root here and for the plugin data root in its own
  specification.
- **The collector evidence store** designed on the `spec/cares-evidence` branch is superseded. What
  that design wanted from a store (exact bytes, content named by digest, atomic writes, verification
  before release, a recovery sweep, bytes gated separately from metadata, reads recorded) is provided
  here. Its record of what a collector observed is a node type and is not part of this specification.

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed | Requirement has been designed but not yet accepted for implementation. |
| Approved for Development | Requirement is accepted and ready to be built. |
| In Development | Requirement is actively being implemented. |
| Implemented | Requirement has been built but not fully verified. |
| Verified | Requirement has been implemented and validated against acceptance criteria. |
| Backlog | Requirement is recorded for later and is not designed in detail. |
| Refactoring | Requirement is being reworked without changing intended behavior. |
| Deprecating | Requirement is being phased out. |
| Deprecated | Requirement is no longer active. |
