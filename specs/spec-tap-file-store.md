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

What core knows about a stored file is deliberately little: an identifier, a name, bytes, a digest,
a size and a version. What a file *means* (that it is an SBOM, that it is valid, who published it)
belongs to the plugin that understands the format and lives on that plugin's own node.

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
| req-tap-files-logging | [Operation Logging](#operation-logging) | Proposed | One structured record per operation, reads and refusals included |
| req-tap-files-download | [Download Route](#download-route) | Proposed | A logged-in user with `files.read` downloads a file as an attachment |
| req-tap-files-check | [Report-Only Check](#report-only-check) | Proposed | A command that validates the store and lists what does not match the grid |
| req-tap-files-health | [Health Probe](#health-probe) | Proposed | A probe that reports the root as usable or not |
| req-tap-files-history | [History Stays Possible](#history-stays-possible) | Proposed | Nothing in this release prevents reading any earlier version |
| req-tap-files-retention | [Deletion And Retention](#deletion-and-retention) | Backlog | Removing content, retention periods, and what a tombstone means for bytes |
| req-tap-files-backends | [Other Backends](#other-backends) | Backlog | How a contributed backend is discovered and what it must guarantee |
| req-tap-files-upload | [Browser Upload](#browser-upload) | Backlog | A person adding a file through the web interface |
| req-tap-files-slices | [Reading Inside Files](#reading-inside-files) | Backlog | Searching stored files and returning addressed parts of them |
| req-tap-files-nongoals | [v0 Non-Goals](#v0-non-goals) | Proposed | What this specification deliberately does not do |

### Scope
----
RID: `req-tap-files-scope`

Status: `Proposed`

The file store keeps whole files for the grid. It is a core capability: any app or plugin may use it
through the service gateway (`req-tap-files-gateway`), and no plugin is required for it to work.

**What the store knows about a file.** An identifier, the name it is known by, its bytes, their
SHA-256 digest and size, its versions, and who wrote each version and when.

**What the store does not know.** A file's format, what is inside it, whether it is valid, what it
describes, or where it sits in any folder structure. Folders, and the node types that represent a
file and a directory on the grid, are vocabulary and belong to the plugin that owns that vocabulary.
A file's meaning belongs to the plugin that understands its format, on a node of that plugin's own
type. The store imports no plugin.

**The join between grid and store.** A stored file's identifier is the entity identifier of the node
that represents it. The node carries the file's name, size, digest and file version; the store holds
the bytes under the same identifier. Neither side needs a path field to find the other.

**Not for working data.** A database updated in place, a version-control clone or a cache of fetched
datasets is a plugin data directory (`tap_plugins/specs/spec-tap-plugin-data-directory.md`), which is
sub-grid and has a different volume.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-scope-1 | Core Imports No Plugin | Proposed | The file store's code imports nothing from any plugin package, and works in an instance with zero plugins installed. | Covered by the lean-boot gate once built. |
| req-tap-files-scope-2 | One Store | Proposed | Exactly one module reads or writes under the file store root; a guard test finds no other reference to the root setting outside it. | The same guard the superseded evidence design proposed. |
| req-tap-files-scope-3 | Format-Blind | Proposed | No store operation branches on a file's extension, declared type or content. | |

### The Root
----
RID: `req-tap-files-root`

Status: `Proposed`

The store lives under one root named by one core setting.

- **Setting.** `settings.TAP_FILES_ROOT`, projected from the environment variable `TAP_FILES_ROOT` in
  `tap/settings.py`, default container path `/var/lib/tap/files`. Every consumer reads the setting;
  the variable and the literal appear nowhere else. The rule is the one the secrets root arrived at
  (`req-tap-cares-secrets-root-resolution`).
- **Its own volume.** The compose files mount a named volume at the root in every service that runs
  store code. It is a different volume from the plugin data volume (ruled 2026-11-16). The reason is
  disk-full: plugin caches can grow by gigabytes, and on a shared disk a runaway cache would stop a
  compliance document being written. Separate roots also let a backup treat the two differently.
- **Layout under the root.** Core owns everything under the root:

  | Path | Holds |
  | --- | --- |
  | `ocfl/` | The OCFL storage root. Nothing but OCFL content is ever placed in it. |
  | `staging/` | Files being written, before they are moved into `ocfl/`. Same filesystem, so the move is atomic. |
  | `quarantine/` | Incomplete or invalid content moved aside by recovery or by the check, never deleted. |
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
| req-tap-files-root-1 | One Setting | Proposed | `TAP_FILES_ROOT` is read from the environment in `tap/settings.py` only, and its default path appears in Python only there. | Guard-pinned. |
| req-tap-files-root-2 | Compose Mounts A Named Volume | Proposed | Every compose file that defines a service running store code mounts a named volume at the root and sets the variable; that volume is not the plugin data volume. | |
| req-tap-files-root-3 | Nothing Foreign Under The OCFL Root | Proposed | After any sequence of store operations, including interrupted ones, `ocfl/` contains only the storage-root marker, the layout declaration, the extensions directory and object hierarchy, with no empty directory. | OCFL section 4.1. |
| req-tap-files-root-4 | Roots Do Not Overlap | Proposed | The mount gate fails when the file store root and the plugin data root are the same path or one contains the other. | |

### Mount Gate And Initialisation
----
RID: `req-tap-files-mount-gate`

Status: `Proposed`

**Gate.** Boot refuses to proceed unless the root is a mounted, writable volume: the path exists and
is a directory and not a symbolic link; it is on a different device from the container's root
filesystem; and a real write, `fsync`, rename and remove succeeds in `staging/`. The refusal is a
standup abort (`req-boot-abort-signal`) in the `boot` domain naming the root and the failed check.
The test is one function, shared with the health probe, and is the same test the plugin data
directory uses (`req-tap-plugin-datadir-mount-gate`); the two share an implementation, not a copy.

The failure being prevented is the one Docker does nothing to signal: the volume is not mounted, the
path exists inside the container's own disk, files are written there, and they are gone when the
container is recreated.

In this draft the gate always applies, because the store is a core capability with no declaration
to key a condition on. That is an open decision (Open Decisions, 1).

**Initialisation.** After the gate passes:

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
| req-tap-files-mount-gate-1 | Unmounted Root Aborts | Proposed | With the root path present on the same device as `/`, boot exits non-zero after one `ABORT` record whose reason says the root is not a mounted volume. | |
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
  recommends, and the root inventory equals the newest version's.
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
| req-tap-files-ocfl-2 | Only Expected Warnings | Proposed | The same run reports no warning other than the ones this section accepts by name: the SHA-512 recommendation, and the identifier form if Open Decision 3 keeps the bare identifier. | A new warning is a finding. |
| req-tap-files-ocfl-3 | Sidecar Matches | Proposed | For every inventory file in the store, the adjacent sidecar holds the SHA-256 of that inventory's bytes. | |
| req-tap-files-ocfl-4 | Inventory Schema | Proposed | Every inventory written validates against the shipped schema; an inventory on disk that fails it makes the object unreadable through the store and is reported by the check. | |
| req-tap-files-ocfl-5 | Readable Cold | Proposed | Given only a copy of `ocfl/`, a script using nothing but the standard library can list every object's identifier, logical name, versions and digests, and verify every content file. | The test of Goal 3. |

### Object And File Naming
----
RID: `req-tap-files-naming`

Status: `Proposed`

**The object identifier** is the UUID of the node that represents the file, in its canonical
lower-case hyphenated form.

**The object directory is derived from the identifier alone** (ruled 2026-11-16). OCFL requires "a
deterministic mapping from an object identifier to a unique storage path"; a name and a digest can
both change, so neither may take part. The store uses the registered OCFL layout extension
`0003-hash-and-id-n-tuple-storage-layout` with its defaults: the SHA-256 of the identifier, cut into
three three-character levels, then the identifier itself as the last level.

```
ocfl/839/e6c/5a9/0192f3a1-7c2e-7d4a-9b1c-2f6e5a7b8c9d/
```

The hashed levels keep any one directory from holding millions of entries; the last level is the
identifier, so a person holding a node's identifier can find its directory.

**The stored filename** carries four things, so a file copied out of the store still says what it is:

```
<stem>+<identifier>+v<N>+<sha256>.<extension>
vdr-2026-11-16+0192f3a1-7c2e-7d4a-9b1c-2f6e5a7b8c9d+v1+9f86d0…0f00a08.json
```

- `<stem>` and `<extension>` are derived from the logical name at the time of that version. The stem
  keeps letters, digits, `.`, `_` and `-`, replaces every other character with `_`, drops leading
  dots, and is cut to 100 characters. The extension is the logical name's final suffix when it is 1
  to 16 letters or digits, and is otherwise omitted along with its dot.
- `<identifier>` is the object identifier.
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
| req-tap-files-naming-2 | Layout Matches The Extension | Proposed | For a known identifier the object directory equals the path the `0003` extension's own algorithm and published example produce with default parameters. | |
| req-tap-files-naming-3 | Name Carries All Four | Proposed | Every content file's name parses from the right into a digest equal to the SHA-256 of its bytes, a version equal to its version directory, and an identifier equal to its object's. | |
| req-tap-files-naming-4 | Hostile Names Are Safe | Proposed | Logical names containing `../`, a leading dot, a NUL, a newline, a `+`, a 300-character stem and a reserved device name each either produce a stored filename inside the object's own `content` directory or are refused; none writes anywhere else. | |
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
  inventory gains a version whose state maps the existing digest to the new name. No file is written
  into the new version's directory, so no directory is created for it.
- **Nothing is deleted.** There is no operation that removes an object, a version or a content file
  (`req-tap-files-retention`).

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
| req-tap-files-immutable-2 | Rename Stores No Bytes | Proposed | A rename raises the head version by one, adds no content file, and leaves the digest unchanged. | |
| req-tap-files-immutable-3 | No Delete Operation | Proposed | The backend protocol and the service gateway expose no operation that removes an object, a version or content, and no code path under the store unlinks a file inside `ocfl/`. | Recovery moves incomplete content to quarantine; it does not unlink. |
| req-tap-files-immutable-4 | Stale Writer Refused | Proposed | Adding a version or renaming with an expected version that is not the head is refused with a conflict error carrying both numbers, and changes nothing. | |
| req-tap-files-immutable-5 | Create Is Put-If-Absent | Proposed | Creating an object whose identifier already exists is refused and the existing object is unchanged. | |

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
   Writers do not wait indefinitely; a write that cannot take the lock within a short bound fails
   with a busy error.
2. **Stream to staging while hashing.** Bytes are copied in bounded chunks into a new directory under
   `staging/`, with the SHA-256 computed as they pass. The whole file is never held in memory.
3. **Enforce the size ceiling as bytes arrive.** A write that exceeds `settings.TAP_FILES_MAX_BYTES`
   is abandoned at that point, its staging directory removed, and the operation refused. The ceiling
   bounds what a faulty or hostile source can make the store accept.
4. **Check the caller's digest, when given.** A caller that knows the digest it expects passes it,
   and a mismatch refuses the write. A collector that has verified a document elsewhere uses this to
   prove the store kept the same bytes.
5. **Build the complete result in staging.** For a create, the whole object directory. For a new
   version, the version directory and the new root inventory and sidecar.
6. **Make it durable.** `fsync` each file and its directory.
7. **Move into place.**
   - A create renames the staged object directory to its place under `ocfl/`, creating the hashed
     parent levels first. The rename is atomic, so the object either exists whole or not at all.
   - A new version renames the staged version directory into the object, then replaces the root
     inventory, then its sidecar, each by an atomic rename. The inventory is replaced last because an
     object whose root inventory does not mention a version directory is recoverable, and one whose
     inventory names content that is not there is not.
8. **Log, release the lock, return** the digest, size and version.

**Order against the grid.** Bytes are stored before the node that names them is written, and a
caller whose grid write then fails is left with a stored object and no node. That is the safe
direction: the check reports it (`req-tap-files-check`), and nothing points at bytes that are not
there.

**Recovery.** At boot, and at the start of the check, the store sweeps for what an interrupted write
left behind and moves it to `quarantine/` with a note saying what it was and when it was found:

- anything under `staging/`, since no write is in progress at boot;
- a version directory in an object numbered above the head recorded in its root inventory;
- a hashed parent directory under `ocfl/` left empty by a create that did not finish, which is
  removed, this being the one place the store removes a directory, and only an empty one.

Recovery never changes an object's inventory and never removes content.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-write-1 | Bytes Exact | Proposed | The stored content file's bytes equal the bytes supplied, and the returned digest equals their SHA-256. | |
| req-tap-files-write-2 | Ceiling Enforced Mid-Stream | Proposed | A stream longer than the ceiling is refused after at most the ceiling plus one chunk has been read, and leaves nothing under `ocfl/` or `staging/`. | |
| req-tap-files-write-3 | Declared Digest Checked | Proposed | A create given an expected digest that does not match is refused and stores nothing. | |
| req-tap-files-write-4 | Interrupted Create Leaves No Object | Proposed | A create killed at any step before the final rename leaves no object for its identifier, and after the next boot `ocfl/` validates and the remains are in `quarantine/`. | Test by injecting a failure at each step. |
| req-tap-files-write-5 | Interrupted Version Leaves The Old Head | Proposed | An `add_version` killed at any step leaves the object readable at its previous head with its previous bytes, and after the next boot the object validates. | |
| req-tap-files-write-6 | One Writer Per Object | Proposed | Two concurrent creates for one identifier yield exactly one success; two concurrent `add_version` calls with the same expected version yield one success and one conflict. | Across processes, not only threads. |
| req-tap-files-write-7 | Constant Memory | Proposed | Writing a file many times larger than the chunk size does not raise the process's memory use by more than a small multiple of the chunk size. | |
| req-tap-files-write-8 | Recovery Removes No Content | Proposed | After recovery, every content file that existed under `ocfl/` before it still exists and is unchanged. | |

### Read Path
----
RID: `req-tap-files-read`

Status: `Proposed`

No byte leaves the store unverified. `open` reads the object's root inventory, checks the inventory
against its sidecar, locates the requested version's content file, computes the SHA-256 of the whole
file, compares it with the inventory's digest, and only then returns a stream.

Verification completes before the first byte is released. A stream that verifies as it goes cannot
take back what it has already sent, and a caller that has received half a corrupted file has no way
to know. The cost is reading the file twice, which the size ceiling bounds.

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
| req-tap-files-read-6 | Finding Raised | Proposed | Each integrity failure produces one log record and one `CONCERN` record naming the identifier and the failure kind. | |

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

Grants follow the registry's existing rules: `tap_admin` receives each capability explicitly, and no
capability implies another. Which other built-in roles and program actors receive which is an open
decision (Open Decisions, 4).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-capabilities-1 | Registered With Descriptions | Proposed | The four capabilities are present in the registry file with a description and a risk, and the file validates against its schema. | |
| req-tap-files-capabilities-2 | Grid Read Is Not Enough | Proposed | An actor holding `grid.read` and not `files.read` can read a file's node and is refused its bytes. | |
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

**Who mints the identifier.** The caller. A caller storing a file for a node it is about to create
mints the node's entity identifier first, stores the bytes under it, and then writes the node
carrying the returned digest, size and file version. The gateway does not create or change any node:
the store is format-blind and type-blind, and writing nodes is the job of the service layer the
caller already uses.

**Writers in this release are programs** (ruled 2026-11-16): collectors and other processes running
inside the instance, through this gateway. That covers a file fetched from an outside source and a
file TAP produced itself. There is no path by which a browser adds a file
(`req-tap-files-upload`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-gateway-1 | Every Export Gated | Proposed | Every name the gateway exports is an operation carrying a capability requirement; the boundary guard finds none ungated. | `req-service-boundary-contract-surface`. |
| req-tap-files-gateway-2 | Refused Without The Capability | Proposed | Each gateway operation called by an actor without its capability raises the standard capability error and performs no backend call. | |
| req-tap-files-gateway-3 | Actor From Context | Proposed | The writer recorded in a version's inventory entry is the caller context's actor, and no gateway operation accepts an actor argument. | |
| req-tap-files-gateway-4 | No Grid Write | Proposed | No gateway operation creates, changes or deletes a node or an edge. | |

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

- **Route.** `GET /files/<identifier>/download`, with an optional `version` query parameter. The
  `/files` prefix is declared reserved by the owning app in the same change
  (`req-tap-auth-app-4`). `HEAD` is answered with the same headers and no body.
- **Who may.** The request must come from an authenticated user; the route is behind the login wall
  and is not exempted from it. The user must hold `files.read`, and must be able to read the node
  whose identifier this is, which must exist and be live. A file whose node is tombstoned is not
  downloadable through this route, though its bytes remain in the store.
- **What is sent.** The verified bytes (`req-tap-files-read`), with:
  - `Content-Disposition: attachment` carrying the logical name, encoded as RFC 6266 describes, so
    the file is saved and never rendered in the page's origin;
  - `Content-Type: application/octet-stream` and `X-Content-Type-Options: nosniff`, so the browser
    does not guess a type and act on it;
  - `Content-Length`, and an `ETag` that is the digest;
  - cache headers that keep the response out of shared caches.
- **What is refused, and how.** No session: the login wall's ordinary response. No capability, or a
  node the user cannot read: a refusal that does not reveal whether the file exists. Unknown
  identifier or version: not found. Integrity failure: a server error that names no detail, with the
  finding logged.

The files served here may have been written by a third party and fetched by a collector. Serving
them as attachments with a fixed type is what makes that safe to do from the instance's own origin:
nothing a stored file contains is ever interpreted by the browser as part of TAP.

Sending every file as `application/octet-stream` and not as the type recorded on its node is this
draft's choice and an open decision (Open Decisions, 5).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-files-download-1 | Bytes And Digest | Proposed | A permitted user receives bytes whose SHA-256 equals the `ETag` and the digest on the file's node. | Closes the done-test of Issue# 1035 - tap. |
| req-tap-files-download-2 | Always An Attachment | Proposed | Every successful response carries `Content-Disposition: attachment`, `Content-Type: application/octet-stream` and `X-Content-Type-Options: nosniff`, for a stored HTML file as for any other. | |
| req-tap-files-download-3 | Login Required | Proposed | An unauthenticated request receives the login wall's response and no bytes, and the route is absent from the login-exempt prefixes. | |
| req-tap-files-download-4 | Capability Required | Proposed | A logged-in user without `files.read` is refused, and the response is the same whether or not the identifier exists. | |
| req-tap-files-download-5 | Tombstoned Not Served | Proposed | After the file's node is tombstoned, the route refuses and the object is still present in the store. | |
| req-tap-files-download-6 | Hostile Name Safe In Header | Proposed | A logical name containing a quote, a newline, a semicolon and non-ASCII letters produces one well-formed `Content-Disposition` header and no additional header. | Header injection. |
| req-tap-files-download-7 | Prefix Reserved | Proposed | `/files` is in the reserved URL prefixes, and the reserved-prefix test passes. | |
| req-tap-files-download-8 | Changed File Fails Visibly | Proposed | With the content altered on disk the route returns a server error with no file bytes, and an integrity finding is logged. | The integrity half of the Issue# 1035 - tap done-test. |

### Report-Only Check
----
RID: `req-tap-files-check`

Status: `Proposed`

`manage.py files check` examines the store and reports. It changes nothing except to run the recovery
sweep (`req-tap-files-write`), which only moves incomplete content aside.

It reports:

- **Invalid objects.** An object whose structure, inventory, sidecar or naming does not satisfy this
  specification. With `--deep`, also any content file whose bytes do not match its digest.
- **Objects with no live node.** An object whose identifier is not the identifier of a live entity.
  Stored bytes nothing on the grid points at: the result of a write whose grid half failed, or of a
  node tombstoned after its file was stored.
- **What recovery found.** The contents of `quarantine/`, with what each item was.
- **Totals.** Objects, versions, bytes.

The reverse case, a node that claims a stored file the store does not have, cannot be found by core
alone, because core does not know which node types represent files. Core provides `file_exists` so
the plugin that owns such a type can report it, and that report belongs to that plugin.

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
| req-tap-files-check-4 | Changes Nothing | Proposed | After the check runs against a store with findings, every file under `ocfl/` is unchanged. | |
| req-tap-files-check-5 | Seeded Defect Fails | Proposed | The check's own test seeds a defect of each reported class and asserts each is reported, so a passing check is not vacuous. | |

### Health Probe
----
RID: `req-tap-files-health`

Status: `Proposed`

One health probe reports the store as usable or not: the mount test's verdict and reason, the
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
| req-tap-files-health-1 | Unmounted Is Unhealthy | Proposed | With the mount test failing, the probe is unhealthy and its detail carries the reason. | |
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
| req-tap-files-history-2 | Past Bytes Retrievable | Proposed | Given a digest and file version taken from a node's history entry, the store returns bytes with that digest. | Exercised with the first node type that represents a file. |

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

### v0 Non-Goals
----
RID: `req-tap-files-nongoals`

Status: `Proposed`

- **No deletion, retention or garbage collection.** `req-tap-files-retention`.
- **No browser upload.** `req-tap-files-upload`.
- **No backend but the local filesystem.** `req-tap-files-backends`.
- **No reading inside files and no HTTP range.** `req-tap-files-slices`.
- **No node types.** The types that represent a file and a directory on the grid are vocabulary and
  are specified by the plugin that owns them.
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

Decisions this draft makes that the maintainer has not ruled on.

| # | Decision | What the draft says | Why it is open |
| :---: | --- | --- | --- |
| 1 | When the mount gate applies | Always | The ruling to fail hard at boot was given for plugin directories, where a manifest declaration says whether the volume is needed. The store has no such declaration. The alternative is to gate only once something has been stored, which hides a missing volume until the first write. |
| 2 | Where the code lives | A new core app. The name `tap_files` is proposed and not ruled | Ruled 2026-11-16: a new app. It owns the setting, the `/files` prefix, the health probe, the service gateway and the management command. A new app means the architecture document's subsystem table changes in the implementing change, and this document moves under the app's own `specs/` directory when the app exists. |
| 3 | The form of the object identifier | The bare UUID | OCFL says an identifier should be a URI, so a strict validator warns. `urn:uuid:<uuid>` removes the warning, and then the layout extension percent-encodes the colons, so the directory is no longer named by the plain identifier, which the ruling asked for. |
| 4 | Who holds the capabilities | `tap_admin` all four; nothing else stated | A collector must hold `files.create` to store what it fetched, and today one program actor runs every collector, so granting it there is global. Which human roles hold `files.read` decides who can download. |
| 5 | The download's content type | Always `application/octet-stream` | Sending the type recorded on the node would let a browser label the saved file better. It also makes safety depend on a field a writer supplied. The fixed type is the conservative choice. |
| 6 | The size ceiling's default | Left to be set; a setting exists | The first consumers' files are about 1 MB to 10 MB. A default near 100 MiB covers them tenfold; verification reads each file twice, so the ceiling also bounds read cost. |
| 7 | Names | `TAP_FILES_ROOT`, `TAP_FILES_MAX_BYTES`, `files.*`, `/files`, `manage.py files` | Proposed for consistency with existing names; none is ruled. |

## What This Settles Elsewhere

- **Issue# 1035 - tap.** Its done-test is met by `req-tap-files-gateway`, `req-tap-files-download` and
  `req-tap-files-read` together with the node type that carries the reference, which is specified in
  the vocabulary plugin.
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
