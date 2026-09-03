# TAP JSON File Convention

## Philosophy

TAP carries a growing population of on-disk JSON files: boot profiles, runtime secrets, GRIFT seed documents, edge definitions, Gridkin scenarios, JSON Schemas, role/capability registries, and collector manifests. Two problems compound as that population grows.

**Filenames don't say what a file is.** A bare `base.json` or `roles.json` tells you nothing about its purpose, its owner, or its trust class until you open it or grep for the loader. The same name (`roles.json`) could be config, fixture, or output. The operator, the reviewer, and the AI reading the tree all pay the same tax: open-the-file-to-learn-what-it-is.

**Every loader re-implements the same load-and-validate dance.** Read the file → catch `OSError`/`JSONDecodeError` → load the schema (sometimes `@lru_cache`) → `jsonschema.validate` → reformat `exc.absolute_path` into a JSON-pointer location → raise a bespoke exception. That block is copy-pasted, with subtle per-callsite drift, across `tap_boot/profile.py`, `tap_auth/roles.py`, `tap_auth/capabilities.py`, `tap_auth/boot.py`, `plugins/gryphon_playground/gridkin/loader.py`, and a dozen collector manifests. Five different exception types, five slightly different message formats, five places a bug can hide.

This spec defines two coupled conventions, mirroring the shape of [`spec-tap-logging.md`](spec-tap-logging.md) — a *convention* + a *helper module* + a *baseline-ratchet scanner test*:

1. **A typed filename convention.** Every TAP-owned JSON file's purpose is legible from its name. Discovered data/config files carry a role suffix (`<name>.<role>.json`); singleton app-owned config carries an app prefix (`<app>.<name>.json`); schemas carry a `.schema.json` suffix whose stem names what they validate.

2. **One shared load-and-validate helper.** `tap/jsonfiles.py` owns the read → parse → schema-validate → error-location mechanics exactly once. Callers pass the schema explicitly and translate the single `JsonFileError` into their own domain exception. The JSON-pointer location formatter lives in one place, not seven.

Most of the convention already holds: `*.secret.json`, `*.grift.json`, `*.edge.json`, `*.gridkin.json`, and `*.schema.json` are established. This spec makes the convention explicit, closes the gaps (boot profiles, the `tap_auth` registries), routes every loader through one helper, and adds a scanner so the convention can't silently erode.

This is a security-posture edge in the sense of [`spec-security-posture.md`](spec-security-posture.md): a single audited load path is cheaper to harden (size limits, schema-required, redaction hooks) than seven divergent ones, and a trust-class-legible filename (`*.secret.json` is gitignored and never logged; `*.boot.json` is operator config, not untrusted input) is a near-zero-marginal-cost edge laid while the surface is already being rewritten.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Legible Filenames | Every TAP-owned JSON file declares its purpose, owner, and trust class in its name. |
| 2. | One Load Path | A single helper owns read + parse + schema-validate + error formatting; loaders do not re-implement it. |
| 3. | Uniform Errors | One `JsonFileError` with a consistent, machine-readable file + JSON-pointer message; callers translate to domain exceptions without re-deriving the format. |
| 4. | Role-Driven Discovery | Directory scans select files by an explicit `role` parameter (`*.<role>.json`), never a bare `*.json` glob that catches strays. |
| 5. | Non-Erosion | A scanner test enforces the filename convention with a baseline ratchet, so existing debt is recorded and new files must conform. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-json-naming | [Typed Filename Convention](#typed-filename-convention) | Implemented | `<name>.<role>.json` data, `<app>.<name>.json` singletons, `<type>.schema.json` schemas |
| req-tap-json-loader | [Shared Load Helper](#shared-load-helper) | Implemented | `tap/jsonfiles.py::load_json_file` — read + parse + optional validate; one `JsonFileError` |
| req-tap-json-discovery | [Role-Driven Discovery](#role-driven-discovery) | Implemented | `discover_json_files(dir, role=...)` globs `*.<role>.json`, sorted, dotfiles skipped |
| req-tap-json-schema-explicit | [Explicit Per-Caller Schema](#explicit-per-caller-schema) | Implemented | Caller passes the schema (path or dict); no global role→schema registry |
| req-tap-json-adoption | [Loader Adoption](#loader-adoption) | Implemented | Every TAP-owned config/data JSON load+validate routes through the helper; callers wrap |
| req-tap-json-scanner | [Filename Scanner](#filename-scanner) | Implemented | Pytest scanner + baseline ratchet over TAP-owned `.json` files |
| req-tap-json-size-guard | [Load Size Guard](#load-size-guard) | Backlog | Optional `max_bytes` ceiling on the read path; a cheap DoS edge for later |

## Requirements

### Typed Filename Convention
----
RID: `req-tap-json-naming`

Status: `Implemented`

Every TAP-owned JSON file's purpose is legible from its filename. There are exactly three patterns, chosen by how the file is discovered and who owns it.

#### Implementation

**1. Discovered data/config families — `<name>.<role>.json`.** Files found by scanning a directory carry a `role` suffix that is the discovery key. The suffix is load-bearing: the loader globs `*.<role>.json`, so the suffix both names the type and scopes the scan.

| Role | Pattern | Directory | Owner |
| --- | --- | --- | --- |
| `boot` | `<id>.boot.json` | `boot/` | `tap_boot` |
| `secret` | `<key>.secret.json` | `$TAP_SECRETS_ROOT/**` | `tap_cares` |
| `grift` | `<name>.grift.json` | `plugins/<slug>/grift/**` | plugin |
| `edge` | `<slug>.edge.json` | `plugins/<slug>/edges/` | plugin |
| `gridkin` | `<name>.gridkin.json` | `plugins/gryphon_playground/scenarios/` | plugin |

**2. Singleton app-owned config — `<app>.<name>.json`.** A file loaded by an exact hard-coded path (not a scan), owned by one app, carries the app label as a prefix so the tree shows ownership at a glance. The owner is a first-party `tap_*` app, or — for a file living under `plugins/<plugin>/` — the enclosing plugin package. The plugin form keeps the same "owner prefix names the one-of-a-kind file" contract for plugin-owned singletons (e.g. a coverage ledger) without a per-plugin allowlist: the scanner derives the accepted prefix from the file's own `plugins/<plugin>/` path.

| File | Owner |
| --- | --- |
| `tap_auth.roles.json` | `tap_auth` |
| `tap_auth.capabilities.json` | `tap_auth` |
| `plugins/gryphon_playground/scenarios/gryphon_playground.tck-coverage.json` | `gryphon_playground` (plugin) |

**3. Schemas — `<type>.schema.json`.** Every JSON Schema carries the `.schema.json` suffix. Its stem names *what it validates*:

- For a discovered family, the stem **is the role**: `boot.schema.json` validates `*.boot.json`; `secret.schema.json` validates `*.secret.json`. This makes the data↔schema pairing visible and checkable — the schema for role `R` is `R.schema.json`.
- For a singleton, the stem mirrors the data file's name: `roles.schema.json` validates `tap_auth.roles.json`; `capabilities.schema.json` validates `tap_auth.capabilities.json`.

#### Development

The two data patterns answer different questions. A role suffix answers *"what kind of file is this, and how is it found?"* — it must be a suffix because the glob keys on it, and many instances of the same role coexist in one directory. An app prefix answers *"who owns this one-of-a-kind file?"* — there is exactly one `tap_auth.roles.json`, it is never globbed, and the prefix sorts it next to its siblings in a listing and names the owner without opening it.

The schema-stem-is-the-role invariant (`R.schema.json` ↔ `*.R.json`) is the one piece worth defending: it lets the scanner and a human verify, from filenames alone, that a discovered family has exactly one schema and that the schema is named for the thing it constrains. It is why existing `boot-profile.schema.json` is renamed to `boot.schema.json` — the descriptive-but-unpaired name loses the visible link to `*.boot.json`. The other families' schemas (`grift-document.schema.json`, `edge-definition.schema.json`, `gridkin-scenario.schema.json`) keep their descriptive pre-convention names for now; renaming them to their role stem is opportunistic ratchet work like the collector manifests, deferred to the Future pairing tightening rather than churned through the GRIFT/edge/scenario import paths in this change. The v0 scanner enforces suffix membership, not the pairing, so those names pass.

Collector manifests under `plugins/*/collectors/*/` (e.g. `github_collection_manifest.json`) are descriptive singletons loaded by hard path. They predate this convention and are not app-prefixed; they are recorded in the scanner baseline (`req-tap-json-scanner`) rather than renamed in this change — renaming them is opportunistic ratchet work, not a blocker, because their loaders are local and their names are already descriptive.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-json-naming-1 | Role Suffix | Implemented | Discovered data/config files are named `<name>.<role>.json` for a known role. | |
| req-tap-json-naming-2 | App Prefix | Implemented | Hard-path singleton config is named `<app>.<name>.json`, where the owner is a first-party `tap_*` app or, for a file under `plugins/<plugin>/`, the enclosing plugin package. | |
| req-tap-json-naming-3 | Schema Suffix | Implemented | Every JSON Schema is named `<type>.schema.json`. | |
| req-tap-json-naming-4 | Schema Stem Is Role | Implemented | A discovered family's schema stem equals its role: `R.schema.json` ↔ `*.R.json`. | Applied to boot (`boot.schema.json` ↔ `*.boot.json`); grift/edge/gridkin family schemas grandfathered pending the Future pairing check |

### Shared Load Helper
----
RID: `req-tap-json-loader`

Status: `Implemented`

`tap/jsonfiles.py` owns the read → parse → optional-schema-validate → error-location mechanics. A single `JsonFileError` is the one failure type; the JSON-pointer location formatter exists in exactly one place.

#### Implementation

- `tap/jsonfiles.py` exports `load_json_file(path: Path, *, schema: dict | Path | None = None) -> Any`:
  - Reads `path` as UTF-8. An `OSError` raises `JsonFileError` naming the path and the OS reason.
  - Parses with `json.loads`. A `JSONDecodeError` raises `JsonFileError` naming the path, line, and column.
  - If `schema` is given (a loaded schema dict, or a `Path` to a `*.schema.json` file), validates with `jsonschema`. A `ValidationError` raises `JsonFileError` naming the path, the JSON-pointer location (`"/".join(absolute_path) or "<root>"`, computed here and nowhere else), and the validator message.
  - Returns the parsed object on success.
- `JsonFileError(Exception)` carries structured attributes — `path: Path`, `location: str | None`, `reason: str` — so callers can re-wrap with their own message without string-parsing, and `str()` renders the uniform human message.
- `load_schema(path: Path) -> dict` is a thin, `lru_cache`-backed reader for schema files, so callers stop hand-rolling their own cached `_schema()`.
- The helper raises **only** `JsonFileError`; it never raises raw `jsonschema`/`json` exceptions to callers.

#### Development

The helper deliberately does not know about domain exception types. Boot raises `BootProfileError`, the auth registries raise `ImproperlyConfigured`, Gridkin raises `GridkinScenarioError`, secrets raise `SecretLoadError`. Folding those into the helper would couple a core utility to every app's exception taxonomy. Instead the helper raises one `JsonFileError`, and each caller does:

```python
try:
    data = load_json_file(path, schema=SCHEMA)
except JsonFileError as exc:
    raise BootProfileError(f"Boot profile '{profile_id}': {exc}") from exc
```

The structured attributes (`path`, `location`, `reason`) exist precisely so a caller that wants a domain-shaped message can read fields instead of re-parsing the rendered string. This preserves every loader's existing message quality while removing the duplicated mechanics underneath.

`load_json_file` validates *eagerly and raises on the first error* — the dominant pattern. The one caller that collects *all* schema errors for a richer report (`tap_auth/providers/secrets.py`, using `iter_errors`) keeps its multi-error path; the helper's single-error contract is not the right tool there and the spec does not force it through. That is a named, deliberate exception, not drift.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-json-loader-1 | Single Entry Point | Implemented | `load_json_file(path, *, schema=None)` reads, parses, and optionally validates. | |
| req-tap-json-loader-2 | One Error Type | Implemented | The helper raises only `JsonFileError`; never raw `json`/`jsonschema` exceptions. | |
| req-tap-json-loader-3 | Location Formatter | Implemented | The JSON-pointer location is computed inside the helper and nowhere else. | |
| req-tap-json-loader-4 | Structured Attributes | Implemented | `JsonFileError` exposes `path`, `location`, `reason` for caller re-wrapping. | |
| req-tap-json-loader-5 | Cached Schema Reader | Implemented | `load_schema(path)` reads a schema file with `lru_cache`. | |

### Role-Driven Discovery
----
RID: `req-tap-json-discovery`

Status: `Implemented`

Directory scans select files by an explicit `role`, never a bare `*.json` glob.

#### Implementation

- `tap/jsonfiles.py` exports `discover_json_files(directory: Path, *, role: str, recursive: bool = False) -> list[Path]`:
  - Globs `*.{role}.json` (or `rglob` when `recursive=True`) under `directory`.
  - Returns a **sorted** list for deterministic, cross-platform ordering.
  - Skips dotfiles (names starting with `.`) and non-files.
  - Returns `[]` when `directory` is absent or not a directory — a missing optional source is normal, not an error (callers decide whether emptiness is fatal).
- Callers derive the data file's instance id by stripping the `.{role}.json` suffix (the stem-minus-suffix), not `Path.stem` (which only strips the final `.json` and would leave `.{role}`).

#### Development

The bare `boot/*.json` glob in `tap_boot/profile.py` is the motivating bug class: it treats *any* JSON dropped in `boot/` as a profile. Keying discovery on `role="boot"` (`*.boot.json`) makes the scan intentional — a stray `notes.json` or an editor's `.swp`-adjacent file is no longer mis-discovered as a bootable profile. The `role` parameter is the same string that names the file suffix (`req-tap-json-naming`), so discovery and naming share one vocabulary.

The suffix-strip-not-`.stem` detail is a real footgun worth pinning: `Path("base.boot.json").stem` is `"base.boot"`, not `"base"`. Loaders that use the instance id as a profile id / registry key must strip the full `.{role}.json` suffix.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-json-discovery-1 | Role Glob | Implemented | `discover_json_files` globs `*.<role>.json`, not `*.json`. | |
| req-tap-json-discovery-2 | Deterministic Order | Implemented | Results are sorted. | |
| req-tap-json-discovery-3 | Dotfiles Skipped | Implemented | Names beginning with `.` are excluded. | |
| req-tap-json-discovery-4 | Missing Dir Empty | Implemented | A missing/non-directory path returns `[]`, not an error. | |

### Explicit Per-Caller Schema
----
RID: `req-tap-json-schema-explicit`

Status: `Implemented`

Callers pass the schema to validate against. The helper does not maintain a global role→schema registry.

#### Implementation

- Each app keeps owning its schema location (its own `schemas/` directory) and passes the schema to `load_json_file` as a `Path` (or a pre-loaded dict).
- The `<type>.schema.json` naming (`req-tap-json-naming`) is a **convention the human/scanner verifies**, not a lookup the helper performs. There is no magic resolution of role → schema path inside the helper.

#### Development

A global role→schema registry was considered and rejected for v0. Schemas live in per-app `schemas/` directories by deliberate ownership (`tap_auth` owns `tap_auth/schemas/`, plugins own theirs); a central registry would either centralize those paths (breaking ownership) or require a discovery pass at import time (more machinery, a new failure mode). Explicit passing keeps `tap/jsonfiles.py` dependency-free and side-effect-free — it touches the filesystem only when called, never at import. If a future need emerges (e.g. validating arbitrary files by role from a CLI), a registry is an additive layer on top; it is recorded as a possibility, not built.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-json-schema-explicit-1 | Caller Supplies Schema | Implemented | `load_json_file` validates only against the schema the caller passes. | |
| req-tap-json-schema-explicit-2 | No Global Registry | Implemented | The helper performs no role→schema path resolution. | |

### Loader Adoption
----
RID: `req-tap-json-adoption`

Status: `Implemented`

Every TAP-owned load of a config/data JSON file that reads-and/or-validates routes through `tap/jsonfiles.py`. Loaders do not call `json.loads` + `jsonschema.validate` directly for these files.

#### Implementation

The following are migrated to the helper, each catching `JsonFileError` and re-raising its existing domain exception:

| Module | Domain Exception | Notes |
| --- | --- | --- |
| `tap_boot/profile.py` | `BootProfileError` | profile load + `discover_json_files(role="boot")` |
| `tap_auth/roles.py` | `ImproperlyConfigured` | `tap_auth.roles.json` + `roles.schema.json` |
| `tap_auth/capabilities.py` | `ImproperlyConfigured` | `tap_auth.capabilities.json` + `capabilities.schema.json` |
| `tap_auth/boot.py` | `AuthBootError` | auth-section validate; settings-time reader stays tolerant (returns `{}`) |
| `tap_cares/secrets/loader.py` | `SecretLoadError` | parse via helper; structural field checks stay in the loader |
| `tap_cares/collectors/base.py` | (existing) | collection-results schema validate |
| `plugins/gryphon_playground/gridkin/loader.py` | `GridkinScenarioError` | scenario load + `discover_json_files(role="gridkin")` |
| `tap_grid/grift/importer.py` | (existing) | GRIFT document schema load/validate |
| `tap_plugins/manifest.py` | (existing) | `.edge.json` load + edge-definition schema |
| `tap_plugins/validate/service.py` | (existing) | validation-result schema |
| plugin collector manifests | (existing) | aws/github/samsite/fedramp manifest schema validate |

**Exceptions (deliberate, named):**
- `tap_auth/providers/secrets.py` keeps its `iter_errors` multi-error reporting (`req-tap-json-loader` Development). Its file reads + schema load route through the helper; only the all-errors validation stays on `Draft202012Validator`.
- The settings-time auth reader (`read_auth_section`) stays *tolerant* — it must not crash `tap/settings.py` import on a bad file — so it catches `JsonFileError` and returns `{}` with a warning, rather than propagating.
- **In-memory invariant checks against non-file schemas keep `jsonschema.validate`.** `tap_cares/collectors/base.py::_validate_entry` (per-result-entry check against a pinned sub-schema) and `tap_grid/grift/importer.py`'s three CRUD-schema validations validate *already-in-memory* values against *dynamic model schemas*, wired into existing `GriftIssue`/programming-error reporting. They route their **schema-file reads** through `load_schema`, but the in-memory validation is not a file load and keeps its current exception type to preserve those reporting contracts. (`validate_json` is available for the cases where converting is clean; these are the cases where it is not.)

Direct `json.loads` remains acceptable for: tests constructing fixtures, migrations, payload strings already in memory (not files), and non-config data interchange.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-json-adoption-1 | Helper Routing | Implemented | Listed loaders read/validate via `tap/jsonfiles.py`. | |
| req-tap-json-adoption-2 | Domain Wrapping | Implemented | Each caller translates `JsonFileError` to its domain exception, preserving message quality. | |
| req-tap-json-adoption-3 | Tolerant Reader Preserved | Implemented | The settings-time auth reader returns `{}` on failure rather than crashing import. | |
| req-tap-json-adoption-4 | Multi-Error Path Preserved | Implemented | `providers/secrets.py` retains `iter_errors` all-errors reporting. | |

### Filename Scanner
----
RID: `req-tap-json-scanner`

Status: `Implemented`

A pytest scanner enforces the filename convention with a baseline ratchet, mirroring the log-site-id scanner (`spec-tap-logging.md` req-tap-logging-site-id-scanner). Existing non-conforming names are recorded in a baseline; new files must conform.

#### Implementation

- `tap/jsonfiles.py` exports `scan_json_files(roots: list[Path]) -> ScanResult`. It walks every `*.json` under each root, excluding non-TAP-owned trees (`.venv`, `node_modules`, `__pycache__`, `vendor` — the last holds third-party files such as the NIST OSCAL schemas under `plugins/roscale/vendor/`) and standard tooling files (`package.json`, `package-lock.json`, `tsconfig.json`, `*.lock`).
- A filename **conforms** when it matches one of:
  - `*.<role>.json` for a known role in `{boot, secret, grift, edge, gridkin}`;
  - `*.schema.json`;
  - `<app>.<name>.json` where `<app>` is an installed first-party app label;
  - an explicit allow-list entry (test-fixture / expected-output suffixes: `*.expected.json`, files under `**/tests/`, `**/fixtures/`).
- Non-conforming files are compared against the baseline `tap/tests/_json_file_baseline.txt` (relative paths, one per line). The scan **fails** when a non-conforming file is not in the baseline (a new violation), and reports baseline entries that no longer exist (stale, encouraging removal).
- Test entry point: `tap/tests/test_json_files.py` calls `scan_json_files([...])` over the source roots.
- The baseline seeds with today's descriptive-but-unprefixed collector manifests; it ratchets toward empty as those are opportunistically renamed.

#### Development

The baseline-ratchet is the same pragmatic pattern logging uses: record current debt, refuse growth, drive down opportunistically. It is what makes the convention "as mandatory as possible without a big-bang rename" — the collector manifests don't have to be touched in this change to lock the convention for everything new.

The scanner is lexical over filenames, not content — it never opens the JSON. That keeps it fast and free of import-order coupling, and it is the right altitude: the convention is *about names*. Schema-stem-is-role (`req-tap-json-naming-4`) is checkable here too (every `*.schema.json` whose stem is a known role must sit beside files of that role), but v0 keeps the scanner to the membership check and leaves the pairing check as a `Backlog` tightening.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-json-scanner-1 | Scanner Location | Implemented | `tap/jsonfiles.py` exports `scan_json_files(roots)`. | |
| req-tap-json-scanner-2 | Test Location | Implemented | `tap/tests/test_json_files.py` invokes the scanner. | |
| req-tap-json-scanner-3 | Conformance Set | Implemented | Role-suffix, `.schema.json`, app-prefix, and the allow-list are the conforming forms. | |
| req-tap-json-scanner-4 | Baseline Ratchet | Implemented | New non-conforming files fail; baselined ones pass; stale baseline entries are reported. | |
| req-tap-json-scanner-5 | Tooling Excluded | Implemented | `package.json`, lockfiles, `tsconfig.json`, and vendored dirs are excluded. | |

### Load Size Guard
----
RID: `req-tap-json-size-guard`

Status: `Backlog`

An optional `max_bytes` ceiling on `load_json_file`'s read, rejecting oversized files **before** parsing. A cheap denial-of-service edge (a hostile or accidental multi-GB file should fail fast, not OOM the parser). Deferred until a surface actually ingests operator-supplied or third-party JSON at a trust boundary; recorded now because the single load path (`req-tap-json-loader`) is exactly where such a guard belongs, and naming it keeps the seam visible.

Prior art / first concrete instance: the secret size guard (`req-tap-cares-secrets-size-guard`) already enforces a 1 MiB per-file ceiling (with a per-file `metadata.max_bytes` raise) in `tap/runtime_secrets`, but as a *post-read* `st_size` check. This general guard is the *pre-read* version — the absolute ceiling that fails a pathological file before any `read_text` — which the secret guard explicitly defers to (`req-tap-cares-secrets-size-guard-5`).

## Out Of Scope (v0)

- **Renaming collector manifests.** The descriptive-but-unprefixed `plugins/*/collectors/*/` manifests are baselined, not renamed, in this change. Opportunistic ratchet work.
- **YAML / TOML.** This spec governs JSON files only. `tap-plugin.toml` and any future YAML have their own conventions.
- **A global role→schema registry.** Explicitly rejected for v0 (`req-tap-json-schema-explicit`); additive if ever needed.
- **Content-level scanning.** The scanner is lexical over filenames; it does not open or validate file contents.
- **`tap` as a registered Django app.** As with logging, the helper and scanner live in `tap/jsonfiles.py` as a plain module until something concrete demands an `AppConfig`.

## Future

- **Schema-stem-is-role pairing check.** Tighten the scanner to assert every `*.schema.json` whose stem is a known role sits beside files of that role, and that each discovered family has exactly one schema (`req-tap-json-naming-4` enforced, not just conventional).
- **`max_bytes` size guard.** Wire `req-tap-json-size-guard` when a trust-boundary ingestion surface appears.
- **Collector-manifest convention.** Decide whether collector manifests become `<plugin>.<collector>.manifest.json` (app-prefixed) or gain a `manifest` role suffix, then ratchet the baseline to empty.
- **`manage.py check_json_files`.** Expose the scanner as a management command if/when `tap` becomes a registered app, alongside the pytest test (same shape as the deferred `check_log_sites`).
