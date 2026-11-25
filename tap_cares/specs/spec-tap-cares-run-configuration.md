# tap-cares Run Configuration Specification

## Philosophy

A run configuration says what a collector or an emitter is to do on a run: what to collect or send, from or to where in the outside system's own terms, and how. Today there is no place to say it. `CollectorConfig` carries two ids (`tap_cares/collectors/config.py`), so every plugin that needed a setting put it in its secret envelope, the one channel it had (Issue# 308 - tap), or hardcoded it as a class constant. Settings in a secret load once per process, so changing a region list means a restart, and one fixed secret per component means one account per grid (Issue# 907 - tap, reasons 3, 4 and the restart comment).

This spec gives every collector and emitter one generic, history-tracked node for that, and a way for the component to say what shape its settings take. It adds one node type and one edge to core and nothing else: no per-component configuration types, no new run model, no transport. Everything here applies to collectors and emitters alike; where they differ (arming, and who may schedule them), the difference is stated.

Four lines hold the design together:

- **A configuration says what to do and how; the secret envelope says where a credential goes.** A setting that decides where a credential is sent stays beside the credential, under the operator's file-system control. Whoever can edit a node must not be able to point a credential at another host (the rule `req-tap-cares-v0-emitter-7` states for emitter destinations).
- **One path, no silent defaults.** Every collector and emitter declares whether it is configurable; nothing is inferred from silence. A component that is not configurable still runs through a configuration, the one its plugin ships, so every schedule, run, job and batch points at a configuration.
- **Every run records four things.** The configuration's uuid and revision, and the component's uuid and code version. No override at launch time, on a schedule, or in code; the history row answers what a run ran with.
- **A configuration that does not fit its component does not run.** It is refused at save, and if code moves under it, it fails phase 1 as `misconfigured`. It never runs with fields dropped.

Owner rulings 2026-11-25 on Issue# 907 - tap set every rule here; this spec is where they become canon.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | One Node     | One generic, history-tracked node type serves every collector and emitter |
| 2. | Declared     | Every component declares its configurability in code; nothing is inferred |
| 3. | Credential Stays Put | Where a credential is sent never moves out of the operator's secret envelope |
| 4. | Traceable    | Every run and every batch it writes names the configuration, its revision, the component and its code version |
| 5. | Fresh        | A settings change takes effect on the next run with no restart |
| 6. | Fails Closed | An invalid, unmigratable or contradictory configuration refuses to run and says so |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-cares-runconfig-model | [RunConfiguration Model](#runconfiguration-model) | Proposed | One generic, history-tracked, KEYLESS `RunConfiguration` node addressed by its own UUIDv7: name, description, `configurability`, settings, schema id and version, secret ref |
| req-tap-cares-runconfig-edge | [CONFIGURES Edge](#configures-edge) | Proposed | Exactly one `CONFIGURES` edge to a `Collector` or `Emitter`; a configurable component may have many configurations |
| req-tap-cares-runconfig-schema | [Declared Configurability](#declared-configurability) | Proposed | Every component declares exactly one of `CONFIG_SCHEMA` (with `CONFIG_SCHEMA_VERSION`) or `RUN_CONFIGURATION = NOT_CONFIGURABLE`; registration refuses neither or both, and a schema outside the form-safe subset or with a secret-typed field |
| req-tap-cares-runconfig-not-configurable | [The Not-Configurable Configuration](#the-not-configurable-configuration) | Proposed | A not-configurable component's plugin ships its one `not_configurable` configuration as a GRIFT seed; users never write it |
| req-tap-cares-runconfig-seed-guard | [Configuration Seeds Checked Twice](#configuration-seeds-checked-twice) | Proposed | The `schedule-grift-targets` guard and boot preflight check schedule targets, `CONFIGURES` natural keys and one-not-configurable-per-component; a contradictory configuration refuses to run |
| req-tap-cares-runconfig-mode-switch | [Switching Modes](#switching-modes) | Proposed | The plugin release that changes a declaration swaps the seed; a configuration that contradicts its component's declaration never runs; schedules on it fail loudly |
| req-tap-cares-runconfig-validation | [Validation At Save](#validation-at-save) | Proposed | Every write path refuses settings that fail the component's current schema |
| req-tap-cares-runconfig-schema-migration | [Schema Evolution](#schema-evolution) | Proposed | Component-shipped migrations applied by core as a new revision; unmigratable means invalid, never run with fields dropped |
| req-tap-cares-runconfig-credential | [Credential Reference And The Destination Rule](#credential-reference-and-the-destination-rule) | Proposed | A configuration names its secret by `scope:key`, of a kind the component declares; where a credential is sent stays in the envelope |
| req-tap-cares-runconfig-credential-deviation | [Destination Deviation](#destination-deviation) | Backlog | A mechanism to deviate from the destination rule, proposed when someone hits the pain point |
| req-tap-cares-runconfig-selection | [Which Configuration A Run Uses](#which-configuration-a-run-uses) | Proposed | Every schedule targets one configuration by uuid; a manual run picks one; one configuration needs no choice; no launch-time overrides; current revision only |
| req-tap-cares-runconfig-delivery | [Delivery To Code](#delivery-to-code) | Proposed | `CollectorConfig` and `EmitterConfig` always carry the configuration id, revision, settings and secret ref, from one coherent snapshot read under the row lock at run start |
| req-tap-cares-runconfig-traceability | [The Four-Part Run Record](#the-four-part-run-record) | Proposed | Each job and each batch it writes records the configuration uuid and revision and the component uuid and code version; no node or plugin-table field, no hash |
| req-tap-cares-runconfig-series | [The Configuration Is The Observation Series](#the-configuration-is-the-observation-series) | Proposed | The previous run, and all state carried between runs, is the same configuration's; a new `secret_ref` starts a new series; emitters carry none |
| req-tap-cares-runconfig-capabilities | [Capabilities](#capabilities) | Proposed | `cares.configure`; `cares.run_collectors` widened, `cares.run_emitters`; collector schedules keep `cares.manage_schedules` / `cares.toggle_schedules`, emitter schedules `cares.schedule_emitters`; grid-wide in v0 |
| req-tap-cares-runconfig-self-test | [Readiness Takes The Configuration](#readiness-takes-the-configuration) | Proposed | Core's `misconfigured` check on every run of either kind; a collector's `self_test(config)` takes the configuration; concurrency stays per component |
| req-tap-cares-runconfig-emitter-arming | [Emitter Arming Binds The Configuration](#emitter-arming-binds-the-configuration) | Proposed | Arming moves to the configuration and binds code identity, revision and secret ref; any change re-arms; seeding never arms |
| req-tap-cares-runconfig-web | [Web Surfaces](#web-surfaces) | Proposed | Configuration list and page, typed editor, "Not configurable" label, Run per configuration on the CARES landing page, configuration column on job tables |
| req-tap-cares-runconfig-boot | [Boot Profile Configurations](#boot-profile-configurations) | Proposed | Profile `configurations` section addressed by uuid and validated offline in preflight; plugins seed configurations; step `secrets` stays strings |
| req-tap-cares-runconfig-backlog | [Deferred Configuration Work](#deferred-configuration-work) | Backlog | One-off configurations, per-configuration concurrency, the configuration reference as a dimension, scoped grants (Issue# 1204 - tap), SIDE_EFFECTS (Issue# 1371 - tap), the rest of Issue# 907 - tap |

## RunConfiguration Model
----
RID: `req-tap-cares-runconfig-model`

Status: `Proposed`

`RunConfiguration` is a standard `BaseModel` node declared in `tap_cares` through the `add-model` skill. There is one such type for every collector and emitter; a plugin does not declare its own configuration node type. Default dimension `{"tap_cares": "run_configuration"}`.

It is **user-creatable**, not `INTERNAL_ONLY`, on the `Schedule` precedent (`req-tap-cares-scheduler-model-6`): users write a configurable component's configurations through the standard CRUD API, the editor and boot, and a plugin may seed them through GRIFT (`req-tap-cares-runconfig-boot`). A `not_configurable` configuration is written only by its plugin's seed (`req-tap-cares-runconfig-not-configurable`). Every write routes through a `tap_cares` configuration service so that validation (`req-tap-cares-runconfig-validation`) is the same on every path.

It is `NATURAL_KEY = KEYLESS` with the reason "authored, not observed" (`req-grid-entity-natural-key-5`), with no natural key. It is addressed by its own entity id: one minted by the service for a configuration created through the API or editor, and for a plugin seed or a boot profile entry a real UUIDv7 that the author mints once and writes into the bundle or profile, exactly as plugin seeds do (`req-grift-seed-ids-real` in `tap_grid/specs/spec-grift-seed-ids-real-uuid7.md`).

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | Required, human-readable |
| `description` | string | Plain text: what this configuration is for |
| `configurability` | short text | `configurable` for a configuration of a component that declares `CONFIG_SCHEMA`; `not_configurable` for the one configuration of a component that declares `RUN_CONFIGURATION = NOT_CONFIGURABLE` |
| `settings` | JSON object | The settings, valid against the schema named below. Always `{}` when `not_configurable` |
| `schema_id` | short text | The `$id` of the `CONFIG_SCHEMA` the settings were validated against; empty when `not_configurable` |
| `schema_version` | integer, nullable | The `CONFIG_SCHEMA_VERSION` the settings were validated against; null when `not_configurable` |
| `secret_ref` | short text | The envelope this configuration uses, as `scope:key` (`req-tap-cares-runconfig-credential`); empty when it names none |
| `send_authority`, `armed_emitter_version`, `armed_source_hash`, `armed_revision`, `armed_secret_ref` | | Emitter arming (`req-tap-cares-runconfig-emitter-arming`); written only by `arm_emitter`, empty on a collector's configuration |

The configuration's **revision** is its entity's `version` (`Entity.version`, `tap_grid/models.py`), and each revision is a history row. Edits are ordinary history-tracked writes, recorded with their actor on their batch like any other write; there is no separate audit batch for them. Deletion is the service-layer tombstone, or a GRIFT `deletes` entry in a plugin's seed bundle.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-model-1 | One Generic Type | Proposed | `tap_cares` declares `RunConfiguration` with the fields in the table, `KEYLESS` with a stated reason and no natural key; no plugin declares a configuration node type of its own. | Per-component types are out unless a reason appears later. |
| req-tap-cares-runconfig-model-2 | User-Creatable Through One Service | Proposed | `RunConfiguration` is not `INTERNAL_ONLY`; a create or patch of a `configurable` configuration through the CRUD API, the editor, boot and GRIFT all pass through the same validation. | `Schedule` precedent. |
| req-tap-cares-runconfig-model-3 | Revision Is The Entity Version | Proposed | Each write that changes a configuration increments its `Entity.version` and leaves a history row carrying the settings, the secret ref and the actor of that write. | |
| req-tap-cares-runconfig-model-4 | Addressed By Its Own UUIDv7 | Proposed | A configuration seeded by a plugin bundle or a boot profile carries the author-minted UUIDv7 written there, and the same id on every reimport; no id is derived from a name or a component. | `req-grift-seed-ids-real`. |
| req-tap-cares-runconfig-model-5 | No Secret Material | Proposed | No field of `RunConfiguration` holds secret material; `secret_ref` is a reference (`req-tap-cares-secrets-scope-2`). | |
| req-tap-cares-runconfig-model-6 | Configurability Matches The Declaration | Proposed | A write whose `configurability` is not the one its component's declaration requires is refused. | Named for what it means. |

## CONFIGURES Edge
----
RID: `req-tap-cares-runconfig-edge`

Status: `Proposed`

```text
RunConfiguration --CONFIGURES--> Collector | Emitter
```

`CONFIGURES` is declared by `tap_cares` through the `add-edge` skill. It is naked (no `property_schema`). Every `RunConfiguration` has exactly one, to the component it configures. A configurable component may have any number of configurations; until it has one it cannot be run. A not-configurable component has exactly one (`req-tap-cares-runconfig-not-configurable`). A write that changes the edge's target validates the configuration against the new target (`req-tap-cares-runconfig-validation`).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-edge-1 | Exactly One Target | Proposed | A `RunConfiguration` with no `CONFIGURES` edge, or with two, is refused at the close of the write that would leave it so; the target is a `Collector` or an `Emitter` and nothing else. | |
| req-tap-cares-runconfig-edge-2 | Many Per Component | Proposed | Two configurations of one configurable collector, or of one configurable emitter, each with its own settings, can both exist and each can run. | Issue# 907 - tap reason 3: two accounts on one grid. |
| req-tap-cares-runconfig-edge-3 | Binding Is Fixed | Proposed | A configuration's `CONFIGURES` edge is written once, when the configuration is created, and is never retargeted or replaced; a write that would point an existing configuration at another component is refused, whatever capabilities the actor holds. To configure a different component, create a new configuration. So what a schedule dispatches changes only through `SCHEDULED_TARGET` writes, which the schedule gates cover. | Closes a path around the schedule gates (unified AI review of PR# 1388 - tap). |

## Declared Configurability
----
RID: `req-tap-cares-runconfig-schema`

Status: `Proposed`

**No silent defaults.** Every collector and emitter class declares, in its code, exactly one of:

```python
# configurable
CONFIG_SCHEMA: ClassVar[dict]          # a JSON Schema document with an "$id"; top-level type "object"
CONFIG_SCHEMA_VERSION: ClassVar[int]   # 1 or more; raised when the shape changes

# or not configurable
RUN_CONFIGURATION = NOT_CONFIGURABLE   # tap_cares.NOT_CONFIGURABLE, a named constant
```

Registration (`register_collector`, `register_emitter`) refuses a class that declares neither, and one that declares both, with an error naming both choices. An undeclared class is never inferred to be either. A configurable class declares both `CONFIG_SCHEMA` and `CONFIG_SCHEMA_VERSION`. The declaration is all a not-configurable class says in code: its configuration's id and secret ref are in its plugin's seed (`req-tap-cares-runconfig-not-configurable`).

Registration also refuses a configurable class whose schema is not in the **form-safe subset**:

- it uses `anyOf`, `allOf`, `not`, `if` / `then` / `else`, `patternProperties`, `prefixItems`, or any `dependent*` keyword;
- it uses `oneOf` other than as a choice among objects each discriminated by a `const` on a property all the options share;
- it has a **secret-typed field**: a property marked `writeOnly: true` or `format: "password"`. A secret is never in a configuration (`req-tap-cares-runconfig-credential`).

Ordering and multiline hints (`order`, `multiline`) are allowed as annotations; they affect only how the form is drawn.

The subset exists so that one generic form can draw any component's settings. It follows the prior art of Airbyte's connector specification, which restricts JSON Schema to what its form renderer can draw and discriminates `oneOf` options by a constant.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-schema-1 | Declared In Code | Proposed | A class declaring `CONFIG_SCHEMA` without `CONFIG_SCHEMA_VERSION`, or the reverse, or a version that is not an integer of 1 or more, or a schema without `$id` or whose top-level type is not `object`, is refused at registration. | |
| req-tap-cares-runconfig-schema-2 | Form-Safe Subset Enforced | Proposed | Registration refuses each listed keyword, and a `oneOf` whose options are not all objects discriminated by a shared `const`; `order` and `multiline` are accepted. | |
| req-tap-cares-runconfig-schema-3 | No Secret-Typed Field | Proposed | Registration refuses a schema with a property marked `writeOnly: true` or `format: "password"`. | |
| req-tap-cares-runconfig-schema-4 | Exactly One Declaration | Proposed | A collector or emitter class declaring neither `CONFIG_SCHEMA` nor `RUN_CONFIGURATION = NOT_CONFIGURABLE` is refused at registration, and so is one declaring both; each error names both choices. | Undeclared is never inferred. |

## The Not-Configurable Configuration
----
RID: `req-tap-cares-runconfig-not-configurable`

Status: `Proposed`

**One path, one shape.** A component declaring `RUN_CONFIGURATION = NOT_CONFIGURABLE` ships its one configuration as a GRIFT seed in its own plugin: an author-minted UUIDv7, `configurability = not_configurable`, `settings = {}`, its `secret_ref` if it uses a secret, and a `CONFIGURES` edge that names the component through GRIFT's natural-key endpoint (`to_key`, `req-grid-import-grift-edge-endpoints`), for example `{"entity_type": "collector", "key": {"collector_registry": "zizmor:zizmor"}}`. `Collector` and `Emitter` declare natural keys on their registry keys for this (`req-tap-cares-collector-model-13`; `req-tap-cares-v0-emitter-4`), owner ruling 2026-11-25. A seed never names a component by entity id. It is imported at population under the plugin's program actor, like the plugin's other seeds.

Users never write it: `cares.configure` is refused on a `not_configurable` configuration, through the editor, the API, a boot profile or any GRIFT import other than its own plugin's seed. No second configuration may exist for that component. It changes only when its plugin ships a changed seed, and it is removed only by the plugin's seed (a GRIFT `deletes` entry) or with its component. Schedules, runs, jobs and batches use it exactly as they use any other configuration. A not-configurable emitter's seed never arms it (`req-tap-cares-runconfig-emitter-arming`).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-not-configurable-1 | Shipped As A Seed | Proposed | After population, a not-configurable collector or emitter has exactly the one configuration its plugin's seed declares, with that seed's UUIDv7, `configurability = not_configurable`, `settings = {}` and its `secret_ref`; a second boot writes nothing new. | |
| req-tap-cares-runconfig-not-configurable-2 | Users Never Write It | Proposed | An edit or delete of a `not_configurable` configuration through the editor, the API, a boot profile or another plugin's bundle is refused, even for an actor holding `cares.configure`. | |
| req-tap-cares-runconfig-not-configurable-3 | No Second Configuration | Proposed | Creating any further configuration for a not-configurable component is refused on every path. | |

## Configuration Seeds Checked Twice
----
RID: `req-tap-cares-runconfig-seed-guard`

Status: `Proposed`

The rule "exactly one `not_configurable` configuration per not-configurable component, none for a configurable one" and the rule "every schedule targets a real configuration" are enforced loudly at two points, and refused once more at run time.

- **Authoring time.** The `schedule-grift-targets` guard (`tap_cares/guards/schedule_grift.py`, today checking collector derived ids under `req-tap-cares-collector-model-10`) checks instead that every bundle `SCHEDULED_TARGET` resolves to a `RunConfiguration` seeded in a plugin bundle, or declared in a boot profile entry, that `CONFIGURES` a registered collector or emitter; that every seed's `CONFIGURES` natural-key endpoint resolves to a registered component; and that each `NOT_CONFIGURABLE` component has exactly one seeded `not_configurable` configuration while a configurable component has none.
- **Boot.** Population preflight refuses, before any grid write, a profile whose enabled plugins' seeds and profile entries break either rule, naming the component and the configurations.
- **Run.** A run of a component whose configurations contradict its declaration is refused, naming the component and the configuration.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-seed-guard-1 | Schedule Targets Resolve | Proposed | The guard fails a bundle `SCHEDULED_TARGET` whose uuid is not a `RunConfiguration` seeded in a plugin bundle or a boot profile entry, or whose configuration does not `CONFIGURES` a registered collector or emitter, or whose configuration `CONFIGURES` an emitter: no plugin bundle schedules an emitter, so an install never schedules a send (`req-tap-cares-v0-emitter-4`); an emitter schedule is an operator write under `cares.schedule_emitters`. | Replaces the derived-id check. |
| req-tap-cares-runconfig-seed-guard-2 | One Not-Configurable Seed | Proposed | The guard fails a `NOT_CONFIGURABLE` component with no seeded `not_configurable` configuration or with two, and a configurable component with any. | |
| req-tap-cares-runconfig-seed-guard-3 | Boot Refuses | Proposed | A profile whose enabled seeds break either rule aborts in preflight before any grid write, naming the component. | |
| req-tap-cares-runconfig-seed-guard-4 | Run Refuses | Proposed | A run of a component whose configurations contradict its declaration is refused before any write, naming the component and configuration. | |
| req-tap-cares-runconfig-seed-guard-5 | CONFIGURES Keys Resolve | Proposed | The guard fails a seed whose `CONFIGURES` endpoint is not a natural key, or whose `collector_registry` / `emitter_registry` names no registered collector or emitter. | |

## Switching Modes
----
RID: `req-tap-cares-runconfig-mode-switch`

Status: `Proposed`

A component moves from `NOT_CONFIGURABLE` to a `CONFIG_SCHEMA`, or back, in a plugin release. That release removes the old `not_configurable` seed (a GRIFT `deletes` entry) when it leaves `NOT_CONFIGURABLE`, and ships the new one when it enters it. Nothing follows on its own: a configuration whose `configurability` contradicts its component's current declaration refuses to run, naming itself and the declaration, and a schedule targeting it, or targeting a removed configuration, fails loudly at every due slot (a `failed` fire whose `summary` names the configuration) until someone retargets it. It never silently follows to a new configuration.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-mode-switch-1 | The Release Swaps The Seed | Proposed | A plugin release that changes a component's declaration removes the old `not_configurable` seed or ships the new one, and the guard (`req-tap-cares-runconfig-seed-guard-2`) passes on it. | |
| req-tap-cares-runconfig-mode-switch-2 | Contradiction Refuses To Run | Proposed | A `configurable` configuration of a component now `NOT_CONFIGURABLE`, or the reverse, refuses to run, naming itself and the declaration. | |
| req-tap-cares-runconfig-mode-switch-3 | Schedules Fail Loudly | Proposed | A schedule targeting a contradictory or removed configuration records a `failed` fire naming it at every due slot, starts no run, and is not retargeted by core. | |

## Validation At Save
----
RID: `req-tap-cares-runconfig-validation`

Status: `Proposed`

A write that would leave a configuration's settings invalid against its component's current `CONFIG_SCHEMA` is refused, whatever path it comes by: the editor, the API, a GRIFT import, or boot. The refusal names each failing field. On a valid write the service stamps `schema_id` and `schema_version` from the schema it validated against; a caller does not supply them. A `not_configurable` configuration accepts only `settings = {}` and only from its plugin's seed (`req-tap-cares-runconfig-not-configurable`).

The arming fields are not writable through this service (`req-tap-cares-runconfig-emitter-arming`).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-validation-1 | Refused On Every Path | Proposed | The same invalid settings are refused through the editor, the API, a GRIFT import and boot, and nothing is written. | |
| req-tap-cares-runconfig-validation-2 | Schema Stamp Derived | Proposed | After a valid write, `schema_id` and `schema_version` equal the component's current schema; values a caller supplies for them are ignored or refused, never stored. | |
| req-tap-cares-runconfig-validation-3 | Arming Fields Closed | Proposed | A write through the configuration service that changes any arming field is refused. | |

## Schema Evolution
----
RID: `req-tap-cares-runconfig-schema-migration`

Status: `Proposed`

When a configurable component raises `CONFIG_SCHEMA_VERSION`, it may ship migration functions, one per step, each taking the settings at one version and returning them at the next. They are pure: no grid read, no write, no I/O. When a run reads a configuration whose `schema_version` is lower than the component's current one, core applies the steps in order, validates the result against the current schema, and writes it as a new revision authored by the component's program actor, before the run goes on; the run records that new revision. The read and the migration happen inside the run-start snapshot (`req-tap-cares-runconfig-delivery`): the migration write carries `entity_expected_version` equal to the revision it migrated from, so a migration computed from a stale revision is refused rather than overwriting a newer edit, and of two workers racing to migrate the same revision exactly one write lands; the other re-reads and finds the configuration current.

A configuration is **invalid** when its settings fail the current schema, when it cannot be migrated (a missing step, a step that raises, a result that fails the schema), or when its `schema_version` is higher than the code's. An invalid configuration:

- refuses to run: the run ends `misconfigured` before any work (`req-tap-cares-runconfig-self-test`), and nothing is written but the job's own record;
- is flagged on its page (`req-tap-cares-runconfig-web`);
- never runs with unknown fields dropped or defaults silently filled.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-schema-migration-1 | Migrated As A New Revision | Proposed | A configuration at version 1 of a component now at version 2 with a 1→2 step is migrated when a run reads it; the new revision is authored by the component's program actor and the run records it. | |
| req-tap-cares-runconfig-schema-migration-2 | Unmigratable Is Invalid | Proposed | With no step, a step that raises, or a result failing the schema, the run ends `misconfigured`, writes no batch, and the configuration is unchanged. | |
| req-tap-cares-runconfig-schema-migration-3 | Never Run With Fields Dropped | Proposed | Settings carrying a field the current schema does not allow fail validation; no run strips the field and proceeds. | |
| req-tap-cares-runconfig-schema-migration-4 | Newer Than The Code | Proposed | A configuration whose `schema_version` is above the component's current version is invalid and is not rewritten. | A downgrade does not migrate backwards. |
| req-tap-cares-runconfig-schema-migration-5 | Migration Cannot Overwrite An Edit | Proposed | A migration whose `entity_expected_version` no longer matches the configuration's version is refused and writes nothing; an edit made between the read and the migration survives. | |

## Credential Reference And The Destination Rule
----
RID: `req-tap-cares-runconfig-credential`

Status: `Proposed`

A configuration names the envelope it uses by `scope:key` in `secret_ref`. It may name only an envelope of a kind its component declares: an emitter declares its kind with `SECRET_KIND` / `SECRET_SCHEMA` (`req-tap-cares-v0-emitter`); a collector declares the kinds its configurations may name, each with its data schema, in a `SECRET_KINDS` mapping on its class. A component that declares no kind has configurations with no `secret_ref`. A not-configurable component's `secret_ref` is written in its plugin's seed, where today's collectors hardcode a fixed `SecretRef` in code. At save, a malformed ref, or a ref to a loaded envelope whose kind the component does not declare, is refused; an envelope not loaded at save time is not refused there, because secrets are provisioned off-grid. At run start, the envelope must resolve, be of a declared kind and validate against that kind's schema (`require_secret_kind(data_schema=...)`, `req-tap-cares-secrets-validation`), or the run ends `misconfigured`. Secret rotation is unchanged: restart to rotate (`req-tap-cares-secrets-rotation`).

**The destination rule (strict).** Any setting that decides where a credential is sent stays in the secret envelope beside the credential, under the operator's file-system control, and never in a configuration. That covers, by name in today's plugins: API base URLs and hosts (`api_base_url`, `base_url`, `api_host`), TLS trust (`ca_bundle`, `ssl_verify`), an AWS assume-role `role_arn` (and its `role_session_name`, `duration_seconds`), and download mirrors; for an emitter, its destination (`req-tap-cares-v0-emitter-7`). A configuration holds only what to do and how: owner, repositories, regions, scope, limits, persona, selection. grype's and vuln_mosaic's mirror settings stay in their operator settings files (`tap_plugin/grype/settings.py`, `tap_plugin/vuln_mosaic/settings.py`), on purpose. The rule is a contract on the component's schema author, checked in review; core cannot tell from a schema what a field means.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-credential-1 | Ref Limited To Declared Kinds | Proposed | Saving a configuration whose `secret_ref` names a loaded envelope of a kind its component does not declare is refused; one of a declared kind is accepted. | |
| req-tap-cares-runconfig-credential-2 | Checked Again At Run Start | Proposed | A run whose configuration's envelope is missing, of an undeclared kind, or invalid against its kind's schema ends `misconfigured` and writes no batch. | |
| req-tap-cares-runconfig-credential-3 | Two Credentials, Two Configurations | Proposed | Two configurations of one configurable collector or emitter naming different envelopes each run with their own envelope. | Issue# 907 - tap reason 3. |
| req-tap-cares-runconfig-credential-4 | Destination Stays In The Envelope | Proposed | No `CONFIG_SCHEMA` in core or in a first-party plugin declares a field that decides where a credential is sent; such settings are read from the envelope. | Review contract; the listed fields are the known set. |

## Destination Deviation
----
RID: `req-tap-cares-runconfig-credential-deviation`

Status: `Backlog`

A mechanism for a deployment to deviate from the destination rule (`req-tap-cares-runconfig-credential`), for example letting a configuration choose among destinations an operator has approved. It is not designed here. When someone hits this pain point, that is the trigger to propose building it.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-credential-deviation-1 | Proposed On Demand | Backlog | A deviation mechanism is proposed when a real case needs one, and not before. | |

## Which Configuration A Run Uses
----
RID: `req-tap-cares-runconfig-selection`

Status: `Proposed`

- **Schedules.** Every `Schedule` targets one `RunConfiguration` through `SCHEDULED_TARGET`, by the configuration's uuid (amending `req-tap-cares-scheduler-edges`); a `SCHEDULED_TARGET` straight to a `Collector` or `Emitter` goes away. A schedule names only the configuration, never a revision or a code version, and carries no overrides of its own. The scheduler runs the component the configuration `CONFIGURES` with that configuration. A schedule on a contradictory or removed configuration fails loudly (`req-tap-cares-runconfig-mode-switch`).
- **Manual runs.** `run_collection(collector, *, run_configuration=None, ...)` and `run_emission(emitter, *, run_configuration=None, ...)` take the configuration to run. A component with exactly one configuration needs no choice: it is used. A component with several refuses a call that names none. A configuration that does not `CONFIGURES` the component is refused. A configurable component with no configuration cannot be run until one is created. Every run therefore has a configuration; a not-configurable component's is its seeded one.
- **No launch-time overrides.** Neither entry point, nor any caller, passes settings. Every run points at a stored revision.
- **Current revision only.** A run uses the configuration's revision current when it reads it (`req-tap-cares-runconfig-delivery`). Re-running means running that configuration again now. No run replays an old revision.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-selection-1 | Schedule Targets A Configuration | Proposed | A schedule whose `SCHEDULED_TARGET` is a `RunConfiguration` fires a run of the collector or emitter it configures, with it; a `SCHEDULED_TARGET` to a `Collector` or `Emitter` is refused; the `Schedule` has no settings, revision or version field. | |
| req-tap-cares-runconfig-selection-2 | One Configuration, No Choice | Proposed | `run_collection` and `run_emission` on a component with exactly one configuration (including a not-configurable one) use it; on a component with two and none named, or with none at all, they are refused before any write; a configuration of another component is refused. | |
| req-tap-cares-runconfig-selection-3 | No Overrides | Proposed | `run_collection`, `run_emission` and the scheduler accept no settings argument; a run's settings are exactly its recorded revision's. | |
| req-tap-cares-runconfig-selection-4 | No Replay | Proposed | No entry point accepts a revision number; a run started after an edit uses the edited revision. | |

## Delivery To Code
----
RID: `req-tap-cares-runconfig-delivery`

Status: `Proposed`

`CollectorConfig` and `EmitterConfig` stay frozen and JSON-safe and both gain the same four fields:

```python
@dataclass(frozen=True, slots=True)
class CollectorConfig:                         # EmitterConfig: emitter_entity_id, emission_job_entity_id
    collector_entity_id: UUID
    collection_job_entity_id: UUID
    run_configuration_entity_id: UUID          # never None: every run has a configuration
    run_configuration_revision: int
    settings: dict                             # validated (and migrated) settings; {} when not_configurable
    secret_ref: str                            # "" when the configuration names none
```

The task payload carries only the configuration's entity id. The task body (`run_collector`, `run_emitter`) reads the configuration fresh at run start, before any component code, as **one coherent snapshot**:

1. It reads the configuration under its row lock.
2. It applies any migration (`req-tap-cares-runconfig-schema-migration`) with `entity_expected_version`, so a stale migration cannot overwrite a newer edit.
3. It validates the snapshot, checks its envelope (`req-tap-cares-runconfig-credential`) and, for an emitter, evaluates arming (`req-tap-cares-runconfig-emitter-arming`), all against that same snapshot.
4. It records that exact revision on the job (`req-tap-cares-runconfig-traceability`) and builds the config object from it.
5. It releases the lock before any plugin code runs.

So the settings and `secret_ref` a component receives are exactly those of the revision its job records, and an edit that commits during the start lands as the next revision, for the next run. A settings change therefore takes effect on the next run with no restart; a change to the envelope's contents still needs one (`req-tap-cares-secrets-rotation`).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-delivery-1 | Config Carries The Configuration | Proposed | A collector's or emitter's `self.config` holds the configuration id, the revision read, the settings and the secret ref; the object is frozen and round-trips through JSON. | Amends `req-tap-cares-collector-config-6`. |
| req-tap-cares-runconfig-delivery-2 | Read At Run Start | Proposed | A configuration edited after a job is enqueued and before it starts is run at the edited revision, and the job records that revision. | |
| req-tap-cares-runconfig-delivery-3 | No Restart For Settings | Proposed | An edit to settings is seen by the next run in the same running process. | |
| req-tap-cares-runconfig-delivery-4 | Not Configurable, Same Shape | Proposed | A not-configurable component's run receives its seeded configuration's id and revision, `settings = {}` and the seed's secret ref; no run receives a null configuration id. | |
| req-tap-cares-runconfig-delivery-5 | Edit Racing A Run's Start | Proposed | With an edit committed concurrently with a run's start, the revision the job records retrieves from history exactly the settings and `secret_ref` the component received. | |
| req-tap-cares-runconfig-delivery-6 | Two Workers Racing A Migration | Proposed | Two runs starting together on a configuration that needs migrating produce exactly one migration revision, and an edit committed meanwhile is not lost. | |
| req-tap-cares-runconfig-delivery-7 | Lock Released Before Plugin Code | Proposed | No plugin hook runs while the configuration's row lock is held. | |

## The Four-Part Run Record
----
RID: `req-tap-cares-runconfig-traceability`

Status: `Proposed`

Every `CollectionJob` and `EmissionJob`, and every batch it writes, records four things:

| Part | On the job | On each batch it writes |
| --- | --- | --- |
| Configuration uuid | `run_configuration_id` (UUID, new) | `metadata.run_configuration.entity_id` |
| Configuration revision | `run_configuration_revision` (integer, new) | `metadata.run_configuration.revision` |
| Component uuid | the job's one inbound `HAS_COLLECTION_JOB` / `HAS_EMISSION_JOB` edge, written by `run_collection` / `run_emission` | the component's entity id in its identity key (`metadata.collector` or `metadata.emitter`) |
| Component code version | an emitter's `emitter_version` and `source_hash` with its build stamp (`req-tap-cares-v0-emitter-20`); a collector's build stamp (plugin slug, release, commit) and authored `COLLECTOR_VERSION` | the same, in the same key |

The task body writes the job's two new columns in the same write that moves the run to `RUNNING`, beside the code identity. The batch keys are written to every batch the run imports and to its lifecycle batch, by the same rules and with the same refusals that `req-tap-cares-collector-version` rules 6 to 8 give the `collector` key; `run_configuration` and `emitter` are reserved keys like it. Runs opened with `open_run` reach all four through their owner job (`req-tap-cares-run-node`). **The collector code-version half is Issue# 1307 - tap's ruled shape** (`req-tap-cares-collector-version`), built in the same collector pass as the cut-over; this spec states the record shape and does not re-specify it.

A node reaches the configuration it was written under the way it reaches the code version: from its spine pointers `last_changed_batch_id` or `last_observed_batch_id` (`req-grid-entity-batch-pointers`) to the batch, then to the run (`req-tap-cares-collector-version` rule 9), then to the configuration's history row at the recorded revision. A run-minted node reaches it through its `run_id` (`req-tap-cares-run-id`) and the run's owner job.

What is not added: no node gets a configuration field, no plugin table gets a column, and the run carries no hash of the configuration's content. The revision is the pin. The two job columns land in core's tables in the same version record as the collector-version fields, so core 0.5.0 migrates the fleet once.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-traceability-1 | Job Records Four Parts | Proposed | After every run, of a collector or an emitter, its job yields the configuration's entity id, the revision the task body read, the component's entity id and its code version. | |
| req-tap-cares-runconfig-traceability-2 | Every Batch Carries Them | Proposed | Every batch a run imports, and its lifecycle batch, has `metadata.run_configuration` with the id and revision and the component's identity key with its entity id and code version; a caller or a component's document that sets either key itself is refused. | Mirrors `req-tap-cares-collector-version-6`, `-7`. |
| req-tap-cares-runconfig-traceability-3 | Reached From A Row | Proposed | From a row a run's import last changed, a query reaches the configuration's history row at the revision that run used. | |
| req-tap-cares-runconfig-traceability-4 | Nothing On Nodes Or Plugin Tables | Proposed | No core or plugin node type gains a configuration field or column; plugin migrations are unchanged by this requirement. | Hard constraint for 0.5.0. |
| req-tap-cares-runconfig-traceability-5 | No Content Hash | Proposed | Neither the job nor the batch records a hash of the settings. | Owner ruling 2026-11-21, Issue# 907 - tap. |

## The Configuration Is The Observation Series
----
RID: `req-tap-cares-runconfig-series`

Status: `Proposed`

A run compares itself only with runs of the **same configuration**. Two configurations of one collector are two observation series: they may watch different accounts, regions or scopes, and neither run's absence of something says anything about what the other saw.

- **The previous run** of a collection is the most recently finished successful `CollectionJob` whose recorded configuration (`req-tap-cares-runconfig-traceability`) is this run's configuration and whose recorded revision carries this run's `secret_ref`, other than this run. Today `_previous_run` (`tap_cares/tasks.py`) walks `Collector --HAS_COLLECTION_JOB-->` and takes the collector's latest successful job; it becomes this lookup. Candidate derivation (`tap_grid/candidates.py`) compares scope, and derives `scope_withdrawn`, only against that run (`req-grid-reconcile-previous-run`).
- **Revisions of one configuration are one series.** An edit that narrows a configuration's scope is compared with the run before it and still produces `scope_withdrawn` candidates.
- **A new `secret_ref` starts a new series.** The series boundary is found from the record: a previous run counts only if the revision it recorded names the same `secret_ref` as this run's. Pointing a configuration at another account therefore has no previous run, and never proposes withdrawing what the old account saw.
- **All state carried from one run to the next is keyed the same way**, by configuration and within it by `secret_ref`, wherever core or a component keeps it.
- **Emitters.** Core keeps no previous-run comparison or carried state for an emitter: each run is new, retries live inside a run, and delivery identity is the emitter's own (`req-tap-cares-v0-emitter`). An emitter that keeps state of its own between runs keys it by configuration in the same way.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-series-1 | Previous Run Of The Same Configuration | Proposed | With two configurations of one collector, each run's previous run is the latest successful run of its own configuration, never the other's, whichever finished last. | |
| req-tap-cares-runconfig-series-2 | Edits Stay In The Series | Proposed | A run after a revision that narrowed the scope compares with the run before the edit and records `scope_withdrawn` candidates for what fell out of scope. | |
| req-tap-cares-runconfig-series-3 | New Credential, New Series | Proposed | A run after a revision that changed `secret_ref` has no previous run (`previous: null`) and records no `scope_withdrawn` candidate. | |
| req-tap-cares-runconfig-series-4 | Emitters Carry None | Proposed | No emission reads an earlier emission's record to decide what it does. | |

## Capabilities
----
RID: `req-tap-cares-runconfig-capabilities`

Status: `Proposed`

| Capability | Gates |
| --- | --- |
| `cares.configure` (new) | Creating, editing and deleting a `configurable` `RunConfiguration` of a collector or an emitter, and writing its `CONFIGURES` edge at creation (the edge is fixed after that, `req-tap-cares-runconfig-edge-3`); refused on a `not_configurable` one |
| `cares.run_collectors` (widened) | Running a collector with a chosen configuration, manually or as a self-test-only run |
| `cares.run_emitters` | Running an emitter with a chosen configuration (`req-tap-cares-v0-emitter-12`) |
| `cares.manage_schedules` (existing) | Writing a `SCHEDULED_TARGET` edge to a collector's configuration (create or retarget), and changing `cron_expression` or `max_active_runs` on such a schedule |
| `cares.toggle_schedules` (existing) | Enabling or disabling a schedule that targets a collector's configuration (pause and resume), separable from `cares.manage_schedules` so an incident responder can pause automation without creating it |
| `cares.schedule_emitters` | The same writes, enabling included, for an emitter's configuration (`req-tap-cares-v0-emitter-22`) |

All are grid-wide in v0. Because a configuration names its secret, `cares.configure` is in v0 equivalent to authority to use every loaded envelope of a kind any component declares: an actor holding it can bind a component to another account's credential, and with the matching run capability, run against it. Grant it only to actors trusted with every credential on the grid until the scoped grant lands. Grants scoped to one component or one configuration, and a per-credential "use" grant over which envelopes a configuration may name, belong to Issue# 1204 - tap (`req-tap-cares-runconfig-backlog`). The scheduling gates differ by kind on purpose: an emitter's schedule decides when data leaves the box. Collector schedules add no capability: the existing `cares.manage_schedules` and `cares.toggle_schedules` (`tap_auth/tap_auth.capabilities.json`; enforced at `tap_cares/services/scheduler.py`) gate a schedule targeting a collector's configuration. Today `cares.manage_schedules` gates `create_schedule` and `cares.toggle_schedules` gates `set_schedule_enabled`; this spec extends `cares.manage_schedules` to retargets and to edits of `cron_expression` or `max_active_runs`, mirroring the emitter gate (owner ruling 2026-11-25: no new gate beside two that already do the job).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-capabilities-1 | Configure Is Gated | Proposed | An actor without `cares.configure` is refused every write to a `configurable` `RunConfiguration` or its `CONFIGURES` edge; with it, the write proceeds to validation; with or without it, a write to a `not_configurable` one is refused. | |
| req-tap-cares-runconfig-capabilities-2 | Run A Chosen Configuration | Proposed | An actor with `cares.run_collectors` can run any configuration of any collector, and one with `cares.run_emitters` any configuration of any emitter; one without the capability cannot run any of that kind. | |
| req-tap-cares-runconfig-capabilities-3 | Scheduling A Collector Configuration | Proposed | A `SCHEDULED_TARGET` write to a collector's configuration, or a change to `cron_expression` or `max_active_runs` on such a schedule, is refused for an actor without `cares.manage_schedules`; enabling or disabling it is refused for an actor without `cares.toggle_schedules`. No new capability gates collector schedules. | |
| req-tap-cares-runconfig-capabilities-4 | Edits Are Ordinary Writes | Proposed | A configuration edit is recorded in history with its actor and batch like any other write; no separate audit batch is opened. | Emitter arming keeps its own audit batch. |
| req-tap-cares-runconfig-capabilities-5 | Configure Carries Credential Choice | Proposed | The capability's description in `tap_auth.capabilities.json` states that `cares.configure` lets its holder bind a component to any loaded envelope of a declared kind; an actor with `cares.configure` can set a configuration's `secret_ref` to any such envelope and no narrower grant exists in v0. | Scoped per-credential grant: Issue# 1204 - tap. |

## Readiness Takes The Configuration
----
RID: `req-tap-cares-runconfig-self-test`

Status: `Proposed`

Before any component code runs, the task body of either kind checks the configuration itself: it resolves, it `CONFIGURES` this component, its `configurability` agrees with the component's declaration, it is valid or migrates (`req-tap-cares-runconfig-schema-migration`), and its envelope resolves to a declared kind (`req-tap-cares-runconfig-credential`). Any failure ends the run `misconfigured` with a `RUN_CONFIGURATION_INVALID` reason and no batch: a collection job fails phase 1 by the standard failure mode (`req-tap-cares-collector-failure-mode`), and an emission closes `failed` with `failure_kind = misconfigured` before `emit` is called and with no attempt record.

A collector's self-test hook becomes `self_test(cls, config)`, receiving the same `CollectorConfig` the run will get; the no-argument form is dropped, since there is always a configuration. This retires the "single ambient configuration" of `req-tap-cares-collector-self-test-15`. An emitter has no core self-test hook today (it checks itself in `emit`, `req-tap-cares-v0-emitter`); if one is added it takes the configuration the same way.

Concurrency stays per component in v0 (`req-tap-cares-collector-concurrency`; per run type for emitters, `req-tap-cares-run-overlap`); per-configuration concurrency is Backlog.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-self-test-1 | Hook Takes The Config | Proposed | Every collector's `self_test(config)` is called with the run's `CollectorConfig`, configurable or not; no no-argument form remains on `CollectorBase`. | |
| req-tap-cares-runconfig-self-test-2 | Core Checks The Configuration First | Proposed | An invalid, unmigratable, contradictory or wrongly-targeted configuration, or one whose envelope does not resolve to a declared kind, ends a collection `misconfigured` with `RUN_CONFIGURATION_INVALID` without calling the hook; the job ends `FAILED` with no batch written. | |
| req-tap-cares-runconfig-self-test-3 | Emitter Twin | Proposed | An emission whose configuration fails the same checks closes `failed` with `failure_kind = misconfigured` and no attempt record. | |

## Emitter Arming Binds The Configuration
----
RID: `req-tap-cares-runconfig-emitter-arming`

Status: `Proposed`

This is where emitters and collectors really differ: an emitter's effect lands on someone else's system, so its configuration is armed by an operator before it sends (`req-tap-cares-v0-emitter`). Arming moves from the `Emitter` to the `RunConfiguration` (amending `req-tap-cares-v0-emitter-12`). `manage.py arm_emitter <run configuration entity id> --on|--off --as <username>` is the one writer of the configuration's arming fields, gated by `cares.arm_emitters` and written on a batch of its own whose metadata is the audit record, as today. Arming `--on` binds:

- the code identity: `EMITTER_VERSION` and `source_hash` (`armed_emitter_version`, `armed_source_hash`);
- the configuration revision (`armed_revision`): the revision the arm write itself produces, so the next write leaves it behind;
- the secret ref (`armed_secret_ref`).

At each run, any difference between the present and what was armed (version, source hash, revision, secret ref) makes the run a dry run with `dry_run_reason = arm_stale` until re-armed. Narrowing counts as a change; any change re-arms. An unarmed configuration's runs are dry runs with `dry_run_reason = unarmed`. Each configuration of one emitter is armed separately.

A not-configurable emitter's seeded configuration is armed the same way, by an operator. **Seeding never arms:** a seed that carries arming fields is refused, and a seed that changes a not-configurable configuration (a new `secret_ref`, say) makes a new revision and so leaves it `arm_stale`. A plugin may seed an emitter's `not_configurable` configuration; a configurable emitter's configurations are an operator's to create (editor, API or boot profile), never a plugin bundle's.

v0 has no `SIDE_EFFECTS` (`req-tap-cares-v0-emitter-1`, Retired). When Issue# 1371 - tap builds them, they are per configuration and arming binds them too; nothing here forecloses that.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-emitter-arming-1 | Arming Is Per Configuration | Proposed | Arming one configuration of an emitter leaves its other configurations unarmed; each sends only when itself armed and not stale. | |
| req-tap-cares-runconfig-emitter-arming-2 | Any Change Re-Arms | Proposed | After arming, an edit to the settings, a change of `secret_ref`, a migration revision, a changed seed, a changed `EMITTER_VERSION` or a changed `source_hash` each make the next run a dry run with `dry_run_reason = arm_stale`. | Precision over churn. |
| req-tap-cares-runconfig-emitter-arming-3 | One Writer | Proposed | Only `arm_emitter`, under `cares.arm_emitters`, writes the arming fields, on its own audit batch; the configuration service and every seed import refuse them. | Seeding never arms. |

## Web Surfaces
----
RID: `req-tap-cares-runconfig-web`

Status: `Proposed`

- **List.** A run configurations list: every configuration of every collector and emitter, with its component, name, description, configurability, schema version and whether it is valid.
- **Page.** A configuration page: its settings, its secret ref (the reference only, never envelope contents), its revision history, a flag when it is invalid, contradictory or awaits migration, and a table of the runs that used it with the revision each used. A `not_configurable` configuration is labelled "Not configurable", with a line saying the component runs without settings, and offers no edit.
- **Edit.** Create and edit through the generic editor (`spec-web-editor.md`): one generic `EditorDescriptor` builds a typed Django form from the component's `CONFIG_SCHEMA`, so the editor's typed-first rule holds and raw JSON stays the fallback (`req-web-editor-typed-4`). Save goes through the configuration service and shows its refusals per field.
- **Run.** On the CARES landing page a Run button per configuration replaces the per-collector Run button (amending `req-tap-cares-administrivia-manual-run`); the Self-test button sits beside a collector configuration's. A not-configurable component's row is its one configuration, labelled "Not configurable". Emitter Run controls are Backlog with the emitter table (`req-tap-cares-v0-emitter-14`); when they land they are per configuration too.
- **Job tables.** Each component's job tables, collection and emission, gain a configuration column linking to the configuration page at the revision the run used.

The pages are hosted by the Administrivia plugin (`req-tap-cares-administrivia-ownership`).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-web-1 | List And Page | Proposed | The list shows every configuration; its page shows settings, secret ref, revision history, validity and the runs that used it with their revisions; a `not_configurable` one reads "Not configurable", says the component runs without settings, and has no edit action. | |
| req-tap-cares-runconfig-web-2 | Generic Typed Form | Proposed | One `EditorDescriptor` renders a typed form for any form-safe `CONFIG_SCHEMA`, including a `const`-discriminated `oneOf`, and saves through the configuration service. | |
| req-tap-cares-runconfig-web-3 | Run Per Configuration | Proposed | The CARES landing page offers Run and Self-test per collector configuration and no per-collector Run; each calls `run_collection` with that configuration. | |
| req-tap-cares-runconfig-web-4 | Configuration Column | Proposed | Collection and emission job tables show the configuration and revision each run used. | |

## Boot Profile Configurations
----
RID: `req-tap-cares-runconfig-boot`

Status: `Proposed`

A boot profile may carry a top-level `configurations` section: a list of entries, each with its own author-minted UUIDv7 `entity_id` (`req-tap-cares-runconfig-model-4`), its component by registry key, and `name`, `description`, `settings` and an optional `secret` (`"scope:key"`). An entry is for a configurable collector or emitter; one for a not-configurable component is refused. Preflight validates every enabled entry offline (no network, in the container) against the component's `CONFIG_SCHEMA` before any grid mutation, and an entry's `secret` must resolve to the profile's `required_secrets` like a step's ref (`req-boot-required-secrets-3`). Apply creates or updates each configuration by its `entity_id` through the configuration service; an unchanged entry writes nothing. Each entry is applied before the first enabled `fire-collector` step of its component, or at the end of the population phase when none fires it, and it wins over a plugin-seeded configuration with the same `entity_id`. A `fire-collector` step names its `configuration` by `entity_id` when its collector has more than one.

A plugin may GRIFT-seed configurations in its seed bundles: default configurations of its configurable collectors, and the one `not_configurable` configuration of each of its not-configurable collectors and emitters (`req-tap-cares-runconfig-not-configurable`). It may not seed a configurable emitter's configuration (`req-tap-cares-runconfig-emitter-arming`). The checks on seeds are `req-tap-cares-runconfig-seed-guard`.

The `fire-collector` step's `secrets` field stays a list of strings (`tap_boot/schemas/boot.schema.json`).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-boot-1 | Offline Preflight | Proposed | A profile entry whose settings fail its component's `CONFIG_SCHEMA`, or that names a not-configurable component, aborts boot in preflight, before any grid write, naming the entry and field. | |
| req-tap-cares-runconfig-boot-2 | Idempotent Apply | Proposed | Booting the same profile twice writes each configuration once, under its `entity_id`; a changed entry writes one new revision. | `req-boot-idempotent`. |
| req-tap-cares-runconfig-boot-3 | Plugin Seeds | Proposed | A plugin seed bundle can create a configuration of its own configurable collector and the `not_configurable` configuration of its own not-configurable collector or emitter; a bundle configuration of a configurable emitter is refused. | |
| req-tap-cares-runconfig-boot-4 | Step Secrets Stay Strings | Proposed | The `fire-collector` step's `secrets` schema is unchanged; settings never appear on a step. | |

## Deferred Configuration Work
----
RID: `req-tap-cares-runconfig-backlog`

Status: `Backlog`

- **One-off run configurations.** A likely shape: clone a configuration, edit it, run it, and mark it temporary or one-off. Not designed.
- **Per-configuration concurrency.** v0 concurrency is per component (`req-tap-cares-runconfig-self-test`).
- **The configuration reference as a dimension.** The reference a run and its batches carry feels adjacent to a dimension (owner ruling 2026-11-25). It stays a standard column and metadata field for now; whether it should become one is open.
- **Scoped grants** (Issue# 1204 - tap): grants per component or per configuration, and a per-credential "use" grant.
- **A collector-side analogue of emitter arming**, and options such as no self-approval (the person who edits a configuration may not arm it) (Issue# 1204 - tap).
- **Per-configuration `SIDE_EFFECTS`** (Issue# 1371 - tap).
- **Staying on Issue# 907 - tap**, out of this spec: dimensions per collection; edge authority; the actor or role a run executes as (Issue# 1204 - tap); dangling-edge and rejection policy; reconcile authority fields, which stay on `Collector` (`req-tap-cares-collector-model-12`); file-based operator settings.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-runconfig-backlog-1 | Deferred Work Named | Backlog | Each item lands as its own requirement when a consumer needs it. | |

## Adoption

Moving each plugin onto run configurations (the cut-over) is separate work, one issue per plugin.

**First step: declare.** Every plugin, and core's in-repo test plugins (`grid_fixtures` and the `validation_sample` fixture, `tap_plugins/tests/fixtures/validation_sample`, first), adds a one-line declaration to each collector and emitter class, `RUN_CONFIGURATION = NOT_CONFIGURABLE` or its `CONFIG_SCHEMA`, and a not-configurable component's plugin ships its seed. Once core enforces `req-tap-cares-runconfig-schema-4` and `req-tap-cares-runconfig-seed-guard`, plugin CI goes red and boot refuses until each plugin declares. That is a deliberate, loud failure, not a regression to work around.

**Schedules.** Plugin schedule bundles that target a collector today retarget, as part of the cut-over, to the uuid of that collector's seeded configuration (a configurable default, or its `not_configurable` one).

What moves and what stays, under `req-tap-cares-runconfig-credential` (inventory read from the plugin repositories and their specs):

| Plugin | Moves to a configuration | Stays in the envelope or operator file |
| --- | --- | --- |
| aws_core | `regions` / `regions_allowed`, `partition`, `use_fips_endpoint`, `expected_account_id`, include / exclude types, `accounts_allowed`, `retire_within_selection`, findings budgets, Inspector and SSM compliance flags, `generate_credential_report` | Assume-role `role_arn`, `role_session_name`, `duration_seconds`; the credential |
| github_core | `owner`, `repos`, `initial_run_limit`; the SBOM collector's settings file beside its secret | `api_base_url`; the credential |
| qualys | `subscription`, `scope`, `sources`, `integrations`, `networks` | `api_host`, `ca_bundle`; the credential |
| anchore | `account`, `scope.*`, `inventory_max_age_hours`, `limits.*`, `create.*` | `base_url`, `ca_bundle`, `scheme`; the credential |
| tenable (spec only) | `network_name`, `scope`, `scan_result_window_days`, `feed_stale_days` | `base_url`, `ssl_verify`, `ca_bundle`; the credential |
| zizmor | `PERSONA`, today a constant (Issue# 310 - tap) | |
| compliance_core, fedramp_20x_vdr | `SEARCH_ENTITY_IDS`, today a constant | |
| grype, vuln_mosaic | | Mirror settings, in their operator settings files |

## Prior Art

- **Airbyte connector specification.** A JSON Schema subset its UI renders as a form, `oneOf` discriminated by a constant, `order` and `multiline` hints, and secrets marked in the schema. Borrowed: the subset and the hints. Changed: a secret-marked field is refused here rather than stored, because secrets never enter a configuration.
- **Airbyte attempts, SLSA provenance, Airflow 3 bundle versions** (surveyed on Issue# 907 - tap, 2026-11-21): the run points at the exact configuration it ran with. That is the id and revision on the job and the batch.
- **Meltano** keys incremental state by a state ID per pipeline, not per extractor; the series here is the configuration, not the collector.
- **Issue# 308 - tap.** zizmor's plugin-owned settings node, user-creatable on the `Schedule` precedent, is the shape this generalizes.
