# Plugin Manifest v0 Specification

## Philosophy

The plugin manifest exists so a TAP plugin can declare its load surface in a way that is inspectable before arbitrary Python startup logic runs. In v0 the manifest should be concrete enough for humans and loaders to rely on, but small enough that it does not become a second programming language.

The manifest is not a general package descriptor. It is TAP-specific metadata for TAP plugin loading. Its job is to answer a narrow set of questions consistently:

- what plugin is this
- what TAP-managed model types does it contribute
- what edge types does it contribute
- what editor descriptors does it contribute
- what search runners does it contribute
- what bundled GRIFT files does it publish

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Concrete      | The manifest defines exact v0 fields rather than high-level intent only |
| 2. | Strict        | Unknown keys and malformed entries are rejected                 |
| 3. | Declarative   | The manifest describes plugin surfaces without embedding loader logic |
| 4. | Reviewable    | A human can understand a plugin's TAP load surface from one file |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-plugin-manifest-v0-scaffold | [Plugin Package Scaffold](#plugin-package-scaffold) | Implemented | Minimum required files and Django AppConfig conventions |
| req-tap-plugin-manifest-v0-file | [Manifest File And Format](#manifest-file-and-format) | Implemented | Fixed file name and TOML format |
| req-tap-plugin-manifest-v0-top | [Top-Level Fields](#top-level-fields) | Implemented | Exact required and optional root fields |
| req-tap-plugin-manifest-v0-models | [Model Mappings](#model-mappings) | Implemented | Exact slug-to-class mapping for declared TAP model types |
| req-tap-plugin-manifest-v0-edges | [Edge Mappings](#edge-mappings) | Implemented | Exact slug-to-file mapping for declared edge types |
| req-tap-plugin-manifest-v0-edge-file | [Edge Definition File](#edge-definition-file) | Implemented | Strict JSON shape for individual edge definition files |
| req-tap-plugin-manifest-v0-editors | [Editor Mappings](#editor-mappings) | Implemented | Exact entity-type-to-descriptor mapping for declared editors |
| req-tap-plugin-manifest-v0-searches | [Search Mappings](#search-mappings) | Implemented | Exact runner-key-to-callable mapping for declared search runners |
| req-tap-plugin-manifest-v0-grift | [GRIFT Mappings](#grift-mappings) | Implemented | Bundle-to-file mapping for declared GRIFT bundles; auto-imported on plugin load |
| req-tap-plugin-manifest-v0-paths | [Path Rules And Conventions](#path-rules-and-conventions) | Implemented | Required directories, relative paths, data/ subdirectory support |
| req-tap-plugin-manifest-v0-validation | [Validation Rules](#validation-rules) | Implemented | Strict validation and loader checks |
| req-tap-plugin-manifest-v0-nongoals | [v0 Non-Goals](#v0-non-goals) | Proposed | Explicitly deferred manifest concerns |

### Plugin Package Scaffold
----
RID: `req-tap-plugin-manifest-v0-scaffold`
Status: `Implemented`

Every TAP plugin is a Django app package. Three files are always required to create a working plugin.

#### Status Details
Implemented alongside the manifest loader. `TapPluginConfig` auto-derives `name`, `label`, and `verbose_name` so subclasses need no explicit attributes.

#### Implementation

**`__init__.py`**

Standard Python package marker. Must exist; must be empty (or contain only a module docstring). `default_app_config` must not be set — Django 3.2+ auto-discovers the single `AppConfig` subclass in `apps.py`.

```python
"""My plugin — short description."""
```

**`apps.py`**

Defines the Django `AppConfig` for the plugin. Must contain exactly one `TapPluginConfig` subclass. No explicit attributes are required:

- `name` is auto-derived from the subclass module path (e.g. `plugins.my_plugin.apps` → `plugins.my_plugin`)
- `label` is read from the manifest `slug` field at Django startup
- `verbose_name` is read from the manifest `name` field at Django startup

The class body should be `pass` unless you have a genuine reason to override a specific attribute.

```python
"""My plugin AppConfig."""

from tap_plugins.base import TapPluginConfig


class MyPluginConfig(TapPluginConfig):
    pass
```

**`tap-plugin.toml`**

The plugin manifest. See [Manifest File And Format](#manifest-file-and-format) and subsequent sections for the full schema.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-manifest-v0-scaffold-1 | Init File Required | Implemented | Every plugin package must have an `__init__.py`. | |
| req-tap-plugin-manifest-v0-scaffold-2 | Init File Empty | Implemented | `__init__.py` contains no `default_app_config` and no TAP bootstrap logic. | |
| req-tap-plugin-manifest-v0-scaffold-3 | Apps File Required | Implemented | Every plugin package must have an `apps.py` with exactly one `TapPluginConfig` subclass. | |
| req-tap-plugin-manifest-v0-scaffold-4 | Name Auto-Derived | Implemented | `TapPluginConfig` derives `name` from the subclass `__module__`; subclasses must not declare it explicitly. | |
| req-tap-plugin-manifest-v0-scaffold-5 | Label And Verbose Name Auto-Derived | Implemented | `label` and `verbose_name` are read from `tap-plugin.toml` `slug` and `name` at Django startup; subclasses must not declare them explicitly. | |
| req-tap-plugin-manifest-v0-scaffold-6 | Minimal Subclass Body | Implemented | The `TapPluginConfig` subclass body should be `pass`; no manual `ready()` override is needed for manifest-declared surfaces. | |
| req-tap-plugin-manifest-v0-scaffold-7 | Manifest File Required | Implemented | `tap-plugin.toml` must exist at the plugin root. | |

#### Future
If TAP adds a plugin scaffolding CLI command, it should generate these three files automatically.

### Manifest File And Format
----
RID: `req-tap-plugin-manifest-v0-file`
Status: `Implemented`

The plugin manifest is a TOML file with a fixed name.

#### Status Details
Proposed as the concrete follow-on to the plugin load lifecycle spec.

#### Implementation
In v0:

- the manifest file name is `tap-plugin.toml`
- the file lives at the plugin root
- the manifest format is TOML
- the manifest is purely declarative

The loader reads `tap-plugin.toml` as the canonical declaration file for plugin identity, TAP-managed model declarations, and bundled GRIFT declarations.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-manifest-v0-file-1 | Fixed File Name | Implemented | The plugin manifest file is named `tap-plugin.toml`. | |
| req-tap-plugin-manifest-v0-file-2 | Plugin Root Location | Implemented | The manifest lives at the plugin root. | |
| req-tap-plugin-manifest-v0-file-3 | TOML Format | Implemented | The manifest is encoded as TOML. | |
| req-tap-plugin-manifest-v0-file-4 | Declarative Only | Implemented | The manifest contains declarations only, not loader hooks or executable behavior. | |

#### Future
Later work may define how the plugin root is discovered or whether manifests can be generated, but v0 assumes a direct file at the plugin root.

### Top-Level Fields
----
RID: `req-tap-plugin-manifest-v0-top`
Status: `Implemented`

The v0 manifest has a small, explicit top-level shape.

#### Status Details
Proposed to eliminate ambiguity about required identity and version fields.

#### Implementation
The top-level manifest fields are:

Required:

- `manifest_version`: string
- `plugin_version`: string
- `slug`: string
- `name`: string

Optional:

- `description`: string
- `requires_tap`: string — a PEP 440 version specifier naming the range of TAP core (`tap`) versions this plugin supports (e.g. `">=0.1,<0.2"`). The compatibility floor; see `req-tap-plugin-extdev-compat-floor` in `spec-tap-plugin-external-development.md`. Absent means no declared floor (allowed in v0). A malformed specifier is rejected at parse time. The pre-boot compatibility gate refuses a plugin whose declared range excludes the running core — reject-at-boot, not run-then-crash.

Optional sections:

- `models`
- `edges`
- `editors`
- `searches`
- `grift`

Unknown top-level keys are invalid.

The top-level fields mean:

- `manifest_version`: the version of the manifest schema understood by TAP
- `plugin_version`: the version of the plugin itself
- `slug`: the canonical TAP plugin slug
- `name`: the human-readable plugin name
- `description`: optional short human-readable description
- `requires_tap`: optional PEP 440 core-version compatibility range

In v0, `manifest_version` should be `"0"`.

### Example

```toml
manifest_version = "0"
plugin_version = "0.1.0"
slug = "lotr"
name = "Lord of the Rings"
description = "Middle-earth example plugin."
requires_tap = ">=0.1,<0.2"
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-manifest-v0-top-1 | Required Identity Fields | Implemented | The manifest requires `manifest_version`, `plugin_version`, `slug`, and `name`. | |
| req-tap-plugin-manifest-v0-top-2 | Optional Description | Implemented | `description` is optional. | |
| req-tap-plugin-manifest-v0-top-3 | Optional Sections | Implemented | `models`, `edges`, `editors`, `searches`, and `grift` sections may be omitted when empty. | |
| req-tap-plugin-manifest-v0-top-4 | Unknown Top-Level Keys Rejected | Implemented | Unknown top-level keys are invalid. | |
| req-tap-plugin-manifest-v0-top-5 | Manifest Version Fixed | Implemented | v0 manifests use `manifest_version = "0"`. | |
| req-tap-plugin-manifest-v0-top-6 | Optional Compatibility Floor | Implemented | `requires_tap`, when present, is a PEP 440 core-version specifier; malformed values are rejected at parse time. Enforcement is `req-tap-plugin-extdev-compat-floor`. | |

#### Future
`requires_tap` (top-6) realizes the compatibility-range note below. Later versions may still add authorship, licensing, and capability flags. The grid-plugin *protocol* version (`req-tap-plugin-extdev-protocol`) is the deferred coarse wire-contract companion to `requires_tap`.

### Edge Mappings
----
RID: `req-tap-plugin-manifest-v0-edges`
Status: `Implemented`

The manifest declares plugin-defined edge types explicitly as slug-to-file mappings.

#### Status Details
Proposed to move edge type declarations out of ad hoc `apps.py` metadata and into the same declarative plugin surface as models and GRIFT.

#### Implementation
Edge declarations use a TOML table:

```toml
[edges]
WIELDS = "edges/wields.edge.json"
LOCATED_IN = "edges/located_in.edge.json"
```

Each key in `[edges]` is an edge type slug.
Each value in `[edges]` is the relative path from the plugin root to a strict JSON file defining that edge type.

In v0:

- edge definition files live under an `edges/` directory at the plugin root
- each edge type is declared in its own file
- edge definition files use the `.edge.json` extension

The loader validates that:

- each declared edge path exists
- each declared edge path resolves within the plugin root
- each edge definition file parses as JSON
- each edge definition is strict and uses only declared fields
- the edge file's `slug` matches the manifest key

Duplicate edge slugs are structurally impossible within one TOML table.
Duplicate edge file paths inside one manifest are invalid.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-manifest-v0-edges-1 | Mapping Table | Implemented | Edge declarations use an `[edges]` TOML table. | |
| req-tap-plugin-manifest-v0-edges-2 | Slug To File Shape | Implemented | Each `[edges]` entry maps an edge type slug to a relative edge definition file path. | |
| req-tap-plugin-manifest-v0-edges-3 | One File Per Edge | Implemented | Each edge type is declared in its own file. | |
| req-tap-plugin-manifest-v0-edges-4 | Edge Directory Required | Implemented | Edge definition files live under an `edges/` directory at the plugin root. | |
| req-tap-plugin-manifest-v0-edges-5 | Canonical Edge Extension | Implemented | Edge definition files use the `.edge.json` extension. | |
| req-tap-plugin-manifest-v0-edges-6 | Loader Validates Slug Match | Implemented | The loader validates that the edge file's `slug` matches the manifest key. | |
| req-tap-plugin-manifest-v0-edges-7 | Duplicate Slugs Impossible | Implemented | The TOML table structure prevents duplicate edge slug keys within one manifest. | |
| req-tap-plugin-manifest-v0-edges-8 | Duplicate Paths Invalid | Implemented | Duplicate edge definition file paths in one manifest are invalid. | |

#### Future
Later versions may allow shared schema fragments or richer target selectors, but v0 keeps one strict JSON object per edge type.

### Edge Definition File
----
RID: `req-tap-plugin-manifest-v0-edge-file`
Status: `Implemented`

Each declared edge path points to one strict JSON object describing a single edge type.

#### Status Details
Proposed to keep edge definitions simple, diffable, and loader-friendly.

#### Implementation
An edge definition file is JSON and contains:

Required fields:

- `slug`: string
- `name`: string
- `description`: string

Optional fields:

- `sources`: array of strings
- `targets`: array of strings
- `property_schema`: object
- `default_dimensions`: object

Unknown keys are invalid.

The file format intentionally simplifies `sources` and `targets` from the current Python declaration shape. In v0 they are simple string arrays of TAP type slugs rather than arrays of `{ "type": "..." }` objects.

Example:

```json
{
  "slug": "WIELDS",
  "name": "Wields",
  "description": "Character wields an artifact.",
  "sources": ["character"],
  "targets": ["artifact"],
  "property_schema": {
    "type": "object",
    "properties": {
      "proficiency": {
        "type": "string",
        "enum": ["novice", "apprentice", "master"]
      },
      "primary": {
        "type": "boolean"
      }
    }
  }
}
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-manifest-v0-edge-file-1 | Strict Json Object | Implemented | Each edge definition file is one JSON object. | |
| req-tap-plugin-manifest-v0-edge-file-2 | Required Core Fields | Implemented | Each edge definition file requires `slug`, `name`, and `description`. | |
| req-tap-plugin-manifest-v0-edge-file-3 | Simplified Endpoint Arrays | Implemented | `sources` and `targets`, when present, are arrays of TAP type slug strings. | |
| req-tap-plugin-manifest-v0-edge-file-4 | Optional Property Schema | Implemented | `property_schema` may be declared as an object. | |
| req-tap-plugin-manifest-v0-edge-file-5 | Optional Default Dimensions | Implemented | `default_dimensions` may be declared as an object. | |
| req-tap-plugin-manifest-v0-edge-file-6 | Unknown Keys Rejected | Implemented | Unknown keys in an edge definition file are invalid. | |

#### Future
If TAP later needs richer endpoint selectors, it can introduce them in a later manifest version without forcing them into v0.

### Editor Mappings
----
RID: `req-tap-plugin-manifest-v0-editors`
Status: `Implemented`

The manifest declares editor descriptors explicitly as entity-type-to-class mappings.

#### Status Details
Proposed to let editors declare who they can edit without forcing models to carry UI references or making templates a first-class manifest surface.

#### Implementation
Editor declarations use a TOML table:

```toml
[editors]
character = "plugins.lotr.editors.character.CharacterEditorDescriptor"
```

Each key in `[editors]` is the entity type slug edited by the descriptor.
Each value in `[editors]` is the concrete Python import path for the editor descriptor class.

In v0:

- `editors/` is an optional directory at the plugin root for editor descriptors and their associated Django form classes
- if `[editors]` is present, editor descriptor code should live under `editors/`
- there is at most one editor per entity type within a plugin

The loader validates that:

- each editor class path resolves
- the class is a concrete `EditorDescriptor`
- the descriptor class agrees with the declared entity type key

Duplicate editor entity type keys are structurally impossible within one TOML table.

Templates used by editor descriptors are not declared in the manifest in v0. They remain ordinary Django template assets referenced by the descriptor.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-manifest-v0-editors-1 | Mapping Table | Implemented | Editor declarations use an `[editors]` TOML table. | |
| req-tap-plugin-manifest-v0-editors-2 | Entity Type To Descriptor Shape | Implemented | Each `[editors]` entry maps an entity type slug to a concrete editor descriptor class path. | |
| req-tap-plugin-manifest-v0-editors-3 | Optional Editors Directory | Implemented | `editors/` is optional and is only needed when a plugin declares editors. | |
| req-tap-plugin-manifest-v0-editors-4 | One Editor Per Entity Type | Implemented | v0 allows at most one editor per entity type within a plugin. | |
| req-tap-plugin-manifest-v0-editors-5 | Loader Validates Descriptor Class | Implemented | The loader validates that each declared editor class resolves to a concrete `EditorDescriptor`. | |
| req-tap-plugin-manifest-v0-editors-6 | Loader Validates Entity Type Match | Implemented | The loader validates that each declared editor descriptor matches the manifest entity type key. | |
| req-tap-plugin-manifest-v0-editors-7 | Templates Stay Implicit | Implemented | Templates referenced by editor descriptors are not separately declared in the manifest in v0. | |

#### Future
If TAP later introduces non-web editor surfaces or multiple editor variants per type, the manifest can grow a more structured editor declaration model.

### Search Mappings
----
RID: `req-tap-plugin-manifest-v0-searches`
Status: `Implemented`

The manifest declares search runners explicitly as runner-key-to-callable mappings.

#### Status Details
Proposed to move search runner registration out of ad hoc `ready()` code and into the same declarative plugin surface as editors.

#### Implementation
Search declarations use a TOML table:

```toml
[searches]
list-characters-with-bio = "plugins.lotr.searches.characters.list_characters_with_bio"
```

Each key in `[searches]` is the short runner key declared by the plugin.
Each value in `[searches]` is the concrete Python import path for the search runner callable.

In v0:

- `searches/` is the required directory for search runner modules when a plugin declares searches
- there is at most one search runner per runner key within a plugin
- the manifest uses the short runner key for readability
- the loader is responsible for registering the runner in TAP's scoped registry using the plugin/module scope so persisted searches may continue using the fully qualified runner key form

The loader validates that:

- each search callable path resolves
- the resolved object is callable

Duplicate runner keys are structurally impossible within one TOML table.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-manifest-v0-searches-1 | Mapping Table | Implemented | Search declarations use a `[searches]` TOML table. | |
| req-tap-plugin-manifest-v0-searches-2 | Runner Key To Callable Shape | Implemented | Each `[searches]` entry maps a short runner key to a concrete callable path. | |
| req-tap-plugin-manifest-v0-searches-3 | Searches Directory Convention | Implemented | `searches/` is the required directory for search runner modules when a plugin declares searches. | |
| req-tap-plugin-manifest-v0-searches-4 | One Runner Per Key | Implemented | v0 allows at most one search runner per runner key within a plugin. | |
| req-tap-plugin-manifest-v0-searches-5 | Loader Validates Callable | Implemented | The loader validates that each declared search target resolves to a callable. | |
| req-tap-plugin-manifest-v0-searches-6 | Scoped Registration Contract | Implemented | The loader registers manifest-declared search runners using TAP's scoped search runner registry so persisted searches may use the fully qualified runner key form. | |

#### Future
If TAP later adds richer search metadata, the manifest may grow optional display or parameter-description fields without changing the core runner mapping concept.

### Model Mappings
----
RID: `req-tap-plugin-manifest-v0-models`
Status: `Implemented`

The manifest declares TAP-managed plugin model types explicitly as slug-to-class mappings.

#### Status Details
Proposed to make model loading TAP-type-oriented rather than module-oriented.

#### Implementation
Model declarations use a TOML table:

```toml
[models]
character = "plugins.lotr.models.character.Character"
```

Each key in `[models]` is a TAP type slug.
Each value in `[models]` is the concrete Python import path for the TAP-managed model class.

The loader validates that:

- the class path value resolves
- the class is a concrete TAP-managed model class
- the class agrees with the declared slug key

Duplicate model slugs are structurally impossible within one TOML table.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-manifest-v0-models-1 | Mapping Table | Implemented | Model declarations use a `[models]` TOML table. | |
| req-tap-plugin-manifest-v0-models-2 | Slug To Class Shape | Implemented | Each `[models]` entry maps a TAP type slug to a concrete class path. | |
| req-tap-plugin-manifest-v0-models-3 | Concrete Class Path | Implemented | Each mapping value names a concrete Python class path, not just a module path. | |
| req-tap-plugin-manifest-v0-models-4 | Loader Validates Class | Implemented | The loader validates that each declared class exists and is a concrete TAP-managed model. | |
| req-tap-plugin-manifest-v0-models-5 | Loader Validates Slug Match | Implemented | The loader validates that each declared class matches the declared TAP type slug key. | |
| req-tap-plugin-manifest-v0-models-6 | Duplicate Slugs Impossible | Implemented | The TOML table structure prevents duplicate model slug keys within one manifest. | |

#### Future
Later versions may add optional display metadata here or may source more of that data from the model class itself.

### GRIFT Mappings
----
RID: `req-tap-plugin-manifest-v0-grift`
Status: `Implemented`

The manifest declares bundled GRIFT files explicitly as bundle-name-to-file mappings.

#### Status Details
Implemented. Declared GRIFT bundles are imported automatically on every plugin load via `TapPluginConfig.ready()`. Import uses upsert mode, so repeated loads are safe. Logging is via the Django logger — no stdout side-effects at startup.

#### Implementation
GRIFT declarations use a TOML table:

```toml
[grift]
core-data = "grift/core-data.grift.json"
```

Each key in `[grift]` is a logical bundle name unique within the plugin.
Each value in `[grift]` is the relative path from the plugin root to the GRIFT file.

All GRIFT file paths in v0 must end in `.grift.json`.

The loader validates at startup that each declared path exists.
GRIFT parsing and content validation happen during import.

On every `ready()` call, `TapPluginConfig` calls `grift_import` for each declared bundle using `dangling_edge_mode="warn"`. Import runs in upsert mode — nodes and edges that already exist are updated in place rather than duplicated. If the database is not yet ready (e.g. during initial migrations), the import is silently skipped and logged at DEBUG level.

Duplicate GRIFT bundle names are structurally impossible within one TOML table.
Duplicate GRIFT paths inside one manifest are invalid.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-manifest-v0-grift-1 | Mapping Table | Implemented | GRIFT declarations use a `[grift]` TOML table. | |
| req-tap-plugin-manifest-v0-grift-2 | Bundle To File Shape | Implemented | Each `[grift]` entry maps a bundle name to a relative file path. | |
| req-tap-plugin-manifest-v0-grift-3 | Canonical Grift Extension | Implemented | GRIFT file paths end in `.grift.json`. | |
| req-tap-plugin-manifest-v0-grift-4 | Relative Path | Implemented | Each mapping value is stored relative to the plugin root. | |
| req-tap-plugin-manifest-v0-grift-5 | Startup Path Validation | Implemented | Startup validation confirms that each declared GRIFT path exists. | |
| req-tap-plugin-manifest-v0-grift-6 | Auto-Import On Plugin Load | Implemented | `TapPluginConfig.ready()` calls `grift_import` for each declared bundle on every plugin load. | |
| req-tap-plugin-manifest-v0-grift-7 | Import Idempotent | Implemented | GRIFT import runs in upsert mode; repeated loads do not duplicate data. | |
| req-tap-plugin-manifest-v0-grift-8 | Database Not Ready Tolerated | Implemented | If the database is not ready at startup, GRIFT import is silently skipped (DEBUG log). | |
| req-tap-plugin-manifest-v0-grift-9 | Duplicate Names Impossible | Implemented | The TOML table structure prevents duplicate GRIFT bundle names within one manifest. | |
| req-tap-plugin-manifest-v0-grift-10 | Duplicate Paths Invalid | Implemented | Duplicate GRIFT bundle paths in one manifest are invalid. | |

#### Future
When a plugin state system is introduced, auto-import can be conditioned on plugin install state (e.g. only import if the bundle has not been imported at the current version). Until then, every startup re-runs the upsert. Per-bundle import modes (replace, skip, etc.) are also deferred to a future manifest version.

### Path Rules And Conventions
----
RID: `req-tap-plugin-manifest-v0-paths`
Status: `In Development`

The manifest requires specific directories and supports `grift/` subdirectory organization without requiring sub-paths to be declared.

#### Status Details
Updated: convention directories are required only when the plugin declares the corresponding manifest surface. A plugin that does not declare `[models]` does not need a `models/` directory. `grift/` allows optional sub-directories as an organizational convenience that does not change loader semantics.

#### Implementation
In v0:

- `models/` is required at the plugin root when the plugin declares a `[models]` section. A plugin without `[models]` may omit `models/` entirely.
- `edges/` is required at the plugin root when the plugin declares an `[edges]` section.
- `editors/` is optional; needed only when a plugin declares `[editors]`.
- `searches/` is required at the plugin root when the plugin declares a `[searches]` section.
- `grift/` is required at the plugin root when the plugin declares a `[grift]` section.

`grift/` sub-directories are allowed as a convenience for organizing large or multi-category data sets (e.g. `grift/nodes/characters.grift.json`, `grift/edges.grift.json`). Sub-directory paths are declared explicitly in the manifest `[grift]` table the same way as top-level paths. TAP does not require that sub-directories be declared separately; only file-level GRIFT entries are declarable.

TAP does not load every file found in `models/`, `edges/`, `editors/`, `searches/`, or `grift/` automatically. Only manifest-declared entries are part of the plugin load contract.

Manifest-declared paths are evaluated relative to the plugin root.

If files exist in `models/`, `edges/`, `editors/`, `searches/`, or `grift/` (including sub-directories) but are not declared in the manifest:

- TAP warns that they are undeclared
- TAP does not treat them as loadable plugin surfaces

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-manifest-v0-paths-1 | Required Directories Defined | Implemented | Convention directories (`models/`, `edges/`, `grift/`, `searches/`) are required only when the plugin declares the corresponding manifest surface. `editors/` is optional even when declared. | |
| req-tap-plugin-manifest-v0-paths-2 | No Implicit Autoload | Implemented | Files in `models/`, `edges/`, `editors/`, `searches/`, or `grift/` are not loaded solely because they are present. | |
| req-tap-plugin-manifest-v0-paths-3 | Relative To Plugin Root | Implemented | Manifest paths are resolved relative to the plugin root. | |
| req-tap-plugin-manifest-v0-paths-4 | Undeclared Files Warn | Implemented | Undeclared files in convention directories produce warnings, not startup errors. | |
| req-tap-plugin-manifest-v0-paths-5 | Grift Subdirectories Allowed | Implemented | `grift/` may contain sub-directories for organizational convenience without requiring sub-path declarations. | |
| req-tap-plugin-manifest-v0-paths-6 | Models Directory Conditional | Implemented | `models/` is required only when the plugin declares `[models]`. | |
| req-tap-plugin-manifest-v0-paths-7 | Edges Directory Conditional | Implemented | `edges/` is required only when the plugin declares `[edges]`. | |
| req-tap-plugin-manifest-v0-paths-8 | Editors Directory Optional | Implemented | A plugin may omit `editors/` entirely even when it declares editors. | |
| req-tap-plugin-manifest-v0-paths-9 | Searches Directory Conditional | Implemented | `searches/` is required only when the plugin declares `[searches]`. | |

#### Future
Later tooling may scaffold these directories automatically or offer commands to reconcile undeclared files with manifest entries. Sub-directory conventions within `grift/` may be standardized if patterns emerge across plugins.

### Validation Rules
----
RID: `req-tap-plugin-manifest-v0-validation`
Status: `Implemented`

The v0 manifest is intentionally strict.

#### Status Details
Proposed to make the manifest reliable as a loader contract rather than informal documentation.

#### Implementation
General validation rules:

- the manifest must parse as TOML
- all required top-level fields must be present
- unknown keys are rejected at the top level
- required field values must be strings
- empty strings are invalid for required fields

Model validation rules:

- model slug keys must be unique within `models`
- `class` path values should be unique within `models`
- each class path must resolve to a concrete TAP-managed model class
- each resolved class must agree with its declared slug

Edge validation rules:

- edge slug keys must be unique within `edges`
- edge file paths must be unique within `edges`
- each path must exist at startup
- each path must use the `.edge.json` extension
- each path must resolve to one strict JSON object
- each edge file `slug` must match the manifest key
- `sources` and `targets`, when present, must be arrays of strings

Editor validation rules:

- editor entity type keys must be unique within `editors`
- each editor class path must resolve to a concrete `EditorDescriptor`
- each resolved descriptor must agree with its declared entity type key

Search validation rules:

- search runner keys must be unique within `searches`
- each search callable path must resolve to a callable
- manifest keys are short runner keys; scoped fully qualified registration is handled by the loader

GRIFT validation rules:

- GRIFT bundle name keys must be unique within `grift`
- `path` values must be unique within `grift`
- each `path` must exist at startup
- path traversal outside the plugin root is invalid

The manifest spec is strict by default and does not define a `_reserved` escape hatch in v0.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-manifest-v0-validation-1 | TOML Parse Required | Implemented | The manifest must parse as valid TOML. | |
| req-tap-plugin-manifest-v0-validation-2 | Required Strings Present | Implemented | Required fields must exist and be non-empty strings. | |
| req-tap-plugin-manifest-v0-validation-3 | Unknown Keys Rejected Everywhere | Implemented | Unknown keys are rejected at the top level and in section entries. | |
| req-tap-plugin-manifest-v0-validation-4 | Plugin-Root Path Safety | Implemented | Declared edge and GRIFT paths may not escape the plugin root. | |
| req-tap-plugin-manifest-v0-validation-5 | Model Resolution Enforced | Implemented | Declared model class paths must resolve to valid concrete TAP-managed model classes. | |
| req-tap-plugin-manifest-v0-validation-6 | Edge Resolution Enforced | Implemented | Declared edge file paths must resolve to valid strict edge definition files with matching slugs. | |
| req-tap-plugin-manifest-v0-validation-7 | Editor Resolution Enforced | Implemented | Declared editor class paths must resolve to valid concrete editor descriptors with matching entity types. | |
| req-tap-plugin-manifest-v0-validation-8 | Search Resolution Enforced | Implemented | Declared search callable paths must resolve to valid callables and register through the scoped runner contract. | |
| req-tap-plugin-manifest-v0-validation-9 | Strict By Default | Implemented | v0 does not define a generic reserved or future-extension section. | |
| req-tap-plugin-manifest-v0-secrets | Secret Kinds Declaration | Backlog | A future optional `[secrets]` table declares the secret kinds a plugin's collectors/consumers resolve (scope is implicitly the plugin `slug`; entries name `key`, `kind`, and a one-line conditional-necessity summary) — the "declare" half of declare-vs-decide for credentials, mirroring `[fips]`. Payoff is a conformance cross-check: (a) a plugin resolving an undeclared `scope:key` WARNs, `--strict` fails (the FIPS undeclared-leak semantics); (b) a boot profile's `required_secrets` + step consumption refs (`req-boot-required-secrets`, `spec-tap-boot-v0.md`) are verified against the union of what its enabled steps' plugins declare — catching both gaps and stale entries mechanically. Kind `data` schemas stay consumer-owned (`req-tap-cares-secrets-consumer-kinds`); the table declares identity + necessity summary only, never values. Demand-gated: build with the provisioning/conformance tooling, not before. | Composes `req-boot-required-secrets` and `req-tap-cares-secrets-cross-scope-concern` (the runtime tripwire this makes statically checkable). |
| req-tap-plugin-manifest-v0-fips | FIPS Crypto Posture Declaration | Implemented | An optional `[fips]` table declares the plugin author's FACTUAL crypto posture — the "declare" half of declare-vs-decide (`req-fips-crypto-bom`). `status` is required: `compatible` (claims only FIPS-validated crypto — the system OpenSSL #4282 provider) or `uses-nonvalidated` (honestly acknowledges non-FIPS crypto, which REQUIRES a non-empty `reason`, mirroring the operator waiver's mandatory justification); `providers` optionally names the acknowledged non-validated providers. It is a declaration, NOT a self-exemption: a plugin cannot excuse itself from a deployment's FIPS posture — only the operator waives, via the boot profile's `fips_waivers`, enforced by the boot-time system gate. The `crypto-providers` conformance check VERIFIES the declaration against the crypto-BOM scan of the plugin's shipped artifacts + declared deps: a false `compatible` (scan finds non-validated crypto) FAILS; an honest `uses-nonvalidated` PASSES; an UNDECLARED leak WARNs (`--strict` → fail). Absent `[fips]` is never assumed compatible. | Composes `req-fips-crypto-bom` (the scanner + boot gate + operator waivers) and `req-tap-plugin-validate-*` (the conformance surface). |

#### Future
If v1 needs smoother evolution, it may introduce controlled extension points after more real plugins exist.

### v0 Non-Goals
----
RID: `req-tap-plugin-manifest-v0-nongoals`
Status: `Proposed`

The v0 manifest intentionally covers only a narrow plugin surface.

#### Status Details
Proposed so the first concrete schema does not grow into a full plugin platform descriptor.

#### Implementation
The v0 manifest does not define:

- plugin dependencies
- uv-installable Python package dependencies
- API router declarations
- task or job declarations
- install or uninstall metadata
- enablement state
- per-bundle GRIFT import modes

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-manifest-v0-nongoals-1 | Dependencies Deferred | Proposed | v0 does not define dependency fields. | |
| req-tap-plugin-manifest-v0-nongoals-2 | Wider UI And API Surfaces Deferred | Proposed | Beyond editor declarations, v0 does not define API, panel, or broader UI contribution fields. | |
| req-tap-plugin-manifest-v0-nongoals-3 | Rich Search Metadata Deferred | Proposed | v0 declares search runners but does not add richer search metadata such as labels, parameters, or categories. | |
| req-tap-plugin-manifest-v0-nongoals-4 | Per-Bundle Import Modes Deferred | Proposed | v0 always imports GRIFT bundles in upsert mode; per-bundle mode fields are not declared in the manifest. | |
| req-tap-plugin-manifest-v0-nongoals-5 | Python Dependencies Stay Out Of Manifest | Proposed | uv-installable Python package dependencies are not declared in `tap-plugin.toml`; future plugin-local dependency work belongs in plugin `pyproject.toml` files and the uv workspace shape. | See `req-tap-plugin-arch-python-deps` in `spec-tap-plugin-architecture.md`. |

#### Future
The next likely additions are broader UI contribution surfaces and search-related declarations once enough real plugins exist to justify them.
