# Plugin Data Directory Specification

## Philosophy

Some plugins need a place on disk that is theirs: a SQLite database they update in place, a bare git
clone, a downloaded scanner binary, a cache of large files fetched from a public source. None of that
is graph data, and none of it can be expressed as "store these bytes, read these bytes back". It needs
a real directory on a real local filesystem.

Until now a plugin that needed one resolved its own: its own environment variable, its own default
under the runtime user's home, inside the container's writable layer. The data vanished whenever the
container was recreated, nothing in core knew the directory existed, and every plugin answered "where
do I put my stuff" a different way. Issue# 456 - tap recorded this as a pattern to standardise once it
had appeared twice. It has now appeared more than twice.

This specification gives every plugin one answer. Core owns one mounted root. A plugin declares in its
manifest that it needs a directory and says what kind of data it holds. Core creates
`<root>/<slug>/`, hands the plugin the path, and reports what is there. Inside its directory the plugin
uses ordinary file calls and structures things however it likes.

Two boundaries keep this small:

- **This is sub-grid.** A plugin data directory has no node on the grid and no file inside it is
  represented on the grid (ruled 2026-11-16). Core can see the directory's outline (it exists, who
  owns it, how big it is); it does not see individual writes. Files that should be catalogued,
  versioned, downloadable and logged belong in the on-grid file store, which is a separate
  specification and a separate mounted volume.
- **The trust boundary is the instance, not the plugin.** Plugins are trusted code. Nothing here
  sandboxes a plugin or prevents one plugin from touching another's directory. The guards in this
  specification exist to stop accidents (data silently written to a disk that is thrown away, a
  directory deleted by mistake, a cache copied into every backup), not to contain hostile code.

### Prior Art

Surveyed 2026-11-16 by a research agent; each line says whether the source was read in that survey or
recalled. Inspiration only: no code was taken.

| Project | Mechanism | What this specification takes | What does not fit |
| --- | --- | --- | --- |
| systemd (`systemd.exec`, read) | A unit declares `StateDirectory=` / `CacheDirectory=`; the manager creates the directory, fixes ownership only when the top level mismatches, and passes the path in an environment variable. State and cache are never removed on stop; removal is the explicit `systemctl clean`. Directory quotas arrived in v258 and are silently "not set" where the filesystem lacks project quotas. | Declare the kind up front; the host creates the directory and hands over the path; purge is a separate explicit verb; a size limit is reported as enforced only where the host really enforces it. | Per-unit users and the `private/` indirection; TAP runs every plugin as one runtime user. |
| XDG Base Directory specification (read) | Separate roots for data, state and cache; directories created `0700`; applications must cope when a write fails. | The cache versus state vocabulary and the `0700` default. | Per-user home layout. |
| Cache Directory Tagging Specification (read) | A file named `CACHEDIR.TAG` whose first 43 octets are `Signature: 8a477f597d28d172789f06886806bc55` marks a directory backup tools should skip; `tar --exclude-caches` honours it. | Core writes the tag into every directory declared a cache. | Nothing. |
| Android app-specific storage (read) | An app gets a private files directory and a private cache directory; the cache quota is advisory and over-quota caches are the first cleared when space runs low. | A declared size on a cache is a budget, not a write barrier. | Automatic eviction by the host; this specification never deletes automatically. |
| Snap and Flatpak (read; Flatpak's uninstall flag recalled) | Per-app data directories handed to the app by the host; removing the app keeps or snapshots its data, and deletion is an explicit flag. | Uninstall never deletes data. | Snap's per-revision copies, which are unworkable for gigabyte directories. |
| VS Code extension API (read; orphan complaint recalled) | The host hands an extension its storage location through the extension context and deprecated the string-path variants extensions rebuilt by hand. Storage left behind after uninstall has no purge verb. | One accessor is the only way to learn the path; an orphan list and a purge verb exist from the first release. | Nothing. |
| Kubernetes (read) | A volume not treated as ephemeral storage is not measured by the platform: "You need to monitor the disk usage by yourself." The default measurement is a periodic directory walk. | Core measures by a bounded walk and publishes the figure with the time it was taken. | Eviction as the response to an over-size tenant. |
| SQLite documentation (read) | Write-ahead mode "does not work over a network filesystem"; network file locks are unreliable; a plain copy of a live database can mix old and new content. | The root must be a local filesystem; the report names the filesystem type. | Nothing. |

Two regrets recur across these systems and shape the requirements below: no split between cache and
state from the first release (XDG and iOS both added it later), and data silently landing on storage
that is thrown away because the intended volume was not mounted.

## Goals

|    |                |                                                                                          |
| :---: | ---         | ---                                                                                      |
| 1. | One Answer      | Every plugin that needs disk gets it the same way: declare it, ask core for the path     |
| 2. | Never Silent    | Data never lands on throw-away storage unnoticed, and nothing is deleted automatically   |
| 3. | Declared Kind   | A directory says whether it is a re-fetchable cache or state that must be kept           |
| 4. | Visible Outline | An operator can see which plugins hold disk, where, how much, and what is in it          |
| 5. | Small           | Core provides a directory and facts about it; it does not mediate the plugin's file I/O  |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-plugin-datadir-scope | [Scope](#scope) | Proposed | A sub-grid working directory per plugin; not the file store; no grid node |
| req-tap-plugin-datadir-root | [The Root](#the-root) | Proposed | One core setting, one mounted local volume, resolved in one place |
| req-tap-plugin-datadir-manifest | [Manifest Declaration](#manifest-declaration) | Proposed | A `[data_directory]` table: purpose, durability, declared maximum size |
| req-tap-plugin-datadir-provision | [Provisioning](#provisioning) | Proposed | Core creates `<root>/<slug>/`, private to the runtime user, with a core-written description file |
| req-tap-plugin-datadir-mount-gate | [Mount Gate](#mount-gate) | Proposed | Boot refuses when a plugin declares a directory and the root is not a mounted, writable volume |
| req-tap-plugin-datadir-accessor | [The Accessor](#the-accessor) | Proposed | One function returns a plugin's directory; an undeclared plugin is refused |
| req-tap-plugin-datadir-sharing | [Sharing Between Plugins](#sharing-between-plugins) | Proposed | Use the owning plugin's interface; not enforced |
| req-tap-plugin-datadir-lifecycle | [Lifecycle And Purge](#lifecycle-and-purge) | Proposed | Nothing is deleted automatically; orphans are listed; purge is an explicit command |
| req-tap-plugin-datadir-report | [Reported Facts](#reported-facts) | Proposed | The plugin report carries each directory's facts and a bounded listing of its contents |
| req-tap-plugin-datadir-health | [Health Probe](#health-probe) | Proposed | A probe reports the root and each declared directory as usable or not |
| req-tap-plugin-datadir-backup-facts | [Facts A Backup Will Need](#facts-a-backup-will-need) | Proposed | Durability is recorded and caches are tagged now; building the backup is not in this specification |
| req-tap-plugin-datadir-size-use | [Using The Declared Size](#using-the-declared-size) | Backlog | What the declared maximum is compared against and what happens when it is exceeded |
| req-tap-plugin-datadir-free-floor | [Free-Space Floor](#free-space-floor) | Backlog | One floor on free space for the whole volume, checked before large writes |
| req-tap-plugin-datadir-helpers | [Shared Helpers](#shared-helpers) | Backlog | Staged swap, single-writer lock and dataset age as core helpers |
| req-tap-plugin-datadir-nongoals | [v0 Non-Goals](#v0-non-goals) | Proposed | What this specification deliberately does not do |

### Scope
----
RID: `req-tap-plugin-datadir-scope`

Status: `Proposed`

A plugin data directory is a directory under a core-owned root, named by the plugin's slug, that the
plugin reads and writes with ordinary file calls. It is for working data whose shape only the plugin
understands: databases written in place, version-control clones, downloaded tools, caches of fetched
datasets, scratch trees.

It is **not** the file store. A file that a user should be able to find on the grid, download,
and see the history of is stored through the file store and has a node. A plugin may use both: a
directory for its working data and the file store for the documents it wants seen.

No node represents a plugin data directory, and no node represents anything inside one (ruled
2026-11-16: "this is sub-grid information"). The facts core reports about a directory
(`req-tap-plugin-datadir-report`) come from the manifest and the filesystem, not from the grid.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-datadir-scope-1 | No Grid Type | Proposed | No TAP-managed node or edge type represents a plugin data directory or its contents; provisioning, reporting and purging create no grid write. | |
| req-tap-plugin-datadir-scope-2 | Separate From The File Store | Proposed | The plugin data root and the file store root are different settings resolving to different directories; core refuses to start the mount gate's check as passed when the two resolve to the same path or one contains the other. | Two volumes, ruled 2026-11-16. |

### The Root
----
RID: `req-tap-plugin-datadir-root`

Status: `Proposed`

All plugin data directories live under one root, named by one core setting.

- **Setting.** `settings.TAP_PLUGIN_DATA_ROOT`, projected from the environment variable
  `TAP_PLUGIN_DATA_ROOT` in `tap/settings.py` in the house style, with the container path
  `/var/lib/tap/plugin-data` as its default. Every consumer reads the setting; none reads the
  environment variable or restates the default. This follows the rule the secrets root arrived at
  after five independent resolutions were found (`req-tap-cares-secrets-root-resolution`).
- **No settings-free lookup yet.** The secrets root has a second, settings-free lookup because
  pre-boot and host tools need it before Django exists. Nothing settings-free needs the plugin data
  root today, so there is one lookup. If a settings-free caller appears it gets a stdlib-only leaf
  beside `tap/secrets_root.py`, tagged as a known duplicate, and not an inline read.
- **Volume.** The compose files mount a named volume at the root in the `web` service. A named volume
  belongs to one compose project, so each development session has its own plugin data and tearing a
  session down destroys it. Sharing one plugin data volume across sessions is not supported: it would
  put several writers on directories whose locks and staged swaps assume one.
- **Image.** The image creates the root directory owned by the runtime user in the same way it
  prepares the other runtime-owned paths, so a new empty named volume starts with usable ownership.
- **Local filesystem.** The root must be a local filesystem. A host directory shared into a container
  through a network or virtualised file-sharing layer is not supported, because SQLite's write-ahead
  mode and POSIX file locks are not reliable there. The report names the filesystem type so an
  operator can see what they have (`req-tap-plugin-datadir-report`).
- **One process family.** Only code running in a container that mounts the volume can reach a plugin
  directory. Today that is the `web` service, which also runs the scheduler. A future worker service
  that runs plugin code must mount the same volume.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-datadir-root-1 | One Setting | Proposed | `TAP_PLUGIN_DATA_ROOT` is read from the environment in `tap/settings.py` only, and the default container path appears in Python only there. | Guard-pinned, as the secrets root is. |
| req-tap-plugin-datadir-root-2 | Compose Mounts A Named Volume | Proposed | Every compose file that defines the `web` service mounts a named volume at the root's container path and sets the environment variable to that path. | Includes the CI and Codespaces overlays. |
| req-tap-plugin-datadir-root-3 | Image Prepares Ownership | Proposed | In the built image the root path exists and is owned and writable by the runtime user. | So an empty named volume inherits usable ownership. |
| req-tap-plugin-datadir-root-4 | Core Never Creates The Root | Proposed | No core code creates the root directory itself; a missing root is reported by the mount gate, never repaired. | Creating it would hide an unmounted volume. |

### Manifest Declaration
----
RID: `req-tap-plugin-datadir-manifest`

Status: `Proposed`

A plugin that needs a directory declares it in `tap-plugin.toml` with one optional table:

```toml
[data_directory]
purpose = "Local copies of public datasets, refreshed hourly."
durability = "cache"
max_bytes = 2147483648
```

| Key | Required | Meaning |
| --- | :---: | --- |
| `purpose` | Yes | One sentence saying what the plugin keeps there. Shown to operators. Non-empty, at most 255 characters, no control characters. |
| `durability` | Yes | `"cache"`: everything in the directory can be fetched or rebuilt, and losing it costs time only. `"state"`: something in the directory cannot be rebuilt and must survive. A directory holding both is `"state"`. |
| `max_bytes` | Yes | The largest size the author expects the directory to reach, in bytes, as a positive integer. A declared convention in this release: core records and reports it and does nothing else with it (`req-tap-plugin-datadir-size-use`). |

The table is absent for a plugin that needs no directory, and such a plugin gets none.

`data_directory` joins the manifest's allowed top-level keys, and unknown keys inside the table are
rejected, consistent with `req-tap-plugin-manifest-v0-validation`. Because unknown top-level keys are
rejected, a plugin that declares the table cannot load on a core that predates it; such a plugin
raises its `requires_tap` floor to the first core release that carries this specification.

One directory per plugin. A plugin that wants to separate cache from state inside its directory does
so with its own subdirectories and declares `"state"`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-datadir-manifest-1 | Optional Table | Proposed | A manifest with no `[data_directory]` table parses, and the parsed manifest records that no directory is declared. | |
| req-tap-plugin-datadir-manifest-2 | Required Keys | Proposed | A table missing `purpose`, `durability` or `max_bytes` fails the manifest load with an error naming the missing key. | |
| req-tap-plugin-datadir-manifest-3 | Durability Is One Of Two | Proposed | Any `durability` other than `"cache"` or `"state"` fails the load. | |
| req-tap-plugin-datadir-manifest-4 | Size Is A Positive Integer | Proposed | A `max_bytes` that is zero, negative, a float, a string or a boolean fails the load. | TOML booleans are not integers. |
| req-tap-plugin-datadir-manifest-5 | Unknown Keys Rejected | Proposed | An unrecognised key inside the table fails the load and the error names it. | |
| req-tap-plugin-datadir-manifest-6 | Validator Reports It | Proposed | `validate_plugin` reports the declared directory (durability, purpose, declared size) in its output, and reports a plugin whose code calls the accessor without declaring the table. | The second half is a static check and may be best-effort; say so in the report. |

### Provisioning
----
RID: `req-tap-plugin-datadir-provision`

Status: `Proposed`

Core, not the plugin, creates a declared directory.

- **Where.** `<root>/<slug>/`. A slug matches `[a-z0-9_]+` (`tap.plugin_identity.SLUG_ALPHABET_PATTERN`),
  so it contains no path separator, no dot and no upper case, and is safe as a single directory name
  on a case-insensitive filesystem. Core validates the slug with `valid_slug` before joining it to
  the root and does not rely on the manifest loader having done so.
- **When.** During boot, after the mount gate passes, for every installed plugin that declares a
  directory. Provisioning is idempotent: an existing directory with the right owner is left exactly
  as it is.
- **Mode.** Created `0700` and then explicitly set to `0700`, because the process umask applies to
  creation.
- **What core refuses.** If `<root>/<slug>` exists and is a symbolic link, or is not a directory, or
  is not owned by the runtime user, provisioning fails for that plugin with an error naming the path
  and the fact found. Core does not follow the link, replace the file or change ownership.
- **Description file.** Core writes `.tap-plugin-dir.json` in the directory: the slug, the declared
  durability and purpose, the declared maximum size, the plugin version that first caused the
  directory to be created, the creation time, and a format version. It is rewritten when the
  declaration changes and is otherwise left alone. It ships with a JSON Schema and is validated
  against it when read. Its purpose is that a directory found on a volume, with no instance running,
  says what it is.
- **Cache tag.** For a directory declared `"cache"`, core writes a `CACHEDIR.TAG` file with the
  standard signature line, and rewrites it if it is missing. For a directory declared `"state"`, core
  removes a `CACHEDIR.TAG` it finds at the top level, so a directory that changed from cache to state
  is not silently skipped by backup tools.
- **Reserved names.** Inside a plugin directory, names beginning `.tap-` and the name `CACHEDIR.TAG`
  belong to core. A plugin does not create, modify or delete them.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-datadir-provision-1 | Created Private | Proposed | After boot, each declared directory exists, is a real directory, is owned by the runtime user and has mode `0700`. | |
| req-tap-plugin-datadir-provision-2 | Idempotent | Proposed | A second boot changes no byte and no timestamp inside an existing, correctly owned directory other than core's own files when the declaration changed. | |
| req-tap-plugin-datadir-provision-3 | Symlink Refused | Proposed | When `<root>/<slug>` is a symbolic link, provisioning fails, names the path, and creates or changes nothing at the link's target. | |
| req-tap-plugin-datadir-provision-4 | Wrong Owner Refused | Proposed | When the directory exists under a different owner, provisioning fails and performs no `chown`. | |
| req-tap-plugin-datadir-provision-5 | Description File Valid | Proposed | Every provisioned directory holds a `.tap-plugin-dir.json` that validates against its published schema and agrees with the manifest. | |
| req-tap-plugin-datadir-provision-6 | Cache Tag Follows Durability | Proposed | A `"cache"` directory holds a `CACHEDIR.TAG` whose first 43 octets are the standard signature; a `"state"` directory holds none at its top level after boot. | |
| req-tap-plugin-datadir-provision-7 | Undeclared Gets Nothing | Proposed | No directory is created for an installed plugin that declares no table. | |

### Mount Gate
----
RID: `req-tap-plugin-datadir-mount-gate`

Status: `Proposed`

The failure this gate exists to prevent: the volume is not mounted, the path exists anyway inside the
container's writable layer, the plugin writes there happily, and everything is lost when the
container is recreated. Docker does nothing to signal this case.

**Rule (ruled 2026-11-16).** When at least one installed plugin declares a data directory, boot
refuses to proceed unless the root is a mounted, writable volume. The refusal is a standup abort
(`req-boot-abort-signal`) in the `boot` domain, with a reason naming the root and the check that
failed. There is no fallback to another location.

An instance in which no installed plugin declares a directory boots without the volume. This
condition is the specification author's reading of the ruling and is listed under Open Decisions.

**What "mounted and writable" means.** One function decides it, and boot, the health probe and the
report all call that function:

1. The root path exists and is a directory, not a symbolic link.
2. The root is on a different device from the container's root filesystem: `st_dev` of the root
   differs from `st_dev` of `/`. A directory that merely exists inside the image fails this.
3. A real write succeeds: create a file under a core-reserved name in the root, write, `fsync`,
   rename, remove. A permission check alone is not accepted as evidence.

`os.path.ismount` is not used as the test. Python documents that it cannot reliably detect a bind
mount on the same filesystem, and the device comparison in step 2 answers the question that matters
here, which is whether the data would land in the container's own disk.

**Why boot and not process start.** Refusing at `django.setup()` would crash-loop the instance and
take away `manage.py`, the health command and a shell, which are the tools an operator needs to
diagnose the problem. That is the lesson recorded for secrets loading
(`req-tap-cares-secrets-resilient-load`). So the gate is a boot step, and the accessor independently
refuses at the moment a plugin asks (`req-tap-plugin-datadir-accessor`), which covers a process that
was started without running boot.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-datadir-mount-gate-1 | Missing Root Aborts | Proposed | With a declaring plugin installed and the root path absent, boot exits non-zero after emitting one `ABORT` record whose reason names the root. | |
| req-tap-plugin-datadir-mount-gate-2 | Unmounted Root Aborts | Proposed | With a declaring plugin installed and the root present on the same device as `/`, boot aborts the same way and the reason says the root is not a mounted volume. | The case the gate exists for. |
| req-tap-plugin-datadir-mount-gate-3 | Unwritable Root Aborts | Proposed | With the root mounted but the write probe failing, boot aborts and the reason carries the operating-system error. | |
| req-tap-plugin-datadir-mount-gate-4 | No Declaring Plugin, No Gate | Proposed | With no installed plugin declaring a directory, boot succeeds whether or not the root exists. | Open Decision 1. |
| req-tap-plugin-datadir-mount-gate-5 | One Decision Function | Proposed | Boot, the health probe and the report obtain the verdict from the same function; no second implementation of the mount test exists. | |
| req-tap-plugin-datadir-mount-gate-6 | No Fallback Path | Proposed | No code path provisions or returns a plugin directory outside the configured root. | |

### The Accessor
----
RID: `req-tap-plugin-datadir-accessor`

Status: `Proposed`

A plugin learns its directory by calling one function, `tap_plugins.data_dir(slug)`, which returns a
`pathlib.Path`.

- It returns the canonical real path of `<root>/<slug>`. Handing out one canonical spelling matters
  for SQLite, which treats two different path names to one database as two databases.
- It raises `PluginDataDirectoryError` when the slug is not a valid slug, when no installed plugin
  with that slug declares a directory, when the mount test fails, or when the directory has not been
  provisioned. The message says which.
- It does not create anything. Provisioning is boot's job, so that a missing directory is noticed.
- It is cheap: the mount verdict is computed once per process and reused, and the write probe is
  not repeated on every call.

**Plugins ask; they do not derive.** A plugin does not read `TAP_PLUGIN_DATA_ROOT`, does not build
the path from the setting, and does not keep its own environment variable for the location. This is
stated as the practice every plugin follows. It is not enforced by a guard in this release.

For tests, the root is an ordinary setting and is overridden with a temporary directory in the usual
way; the device comparison in the mount test is the one seam a test replaces.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-datadir-accessor-1 | Returns The Canonical Path | Proposed | For a declaring, provisioned plugin the accessor returns the real path of `<root>/<slug>`, and two calls return equal values. | |
| req-tap-plugin-datadir-accessor-2 | Undeclared Refused | Proposed | For an installed plugin with no table, and for a slug that is not installed, the accessor raises and creates nothing. | |
| req-tap-plugin-datadir-accessor-3 | Invalid Slug Refused | Proposed | A slug containing a path separator, a dot, upper case or an empty string raises before any filesystem call. | |
| req-tap-plugin-datadir-accessor-4 | Unusable Root Refused | Proposed | When the mount test fails, the accessor raises with the same reason the mount gate would give, and returns no path. | Covers a process started without boot. |
| req-tap-plugin-datadir-accessor-5 | Never Creates | Proposed | The accessor performs no `mkdir`; an unprovisioned directory is an error. | |

### Sharing Between Plugins
----
RID: `req-tap-plugin-datadir-sharing`

Status: `Proposed`

Every plugin's directory sits under the same root, so one plugin can reach another's files. That is
accepted (ruled 2026-11-16): the trust boundary is the instance, not the plugin, and no guard in this
release prevents a read or a write across plugin directories.

The practice plugins follow is the one TAP already requires of plugin-to-plugin reuse
(`req-tap-test-hermetic-plugins`): a plugin that wants another plugin's data calls an interface that
plugin publishes, such as a read function, and does not open its files. The owning plugin is the only
writer of its directory. Every lock and staged swap a plugin builds assumes that.

This requirement is doctrine. It is here so that a later decision to enforce it has a named place to
land, and so that a reviewer who sees one plugin opening another's files knows it is against stated
practice and not merely unusual.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-datadir-sharing-1 | Practice Is Stated To Authors | Proposed | The plugin-authoring guidance that covers data directories states both halves: go through the owner's interface, and only the owner writes. | Carried by the plugin-building skills when this is built. |

### Lifecycle And Purge
----
RID: `req-tap-plugin-datadir-lifecycle`

Status: `Proposed`

Nothing in a plugin data directory is ever deleted by core on its own initiative. Not on boot, not on
plugin removal, not when a directory is over its declared size, and not for a cache.

- **Orphans.** A directory under the root is an orphan when no installed plugin with that slug
  declares a directory. This covers a removed plugin, a plugin whose slug changed (a new slug is a
  new directory; the old one stays), and a plugin that dropped its declaration. Orphans are listed
  in the report and by a management command. They are not touched.
- **Strays.** Anything directly under the root that is not a directory named by a valid slug, and
  not a core-reserved name, is reported as a stray and not touched.
- **Purge.** `manage.py plugin_data purge <slug>` deletes one plugin's directory. It is the only
  deletion path core provides. It:
  - prints what it will delete (path, durability, measured size, entry count) and requires a
    confirming flag; a `"state"` directory, and any orphan whose description file is missing or says
    `"state"`, requires a second, differently named flag;
  - refuses when `<root>/<slug>` is a symbolic link, and never follows a symbolic link while walking;
  - stays on the root's device and inside the real path of the root;
  - is recorded in the log with who ran it, the slug, and what was removed.
- **Listing.** `manage.py plugin_data list` prints every directory under the root with its owner
  status (declared, orphan, stray) and the same facts the report carries.

A plugin clears its own cache whenever it likes; that is the plugin's business inside its own
directory and is not a core operation.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-datadir-lifecycle-1 | No Automatic Deletion | Proposed | No boot step, load step, health probe or report deletes or truncates anything under the root except core's own reserved files in a declared directory. | |
| req-tap-plugin-datadir-lifecycle-2 | Removed Plugin Leaves Its Directory | Proposed | After a plugin is removed from the install set and the instance rebooted, its directory and contents are byte-identical and it is listed as an orphan. | |
| req-tap-plugin-datadir-lifecycle-3 | Purge Needs Confirmation | Proposed | `purge` without the confirming flag deletes nothing and exits non-zero; purging a `"state"` directory with only the first flag deletes nothing. | |
| req-tap-plugin-datadir-lifecycle-4 | Purge Stays Inside | Proposed | With a symbolic link inside the directory pointing at a file outside the root, purge removes the link and leaves the outside file untouched; with `<root>/<slug>` itself a link, purge refuses. | |
| req-tap-plugin-datadir-lifecycle-5 | Purge Is Logged | Proposed | A completed purge writes one log record naming the actor, the slug, the durability and the byte and entry counts removed. | |

### Reported Facts
----
RID: `req-tap-plugin-datadir-report`

Status: `Proposed`

The plugin report (`tap_plugins.report.build_report`, the one source for "what plugins is this
instance running") carries the data-directory facts, so the command-line surface and the human plugin
status surface show the same thing without either walking the filesystem itself.

Per plugin:

- whether a directory is declared, and the declaration (purpose, durability, declared maximum size);
- the path, whether it exists, and whether its owner and mode are as provisioned;
- measured size in allocated bytes, entry count, the time the measurement was taken and how long it
  took, or the reason no measurement is available;
- a bounded listing of the directory's top level: for each entry its name, kind (file, directory,
  link, other), size and modification time, capped at a fixed number of entries with a flag saying
  the listing was cut.

Once, for the root: the configured path, the mount verdict with its reason, the filesystem type, free
bytes and free inodes on the volume, and the lists of orphans and strays.

**Measuring.** Size is measured by walking the directory without following symbolic links and
without leaving the root's device, summing allocated blocks (so a sparse file counts what it
occupies) and counting a hard-linked file once. A walk over a directory with hundreds of thousands
of entries is not instant, so the walk has a time budget; a walk that runs out reports what it
counted and says the figure is partial. The figure is always published with the time it was taken.
The report never blocks a page on an unbounded walk.

The published report schema gains these fields and its schema version is raised in the same change.
The human surface that shows them is owned by the plugin that owns the plugin status page and is
changed there; this specification defines the facts, not the page.

Reading the report requires the capability it already requires. No new capability is introduced.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-datadir-report-1 | Declaration In The Report | Proposed | For a declaring plugin the report carries its purpose, durability and declared maximum size exactly as the manifest states them; for a non-declaring plugin it says no directory is declared. | |
| req-tap-plugin-datadir-report-2 | Measured With A Timestamp | Proposed | Every measured size in the report is accompanied by the time it was measured and whether the walk completed. | |
| req-tap-plugin-datadir-report-3 | Links Not Followed | Proposed | A symbolic link inside a plugin directory pointing at a large file outside it adds the link's own size, not the target's, to the measurement. | |
| req-tap-plugin-datadir-report-4 | Bounded Listing | Proposed | A directory with more top-level entries than the cap yields exactly the cap and a flag saying the listing was cut. | |
| req-tap-plugin-datadir-report-5 | Orphans And Strays Listed | Proposed | A directory under the root with no declaring plugin appears as an orphan, and a top-level file under the root appears as a stray. | |
| req-tap-plugin-datadir-report-6 | Schema Carries It | Proposed | A report containing these fields validates against the published plugin report schema, and the schema version is higher than before this change. | |
| req-tap-plugin-datadir-report-7 | Budget Respected | Proposed | A walk given a budget it cannot meet returns within a small multiple of that budget with a partial figure marked as partial. | |

### Health Probe
----
RID: `req-tap-plugin-datadir-health`

Status: `Proposed`

`tap_plugins` registers one health probe for plugin data, alongside its existing probe.

- With no declaring plugin installed it reports healthy and says there is nothing to check.
- With a declaring plugin installed it reports unhealthy when the mount test fails, naming the
  reason, and unhealthy when any declared directory is missing, is a symbolic link, has the wrong
  owner, or fails a write probe, naming each directory and the fact found.
- Orphans and strays do not make the probe unhealthy. They are reported in the probe's context so an
  operator sees them.
- A directory larger than its declared maximum does not change the verdict in this release
  (`req-tap-plugin-datadir-size-use`).

The probe touches the filesystem and not the database, so it tells the truth when the database is
unreachable. It does not walk directories to measure them.

Adding the probe and the boot gate adds validation surfaces, so the implementing change adds their
rows to the Validation Map (`req-dev-validation-map`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-datadir-health-1 | Healthy When Unused | Proposed | With no declaring plugin the probe is healthy whether or not the root exists. | |
| req-tap-plugin-datadir-health-2 | Unmounted Is Unhealthy | Proposed | With a declaring plugin and a failing mount test the probe is unhealthy and its detail carries the mount test's reason. | |
| req-tap-plugin-datadir-health-3 | Each Bad Directory Named | Proposed | A missing, linked, wrongly owned or unwritable declared directory makes the probe unhealthy and appears by slug in its context. | |
| req-tap-plugin-datadir-health-4 | Orphans Do Not Fail It | Proposed | An orphan directory leaves the verdict healthy and appears in the context. | |

### Facts A Backup Will Need
----
RID: `req-tap-plugin-datadir-backup-facts`

Status: `Proposed`

Building backup and restore for plugin data is not part of this specification (ruled 2026-11-16:
"we're not building backups just yet, right now we're just including the data we'll need"). What this
specification does is make sure the facts a backup will need exist from the first release, because
adding them later is the regret other systems report:

- every directory's durability is declared, recorded in its description file and in the report;
- every cache directory carries the standard cache tag, which existing archive tools already honour;
- the report names the root, so a backup can find every directory without knowing any plugin.

Two things a future backup has to settle, written down so they are not rediscovered:

- A `"state"` directory may hold a live SQLite database, and a plain file copy of one being written
  can mix old and new content. A backup must either take the directory while its plugin is idle or
  ask the plugin for a consistent copy.
- `specs/spec-tap-backup.md` requires every component to appear in the backup manifest and defaults
  new components to included. Plugin data will need its own component there, with cache directories
  recorded as deliberately omitted.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-datadir-backup-facts-1 | Durability Is Recoverable From Disk | Proposed | With no instance running, the durability of every provisioned directory can be read from its description file alone. | |

### Using The Declared Size
----
RID: `req-tap-plugin-datadir-size-use`

Status: `Backlog`

`max_bytes` is declared now and used later (ruled 2026-11-16). When it is taken up, the questions to
settle are these.

- **What it is compared against.** The measured, allocated size from the report's walk, which is
  always slightly out of date.
- **What happens when it is exceeded.** The surveyed systems never refuse the write. They warn, mark
  the tenant unhealthy, or clear caches. Core cannot refuse the write in any case: plugins write with
  ordinary file calls and the web container runs unprivileged, so every kernel mechanism that could
  enforce a per-directory limit (a project quota on XFS or ext4, a separate sized volume) needs root
  or a mount option chosen on the host.
- **Hard enforcement as an operator choice.** systemd's model is the one to follow: where the host
  filesystem supports project quotas the declared size becomes a real limit, and where it does not
  the limit is reported as not enforced. Core must report which is true and never claim enforcement
  it does not have.

### Free-Space Floor
----
RID: `req-tap-plugin-datadir-free-floor`

Status: `Backlog`

In every system surveyed, what actually prevents a full disk is one floor on free space for the whole
volume, not a cap per tenant. The idea, parked 2026-11-16: core keeps a configured floor for the
plugin data volume and offers plugins a check for "is there room for N bytes" before a large
download. It is a hint, because another writer can take the space a moment later, so a plugin must
still handle a full disk cleanly and must treat "disk full" and "quota exceeded" the same way.

### Shared Helpers
----
RID: `req-tap-plugin-datadir-helpers`

Status: `Backlog`

Plugins that hold datasets tend to write the same three things: publish a new copy by staging it
beside the live one and switching atomically, hold a single-writer lock for the duration of a
refresh, and record how old a dataset is. Core could offer these once. Deferred until this
specification is built and a second plugin needs them; at that point the helpers are lifted from a
working plugin, not designed in the abstract.

### v0 Non-Goals
----
RID: `req-tap-plugin-datadir-nongoals`

Status: `Proposed`

- **No grid representation.** No node or edge for a directory or its contents.
- **No mediation of file I/O.** Core does not see, log or limit individual reads and writes inside a
  plugin directory.
- **No isolation between plugins.** No per-plugin user, no permission barrier, no guard.
- **No automatic cleanup.** No eviction, no expiry, no deletion of orphans.
- **No size enforcement and no free-space floor.** Both are Backlog requirements above.
- **No remote storage.** The root is a local filesystem. An object store cannot back a directory that
  holds a SQLite database.
- **No backup or restore.** Only the facts one will need.
- **No more than one directory per plugin.**
- **No sharing of one plugin data volume between development sessions.**

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-datadir-nongoals-1 | Non-Goals Are Listed | Proposed | This section names each deliberate omission, and each omission that has a planned home names the Backlog requirement that holds it. | |

## Open Decisions

Decisions this draft makes that the maintainer has not ruled on. Each is small and each is reversible
before the specification is approved.

| # | Decision | What the draft says | Why it is open |
| :---: | --- | --- | --- |
| 1 | When the mount gate applies | Only when at least one installed plugin declares a directory | The ruling was "hard fail on boot if plugin dir is not mounted / mountable"; the condition is the author's reading. The alternative is to require the volume always. |
| 2 | Whether a plugin declares that it runs files from its directory | Not in this draft | A plugin that downloads and runs a binary will fail at run time on a host that mounts data volumes so nothing on them can execute. A declared `executes = true` and a boot-time test would turn that into a clear boot failure. Raised 2026-11-16, not ruled. |
| 3 | The default container path | `/var/lib/tap/plugin-data` | No existing convention for TAP-owned read-write state under `/var/lib`; the secrets root is under `/run`. |
| 4 | Names: the setting, the manifest table, the accessor, the command | `TAP_PLUGIN_DATA_ROOT`, `[data_directory]`, `tap_plugins.data_dir`, `manage.py plugin_data` | Proposed for consistency with existing names; none is ruled. |
| 5 | Whether `max_bytes` is required | Required | The ruling was to declare the maximum now as a convention. Required makes every declaring plugin state one; optional would let authors skip it. |

## What This Settles Elsewhere

- **Issue# 456 - tap** asked for one declaration surface and one wiring convention for TAP-managed
  storage roots. This specification settles it for the read-write, TAP-owned, plugin-facing case. The
  file store settles it for its own root in its own specification.
- A plugin whose own specification asks core for a platform data directory, or that currently
  resolves a private home directory, moves to the accessor in its own change, in its own repository.
  Its layout inside the directory does not change.

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
