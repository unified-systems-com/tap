# TAP Auth v0 Specification

## Philosophy

`tap_auth` is TAP's authentication and authorization management plane. It exists because actor identity and permission policy are platform-wide concerns, not graph primitives. `tap_grid` owns the graph/data substrate and service-layer operations; `tap_auth` owns who may perform those operations.

The core doctrine is:

> Authentication is surface-specific. Authorization is service-boundary enforcement. Every authenticated surface resolves to a named TAP actor; every TAP operation is authorized at the service boundary by `tap_auth`.

Human authentication starts with Django and django-allauth, with Google/OIDC as the first real provider path because the first customer signal points at Google Workspace and `example.com` is also Google-managed. Enterprise SAML remains a supported direction, but the first implementation should not force SAML before demand. Machine and AI actors are deliberately treated as named program users from the beginning so TAP never normalizes anonymous system work.

Authorization starts with Django groups and permissions as the backend substrate, but TAP exposes its own capability vocabulary. Django permissions are storage and evaluation machinery; TAP capabilities are the platform contract. V1 uses coarse operation-level capabilities, then later refines grid access by dimensions, delegation, and resource scope.

No `User=None` actor is permitted at the application/service boundary. If TAP did something, a named TAP actor did it.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Named Actors | Every TAP operation is attributable to a durable human or program actor. |
| 2. | Central Policy | Authorization decisions happen through one auditable `tap_auth` policy surface. |
| 3. | Django-Native | TAP uses Django users, groups, sessions, permissions, admin, and allauth instead of inventing parallel auth machinery. |
| 4. | Bootable | Auth providers, capabilities, protected groups, and initial admins are configured through boot profiles. |
| 5. | Evolvable | V1 supports coarse AuthZ while leaving clean seams for dimension-scoped access, service accounts, and AI delegation. |

## Roadmap Alignment

This spec supports `plan/road-rampart.md` active steps:

- `step-rampart-first-paid-assessment`: Robco deployment needs Google/Workspace-style login while allowing `example.com` access.
- `step-rampart-first-paying-customer`: AuthN is the first critical-path item before plugin refactor, boot loader, configuration, and subscription launch.

## Prior Art

This spec follows common patterns rather than inventing new auth machinery:

- Django's standard user/group/permission model is the authorization backend.
- django-allauth supplies account, social/OIDC, SAML, MFA, session, and provider integration machinery.
- Grafana and Kubernetes both separate subjects from roles/capabilities and evaluate access at operational boundaries.
- Auth0 and Keycloak both support multi-identity account linking, but warn that automatic linking can be dangerous; TAP reserves the schema shape but disables account linking in v1.
- Airflow connection testing and TAP CARES collector self-tests establish the "provider self-test" pattern: static checks plus optional live reachability checks.

## Supersedes

This spec supersedes the user/auth architecture previously parked under `tap_grid`:

- `tap_grid/specs/spec-grid-user-BACKLOG.md`
- `tap_grid/specs/spec-grid-user-saml-BACKLOG.md`
- user/auth portions of `tap_grid/specs/spec-grid-user-context-BACKLOG.md` remain relevant only where they describe user-scoped graph view context and should be migrated/reframed later.

`tap_grid` should no longer be treated as the owner of user architecture. `tap_grid` may depend on the configured Django `AUTH_USER_MODEL` generically and call the `tap_auth` policy gate, but provider details, login flows, users, groups, and authorization policy live in `tap_auth`.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-auth-app | [Auth App Ownership](#auth-app-ownership) | Implemented | `tap_auth` is the platform auth app and management plane; `/auth/` routes mounted, `/auth` reserved |
| req-tap-auth-user-model | [Canonical User Model](#canonical-user-model) | Proposed | Move canonical user from `tap_grid` to `tap_auth` |
| req-tap-auth-actor-model | [Named Actor Model](#named-actor-model) | Proposed | No service-boundary `User=None`; human/program actor kinds |
| req-tap-auth-builtins | [Protected Built-Ins](#protected-built-ins) | Proposed | Built-in users/groups use immutable natural keys |
| req-tap-auth-capabilities | [Capability Registry](#capability-registry) | Proposed | Declarative JSON file (schema-validated) hard-syncs to Django permissions |
| req-tap-auth-roles | [Role Definitions](#role-definitions) | Implemented | Roles (capability bundles) in a schema-validated JSON file; bootloader least-privilege guarded by test |
| req-tap-auth-program-users | [Program-User Definitions](#program-user-definitions) | Proposed | **Design/deferred.** Program-only-by-construction declarative file; humans operator-only |
| req-tap-auth-policy | [Policy API](#policy-api) | Proposed | One central `authorize()` API; typed errors; denial logging |
| req-tap-auth-service-boundary | [Service Boundary Enforcement](#service-boundary-enforcement) | Proposed | AuthZ at service boundary; AuthN at edges |
| req-tap-auth-boot | [Boot Profile Integration](#boot-profile-integration) | Implemented | Auth config is a boot-profile section with tap_auth-owned schema fragment; last-admin invariant + deploy gate |
| req-tap-auth-providers | [Provider Framework](#provider-framework) | Implemented | Provider-specific validation/self-tests/settings builders; `auth_selftest` command |
| req-tap-auth-google-oidc | [Google OIDC Provider](#google-oidc-provider) | Implemented | First provider type; allowed domains (hd); verified email; allowed_emails; discovery live check |
| req-tap-auth-local | [Local Password Auth](#local-password-auth) | Implemented | Dev/default recovery path; disable (both backends) separate from user deactivation |
| req-tap-auth-external-identity | [External Identity Linkage](#external-identity-linkage) | Implemented | Provider ID + subject; no v1 account linking; TAP social adapter enforces |
| req-tap-auth-sessions | [Session Invalidation](#session-invalidation) | Implemented | Global/per-user/per-session; capability-gated + audited; separate from disabling login |
| req-tap-auth-email-not-identity | [Email Is Not Identity](#email-is-not-identity) | Proposed | Express rule: email (mutable, non-unique, externally-controlled) is never a reliable key to identify/select/authorize a user; key off a stable internal id or `(provider, sub)`. Instantiates `spec-security-posture.md` `req-sec-email-not-identity` |
| req-tap-auth-user-lookup | [User Lookup (Roster Read)](#user-lookup-roster-read) | Proposed | `manage.py list-users` surfaces the stable internal user id that id-keyed write commands consume; defines the `--user-id`-authoritative / `--email`-fails-loud selector convention; read-scoped `auth.read_users` cap; JSON output for AI operators |
| req-tap-auth-deactivation | [User Deactivation](#user-deactivation) | Proposed | Method-agnostic disable regardless of auth method; `manage.py deactivate-user`; composes per-user session invalidation; runtime last-admin guard |
| req-tap-auth-logging | [Actor-Aware Logging](#actor-aware-logging) | Proposed | Stdlib contextvars/filter pattern; no structlog dependency |
| req-tap-auth-ai-placeholder | [AI And Machine Actor Placeholder](#ai-and-machine-actor-placeholder) | Proposed | AI actors are named program actors; delegation deferred |

---

### Auth App Ownership
----
RID: `req-tap-auth-app`  
Status: `Implemented`

`tap_auth` is a first-party Django app that owns TAP authentication, authorization, actor bootstrap, provider configuration, and policy enforcement. It is a platform capability, not a plugin.

#### Implementation

- `tap_auth` owns:
  - canonical user model
  - actor kind and built-in actor metadata
  - protected group metadata
  - TAP capability registry and sync
  - allauth integration and provider-specific modules
  - boot auth schema fragment and boot application logic
  - authorization policy functions and typed auth errors
  - auth-aware logging context helpers
- `tap_grid` owns graph/data mechanics and service operations. It calls `tap_auth.policy.authorize(...)`; it does not know about allauth, Google, SAML, provider secrets, login routes, or boot-profile auth internals.
- `tap_web`, `tap_api`, `tap_cares`, `tap_plugins`, `tap_viz`, and future `tap_ai` authenticate or resolve actors at their edge, then call service operations with actor context.
- `tap_auth` routes and adapters may mount under `/auth/`.
- `/auth` is reserved through the `reserved_url_prefixes` AppConfig registry (`tap_web/reserved.py`) — `tap_auth`'s AppConfig declares `reserved_url_prefixes = ["/auth"]`, and the interim `/auth` entry in `tap_web.reserved._PROJECT_RESERVED_PREFIXES` is removed so the reservation lives with its owner. This is the registry mechanism, not a hand-maintained slug list.
- `tap_web` may provide shared layout/components for auth UI, but `tap_auth` owns auth routes and logic.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-app-1 | Dedicated App | Implemented | TAP has a first-party `tap_auth` app for AuthN/AuthZ. | |
| req-tap-auth-app-2 | Grid Is Not Auth Owner | Implemented | User/provider/policy ownership is removed from `tap_grid` architecture. | |
| req-tap-auth-app-3 | `/auth/` Routes | Implemented | Auth routes mount under `/auth/` rather than allauth's default `/accounts/`. | |
| req-tap-auth-app-4 | Reserved `/auth` Prefix | Implemented | `tap_auth`'s AppConfig declares `reserved_url_prefixes = ["/auth"]` (the `tap_web/reserved.py` registry mechanism), and the interim `/auth` entry in `_PROJECT_RESERVED_PREFIXES` is removed so the reservation lives with its owner — Pages/plugins cannot create slugs under the auth prefix, mirroring `/admin`. | |

---

### Canonical User Model
----
RID: `req-tap-auth-user-model`  
Status: `Proposed`

`tap_auth.User` is TAP's canonical Django `AUTH_USER_MODEL`.

#### Implementation

- `tap_auth.User` subclasses Django `AbstractUser`.
- The existing `tap_grid.User` model is moved/superseded by `tap_auth.User`.
- Because TAP has no production customers yet, a clean destructive migration reset is acceptable and preferred over compatibility shims.
- Custom-user timing discipline (Django warns mid-project `AUTH_USER_MODEL` swaps are painful — it is treated as fixed at initial-migrations time). The destructive reset makes this clean *only if done correctly*: land `tap_auth.User` in `tap_auth`'s **first** migration, point `AUTH_USER_MODEL` at it from the start, and **audit every reference** — model FKs use `settings.AUTH_USER_MODEL` (never `ForeignKey("tap_grid.User")`), runtime code uses `get_user_model()` / `settings.AUTH_USER_MODEL`, and no direct import of the old `tap_grid.User` survives.
- `tap_auth.User` includes:
  - Django `AbstractUser` fields and behavior
  - `user_kind`: required enum, initially `human` or `program`; default `human`
  - `description`: backend-managed text field for operator/system context
  - `description_json`: backend-managed JSON field for structured context, especially program/AI actors
  - `is_tap_builtin`: boolean
  - `tap_builtin_key`: nullable immutable unique natural key for platform-managed actors
  - deactivation metadata: `deactivated_at`, `deactivated_reason`, and `deactivated_by_actor` or equivalent
- `tap_builtin_key` is TAP's immutable natural key for built-in actors, separate from display name/username.
- `CallerContext.user` references the configured Django auth user model generically, not `tap_grid.models.User`.

#### Development

The standard pattern behind `tap_builtin_key` is a natural key / system key: a stable identifier independent of DB primary keys and human-facing display fields. Django uses natural keys for objects whose database PKs are not portable; Django permissions use codenames for similar reasons.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-user-model-1 | User In tap_auth | Proposed | `AUTH_USER_MODEL` points to `tap_auth.User`. | |
| req-tap-auth-user-model-2 | AbstractUser | Proposed | The model subclasses `AbstractUser`. | |
| req-tap-auth-user-model-3 | Actor Fields | Proposed | User rows carry `user_kind`, `description`, `description_json`, `is_tap_builtin`, and `tap_builtin_key`. | |
| req-tap-auth-user-model-4 | Deactivation Metadata | Proposed | User deactivation records reason, time, and actor where applicable. | |
| req-tap-auth-user-model-5 | Generic CallerContext Type | Proposed | Grid caller context does not import a concrete `tap_auth.User` class. | |
| req-tap-auth-user-model-6 | First-Migration Timing | Proposed | `tap_auth.User` lands in `tap_auth`'s first migration; all references use `settings.AUTH_USER_MODEL`/`get_user_model()`, none import the old `tap_grid.User`. | |

---

### Named Actor Model
----
RID: `req-tap-auth-actor-model`  
Status: `Proposed`

Every meaningful TAP operation has a named actor. `User=None` is not valid at the application/service boundary.

#### Implementation

- Supported v1 user kinds:
  - `human`: a named actual person
  - `program`: a non-human actor such as a bootloader, test actor, service account, collector, scheduler, plugin runner, or AI actor
- The `program` kind subdivides by **ownership/origin**, expressed in v0 through the built-in key
  namespace rather than a separate `user_kind`:
  - **internal-app service actors** — owned by a native app (later, a plugin) and run with a
    *static* least-privilege bundle defined alongside the actor. Their built-in keys are namespaced
    `<owning-app>.<component>` (e.g. `tap_cares.collector`, `tap_cares.scheduler`); a native app's internal
    processes execute as this actor.
  - **delegated / AI actors** (future, `req-tap-auth-ai-placeholder`) — also `program`, but bounded
    *per-task by a delegator*, not a static app bundle. Static-bundle-vs-delegated-per-task is the
    real distinction; a separate `user_kind` is deferred until delegated actors exist and that
    distinction becomes load-bearing. Renaming `program` would mis-name this future class, so the
    kind stays `program` and ownership is carried by the namespace.
- `CallerContext.user` is mandatory for public service-layer operations.
- A missing actor raises a typed `missing_actor` error before the operation proceeds.
- Inactive actors raise typed authorization denial at the service boundary.
- Low-level migrations and raw table creation are below this contract; they do not define TAP authorization semantics.
- Tests must use named test actors/fixtures rather than `User=None`.
- The no-`User=None` contract is implemented in the **first** development round, not retrofitted later. It is a deliberate security stance: making "every operation has a named actor" a structural invariant from the start is far cheaper than paring out anonymous code paths after they have spread, and it underpins the later AI/delegation work where attribution is non-negotiable. Expect the change to touch nearly every service entry point at once — that breadth is the reason to do it first, not last.
- Sequencing constraint (chicken-and-egg): the named `program` built-in actors that system-initiated work runs as — bootloader, system, scheduler, collector/plugin runners (`req-tap-auth-builtins`) — are a **hard prerequisite** for enabling `missing_actor` enforcement. They must exist and be resolvable before, or in the same atomic step as, the enforcement flip; otherwise the first internal/system write bricks. Auth boot creates these actors early (`req-tap-auth-boot` ordering) precisely so the boundary always has a named actor to attribute system work to.
- **Binding a program actor into `CallerContext` — `acting_as` today, runner-bound tomorrow.** A no-request unit of work (a Django-Tasks worker body, a scheduler tick, a boot step) has no request middleware to populate `CallerContext.user`, so it binds its own resolved program actor at its entry boundary via `tap_auth.acting_as(actor)` — the no-request analogue of `CallerContextMiddleware` (set the context, restore the prior on exit so a reused worker thread cannot leak one task's actor into the next). `acting_as` is **not** a separate "sudo" mechanism: it constructs the same `CallerContext` and binds the same contextvar the middleware uses, and the save/restore is boundary hygiene identical to the middleware's per-request save/restore. **Backlog:** the cleaner end-state moves the bind out of application code into the **framework boundary** — the task runner establishes the program actor per task exactly as the middleware does per request, so a task only *declares* its actor and the runner binds it. That is gated on the task backend being cleanly hookable (the Steady Queue `takes_context` limitation noted in `spec-tap-cares-collector`); until then the one-line `acting_as` at task entry is the pragmatic boundary bind. `acting_as` then remains only for genuine identity *delegation* (the future AI-on-behalf-of-a-user case, `req-tap-auth-ai-placeholder`) — the one place a true temporary identity switch is warranted.
- `TAP_TEST_MODE` is the single, explicit signal that "this process is the test runner." Its scope is deliberately narrow:
  - default `False` in `tap.settings`; `True` only in `tap.test_settings`.
  - It is **independent of `DEBUG`**. `DEBUG=True` is the normal state of legitimate non-test instances (dev boxes, single-tenant deployments) and is itself a gate on `grid.purge`; it must never imply test mode. Keying test-only behavior on `DEBUG` would mint test-only artifacts into real instances.
  - Its only v1 effect is to gate the creation/sync of test-only built-ins — chiefly the `tap_test` actor (`req-tap-auth-builtins`). Any boot path that would create a test-only built-in refuses unless `TAP_TEST_MODE=True`.
  - Any non-test boot running with `TAP_TEST_MODE=True`, or any attempt to create `tap_test` without it, is a hard failure.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-actor-model-1 | No None Actor | Proposed | Service-boundary operations reject missing actors. | |
| req-tap-auth-actor-model-2 | Human Programmatic Split | Proposed | `human` and `program` are the initial actor kinds. | |
| req-tap-auth-actor-model-3 | Test Mode Separate | Proposed | `TAP_TEST_MODE` exists and is distinct from `DEBUG`. | |
| req-tap-auth-actor-model-4 | Inactive Denied | Proposed | Inactive actors are treated as authorization denials at the service boundary. | |

---

### Protected Built-Ins
----
RID: `req-tap-auth-builtins`  
Status: `Proposed`

TAP-managed built-in actors and groups are protected security objects, not ordinary user metadata.

#### Implementation

- V1 protected built-ins:
  - group: `tap_admin`
  - program actor: `tap_bootloader`
  - program actor: `tap_test`
- `tap_bootloader` is v1, **not future**: the boot spec runs *every* boot service-layer write as it (`spec-tap-boot-v0.md`, `req-boot-phases`), and the named-actor sequencing constraint ([Named Actor Model](#named-actor-model)) makes the system program actors a hard prerequisite for `missing_actor` enforcement. It is created/resolved in the boot `bootstrap` pre-phase and granted an explicit least-privilege boot-capability bundle (`req-tap-auth-capabilities`, `req-boot-phases`) — no `grid.purge`/`grid.delete` — not the full `tap_admin` set.
- Enforcement-coupled built-ins (promoted to v1 **in lockstep with the `missing_actor` enforcement flip**, not minted speculatively ahead of the enforcement that requires them) are **per-app-owned internal-app service actors**, named `<owning-app>.<component>` and granted a least-privilege bundle defined alongside the actor:
  - `tap_cares.collector` — the collector runtime (reads to resolve links; writes/imports collected batches). Was `tap_collector`.
  - `tap_cares.scheduler` — the scheduler (writes its own schedule/fire bookkeeping; triggers runs, which themselves execute as `tap_cares.collector`, not the scheduler). Was `tap_scheduler`.
  - `tap_bootloader` is owned by the boot app (`tap_boot`); it adopts the `tap_boot.*` namespace when the boot increment lands (left as-is until then to avoid churn ahead of that work).
  - A `tap_system` actor is added only if/when an unattended write path exists that is neither boot, scheduler, nor collector.
  In v0 these are declared **centrally in `tap_auth`** (the capability bundles) but are conceptually owned by their app; the interface for an app or plugin to **self-declare** its actors + bundle is Backlog (the per-app/plugin actor-declaration mechanism), exercised first by the plugin refactor. The existing built-in guards — immutable `tap_builtin_key`, hard-sync repair, protected metadata — already prevent a later declarant from impersonating, duplicating, deactivating, or acquiring an existing actor.
- Future built-ins may include:
  - AI actors.
- Built-in user keys are short stable values such as `tap_test`, not globally verbose strings.
- `tap_builtin_key`:
  - nullable for ordinary users
  - unique when non-null
  - set only by `tap_auth` bootstrap/sync code
  - immutable once set
  - required when `is_tap_builtin=True`
- Since Django `Group` is not custom by default, protected group metadata lives in a `tap_auth` table such as `ProtectedGroup` / `BuiltinGroup` with:
  - one-to-one relation to `auth.Group`
  - `builtin_key`
  - `is_protected`
- Protected groups/users cannot be renamed, deleted, deactivated, or repurposed by ordinary user-management paths.
- `tap_test`:
  - is a `program` actor
  - may be auto-created only when `TAP_TEST_MODE=True`
  - is illegal in ordinary customer boot unless a future explicit dev/test override is defined
  - should have both broad admin fixtures and narrower auth-sensitive fixtures available to tests

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-builtins-1 | tap_admin Protected | Proposed | The `tap_admin` group is protected by metadata and policy. | |
| req-tap-auth-builtins-2 | tap_test Protected | Proposed | `tap_test` is a protected program actor legal only in test mode. | |
| req-tap-auth-builtins-3 | Builtin Key Constraint | Proposed | DB/app constraints require built-in users to have immutable unique keys. | |
| req-tap-auth-builtins-4 | Admin Forms Block Protected Mutation | Proposed | Django admin and public forms cannot mutate protected fields or delete protected objects. | |
| req-tap-auth-builtins-5 | Bootloader Is v1 | Proposed | `tap_bootloader` is a v1 protected `program` built-in (boot writes run as it); the per-app-owned `tap_cares.collector`/`tap_cares.scheduler` (and any `tap_system`) actors are promoted in lockstep with the `missing_actor` enforcement flip. | |

---

### Capability Registry
----
RID: `req-tap-auth-capabilities`  
Status: `Proposed`

TAP capabilities are the public authorization vocabulary. Django permissions are the backend projection.

Code derives each name from the `*_CAPABILITY` constants in `tap_auth/capabilities.py` (validated
at import against the JSON registry), with one structural exception: `tap_grid/write_guard.py`
restates the four write-class names in its module-scope frozenset because `tap_auth.enforcement`
imports that module at module scope — tagged `TAP-KNOWN-DUPE(write-scope-caps)` at both sites
(specs/spec-tap-known-dupes.md).

#### Implementation

- Capability names use TAP vocabulary such as:
  - `grid.read`
  - `grid.discover` (introspect the type/schema catalog — reads the registry, not graph data; strictly less sensitive than `grid.read`. Gates the service discovery reads per `req-grid-service-gateway-gated`. Granted to `tap_admin` via `*`; deliberately not yet on `grid.read`-holding roles because v0 has no non-admin discovery consumer — relaxed on demand when a schema/AI surface needs it.)
  - `grid.write`
  - `grid.delete`
  - `grid.import_grift`
  - `grid.admin`
  - `grid.purge`
  - `auth.manage_users`
  - `auth.manage_providers`
  - `config.manage`
  - `plugins.manage`
  - `cares.run_collectors`
  - `ai.delegate`
- Capability checks are operation-level in v1, not model-level.
- The canonical registry lives in a **version-controlled declarative JSON file** (`tap_auth/tap_auth.capabilities.json`), reviewable in git — not buried in inline Python and not DB-only state. `tap_auth/capabilities.py` is a thin loader that reads + validates the file into the in-memory registry; the public Python API (`CAPABILITIES`, `get_capability`, `ALL_CAPABILITY_NAMES`, `codename_for`, the well-known `WRITE_/DELETE_/READ_CAPABILITY` constants enforcement imports) is unchanged.
- The file carries a **top-level `description`** stating what the file is and why it exists, plus, per capability, `name` / `description` / `risk` and an optional structured `description_json`. A mandatory `description` is a standing convention across all three authz config files (capabilities, roles, program-users) — config that grants authority must explain itself.
- **Descriptions flow into the table, not just the file.** `sync_capabilities` writes each capability's `description` **and** `description_json` onto its `Capability` row, so the running system is self-describing and DB-queryable — the context an AI/Paladin actor reads instead of guessing, and the surface against which a reviewer verifies the stated purpose matches the granted action. (`Capability.description_json` was added for this.)
- The file is validated against a **published JSON Schema** (`tap_auth/schemas/capabilities.schema.json`); a malformed file fails loud at load (`ImproperlyConfigured`), never a silent partial registry. `additionalProperties: false` and a name pattern catch typos and rogue fields.
- The DB projection is hard-synced from the canonical file-backed registry, which remains the source of truth.
- Composition is forward-compatible: the same file convention extends per-app/plugin later (`<app>/<app>.capabilities.json`, namespaced names) — see the per-app declaration backlog. v0 loads only `tap_auth`'s file.
- Capabilities are stored as a **real `tap_auth.Capability` table** (a managed model with its own table), not a `managed=False` placeholder. Each row carries the capability's public name, a human-readable `description`, and risk/classification metadata (flagging high-risk actions such as `grid.purge`). A backing Django `Permission` is projected from each `Capability` (the `Capability` model serves as the content-type home for those permission rows, or each `Capability` has a one-to-one `Permission`), so Groups still hold standard Django permissions while the capability metadata lives queryably in the DB.
  - Rationale (chosen 2026-06-12): a real table makes capability descriptions and risk metadata **queryable from the database / service layer**, which is the affordance a future AI/Paladin actor needs — it can be granted DB-level read or a gated service-layer query rather than code access. This matches TAP's declarative-shapes-over-code and satellite-agents-without-code-access direction; a code-only registry would force code access to answer "what does this capability mean / how risky is it." The `managed=False` placeholder approach (descriptions in code only) was considered and rejected for exactly this reason.
  - Threat posture: the `Capability` table holds capability *definitions* (name/description/risk), which are a **projection** of the code/spec registry and hard-synced at boot. Tampering with a definition row, or injecting a rogue capability, is therefore self-correcting and detectable — the next sync reverts it or hard-fails on undeclared drift (`req-tap-auth-capabilities`), and an unknown capability fails closed at runtime. So DB access to *this table specifically* buys little beyond breaking the system (a denial-of-service against authz, which fails closed), not silent privilege escalation. The sensitive runtime state is the **grants** — Group↔Permission and User↔Group membership — not the definitions; and raw DB write access to those is full compromise in any auth system (one could equally flip `is_superuser` or rewrite a password hash), so it is out of scope for this design rather than made worse by it. Read access to definitions is low-sensitivity by intent — queryability is the whole point.
- Public TAP vocabulary remains `grid.read`; the projected Django codename is an implementation detail such as `tap_auth.grid_read`.
- Every capability has a description, stored on its `Capability` row.
- `sync_capabilities()` or equivalent:
  - is explicit and security-critical
  - creates/updates/removes capability rows so DB exactly matches the registry
  - hard-fails on drift
  - hard-fails if asked to authorize an unknown capability at runtime
  - never prunes implicitly. Removing a capability (and its permission rows / group references) is destructive, and a lights-out boot cannot stop to ask for confirmation. Instead, pruning is **explicitly declared** in the boot/sync invocation: the operator — or an AI operator that prepared and validated the config against a staging instance — lists exactly which capabilities are expected to be removed. The sync then:
    - applies only the declared removals;
    - **hard-fails** on any undeclared drift — a capability present in the DB but absent from the registry and not in the declared prune list. It never silently deletes and never silently keeps.
    - **hard-fails** when a declared removal does not match reality (declared-but-not-present), so stale prune declarations are caught too.
  - This keeps standup fully lights-out while making every destructive change a precise, pre-declared, reviewable act. The failure is loud and machine-readable: the error names the exact undeclared-removal set so an AI operator can read it, add those entries to the prune declaration (or correct the registry), and re-run deterministically. We provide the precise path, document it, make the affordance easy to detect — and then demand precision.
- `tap_admin` receives explicit grants for all v1 capabilities; no hidden implication rules.
- Not every built-in actor gets the full set: the `tap_bootloader` program actor receives an explicit **least-privilege** boot-capability bundle (no `grid.purge`/`grid.delete`), not all capabilities, so a boot bug cannot demolish the grid. See `spec-tap-boot-v0.md` (`req-boot-phases`).
- Direct per-user grants are not part of the v1 TAP path. Group-assigned permissions are preferred.
- Plugin-declared capabilities are deferred until there is a real demand signal.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-capabilities-1 | TAP Vocabulary | Proposed | Specs/boot/policy use TAP names like `grid.read`, not Django storage names. | |
| req-tap-auth-capabilities-2 | Declarative File Registry | Implemented | The canonical capability registry is a version-controlled JSON file (`tap_auth/tap_auth.capabilities.json`), loaded by `capabilities.py`; not inline Python and not DB-only state. | |
| req-tap-auth-capabilities-3 | Hard Sync | Proposed | Capability sync makes the DB projection exactly match the registry. | |
| req-tap-auth-capabilities-4 | Descriptions Required | Implemented | Every capability includes a human-readable description; the file itself carries a top-level description. | |
| req-tap-auth-capabilities-5 | tap_admin Explicit Grants | Proposed | `tap_admin` is granted each capability explicitly. | |
| req-tap-auth-capabilities-6 | Unknown Capability Fails | Proposed | Runtime checks for unknown capabilities raise hard errors. | |
| req-tap-auth-capabilities-7 | Real Capability Table | Proposed | Capabilities are a real `tap_auth.Capability` table with DB-queryable description + risk metadata, projecting a Django `Permission`; not a `managed=False` placeholder. | |
| req-tap-auth-capabilities-8 | Schema-Validated File | Implemented | The capabilities file validates against a published JSON Schema; a malformed file fails loud at load. | |
| req-tap-auth-capabilities-9 | Descriptions Reach The Table | Implemented | `description` and `description_json` flow from the file onto the `Capability` row, so the registry is DB-queryable and self-describing. | |

---

### Role Definitions
----
RID: `req-tap-auth-roles`  
Status: `Implemented`

Roles are named, reusable capability bundles — the least-privilege capability set each protected group/built-in actor holds. A role is the grant path: `principal → role → capabilities`. Direct per-user capability grants are not a v1 path (`req-tap-auth-capabilities`).

#### Implementation

- Roles live in a **version-controlled declarative JSON file** (`tap_auth/tap_auth.roles.json`), validated against a published JSON Schema (`tap_auth/schemas/roles.schema.json`). This replaces the inline `*_BUNDLE` tuples formerly buried at the bottom of `capabilities.py`.
- The file carries a **top-level `description`** (what roles are, why they exist); each role carries a mandatory **`description`** (what the role is for and why it holds the caps it does) and an optional structured **`description_json`**. Mandatory descriptions are the standing convention across the authz config files.
- **Descriptions flow into the table.** `sync_protected_groups` hard-syncs each role's `description` and `description_json` onto its `ProtectedGroup` row (new fields added for this), so a group/role is self-describing and DB-queryable — same AI/security rationale as capabilities. The program-actor `User` rows are likewise made self-describing: `sync_builtin_actors` hard-syncs each built-in actor's `description` onto its `User` row (the actor descriptions are code-defined in v0 and move to the program-users file when it lands).
- Each role names either an explicit `capabilities` list or `"*"` (every defined capability). `"*"` is **reserved for `tap_admin`** and means "all capabilities, *including ones plugins add later*" — so a new plugin capability auto-flows to admin without editing `tap_auth.roles.json`, while non-admin roles must opt in explicitly.
- `sync_protected_groups()` grants each protected group exactly its role's capabilities (hard-sync), exactly as before — only the *source* of the bundle moves from code to the file.
- **Security invariants are guarded by tests, not just review** (roles are security boundaries; the schema + tests are the compensating controls for the bundle being data rather than typed code):
  - every capability named by a role must be a defined capability (no typos / rogue caps);
  - the `tap_bootloader` role **excludes `grid.purge` and `grid.delete`** (the least-privilege boot boundary, `spec-tap-boot-v0.md` `req-boot-phases`) and `ai.delegate`;
  - `"*"` is admin-only.
- **Every role declares `assignable_to`** — the principal classes it may be granted to: `"human"` (a person, via the deploy profile's `auth.initial_grants` login path), `"program"` (a built-in program actor bound in `sync.py`), or both. This makes the human/program boundary an explicit, mandatory, schema-validated property of each role rather than an implicit convention:
  - `tap_admin` is **both** — humans (initial admins/grants) and the test-only `tap_test` program actor.
  - `tap_viewer` (read-only, `grid.read` only — the least-privilege bundle for an invited guest/viewer) is **human-only**.
  - `tap_bootloader` / `tap_cares.*` are **program-only** — they can never be handed to a person by login config.
- The loader derives `HUMAN_ASSIGNABLE_ROLES` and `PROGRAM_ASSIGNABLE_ROLES` from the declarations. The boundary is enforced on **both** sides and guarded by tests:
  - **human side** — the `auth.initial_grants` role enum (auth-boot-section schema) is held in sync with `HUMAN_ASSIGNABLE_ROLES`; boot additionally fails loud if a grant names a non-human role (defense against schema/registry drift); and the social adapter refuses to apply a non-human-assignable role even if one leaks into the effective map at runtime.
  - **program side** — `_ensure_program_actor` refuses to bind an actor to a group whose role is not `assignable_to "program"` (so a program actor can't be bound to `tap_viewer`).
- **Layering note:** in v0 the `tap_cares.collector` / `tap_cares.scheduler` roles still live in `tap_auth`'s `tap_auth.roles.json` (their historical placement). Re-homing them so `tap_cares` ships its own roles is the per-app split — deferred with the per-app/plugin declaration mechanism (Backlog). Moving the bundles to a file now fixes the buried-in-code smell; the ownership/layering fix lands with that split.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-roles-1 | Declarative File | Implemented | Roles are a schema-validated JSON file, not inline code. | |
| req-tap-auth-roles-2 | Descriptions Required | Implemented | Top-level file description and a per-role description are mandatory. | |
| req-tap-auth-roles-3 | Defined Caps Only | Implemented | Every role capability is a defined capability; guarded by test. | |
| req-tap-auth-roles-4 | Bootloader Least-Privilege | Implemented | The `tap_bootloader` role excludes `grid.purge`/`grid.delete` (and `ai.delegate`); guarded by test. | |
| req-tap-auth-roles-5 | Role-Mediated Grants | Implemented | Principals receive capabilities via roles, not direct per-user grants. | |
| req-tap-auth-roles-6 | Descriptions Reach The Table | Implemented | A role's `description`/`description_json` hard-sync onto its `ProtectedGroup` row; built-in program actors' descriptions hard-sync onto their `User` rows. | |
| req-tap-auth-roles-7 | Principal-Class Declared | Implemented | Every role declares a mandatory, non-empty `assignable_to` (`human`/`program`/both). The loader exposes `HUMAN_ASSIGNABLE_ROLES`/`PROGRAM_ASSIGNABLE_ROLES`; guarded by test. | |
| req-tap-auth-roles-8 | Assignment Boundary Enforced | Implemented | A program-only role can never be granted to a person (schema enum in sync with the human set + boot validation + adapter refusal), and a human-only role can never be bound to a program actor (`_ensure_program_actor` guard). | |
| req-tap-auth-roles-9 | Viewer Role | Implemented | `tap_viewer` is a human-only read-only role (`grid.read`), the least-privilege bundle for an invited guest/viewer. | |

---

### Program-User Definitions
----
RID: `req-tap-auth-program-users`  
Status: `Proposed`

> **Design only — deferred** to the per-app/plugin actor-declaration pass (Backlog). The shape is ratified here so it is built right when its consumer (the plugin refactor) arrives; v0 still defines program actors via `sync_builtin_actors()` (`req-tap-auth-builtins`).

Program users (program-kind actors: `tap_bootloader`, `tap_cares.scheduler`, `tap_cares.collector`, plugin service accounts, AI actors) are defined declaratively in a **program-only file**.

#### Implementation

- Program users live in a declarative JSON file (`<app>/program-users.json`), validated against a schema, with a mandatory **top-level `description`** and a mandatory **per-entry `description`**; each entry maps a program-user `key` to its `role(s)` (capabilities flow via roles).
- **Program-only by construction (the load-bearing guardrail).** The file type's *only* ingest path constructs program users (`user_kind=program`). There is **no `kind` field and no code path from this file to a human user** — the human-creation capability does not exist in this path. This is the structural form of the human-introduction rule below: you cannot misuse what isn't there, so there is nothing to police per-plugin.
- **Human-introduction rule.** *Plugins extend what the system can do; the operator decides who may use it.* Human `User`s may be introduced only from **operator-controlled sources** — the instance boot profile and, later, the authN/IdP path — never from a plugin or any declarative program-user file. Programmatic human creation beyond the operator's bootstrap admin is parked until a real demand signal; the lone human bootstrap today is the operator's env-driven initial admin (`req-tap-auth-boot`), deliberately separate. A future external-identity plugin (e.g. Google Workspace) models people as grid data or provisions logins *through* authN — it does not mint `User` rows.
- This file is the declarative home that eventually replaces `sync_builtin_actors()`' hardcoded program-actor wiring, and the mechanism by which a plugin self-declares its own program/service actors. The existing built-in guards (immutable `tap_builtin_key`, hard-sync repair, protected metadata — `req-tap-auth-builtins`) still prevent a declarant from impersonating, duplicating, or acquiring an existing actor.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-program-users-1 | Program-Only By Construction | Proposed | The file's only ingest path creates program users; no human can be produced from it (no `kind` field, no human code path). | |
| req-tap-auth-program-users-2 | Schema + Descriptions | Proposed | Schema-validated; top-level and per-entry `description` mandatory. | |
| req-tap-auth-program-users-3 | Role-Mapped | Proposed | Each program user maps to role(s); capabilities flow via roles. | |
| req-tap-auth-program-users-4 | Humans Operator-Only | Proposed | Human users come only from operator sources (boot profile / authN), never a plugin or declarative program-user file. | |

---

### Policy API
----
RID: `req-tap-auth-policy`  
Status: `Proposed`

All authorization decisions flow through a central `tap_auth` policy API.

#### Implementation

- `tap_auth.policy.authorize(...)` is the primary API.
- It checks one capability per call.
- It accepts operation/resource metadata for logging and future policy refinement:

```python
authorize(
    caller_context,
    "grid.write",
    operation="create_node",
    resource_type="grid.node",
    resource=None,
)
```

- It returns `None` on allow.
- It raises typed exceptions on denial/error:
  - `missing_actor`
  - `inactive_actor`
  - `unknown_capability`
  - `capability_denied`
  - `actor_kind_not_allowed`
- Exceptions live in `tap_auth.errors`.
- API/web layers translate denials to 403 or appropriate user-facing pages.
- **Defect-class errors are a separate category from denials.** The on-by-default backstop (`req-tap-auth-policy` On By Default) raises a distinct `unguarded_operation` error when a mutation or Gryphon/Search read reaches its commit/return point and the active actor does **not** hold the capability that operation requires — which also means no `@requires_capability` gate caught it earlier, since a gated path would have denied at the decorator. This is **not** an authorization denial — it is a code-level flaw (an ungated path reached by an unauthorized or actorless caller), and the two must never be conflated:
  - it is classified as an internal defect, surfaced as a 500-class error (not a user-facing 403), because no policy decision was reached — the system itself is mis-wired;
  - it is logged at a loud, unambiguous level (ERROR/CRITICAL) with the unguarded callsite, deliberately distinct from routine denial logs, so it stands out in telemetry;
  - it is exactly the class of signal a deployed field instance must route back for investigation and patching. A clear, dedicated alert type is the first step in that loop and feeds the Paladin observe-and-report foundation. If the existing error taxonomy has no home for "internal security-wiring defect," `unguarded_operation` is it — `tap_auth.errors` owns the category.
  - `unguarded_operation` is the **first concrete `code` Flaw** under `spec-tap-flaw-v0.md`: emitted with `flaw_class=code`, `flaw_tags=[security]`, handled fail-closed-and-continue. The general Flaw mechanism (taxonomy, structured emission, routing axes) is specified there; this requirement is one instance of it, not a parallel mechanism.
- `is_superuser` may continue to own Django admin behavior, but TAP service authorization requires explicit TAP capabilities. `is_superuser=True` is not a TAP app/service bypass.
- `tap_admin` is required for TAP admin authorization even when `is_superuser=True`.
- Django admin's native "superuser sees/does everything" is left intact **by design** — it is the deliberate bottom turtle: the break-glass recovery floor beneath TAP's own authorization. There must always be something under the last turtle. TAP therefore runs two authorization universes on purpose: (1) Django admin, where `is_superuser` is god and operator recovery happens; (2) the TAP service boundary, where only explicit capabilities + `tap_admin` grant access and `is_superuser` means nothing. TAP does **not** attempt to neuter the superuser bypass inside Django admin/DRF — doing so would remove the recovery floor and fight the framework. This split is intentional and documented, not an inconsistency.
- **The recovery floor must stay reachable.** Django-admin-superuser-is-god only helps if an operator can actually reach a login, and local password auth can be disabled everywhere *including admin* (`req-tap-auth-local`) — so the *stated* Django-admin floor can itself be configured away (if external IdP is simultaneously broken, there is no way in). The real bottom turtle in v0 is therefore **host/container shell + management-command access**: an operator with shell can always re-enable local auth, mint a superuser, or reset a password out-of-band. v0/v1 single-tenant deployments are operated with exactly that access, so it is the dependable floor. The standing invariant is that no boot/config may converge to *no reachable admin path* — a live Django-admin login **or** out-of-band management-command access must always remain. `emergency_only` local auth (Backlog) is the promotion path the moment a genuinely no-shell-access customer deployment is real; it is the floor for that future shape, not needed while the operator holds the shell.
  > **Reconciliation (2026-07-07):** for **passwordless-primary** deployments, `spec-tap-auth-passkey-v0.md` (`req-tap-auth-passkey-recovery`) makes shell the *sole* floor explicit: passwords retire including admin, and unauthenticated `/admin/` is fronted by the passkey login rather than a password form. The two-universes split above is unchanged in capability (superuser is still god *inside* admin, `policy.can` still ignores `is_superuser` at the service boundary) — only the *credential* to reach an admin session changes from password to passkey-or-shell. This supersedes the "live Django-admin password login" half of the reachable-floor invariant, re-founding it wholly on out-of-band `manage.py` access.
- Denied decisions are logged from day one with structured `message_data` including:
  - actor
  - actor kind
  - requested capability
  - operation
  - resource type/resource identifier where safe
  - reason code
- Authorization is **on-by-default**, not opt-in. A service operation that completes without having called `authorize()` for the capability it needs is a defect, and the system is built to make that defect loud rather than silent:
  - the coarse v1 capabilities attach via a `@requires_capability(...)` decorator on public service functions (resolving `CallerContext` from the explicit argument), so the default state of a newly-written service function is "guarded", not "open";
  - the write pipeline re-checks, at the commit chokepoint, that the active actor holds the capability the batch's operations require (`grid.write` for creates/updates, `grid.delete` for deletes) via a stateless `policy.can(actor, cap)` lookup — independent defense-in-depth, **not** a record of whether `authorize()` ran; an operation that reaches a write commit with an actor lacking the required capability (or with no actor at all) **fails closed in every mode** — the mutation does not commit. **Security behavior never depends on test mode.** `TAP_TEST_MODE` only raises the volume: it escalates the fail-closed into a hard error that surfaces the unguarded callsite for CI, whereas production fails closed and logs. This is the Oso-style "authorize-can-be-forgotten" backstop: the gate is enforced structurally, not by reviewer vigilance.
  - reads get the same structural backstop at their guaranteed chokepoint. Search is TAP's canonical graph read interface (`req-grid-search-canonical-read`), and it dispatches to one of three execution modes — `orm`, `gryphon`, and `module`. The read backstop is implemented at the **single dispatch point above those three modes**, not inside any one of them: the assertion sits at the top of the read decision tree so all three modes are covered by one gate. A read that reaches mode dispatch with an active actor that does not hold `grid.read` (a stateless `policy.can(actor, "grid.read")` re-check) **fails closed in every mode** — it does not return data; `TAP_TEST_MODE` adds the hard-error-with-callsite diagnostic on top, it does not gate the enforcement. Putting the gate at that one dispatch point gives reads the same "you cannot read without authorizing" guarantee the write pipeline gives mutations, without scattering checks across orm/gryphon/module or across callsites. The remaining direct read endpoints that still bypass Search today (e.g. the entities/edges API list/get routers) either carry the `@requires_capability("grid.read")` decorator or migrate onto the Search dispatch chokepoint as the canonical-read enforcement work lands; until then the decorator is their interim guard.
- **The backstop is stateless — no decision ledger.** An earlier draft implemented this with a contextvar *decision ledger* that recorded each `authorize()` call so the backstop could check whether one had happened; that mechanism is **removed** (it leaked across requests/threads and added scope machinery for no v1 benefit). In capability-only v1, "did we authorize this operation?" and "does the actor hold the capability?" are the same question, so the backstop is a direct `policy.can(actor, needed_cap)` re-check — simpler, genuinely independent defense-in-depth, and with no ambient per-request state to leak. The one case a direct re-check cannot catch — a forgotten gate reached by an actor who *does* hold the capability (a pipeline-skip, not a privilege escalation) — is covered two ways: (a) when the backstop *does* trip it raises with the full stack trace (`stack_info=True`) pinpointing the ungated callsite, so the path is captured **lazily at the failure**, not tracked as bookkeeping on every well-behaved request; and (b) a build-time **static authz-coverage lint** (`req-tap-auth-policy-9`) flags any service-layer write/read sink whose enclosing function lacks a `@requires_capability`/`authorized()` gate, for any actor. Build-time lint catches the ungated path for any actor; the runtime backstop catches the unauthorized/actorless path with the map. The two compose; neither needs a ledger.
- A boolean `can(caller_context, capability, ...)` predicate complements `authorize()`: same evaluation, but returns `True`/`False` instead of raising — for non-enforcement uses such as hiding a UI control or branching, so read-only checks never have to `try/except` the raising gate. `can()` is never a substitute for the enforcing `authorize()` at a mutation boundary.
- Successful authorization decisions are not logged individually in v1 except through the operation's own logs/audit trail.
- **Landed: the INTERNAL_ONLY write bypass is program-actor-only.** The trusted-internal `_internal_only_bypass` that writes INTERNAL_ONLY node types (the public path rejects them) now asserts the acting actor is a `program` actor (`assert_program_actor`) at the `write_batch` chokepoint; a human — or no actor — reaching it fails closed as `unguarded_operation`. This makes INTERNAL_ONLY a real structural property (no human path can write one by any route) rather than code discipline, and is the first **actor-shaped** (not just capability-shaped) backstop.
- **Landed: the ORM read backstop (`req-tap-auth-orm-read-backstop`).** The read backstops above (`assert_read_authorized`, the write pipeline's re-check) guard code that goes *through* the service layer. A read that reaches TAP-managed rows *below* it — a web view or API route that queries the Django ORM directly without authorizing `grid.read` — was the entire class of the 2026-06-30 codex-security scan findings (generic panel fragment, page/nav routes, entity-type catalog; all `<Model>.objects...` with no gate). That class is now structurally caught at the ORM itself, in two layers sharing one capability predicate (`tap_grid/read_guard.py`): **Layer 1** overrides `BaseModelQuerySet._fetch_all`, so every materialization of a TAP-managed queryset (`.get`/`.first`/iteration/`list`/`values`) re-checks `grid.read` — covering every `BaseModel` subclass, including `Edge`, through the one shared QuerySet; **Layer 2** attaches a `connection.execute_wrapper` via `connection_created`, catching the reads `_fetch_all` cannot see (`.count`/`.exists`/`.aggregate`/`.raw`/cursor) and the non-`BaseModel` `EntityType` catalog table. Same fail-closed semantics as the other backstops: a context that lacks `grid.read` raises `unguarded_operation` with the offending model/statement. Two sanctioned exemptions keep it usable: the `unguarded_read()` context manager (explicit escape hatch for admin / management commands / low-level model tests) and the **context-less infrastructure zone** — when no `CallerContext` is bound at all (migrations / `manage.py shell`), the guard allows, because a real request always carries a context (CallerContextMiddleware binds one for every request, `user=None` for anonymous) and every service op sets one, so the finding class is always caught while migrations and the shell stay usable. This makes the **read half** of `req-tap-auth-policy-9` Rule B a runtime guarantee rather than a build-time lint aspiration; the write-sink half and the "forgotten gate reached by a privileged actor" case remain for the lint / approval-ledger work below. Named open edges: `Entity` reads (separate manager, pervasive below the boundary, and the Entity API already carries its own gate) and the ctx-None zone are deliberately not covered here. The guarded-table set itself is not derived in this module: it comes from the shared grid-table classification (`req-grid-table-classification.sec`, `spec-grid-security.md`), the same single source the search-role DB grant consumes — including the pinned relationship that the grant set is exactly the guarded set plus `Entity`'s table.
- **Landed: the ORM write backstop (`req-tap-auth-write-batch-routing`).** The write-side twin of the read backstop, enforcing the standing rule that *every* node/edge mutation routes through the service layer (`write_batch` / `create_node` / `create_edge` / `delete_*` / `purge_node` / `patch_node`) so it carries batch scope, FLIP, provenance, and the `grid.write`/`grid.delete`/`grid.purge` gate. The prior backstops only fired at the `write_batch` commit chokepoint; a direct `instance.save()` / `Model.objects.create()` / `entity.delete()` from a view, panel, editor descriptor, collector, or command bypassed it entirely — the write-side analog of the read findings, and found live in `table_panel.handle_save` and the LOTR editor descriptor. It is now a runtime invariant (`tap_grid/write_guard.py`). Unlike the read backstop (capability-based), this guard is **scope-based**: a node/edge write is permitted only inside a *service-layer write scope*, a contextvar opened by the sanctioned write API. `requires_capability` / `authorized` open the scope for their body whenever the authorized capability is write-class (`grid.write` / `grid.delete` / `grid.purge` / `grid.import_grift`), so every gated service write function — create, update, delete, purge, import — opens it by construction, now and in future; `write_batch` opens it directly. `BaseModel.save`/`delete` and `Entity.save`/`delete` call `enforce_service_write`, which fails closed (`unguarded_operation`) for any write outside a scope. Exemptions: the `unguarded_write()` hatch (admin/infra, and every non-guard test wraps itself in it — tests are the sanctioned below-service write zone) and migrations (models reconstructed in migrations carry no override, so historical `RunPython` writes are unaffected). This makes the **write half** of `req-tap-auth-policy-9` Rule B a runtime guarantee. Named open edge: queryset-level bulk writes (`Model.objects.filter(...).update()/.delete()`) bypass the instance `save`/`delete` hooks, so they are caught by the *static* direct-write lint (`tap/direct_write_coverage.py`), not the runtime guard — the two compose (runtime catches instance writes the static tool cannot resolve; static catches queryset writes the runtime guard cannot see).

##### Backlog — runtime path to retiring the coverage lint (`req-tap-auth-policy-9`)

The coverage lint exists only because the stateless backstop cannot distinguish "reached this sink through a gate" from "reached it by accident as a privileged actor." Two composable **runtime** mechanisms would close that gap and let the lint retire marker-by-marker (runtime guards are preferable to a build-time lint — structural, unbypassable, fail-closed):

- **Context-scoped approval ledger (`req-tap-auth-policy-8` revisited).** Restore the removed ledger's *intent* — record which capabilities were authorized on this execution path — but carry the approval set **on the `CallerContext` itself**, not a separate contextvar. Its lifetime then equals the context's (replaced per request / `acting_as` block / task), so it cannot leak — which was the *only* reason the original ledger was removed. The failure mode flips to safe: a missed *propagation* fails **closed** (over-deny), where the old missed *reset* failed **open** (leak). The backstop then checks "was this cap approved on this path," catching a forgotten gate at runtime. **Crux to settle first:** what records an approval for the identity-bound program paths — `acting_as` granting implicit bundle approval (cheap, but doesn't catch a forgotten gate *inside* the block) vs. explicit `authorized()` blocks on those paths (stronger, more migration). Needs a mutable approval set on the frozen `CallerContext` (shallow-freeze) and a broadened backstop ("holds" → "holds-and-approved").
- **Per-entity-type creation capabilities.** Make "privileged" granular — which entity *types* an actor may create — so a forgotten gate reached by the wrong actor lacks that type's specific capability and the existing "holds the cap" backstop denies it. A model expansion (more capabilities + a type→cap map) worth doing for least-privilege on its own; lint-retirement is the bonus. Composes with the approval ledger and generalizes the just-landed program-actor guard from "any program actor" to "the actor that owns this type."

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-policy-1 | Single API | Proposed | Authorization callers use `tap_auth.policy.authorize(...)`. | |
| req-tap-auth-policy-2 | One Capability | Proposed | Each policy check evaluates exactly one required capability. | |
| req-tap-auth-policy-3 | Typed Errors | Proposed | Denials/errors raise typed `tap_auth.errors` exceptions. | |
| req-tap-auth-policy-4 | Denial Logs | Proposed | Denials emit structured security logs. | |
| req-tap-auth-policy-5 | No Superuser Bypass | Proposed | TAP service AuthZ does not treat Django `is_superuser` as a bypass. | |
| req-tap-auth-policy-6 | Admin Recovery Floor | Proposed | Django admin's superuser-is-god behavior is intentionally preserved as the break-glass recovery floor; TAP does not neuter it. The floor must stay *reachable* — since local auth can be disabled including admin, the dependable v0 floor is out-of-band shell/management-command access, and no boot/config may converge to no reachable admin path. | |
| req-tap-auth-policy-7 | On By Default | Proposed | Service mutations and Gryphon/Search reads are structurally enforced: an operation that reaches commit/return with an actor lacking the required capability (or no actor) fails closed **in every mode** as an `unguarded_operation` defect (test mode only adds diagnostics). A `can()` predicate exists for non-enforcement checks. | |
| req-tap-auth-policy-8 | Stateless Backstop | Proposed | The backstop is a stateless `policy.can(actor, needed_cap)` re-check at the write-commit / read-dispatch chokepoint — **not** a contextvar decision ledger. No ambient authorization state is tracked across a request/thread; the prior ledger mechanism (`record_authorization`/`authorized_capabilities`/push-pop scopes) is removed. When the backstop trips it raises `unguarded_operation` with the full stack trace of the ungated callsite. | |
| req-tap-auth-policy-9 | Coverage Lint | Proposed | A build-time static lint (in-house AST scanner reusing the `test_log_site_ids` scanner + baseline-ratchet machinery) in two rules. **Rule A — implemented** (`tap/authz_coverage.py` + `tap/tests/test_authz_coverage.py`): flags any service-layer write/read sink (`write_batch`, the Search/Gryphon executors, `grift_import`, the `_*_internal` write helpers) whose enclosing function lacks a `@requires_capability`/`authorized()` gate. **Rule B — implemented** (`tap/direct_write_coverage.py` + `tap/tests/test_direct_write_coverage.py`): flags statically-resolvable class-level direct writes to graph-managed models (`<Model>.objects.create/get_or_create/bulk_create/bulk_update/update`, `<Model>.objects.filter(...).delete()/.update()`, `<Model>(...).save()`) outside the sanctioned service layer; it enumerates graph-managed `BaseModel` subclasses at runtime from the model registry (incl. plugin models + `Entity`), which a purely-syntactic tool cannot, and ratchets against `tap/guards/baselines/direct_write.txt` (empty — clean) with a `# TAP-WRITE-COV: <reason>` inline escape hatch. Because the rule's correctness depends on *which* class a name refers to, Rule B carries a per-file import binder for the one name a non-managed model also bears (`req-tap-auth-policy-9-name-resolution`) and a freshness check on its own escape hatch (`req-tap-auth-policy-9-unused-exemption`). Together with Rule A this catches the forgotten-gate-by-a-privileged-actor case the runtime backstop cannot. **Note:** both halves of Rule B are now *also* met at runtime — the *read* half by `req-tap-auth-orm-read-backstop` and the *write* half by `req-tap-auth-write-batch-routing` (both structural, fail-closed); the static lint adds authoring-time detection and covers queryset-level bulk writes the instance-level runtime guard cannot see. Builds vs. Semgrep: the runtime `BaseModel` enumeration + the existing baseline-ratchet + pytest gate — revisit Semgrep only at a suite of rules. | |
| req-tap-auth-policy-9-name-resolution | Rule B Resolves Names, Not Strings | Implemented | Rule B's correctness depends on *which* class a name refers to, so it must not match graph-managed models by bare class name alone: a class name a NON-managed model also bears (`tap_auth.User`, shared with the graph-managed `computing_core.User`) would be flagged on every `<Name>.objects.*` write purely by the string collision — a false positive whose only "coverage" of the line was the collision itself. The scanner carries a per-file import binder (models pyflakes' `ImportationFrom`; the file-local layer Ruff/Semgrep stop at — no astroid/CodeQL global inference needed when the origin is in the file's own `import` line) that resolves each collision name to its dotted origin and skips a write whose owner resolves under a non-managed app root. Fail-closed: a name that resolves under a managed root, or cannot be resolved at all (star/relative import, local shadow), stays flagged, so no genuine graph write is dropped by a resolution gap. Impl: `tap.source_scan.build_import_bindings` + `ManagedModelIndex.is_managed`; proof: `tap/tests/test_direct_write_coverage.py`. | Closes the 2026-07 guard-bypass finding: the direct-write guard's coverage of `dev_record.py` existed only because `computing_core.User` shared a name with `tap_auth.User`. |
| req-tap-auth-policy-9-unused-exemption | Rule B Exemptions Rot Loudly | Implemented | A `# TAP-WRITE-COV` exemption that no longer sits on the physical span of a flagged write suppresses nothing — the write it covered was rerouted, resolved out of scope, or moved — and lies in wait to silence a *different* future write on its line (the true-but-orthogonal-reason failure mode). The scanner detects such orphaned exemptions (tokenize-precise, so the marker inside a string literal is never mistaken for a live comment) and a guard fails them, so a stale excuse rots loudly rather than silently mis-covering — the discipline of mypy `warn_unused_ignores` / Pylint `useless-suppression`. Impl: `tap.direct_write_coverage.scan_direct_writes` (`unused_exemptions`) + `DirectWriteExemptionGuard`; proof: `tap/tests/test_direct_write_coverage.py`. | Names, as a check, the lesson of the 2026-07 finding: an escape hatch justified by a true-but-orthogonal reason silences the alarm permanently. |
| req-tap-auth-orm-read-backstop | ORM Read Backstop | Implemented | A read of TAP-managed graph data via the Django ORM re-checks `grid.read` at the ORM chokepoint itself, failing closed (`unguarded_operation`) for a context that lacks it. Layer 1: `BaseModelQuerySet._fetch_all` (all `BaseModel` materialization). Layer 2: a `connection.execute_wrapper` (count/exists/aggregate/raw/cursor + the non-`BaseModel` `EntityType` catalog). Exemptions: the `unguarded_read()` hatch and the context-less infrastructure zone (migrations/shell). On trip it emits a class-aware `security` Flaw (`code`/`app` by offending callsite, via `tap.flaws.report_service_layer_bypass`). Impl: `tap_grid/read_guard.py`; proof: `tap_grid/tests/test_read_guard.py`. | Closes the 2026-06-30 codex-security scan finding class at the data layer. |
| req-tap-auth-credential-bind-provenance | Credential-Bind Provenance | Implemented | `WebAuthnCredential` (a public key that authenticates as its user) and `WebAuthnUserHandle` (the id discoverable login resolves by) are the identity-binding surface — functionally the most privileged writes in the codebase, yet **off the Entity spine**, so the direct-write lint (`req-tap-auth-policy-9`) correctly ignores them and they had no Validation Map row (an invisible gap). This closes it: a build-time guard fails unless every class-level write to either model carries an inline `# TAP-CRED-BIND: <provenance>` tag whose value is valid for that model — `pop-ceremony`/`dev-profile-gate`/`assertion-counter` for a credential, `pre-registration-handle`/`dev-profile-gate` for a handle. A public-key credential can therefore be *bound* only by a proof-of-possession ceremony or the dev_local-gated replay, never a weaker provenance; a queryset `.update()` cannot touch `public_key` untracked; and a new untagged bind (the regression shape) fails at authoring time. The invariant is **containment + local verifiability**, not static proof-of-possession (interprocedural — see `spec-dev-validation.md` Prior Art): the tag names the positive safety reason (finding #8), and each named provenance IS locally checkable (`pop-ceremony` ⇒ `verify_registration_response` in-function; `dev-profile-gate` ⇒ `assert_dev_import_allowed` in-function). Impl: `tap_auth/credential_bind_coverage.py` + `tap_auth/guards/credential_bind.py`; proof: `tap_auth/tests/test_credential_bind_coverage.py`. Hard lint, no baseline. | The credential-surface twin of the dev-passkey import guard (`req-tap-auth-passkey-dev-bootstrap-16`); names, as a check, the "nothing guards credential binds" finding of 2026-07. |
| req-tap-auth-credential-bind-chokepoint | Typed Identity-Bind Chokepoint | Proposed | The stronger form of `req-tap-auth-credential-bind-provenance`: route every identity bind through one `bind_identity(user, *, provenance: BindProvenance)` service function, where `BindProvenance` is a closed union whose interesting variants can only be *constructed* by the thing that earns them — a `CeremonyVerified` only comes out of `verify_registration_response`, a `DevImport` only from the `dev_local`-gated path. Direct `WebAuthnCredential`/`WebAuthnUserHandle` writes are then forbidden outside `bind_identity`, so provenance becomes un-omittable **at the type level**, not merely asserted in a `# TAP-CRED-BIND` comment — the capability/typestate encoding the tag guard approximates (`spec-dev-validation.md` Prior Art, "make illegal states unrepresentable"). `bind_credential` in `ceremony.py` is already half of this (a verified chokepoint taking `expected_challenge`); the remaining work is (a) a sibling entry for the dev-import and handle paths carrying their provenance, and (b) forbidding the raw writes so the provenance guard's site set collapses to one function — the signal the refactor is complete. Deferred: it refactors live passkey code, so it rides the passkey surface rather than landing ahead of it. | The capability-encoded successor to the comment-tag guard; named so the graduation path is canon, not folklore. |
| req-tap-auth-credential-bind-runtime | Runtime Identity-Bind Backstop | Proposed | The runtime twin of the static tag guard and the type chokepoint: a `save()`-path guard on `WebAuthnCredential`/`WebAuthnUserHandle` — off the Entity spine, so `req-tap-auth-write-batch-routing`'s `write_guard` does not cover them — that fails closed unless inside an active `bind_identity` scope, the credential-surface analog of the ORM write backstop. Catches the *instance* writes (`obj.save()`) the static scanner cannot resolve statically. Heaviest layer (touches the model save path); deferred until demand and sequenced **after** `req-tap-auth-credential-bind-chokepoint`, which establishes the scope it checks. | Closes the instance-write gap the static provenance guard structurally leaves open. |
| req-tap-auth-write-batch-routing | ORM Write Backstop | Implemented | A node/edge mutation is permitted only inside a service-layer write scope, so every write routes through the sanctioned API (`write_batch` / `create_node` / `create_edge` / `delete_*` / `purge_node` / `patch_node`) and carries batch scope, FLIP, provenance, and its write-class gate. Scope-based (not capability-based): `requires_capability`/`authorized` open it for write-class caps (`grid.write`/`grid.delete`/`grid.purge`/`grid.import_grift`); `BaseModel.save`/`delete` and `Entity.save`/`delete` call `enforce_service_write`, failing closed (`unguarded_operation`) outside a scope. Exemptions: the `unguarded_write()` hatch (admin/infra + tests) and migrations. Queryset-level bulk writes are covered by the static direct-write lint instead. On trip it emits a class-aware `security` Flaw (`code`/`app` by offending callsite, via `tap.flaws.report_service_layer_bypass`). Impl: `tap_grid/write_guard.py`; proof: `tap_grid/tests/test_write_guard.py`. | Enforces "everything routes through batches"; write-side twin of the read backstop. |

---

### Service Boundary Enforcement
----
RID: `req-tap-auth-service-boundary`  
Status: `Proposed`

AuthN happens at edges. AuthZ happens at the service boundary.

#### Implementation

- Edge surfaces authenticate:
  - web sessions
  - API sessions
  - future API tokens
  - allauth Google/OIDC/SAML callbacks
  - bootloader/runtime actor resolution
  - future service account tokens
  - future AI/delegation credentials
- All edge surfaces collapse to:

```text
actor -> CallerContext -> service call -> tap_auth policy gate
```

- Passing request authentication never implies permission to perform a TAP operation.
- All graph reads require `grid.read`, including:
  - direct service reads
  - Gryphon
  - Search
  - API read endpoints
  - page/panel render paths
- All graph writes require `grid.write` or a more specific operation capability.
- Deletes require `grid.delete`.
- GRIFT import has a named `grid.import_grift` capability but is not made stricter than ordinary graph writes in v1 because GRIFT is TAP's standard interchange/write-batch surface.
- `grid.purge` requires both:
  - `grid.purge` capability
  - `DEBUG=True`
- Public route policy is deferred. V1 protects application/API routes by default, with auth routes, static assets, and basic health carved out as needed.
- **Cross-app capability composition.** Capability gates **compose across service layers; they never migrate down.** The grid service layer gates `grid.*` **type-agnostically** — it authorizes `grid.read`/`grid.write` for *any* node/edge access and never special-cases who owns the type, so it stays ignorant of `plugins.read`, `cares.*`, etc. An app service layer gates its own `app.*` capability and composes **above** the grid layer by calling it: viewing the plugin report needs `plugins.read` (checked in `tap_plugins`) *and* `grid.read` (checked in `tap_grid` when the read routes through it) — two gates, two owners, each authorizing only its own vocabulary. Putting an app capability's *enforcement* inside `tap_grid` would give the grid app knowledge of another app's wheelhouse (the cross-app coupling `avoid-tap-app-interdependencies` forbids); composition avoids the coupling entirely, so no "enable only if `tap_plugins` installed" feature-flag is needed — you do not guard a coupling you never create. Capability **definition** stays centralized in the `tap_auth` registry (`req-tap-auth-capabilities`); only **enforcement** lives in the owning app's service function. Prefer a capability-gated *service function* over a per-panel/per-view gate — one gate point every caller (panel, API, trusted CLI) shares. Reference instance: `tap_plugins.report.get_plugin_report()` authorizes `plugins.read` then calls the grid layer, which independently gates `grid.read`; `tap_grid` holds zero references to `plugins.read`. The one case that forces the grid layer to know an app capability is per-entity-**type** app gating (e.g. reading plugin-typed *nodes* requires `plugins.read`); the canonical resolution when it bites is for the **entity type to declare its required read-capability and the grid service layer to consult that declaration generically** via the registry-backed discovery system — a one-field declaration on the type, not `tap_grid` hardcoding the cap. Deferred until plugins are actually grid nodes.
- **Service boundary structure — see the convention.** Guarded service layers follow [`spec-service-layer-boundary.md`](../../specs/spec-service-layer-boundary.md) for their *structure*: the gateway / public-contract / below-gate zones (`req-service-boundary-model`), export-as-contract with the operation-vs-contract-symbol split and the union invariant (`req-service-boundary-export`), and the shared reusable guard (`req-service-boundary-guard`). `tap_auth` does not re-specify those rules; it adds only the capability semantics — AuthN at the edge, AuthZ at the service boundary, capabilities compose **upward**, and no app capability's *enforcement* migrates down into `tap_grid` (the composition rule above).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-service-boundary-1 | Edge AuthN | Proposed | Web/API/provider surfaces authenticate users or actors. | |
| req-tap-auth-service-boundary-2 | Service AuthZ | Proposed | TAP operations call `tap_auth` at the service boundary. | |
| req-tap-auth-service-boundary-3 | Reads Protected | Proposed | All graph read surfaces require `grid.read`. | |
| req-tap-auth-service-boundary-4 | Writes Protected | Proposed | All graph write surfaces require `grid.write` or a specific write capability. | |
| req-tap-auth-service-boundary-5 | Purge Double Gate | Proposed | Purge requires `grid.purge` and `DEBUG=True`. | |
| req-tap-auth-service-boundary-6 | Capability Composition | Implemented | App capabilities gate in the owning app's service layer and compose above the type-agnostic `grid.*` gate; no capability's enforcement migrates into `tap_grid`. Reference: `tap_plugins.report.get_plugin_report()` gates `plugins.read` then calls the grid layer. | |
| req-tap-auth-service-boundary-7 | Adopts Boundary Convention | Proposed | Guarded service layers follow `spec-service-layer-boundary.md` for gateway/contract/impl separation, export-as-contract, and the reusable guard; `tap_auth` owns only the capability semantics (composition and which capabilities). | Cite, not copy. |

---

### Boot Profile Integration
----
RID: `req-tap-auth-boot`  
Status: `Implemented`

Auth configuration is a first-class section of the TAP boot profile.

#### Implementation

- Auth config lives under an `auth` section in the larger TAP boot profile.
- `tap_auth` owns a reusable JSON Schema fragment under `tap_auth/schemas/`.
- The bootloader composes reusable schema fragments from capability apps rather than copying auth schema into a monolithic boot schema.
- Boot validates the full auth config before applying auth mutations.
- A boot dry-run/test command or function is exposed so operators can validate configuration before launch.
- Auth-enabled **deploy** boot validates the Django deployment security posture before serving: `SECRET_KEY` set and non-default, `DEBUG=False`, `ALLOWED_HOSTS` set, and the secure-transport settings (`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, HTTPS/HSTS) appropriate to the deployment. It runs (or echoes) `manage.py check --deploy` and treats the relevant findings as boot failures for a customer/deploy profile. Dev/local boot may relax this, but loudly. (The `TAP_BASE_URL` / HTTPS provider-callback assumptions in `req-tap-auth-providers` depend on this posture being real.)
- Auth boot runs early:
  1. capability sync
  2. protected group sync
  3. built-in actor sync
  4. initial admin/grant add/update (on login)
  5. provider validation/settings build
  6. provider/domain deactivation handling
  7. later plugin/collector boot steps
- Auth bootstrap is explicit through a bootloader/manage.py command, not silent app startup mutation.
- Boot logs actions now; durable boot reports can come later.
- Auth boot logs add/update/sync/deactivation decisions with secrets redacted.
- `tap_admin` membership is add/update-only in v1 to avoid accidental removal by typo.
- **Email → role grants (`initial_grants`).** Beyond the single-role `initial_admins`, the profile may declare `initial_grants`: a map of verified email → the **human-assignable** roles (`req-tap-auth-roles`) granted to that person on each login. This is how a non-admin is admitted — e.g. an invited guest granted `tap_viewer` (read-only) rather than admin-or-nothing. The role values are constrained to the human-assignable set by the schema enum (held in sync with the loader), and boot fails loud on any non-human/unknown role (defense against drift); the social adapter additionally refuses a non-human-assignable role at runtime, so login config can never hand a person a program actor's authority. Grants are **add/update-only and idempotent** — applied on login, never reconciled or revoked, so a typo or de-listing cannot silently drop access; **de-provisioning a guest is a separate explicit action** (group removal + session invalidation), deliberately not a profile edit. `initial_admins` is retained as documented sugar for `initial_grants` with role `["tap_admin"]`; boot folds the two declarative sources into one effective map. The role name is spelled twice by design — `tap_auth/roles.py` `ADMIN_ROLE` for in-Django callers, and a settings-time copy in `tap_auth/boot.py`, which cannot import the role registry mid-settings-import — tagged `TAP-KNOWN-DUPE(admin-role)` at both sites (specs/spec-tap-known-dupes.md).
- Capability assignment to `tap_admin` is hard-synced.
- Capability pruning is explicit, not implicit: the auth boot config carries a declared prune list of capabilities expected to be removed. Capability sync applies only declared removals and hard-fails on any undeclared drift (`req-tap-auth-capabilities`). This preserves lights-out standup while keeping destructive capability changes pre-declared and reviewable.
- **Last-admin invariant.** Ordinary auth-enabled customer boot must never converge to zero active human `tap_admin`. Boot fails loud if applying the profile would leave no active human admin — *including* the case where provider/domain removal would deactivate the last human admin (`req-tap-auth-external-identity`). A declared path to admin on first login satisfies the invariant: a non-empty `initial_admins` **or** any `initial_grants` entry that grants `tap_admin` (a `tap_viewer`-only grant does **not**). This is the default and is not silently overridable.
- The **only** way boot may proceed into an admin-lockout state is an explicit break-glass declaration in the profile — an `allow_admin_lockout`-style flag, the same explicit-destructive-declaration pattern as capability pruning (`req-tap-auth-capabilities`) — **plus** a documented recovery path. Absent that declaration, a profile that would lock out every admin is a hard boot failure, not a silent secure-lockout. The declared-but-not-actually-lockout case need not fail.
- When `allow_admin_lockout` is declared, secure lockout is permitted by design; recovery then happens via the out-of-band floor (management-command / shell access — see [Policy API](#policy-api) recovery floor) or available local auth. Satellite/headless deployments that expect no human admin are a future explicit relaxation of this invariant, not the default.

#### Suggested Implementation Sequence

These phases are guidance for implementation sessions, not a requirement to execute in this exact order:

1. Create `tap_auth`, move/reset canonical `User`, add actor/builtin fields.
2. Add capability registry, `Capability` home, `sync_capabilities()`, `tap_admin`, `tap_test`.
3. Add `authorize(...)`, typed errors, denial logging, and test fixtures.
4. Wire service-boundary checks for grid read/write/delete/purge/import paths.
5. Add boot schema fragment and auth boot application.
6. Add allauth and `google_oidc` provider config/self-test/build path.
7. Add local-auth disable and session invalidation management operations.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-boot-1 | Boot Section | Implemented | Boot profiles include an `auth` section. | |
| req-tap-auth-boot-2 | Schema Fragment | Implemented | `tap_auth` owns a reusable boot JSON Schema fragment. | |
| req-tap-auth-boot-3 | Validate Before Apply | Implemented | Auth boot validates before mutating state. | |
| req-tap-auth-boot-4 | Dry Run | Proposed | Operators can test/dry-run auth boot config. | |
| req-tap-auth-boot-5 | Early Ordering | Implemented | Auth boot runs before plugin/collector boot paths that require actors. | |
| req-tap-auth-boot-6 | Explicit Command | Implemented | Auth bootstrap is an explicit command/boot step. | |
| req-tap-auth-boot-7 | Deploy Security Check | Implemented | Auth-enabled deploy boot validates Django deployment security (`check --deploy`: `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, secure cookies/HTTPS) and fails a customer/deploy profile on relevant findings. | |
| req-tap-auth-boot-8 | Email→Role Grants | Implemented | The profile declares `initial_grants` (verified email → human-assignable roles), applied add-only/idempotent on login; `initial_admins` folds in as `["tap_admin"]`. Role values constrained to the human-assignable set (schema enum in sync with the loader) and boot fails loud on a non-human/unknown role; the last-admin invariant is satisfied by `initial_admins` or an `initial_grants` `tap_admin`. | |

---

### Provider Framework
----
RID: `req-tap-auth-providers`  
Status: `Implemented`

Provider-specific login machinery is isolated under `tap_auth/providers/`.

#### Implementation

- Provider entries in boot config are multi-provider from v1.
- Each provider has:
  - stable `id`
  - `type`
  - `display_name`
  - provider-specific config
  - secret references
  - `critical_for_boot`
  - auto-provisioning policy
- Provider IDs are stable natural keys such as `example-google` and `robco-google`.
- Provider display names are separate from IDs.
- Provider secrets are referenced by keys under `TAP_SECRETS_ROOT`; secrets are never embedded in boot profiles or DB rows.
- Provider secrets are resolved from the shared `*.secret.json` store via the **app-neutral `tap/runtime_secrets` resolver** (the same file-discovery and envelope contract tap_cares uses; see `spec-tap-cares-secrets` → *Shared Resolver*). tap_auth deliberately resolves **independently of the `tap_cares` app**: allauth settings are built at settings-import time, before `tap_cares.ready()` loads its registry, and tap_auth must not depend on tap_cares (the `tap_*` apps stay independently shippable; `tap/` and `tap_grid` are the only shared-dependency layers). tap_auth therefore reads the upstream resolver directly and owns its provider-side `oidc_client` data-block schema; the tap_cares *registry*, resilient-load report, and secrets health probe are not on this path.
- A **`tap_auth.providers` health probe** (group `tap_auth`, non-critical) runs each configured provider's **offline** self-test on a *running* instance — the runtime view of what boot already validates at standup — reusing `self_test` as the single source of truth so the two cannot drift. No providers configured is healthy (local auth only, conditional necessity); a configured provider whose secret is missing/malformed makes the probe `unhealthy` and the instance `degraded` (loud, non-blocking — boot already hard-gates `critical_for_boot` providers). This is the worked reference for the per-consumer conditional-secret-validation pattern (`spec-tap-cares-secrets.md` → *Conditional Validation Lives In Health Probes*); collectors mirror it via the `CollectorBase` offline self-test.
- Provider implementations expose a common interface or functional equivalent:

```python
validate_config(provider_config)
resolve_secrets(provider_config)
self_test(provider_config, secrets, *, live: bool)
build_allauth_settings(provider_config, secrets)
```

- Provider self-tests split into:
  - `offline`: shape, required settings, secret references, secret presence, local derivations
  - `live`: network/IdP reachability and metadata checks
- Self-test result states:
  - `pass`
  - `warn`
  - `fail`
  - `skip`
- Self-test results include docs/help links.
- Provider self-tests are a deliberate first-class investment, not over-engineering. IdPs break the same way collector upstreams break — credential rotation, OIDC discovery-document changes, tenant/domain config drift — and those are exactly the failures that crack a security integration in production. Built-in self-tests give an AI operator / the future Paladin healer a standard, code-free way to probe "what is wrong with auth right now" without writing bespoke diagnostics, mirroring the established `CollectorBase` self-test pattern so the two surfaces feel the same. A check that returns `fail` because the upstream changed is signal, not noise: that same change would have broken the integration regardless, and the self-test surfaces it precisely instead of as a mystery login failure. The knobs go in now; we adapt the specific checks as real IdP failure modes teach us which ones matter.
- Boot fails on any provider `fail`; `warn` continues with clear logs.
- Deploy boot defaults to live checks for external providers.
- Dry-run/offline modes may skip live checks but log loudly.
- Unknown provider types fail immediately.
- `critical_for_boot` controls live availability:
  - `true`: failed live self-test fails deploy boot
  - `false`: upstream unavailable logs loudly and provider login is unavailable, but boot may continue
- Malformed static config fails boot even when `critical_for_boot=false`.
- Provider availability is log-only in v1; durable provider health/status is future UI work.
- `TAP_BASE_URL` is required when external providers are configured.
- Provider callback URLs derive from `TAP_BASE_URL` by default, with explicit override only when needed.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-providers-1 | Provider Modules | Implemented | Provider specifics live under `tap_auth/providers/`. | |
| req-tap-auth-providers-2 | Multi Provider Shape | Implemented | Boot config supports multiple providers from v1. | |
| req-tap-auth-providers-3 | Secret References | Implemented | Provider secrets are references, never embedded values. | |
| req-tap-auth-providers-4 | Self-Test Interface | Implemented | Providers expose validation/self-test/settings-builder behavior. | |
| req-tap-auth-providers-5 | Offline Live Phases | Implemented | Self-tests distinguish offline and live checks. | |
| req-tap-auth-providers-6 | Criticality | Implemented | `critical_for_boot` controls whether live provider unavailability fails boot. | |
| req-tap-auth-providers-7 | Base URL Required | Implemented | External providers require `TAP_BASE_URL`. | |
| req-tap-auth-providers-8 | Providers Health Probe | Implemented | A non-critical `tap_auth.providers` health probe runs configured providers' offline self-test on a running instance, reusing `self_test`; no providers is healthy, a broken configured provider degrades. | The conditional-secret-validation reference (`req-tap-cares-secrets-conditional-validation`). |

---

### Google OIDC Provider
----
RID: `req-tap-auth-google-oidc`  
Status: `Implemented`

`google_oidc` is the first concrete external provider type.

#### Implementation

- Google/OIDC is first because Robco likely uses Google Workspace and `example.com` is Google-managed.
- `example.com` and Robco are represented as separate `google_oidc` providers.
- Customer/deploy providers require `allowed_domains`.
- Providers may optionally declare `allowed_emails`: an explicit allowlist of individual accounts. When present, only those accounts may log in through this provider; absent or empty means domain-only (no per-account restriction). This is how a `example.com` provider can be pinned to a single operator — e.g. allow only `operator@example.com` even though the whole `example.com` domain is otherwise eligible.
  - `allowed_emails` is matched against the provider-asserted **verified** email (`email` with `email_verified=true`), normalized and case-insensitive.
  - It is an authorization filter, not an identity key. Because email is mutable and `req-tap-auth-external-identity` keeps `sub` as the durable identity, `allowed_emails` is enforced on **every** login, not only at first provisioning. An already-provisioned account whose email drops out of the allowlist is denied at the next login.
  - `allowed_emails` only ever narrows within `allowed_domains`; both checks apply. It never widens access beyond the allowed domains and never bypasses `email_verified`.
  - A login from an allowed domain whose verified email is **not** in a configured `allowed_emails` fails closed with a distinct reason code (`account_not_allowlisted`), separate from a domain rejection (`domain_not_allowed`) and from a generic no-capabilities landing. This denial is:
    - logged as a structured security event (provider id, reason code, verified email where safe, truncated/hashed subject) so an operator can see who was turned away;
    - returned to the calling AuthN surface (the allauth callback/adapter) as a typed result so it can show the user a *specific* hint — they authenticated correctly with the right domain, but their account is not on this deployment's allowlist and an administrator must add them — rather than an opaque failure.
  - These login-denial reason codes belong to the `tap_auth.errors` vocabulary alongside the policy errors, so AuthN-edge denials and service-boundary denials draw from one taxonomy.
- There is no "any Google account" escape hatch. A provider that wants broad access lists the relevant domain(s) in `allowed_domains` explicitly; dev environments use local password auth (`req-tap-auth-local`) or a deliberately broad `allowed_domains`.
- Auto-provisioning is provider-specific.
- Auto-provisioning requires:
  - allowed provider
  - allowed domain
  - account present in `allowed_emails` when that allowlist is configured
  - `email_verified=true`
- Existing linked human users are blocked from login if Google later returns `email_verified=false`.
- Allowed domains are enforced using the **returned** Google `hd` claim in the ID token — the trustworthy hosted-domain assertion. The request-side `hd` *hint* is never used for access control (Google's own guidance: rely on the returned claim, not the request parameter).
- Email-domain fallback (matching the verified-email domain when no `hd` is present, e.g. consumer Google accounts) is **opt-in per provider and OFF by default for customer/deploy providers**. A Workspace-backed customer provider (e.g. Robco) requires a returned `hd` match and does **not** silently fall back to email-domain matching.
  - When a provider explicitly enables email-domain fallback, every fallback decision is logged — the absence of `hd` is itself security-relevant.
  - `email_verified=true` is still required regardless of which path matched.
- `google_oidc` live self-test fetches Google's OIDC discovery document.
- The self-test covers reachability at **boot**; the **runtime** complement is that a transient provider-unreachable *during the login/callback flow* (allauth fetching the discovery doc, exchanging the authorization code, or fetching userinfo — all `requests` calls) is caught at the auth edge and rendered as a friendly, retryable page (HTTP 503 with `Retry-After`) rather than an uncaught 500. The rescue is scoped to the `/auth/` flow — the one place TAP makes outbound IdP calls inside a request — so a `requests` failure from any other view stays a real 500 (a genuine defect, not masked). This is graceful failure, not a security control: a denied login is still a deliberate 403 via the adapter, distinct from an unreachable-IdP 503.
- Auto-provisioned users receive no TAP groups unless explicitly configured as initial admins.
- Authenticated users may have no TAP permissions; they see a generic no-access page.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-google-oidc-1 | Concrete Provider | Implemented | `google_oidc` is the first provider type. | |
| req-tap-auth-google-oidc-2 | Allowed Domains | Implemented | Customer/deploy Google providers require allowed domains. | |
| req-tap-auth-google-oidc-3 | Verified Email | Implemented | Auto-provision and continued login require verified email. | |
| req-tap-auth-google-oidc-4 | Discovery Check | Implemented | Live self-test fetches Google OIDC discovery metadata. | |
| req-tap-auth-google-oidc-5 | No Default Groups | Implemented | Auto-provisioned users get no groups unless explicitly initial-admin configured. | |
| req-tap-auth-google-oidc-6 | Named Allowlist | Implemented | Providers may restrict login to an explicit `allowed_emails` allowlist, enforced on every login and only within the allowed domains; there is no any-account escape hatch. | |
| req-tap-auth-google-oidc-7 | Allowlist Denial Surfaced | Implemented | A domain-allowed but non-allowlisted login fails closed with a distinct `account_not_allowlisted` reason that is logged and returned to the AuthN surface for a specific user-facing hint. | |
| req-tap-auth-google-oidc-8 | Returned hd Only | Implemented | Domain enforcement uses the returned `hd` claim, never the request-side hint; email-domain fallback is opt-in per provider and off by default for customer providers. | |
| req-tap-auth-google-oidc-9 | Runtime Unreachable Graceful | Implemented | A transient provider-reachability failure (`requests.RequestException`) during the OAuth login/callback flow renders a retryable 503 page instead of an uncaught 500; scoped to `/auth/` so non-auth `requests` failures stay real 500s. The runtime complement to the boot-time discovery self-test (-4). | |
| req-tap-auth-google-oidc-fips-algorithm | FIPS Algorithm Clash Graceful | Implemented | Under `TAP_FIPS=1`, an IdP signing its `id_token` with a non-approved algorithm (JWS `ES256K`, or RSA < 2048 bits) fails inside allauth's `jwtkit.fetch_key → algorithm.from_jwk()` with `cryptography.InternalError` / `ValueError` — neither a `PyJWTError` nor an allauth error type, so it escapes both allauth's handler and the `-9` `RequestException` rescue into an uncaught 500 with no hint FIPS is the cause. `CallerContextMiddleware.process_exception` recognizes the signatures via `tap.crypto_errors.explain_crypto_error` (Django-free, in `tap/` per no-`tap_*`-interdeps) and renders a branded **502** (the IdP returned something this FIPS-mode instance cannot process — not transient, so no `Retry-After`), scoped to `/auth/`. Built in the change that flipped `TAP_FIPS=1` (req-cicd-base-image-lifecycle-6). Design + exact signatures: `docs/misc/doc-fips-assessment-record.md` §5.3. | |

---

### Local Password Auth
----
RID: `req-tap-auth-local`  
Status: `Implemented`

Local Django password auth remains available for dev and recovery, but customer deployments should prefer external IdP login.

> **Reconciliation (2026-07-07):** `spec-tap-auth-passkey-v0.md` (`req-tap-auth-passkey-recovery`) revises this requirement for **passwordless-primary** deployments: local password login moves from "dev/default recovery path" to "retired from the routine surface by default, including Django admin; dev-only if explicitly enabled." The `TAP_LOCAL_PASSWORD_ENABLED` toggle is retained as the mechanism; the default posture for a passkey deployment is off, with out-of-band shell as the sole recovery floor. See that spec's Supersedes / Reconciles.

#### Implementation

- Local password login defaults enabled in dev.
- Customer boot profiles should disable local password login unless explicitly enabled once IdP integration is ready.
- Local-only production/on-prem installs are allowed but external IdP is recommended.
- Disabling local password auth:
  - blocks password login everywhere, including Django admin
  - does not deactivate local users
  - does not invalidate current sessions by itself
- Session invalidation is a separate management command/operation.
- Disabling local password auth must not make the instance unrecoverable. Because disabling covers Django admin too, the dependable recovery floor is the out-of-band management-command / shell access described in [Policy API](#policy-api) (recovery floor) — not a live admin login. `emergency_only` local auth mode is deferred to Backlog and is the promotion path once a genuinely no-shell-access deployment exists.
- Spawn/dev currently creates a Django `admin` superuser through `createsuperuser --noinput`; the v1 bridge should add that user to `tap_admin`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-local-1 | Dev Enabled | Implemented | Local password login is available in dev by default. | |
| req-tap-auth-local-2 | Customer Explicit | Implemented | Customer boot profiles explicitly choose local login behavior. | |
| req-tap-auth-local-3 | Admin Covered | Implemented | Disabling local login applies to Django admin too. | |
| req-tap-auth-local-4 | No Deactivation | Implemented | Disabling local login does not deactivate local users. | |
| req-tap-auth-local-5 | Spawn Bridge | Implemented | Spawn-created `admin` joins `tap_admin`. | |

---

### External Identity Linkage
----
RID: `req-tap-auth-external-identity`  
Status: `Implemented`

External identity records link provider-authenticated subjects to canonical TAP users.

#### Implementation

- The durable identity key is provider ID + upstream subject:
  - OIDC: `sub`
  - SAML: NameID or configured stable subject
- Email is a profile field and reconciliation hint, not identity.
- V1 stores explicit columns only, not raw claims or broad `safe_claims_json`.
- Suggested stored fields:
  - provider ID
  - provider type
  - subject
  - user FK
  - email snapshot
  - display name snapshot
  - hosted domain/domain snapshot
  - first seen
  - last seen
  - last login
  - status
- Raw provider claims/assertions are not stored in v1.
- Provider-managed email updates the TAP user email on login.
- External usernames are generated from provider ID + subject-derived stable value and are not intended for display/login.
- UI shows email/display name, not the generated username.
- Schema may support multiple external identities per TAP user, but v1 account linking is disabled:
  - no self-service linking
  - no automatic email linking
  - no boot/admin linking unless explicitly added later
- If a login arrives through a second provider with the same email as an existing TAP user, deny login with an `identity_linking_disabled` style error.
- These guarantees are enforced by a **TAP-owned allauth social adapter**, not left to allauth defaults. allauth will otherwise auto-connect a social login to an existing local account by verified email; the TAP adapter overrides the relevant hooks — `pre_social_login` (refuse the auto-connect / raise the linking-disabled denial on same-email) and the email-authentication hooks (`authenticate_by_email` / `can_authenticate_by_email`) — and `SOCIALACCOUNT_EMAIL_AUTHENTICATION` is held at its secure default (off). "Linking disabled / deny same-email second-provider" is an explicit adapter responsibility, not an aspiration that depends on allauth's defaults staying favorable.
- The same posture **pins** the related allauth login-safety settings explicitly rather than relying on defaults staying favorable:
  - `SOCIALACCOUNT_LOGIN_ON_GET = False` — POST-only login initiation, allauth's recommended guard against login-CSRF / drive-by social login (a GET-triggered login can be forced by a crafted link).
  - The TAP adapter runs all domain / `hd` / `allowed_emails` allowlist and `email_verified` checks (`req-tap-auth-google-oidc`) **before** any allauth auto-signup/provisioning — `pre_social_login` is the chokepoint, so a disallowed account is denied before a TAP user is ever created, never after.
- Duplicate emails are allowed at DB level because email is not identity.
- Ambiguous identity resolution fails closed and logs.
- Full raw subjects are not logged. Admin can see provider ID plus truncated/hashed subject; full subject is hidden unless future explicit debug/admin tooling exposes it.
- Provider/domain removal deactivates affected external users by default.
- Re-adding a provider/domain does not automatically reactivate users; reactivation is explicit.
- User directory/group lifecycle sync from IdP APIs is deferred as backlog security work.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-external-identity-1 | Provider Subject Key | Implemented | External identities are keyed by provider ID + subject. | |
| req-tap-auth-external-identity-2 | No Raw Claims | Implemented | Raw provider claims/assertions are not stored. | |
| req-tap-auth-external-identity-3 | Email Not Identity | Implemented | Email is not used as the durable linkage key; the express, system-wide statement of this is `req-tap-auth-email-not-identity`. | |
| req-tap-auth-external-identity-4 | Linking Disabled | Implemented | V1 denies second-provider/same-email login rather than linking or shadowing. | |
| req-tap-auth-external-identity-5 | Deactivation On Policy Removal | Proposed | Provider/domain removal deactivates affected external users. | |
| req-tap-auth-external-identity-6 | Adapter Enforces No-Linking | Implemented | A TAP-owned allauth social adapter overrides the email-matching hooks (`pre_social_login`, `authenticate_by_email`/`can_authenticate_by_email`) so linking-disabled / same-email denial is enforced, not left to allauth defaults. | |

---

### Session Invalidation
----
RID: `req-tap-auth-sessions`  
Status: `Implemented`

Session invalidation is a separate management operation from disabling login mechanisms.

#### Implementation

- TAP exposes session invalidation as an explicit, audited operation (management command and/or service function) at three scopes — the banhammer for auditing and incident response:
  - **global**: invalidate every active session (full flush of the session store), e.g. mass logout after a suspected platform compromise.
  - **per-user (banhammer)**: invalidate *all* sessions belonging to one user — the incident-response lever for "get this account out of every browser/device now."
  - **per-session (surgical)**: invalidate one specific session, identified by its session key or the redacted session handle surfaced in logs (`req-tap-auth-logging`), e.g. killing a single suspicious session while leaving the user's other sessions intact.
- The mechanism is the boring Django session store, not a parallel system:
  - global = clear/flush the session backend;
  - per-user = enumerate active sessions and remove those whose `_auth_user_id` matches the target. The default DB backend has no user→session foreign key, so v1 does a decode-and-match scan of unexpired sessions (acceptable at v0 scale). A durable user↔session index (e.g. `django-user-sessions`) is deferred backlog until a real "active sessions" management UI demands it.
  - per-session = delete the one session row by key.
- Every invalidation is a logged security event with structured `message_data`: acting actor, scope, target user and/or session (redacted where appropriate), reason, and count invalidated. The audit trail is the point — the banhammer must always be attributable to a named actor.
- Session invalidation is capability-gated (`auth.manage_users`, or a dedicated session-management capability) and is never an anonymous / `User=None` operation.
- Invalidation remains a SEPARATE lever from disabling login mechanisms and from user deactivation. Banning a user during an incident is *composed* from explicit primitives (e.g. deactivate user + per-user invalidate), not a silent side effect of either one. This keeps each lever independently auditable.
- Disabling local auth, disabling providers, or changing provider config does not silently imply blanket session invalidation unless the specific operation chooses to call it.
- User/session management UI surfaces are future work; v1 may use Django admin and management commands.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-sessions-1 | Separate Lever | Implemented | Login disablement and session invalidation are separate operations. | |
| req-tap-auth-sessions-2 | Global Invalidation | Implemented | TAP provides a command/service path to invalidate all active sessions. | |
| req-tap-auth-sessions-3 | Per-User Banhammer | Implemented | An operation invalidates all sessions for a specific user. | |
| req-tap-auth-sessions-4 | Per-Session Invalidation | Implemented | An operation invalidates one specific session by key/handle. | |
| req-tap-auth-sessions-5 | Audited And Attributable | Implemented | Every invalidation is capability-gated and logged with actor, scope, target, reason, and count. | |

---

### Email Is Not Identity
----
RID: `req-tap-auth-email-not-identity`  
Status: `Proposed`

**Email is not a reliable source of user identification, and MUST NOT be used as the key to identify, select, look up, authorize, or grant to a user anywhere in the auth system.** Durable identity is a **stable internal `User` id**, or for federated identity the verified `(provider, sub)` pair (`req-tap-auth-external-identity`). This is the express, first-class statement of the principle; the more specific requirements below and around it (`req-tap-auth-user-lookup` selector convention, `req-tap-auth-external-identity`, `req-tap-auth-deactivation`, and `spec-tap-auth-passkey-v0.md` `req-tap-auth-passkey-add-device`) are its instances. It instantiates the cross-cutting security rule `spec-security-posture.md` `req-sec-email-not-identity`.

Email fails as an identity key because it is **mutable** (people change addresses), **not unique** (TAP permits duplicate emails at the DB level by design — `req-tap-auth-external-identity`, so an address resolves to zero/one/many users), and for federated logins **externally controlled** by the provider (only `(provider, sub)` is durable). Worst of all the failure is **silent**: resolving an ambiguous email by first-match mis-identifies a user with no error — account takeover on a credential-mint, wrong-account denial-of-service on a deactivate/session-kill.

#### Implementation

- **Identify / select / target by stable internal id.** Every user-targeting operation (management command, service verb, admin action) keys off the internal `User` id — never email. A unique username (DB-unique) is an acceptable stable selector; email is not. This is the `req-tap-auth-user-lookup` selector convention.
- **Email is at most an ambiguity-refusing convenience.** Where a human-friendly lookup genuinely helps, email MAY be offered only as a convenience that **fails loud on zero or multiple matches** — never a silent `.first()`-style pick.
- **Filter, not key.** Matching a provider-asserted **verified** email against an allow-list (`allowed_emails`, `req-tap-auth-google-oidc`) is a legitimate authorization *gate*, enforced every login; using email to decide *which user this is* is forbidden. Keep the distinction explicit wherever email appears.
- **Named residual — `initial_grants` keys off verified email.** The `initial_grants` map (`req-tap-auth-boot`) grants roles by the authenticated user's *verified* email. This is permitted as the federated admission unit but is safe only under **verified-email uniqueness within the admitted identity space** — sound for a single `hd`-gated Workspace provider, weaker under multi-provider / consumer-domain fallback. Named per `req-sec-honest-risk`, not silently relied upon; the IdP-claim→role mapping (Backlog) is the durable replacement.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-email-not-identity-1 | Stable-Id Keying | Proposed | User identification / selection / authorization in the auth system keys off a stable internal `User` id (or federated `(provider, sub)`), never email. | |
| req-tap-auth-email-not-identity-2 | No Silent Ambiguous Pick | Proposed | Where email is offered as a convenience lookup, it fails loud on zero or multiple matches; a silent first-match pick is a defect (see the `auth_sessions` follow-up under `req-tap-auth-user-lookup`). | |
| req-tap-auth-email-not-identity-3 | Filter ≠ Key | Proposed | Email as a verified authorization filter (allow-list) is permitted; email as an identity key is not; the distinction is stated wherever email appears, and `initial_grants`' email keying is a named residual. | |

---

### User Lookup (Roster Read)
----
RID: `req-tap-auth-user-lookup`  
Status: `Proposed`

Operator-facing user administration keys off the **stable internal `User` id**, not email (email is mutable, non-identity, and DB-level-duplicate-permitted — `req-tap-auth-external-identity`). For that to be usable the id has to be **discoverable**, so a read-only lookup command is the necessary companion to every id-keyed *write* command (`deactivate-user` / `reactivate-user` below, and `spec-tap-auth-passkey-v0.md`'s `enroll-user --add-credential`). This is the one place the internal id is surfaced for an operator to copy into those commands.

#### Implementation

- **Command.** `manage.py list-users [--email <exact-or-substring>] [--role <role>] [--active | --inactive] [--format table|json]` lists users, and for each shows: the **stable internal user id** (the value the write commands consume), email(s), `is_active`, the auth-method kind(s) bound (federated / passkey / local), roles/grants, and last-login. It is strictly **read-only** — it never mutates.
- **Shared selector convention (the id-keyed contract, defined once here).** Every user-targeting *write* command resolves its target by `--user-id` (**authoritative**) and MAY accept `--email` only as a **convenience lookup that fails loud on zero or multiple matches** — never a silent pick, because a duplicate or mistyped email on an account-impacting command (mint-a-credential, deactivate, session-invalidate) is account takeover or wrong-account denial-of-service. A unique `--username` (DB-unique in Django's user model) is an equally-stable authoritative selector where a command already spells it that way; the fail-loud rule applies specifically to the **email** path. `list-users` is precisely how an operator turns a fuzzy email into the exact id to pass. This convention is referenced by `req-tap-auth-deactivation`, `req-tap-auth-sessions`, and `spec-tap-auth-passkey-v0.md` `req-tap-auth-passkey-add-device` rather than restated there.
- **Binds existing commands too (audit, 2026-07-08).** The already-implemented `manage.py auth_sessions` (`req-tap-auth-sessions`) resolves both `--as-user` (the acting admin) and `--user` (the target) via a username-or-email helper whose email fallback currently picks `.first()` — a **silent pick on duplicate email** that this convention forbids (mis-selecting `--as-user` runs the operation under the wrong authority; mis-selecting `--user` kills the wrong account's sessions). Its username path is safe (unique); its email fallback MUST be brought into compliance — fail loud on ≠1 match — as an implementation follow-up. A full sweep (2026-07-08) confirms the remaining email usages are correct-by-design: `allowed_emails`/`hd`/`email_verified` are authorization filters, not identity keys (`req-tap-auth-google-oidc`); the same-email no-linking check fails closed via `.exists()` (`req-tap-auth-external-identity`); and `enroll-user`/`enroll-admin` *create* legitimately take `--email` because they assert a new identity whose existing-user check already fails loud on any match. The one **named assumption**: `initial_grants` keys grants off the authenticated user's *verified* email (`req-tap-auth-boot`), which is safe only under verified-email uniqueness within the admitted identity space (holds for a single `hd`-gated provider; weakens under multi-provider / consumer-domain fallback).
- **Read-scoped capability.** Gated on a **read** capability `auth.read_users`, deliberately distinct from the **write** `auth.manage_users` (fine-grained read-vs-write split): listing the roster discloses who exists and who is admin — real reconnaissance value — and is separable from the power to change accounts, so a support/operator role can hold lookup without mutation. Never an anonymous / `User=None` operation.
- **AI-legible + audited.** `--format json` emits a machine-parseable roster so a Player-3 AI operator (`spec-ai-integration.md`) can consume it read-only; each invocation emits a structured access-audit line (actor / time / filter) because roster enumeration is recon-relevant.
- **Request-agnostic service verb.** A thin wrapper over a service-layer `list_users(...)` read verb, so a future user-management UI or the grid-intent consumer drives the same gated read — additive, not a rewrite.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-user-lookup-1 | Lookup Command | Proposed | `manage.py list-users` lists users with their stable internal id, email(s), active state, auth-method kind(s), roles, and last-login; supports `--email` / `--role` / `--active` / `--inactive` filters and `--format table\|json`; strictly read-only. | |
| req-tap-auth-user-lookup-2 | Id-Keyed Selector Convention | Proposed | User-targeting write commands key off `--user-id` (authoritative); `--email` is accepted only as a convenience that fails loud on zero or multiple matches. Defined here; referenced by deactivation and passkey add-device. | |
| req-tap-auth-user-lookup-3 | Read-Scoped & Audited | Proposed | Gated on a read capability `auth.read_users` distinct from the write `auth.manage_users`; emits a structured access-audit line; `--format json` is machine-parseable for an AI operator. | |

---

### User Deactivation
----
RID: `req-tap-auth-deactivation`  
Status: `Proposed`

Deactivation is a **method-agnostic user-lifecycle lever**: it disables a user *regardless of how they authenticate*, and is the operator's explicit "turn this account off" primitive — distinct from disabling an auth method (`req-tap-auth-local`) and from session invalidation (`req-tap-auth-sessions`). This requirement gives the previously-scattered deactivation primitives — metadata (`req-tap-auth-user-model`), inactive-actor enforcement (`req-tap-auth-actor-model`), and the compose-with-sessions doctrine (`req-tap-auth-sessions`) — one operator-facing home; it cites them rather than restating them.

#### Implementation

- **Operator commands.** `manage.py deactivate-user --user-id … [--reason …] [--invalidate-sessions]` sets the user inactive (`is_active=False`) and records the deactivation metadata (`deactivated_at` / `deactivated_reason` / `deactivated_by_actor`, `req-tap-auth-user-model`). A symmetric `manage.py reactivate-user --user-id …` reverses it; reactivation is **explicit**, never automatic (consistent with `req-tap-auth-external-identity`'s "reactivation is explicit"). Deactivate is **not** delete — the user row and its audit trail are preserved. Both follow the **id-keyed selector convention** (`req-tap-auth-user-lookup`): the target is resolved by `--user-id` (authoritative), with `--email` accepted only as a convenience that fails loud on zero or multiple matches — deactivating the wrong account on a duplicate/typo'd email is a wrong-account denial-of-service, so it is never a silent pick. Use `manage.py list-users` to find the id.
- **Method-agnostic by construction, enforced at every edge.** Deactivation lives on the `User` (the identity anchor *above* every auth method), so it applies regardless of authentication process — but that only holds if each edge honors it. **Every authentication backend MUST reject an inactive user.** Django's `ModelBackend` does this via `user_can_authenticate` (covering local + the federated/allauth path), and the **TAP passkey authentication backend MUST mirror it** — a hand-rolled backend that verifies an assertion without an `is_active` check would let a deactivated user keep logging in by passkey, silently defeating the purpose. Belt-and-suspenders: even a *stale* session of a deactivated user is denied at the service boundary (`req-tap-auth-actor-model` inactive → `inactive_actor`), so a deactivated actor can perform no TAP operation regardless of session state.
- **Session invalidation is a composed, explicit step — and cheap.** Deactivation blocks *future* auth; it does not by itself terminate a live session (`is_active=False` does not evict an existing session). `--invalidate-sessions` composes the per-user banhammer (`req-tap-auth-sessions-3`) so the account is logged out everywhere in one command — explicit, never a silent side effect (the separate-levers doctrine). The **recommended mechanism is per-user session-auth-hash-salt rotation** — the *same* primitive `spec-tap-auth-passkey-v0.md` (`req-tap-auth-passkey-recovery`) already requires so credential revocation kills sessions: rotate a per-user salt feeding `get_session_auth_hash()` and every session dies on its next request (O(1) trigger, no scan, no index, no new dependency), exactly where a password change did the job in the password era. It is *lazy* (next-request), which suffices because the service-boundary inactive-actor denial already blocks any action in the interim; when an *instant* cookie-kill is wanted (incident response), the enumerate-and-delete banhammer (`req-tap-auth-sessions-3`) composes on top.
- **Guardrails.**
  - **Protected built-ins refused** — the command cannot deactivate a protected built-in program actor (`tap_bootloader`, `tap_test`, `tap_cares.*`), consistent with `req-tap-auth-builtins` ("protected users cannot be deactivated by ordinary user-management paths").
  - **Runtime last-admin guard** — the command refuses to deactivate the last active human `tap_admin`, mirroring the boot-time last-admin invariant (`req-tap-auth-boot`) at runtime so an operator cannot accidentally lock the instance out; an explicit break-glass override is required to proceed (out-of-band shell genesis remains the floor regardless).
- **Capability-gated + audited** — `auth.manage_users`; the deactivation metadata is the durable audit record (actor / reason / time), plus a structured security log. Never an anonymous / `User=None` operation.
- **Request-agnostic service verb.** The command is a thin wrapper over a service-layer `deactivate_user(...)` / `reactivate_user(...)` verb, so a future user-management UI or the grid-intent consumer (Backlog) drives the same gated primitive — keeping the door additive, not a rewrite.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-deactivation-1 | Deactivate Command | Proposed | `manage.py deactivate-user` sets `is_active=False` and records deactivation metadata; `reactivate-user` reverses it explicitly; neither deletes the user. Both key off `--user-id` per the `req-tap-auth-user-lookup` selector convention (`--email` fails loud on 0/multiple). | |
| req-tap-auth-deactivation-2 | Method-Agnostic Enforcement | Proposed | Every auth backend (local, federated, **passkey**) rejects an inactive user, and the service boundary denies an inactive actor — a deactivated user cannot authenticate by any method or act on any live session. | |
| req-tap-auth-deactivation-3 | Session Invalidation Composed | Proposed | `--invalidate-sessions` invalidates all of the user's current sessions via the per-user banhammer; recommended impl is per-user auth-hash-salt rotation, shared with `req-tap-auth-passkey-recovery`. | |
| req-tap-auth-deactivation-4 | Guardrails | Proposed | Protected built-ins cannot be deactivated; the last active human `tap_admin` is protected by a runtime last-admin guard (explicit override required). | |
| req-tap-auth-deactivation-5 | Gated & Audited | Proposed | Deactivate/reactivate are `auth.manage_users`-gated and produce structured audit records (actor / reason / time). | |

---

### Actor-Aware Logging
----
RID: `req-tap-auth-logging`  
Status: `Proposed`

TAP logs carry actor/session/request/task attribution through stdlib logging context, not a third-party logging package.

#### Implementation

- No `structlog` dependency in v1.
- Use Python stdlib:
  - `contextvars`
  - `logging.Filter`
  - custom formatter fields
  - existing `dictConfig` in `tap/logging.py`
- Bind execution context at:
  - request start
  - task start
  - bootloader operation start
  - collector/scheduler runner start
  - future AI actor start
- Clear context at every boundary so actors never leak across requests/tasks.
- Context fields should be actor-aware:
  - actor ID
  - actor username
  - actor kind
  - actor display/email where safe
  - auth session ID or stable redacted session handle
  - request ID when added
  - task result ID where present
  - future delegator/on-behalf-of context
- Log context is attribution, not authorization.
- AuthZ denial logs are explicit security messages from `tap_auth.policy`.
- Existing TAP logging site-token rules remain in force.
- Future JSON sinks can emit the same enriched fields.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-logging-1 | Stdlib Only | Proposed | V1 uses stdlib logging/contextvars rather than adding `structlog`. | |
| req-tap-auth-logging-2 | Actor Context | Proposed | Log records are enriched with current actor context when bound. | |
| req-tap-auth-logging-3 | Boundary Clear | Proposed | Context is cleared at request/task/boot boundaries. | |
| req-tap-auth-logging-4 | Not AuthZ | Proposed | Logging context never substitutes for authorization checks. | |

---

### AI And Machine Actor Placeholder
----
RID: `req-tap-auth-ai-placeholder`  
Status: `Proposed`

AI and machine execution must use named TAP actors, but detailed AI delegation is deferred.

#### Implementation

- AI actors are `program` users in v0.
- A delegated AI actor is not the human user.
- Future delegated AI actions carry explicit `on_behalf_of` / delegator context.
- Delegated actors receive explicit capability subsets.
- Delegated actors cannot exceed the delegating user's capabilities.
- Logs/audit show both actor and delegator when delegation exists.
- TAP never treats an AI action as anonymous system work or as an unqualified extension of the human user.
- Real AI mechanics are deferred to future `tap_ai` specs:
  - task/session model
  - model identity
  - tool credentials
  - prompt/session lifecycle
  - delegated task scopes
  - approval workflows
  - plugin-defined AI actors

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-ai-placeholder-1 | AI Is Programmatic | Proposed | AI actors fit under `user_kind=program` in v0. | |
| req-tap-auth-ai-placeholder-2 | Delegation Explicit | Proposed | Future delegation is explicit, bounded, and audited. | |
| req-tap-auth-ai-placeholder-3 | No Anonymous AI | Proposed | AI actions are never represented as `User=None`. | |

## Backlog

- SAML provider implementation.
- Generic OIDC provider after `google_oidc`.
- **IdP-claim → TAP-role mapping (post-MVP).** Delegate role assignment to the customer's identity provider: the IdP asserts group/role membership and TAP maps it to its own roles on each login, instead of (or alongside) the operator-curated `auth.initial_grants` map (`req-tap-auth-boot`). The standard shape is a per-provider **claim→role map** in the provider config (e.g. `{"tap-admins": "tap_admin", "tap-viewers": "tap_viewer"}`), read from the **verified token** at the same chokepoint that already enforces `hd`/`email_verified` (`evaluate_access`), and synced to group membership in the adapter's `save_user` path — `ProviderConfig.config` is already the per-provider passthrough where such a map would live, so the seams exist. Two materially different cases: providers that emit a **`groups`/`roles` claim in the ID token** (Okta, Entra/Azure AD, Auth0, Keycloak) are the easy, token-native path; **Google Workspace does not** (see the Google-specific entry below) and needs the Admin SDK Directory API instead. **The load-bearing design decision is reconciliation semantics:** unlike `initial_grants`, which is deliberately *add-only* (a typo can't revoke), IdP-claim mapping is normally *authoritative/reconciling* — drop out of the upstream group and lose the mapped role on next login, since the point is to delegate lifecycle to the customer's directory. Running both models at once needs an explicit per-source rule (config grants additive; claim-mapped grants authoritative over only the claim-mapped group set). The same security boundary still binds: a claim map may grant **only human-assignable roles** (`req-tap-auth-roles` — never `tap_bootloader`/`tap_cares.*`), regardless of what the upstream group is named. **Deferred because** every current use case has at most a small handful of users (mostly the operator); `allowed_emails` + `initial_grants` cover "let this set of people in" without the extra IdP integration and its credential/security surface. This lands when a customer arrives managing their own users at scale in their own IdP — at which point Okta/Entra (token-native claims) are the natural first targets over Google.
- Group-based access (Google). Gate login and/or map TAP roles by upstream Google Workspace group membership. This is **not** available via Google OIDC ID tokens — unlike Okta/Entra, Google does not emit a `groups` claim — so it requires either the Admin SDK Directory API (a service account with domain-wide delegation + `admin.directory.group.readonly` scope, queried server-side after login) or a SAML provider with group-attribute mapping. Both are separate, heavier integrations with their own credentials and security surface. Until then, `allowed_emails` is the per-account substitute for "let this set of people in."
- Plugin-declared capabilities and groups.
- **Per-app / plugin internal-actor declaration mechanism.** The generalization of v0's centrally-defined native-app actors: a first-class interface by which a native app *or a plugin* declares its own internal-app service actor(s) + least-privilege bundle, materialized and guarded by `tap_auth` sync (the existing immutable-key / hard-sync / protected-metadata guards prevent impersonation, duplication, or acquisition of an existing actor). Deferred to the **plugin refactor**, which is where plugins first need to self-declare actors — including a distinct actor *per collector* for cross-collector attribution (v0 runs all collectors as the single shared `tap_cares.collector`) — and is the right home for it, not the auth sync or boot system hardcoding them. Native apps (`tap_boot`, `tap_cares`) continue to use centrally-defined `tap_auth` bundles until then. (Referenced by the plugin refactor; `req-tap-auth-builtins` lists the v0 per-app-owned actors.)
- **Grid-intent (request/response) triggering of internal operations.** Generalizes the scheduler: a user with the right capability creates an *intent* node on the grid — a schedule, a collection request, an "install-plugin" ask — and an internal-app service actor services it under its own bounded bundle. Two distinct authZ decisions, never collapsed: the capability to **create the intent** (at the grid-write boundary) and the bundle that bounds the **servicing actor**. The payoff over a classic code-path + dedicated table: the operation gains grid history / FLIP / search / linking, backend activity becomes grid-referenced and dimension-separated from monitored data (better than log-lines), and hosted AI reasons about system state with the same grid-search skills it uses for the domain. Needs the not-yet-baked `ask` / `action` / `emitter` node concepts. Scope boundary: this is for operations with a natural grid representation; **non-grid web/API config actions** (plugin enable/disable, route config, things with no grid side) are gated by classic per-request edge authZ (`req-tap-auth-service-boundary`) and are a separate `tap_web` design — not forced onto the grid.
- **On-grid expression of users — records vs. actions (deliberately deferred, demand-driven).** Two separable questions, both post-MVP, with different answers:
  - **User *records* stay off-grid.** Users, groups, and `ExternalIdentity` are Django auth + tap_auth management tables, explicitly excluded from the BaseModel/Entity spine (CLAUDE.md), and stay that way for MVP. The asymmetry runs *toward* waiting (unlike the cheap-now auth security edges): adding a user Entity later is a mechanical additive projection, but formalizing it now commits to a node shape (identity, dimensions, which edges) before the questions it answers exist, and a wrong shape is the expensive part to unwind. Off-grid is also a clean boundary — identity can't be mutated through grid write paths, and FLIP/provenance/AI never touch principals. **Trigger to revisit:** when attribution/ownership/assignment stops being metadata and becomes a *relationship you traverse* — a real **edge** from a person to a grid entity (owned-by / assigned-to / responsible-for), **Gryphon-querying across people**, or **history/FLIP on the principal** itself; the canary is the first collector/plugin that wants "entity X is owned by user Y" as a real edge. When it lands it is an *additive grid projection* (a user Entity keyed on the durable `User` + `ExternalIdentity (provider, sub)` identity, mirroring only the relationship layer), **not** a migration of auth onto the grid — the auth tables stay the source of truth for authN/authZ.
  - **User-management *actions* are a candidate for the grid-intent pattern.** Distinct from the records question: rather than a user-management UI calling service verbs directly, the *actions* (deactivate/reactivate, grant/revoke role, invalidate sessions, invite) could be **proposed to the grid as intent nodes** and consumed by a user-management service actor that performs the off-grid mutation — the same request/response shape as collector-job creation, an instance of the grid-intent triggering pattern above. Payoff: admin actions gain grid history / FLIP / search and AI-legibility ("what access changes were requested/made"), plus the two-decision authZ split (capability to *propose* the intent at the grid-write boundary vs. the bounded actor that *services* it). The clean part is the pairing — off-grid *state* + on-grid *intent* — which buys auditable, queryable admin actions **without** grid-modeling the principals themselves. Still more than MVP needs (the direct gated service verbs behind the administrivia surface are enough), but it is the pattern the collector system is already heading toward, so the cheap hedge is to build the user-management control verbs as request-agnostic service-layer functions that a web view OR a future intent-consumer can drive — keeping this door additive, not a rewrite.
- User-facing account/profile/linking UI.
- Self-service multi-identity account linking.
- Directory/group lifecycle sync from upstream IdPs.
- Durable provider health/status model and auth management UI.
- `emergency_only` local auth mode.
- Satellite/headless auth rules where no human admin is expected.
- Secondary, non-boot auth configuration source (no RID yet — minted when this backlog item is picked up). Auth config is a schema-validated document and the boot profile is one source; support a standalone non-boot config path (single file now; multi-file / DB-or-admin-managed later) without changing the schema fragment or apply logic, so boot-embedded and standalone configs share validation/apply. `spec-tap-boot-v0.md` deliberately keeps the config *source* a thin seam for exactly this.
- Dimension-scoped grid authorization. When built, dimension/object-scoped **read** authorization MUST be pushed into the Gryphon/Search query planning + execution surface (data-filtering at the query layer), never bolted on as a post-fetch filter at page/panel render. Filtering after fetch leaks existence and breaks pagination/aggregation — the Oso "data filtering" lesson, and DRF's explicit warning that object permissions do not filter list endpoints. This is the natural extension of the v1 read backstop that already lives at the Gryphon/Search chokepoint (`req-tap-auth-policy`). When resource/dimension attributes must be read to *reach* a decision, do so through a narrowly-defined **`policy_metadata_read`** primitive (harvested from the retired `spec-tap-auth-assurance-v0.md`) — pinning exactly which fields, which surfaces, and which actor context may use it, and how it avoids leaking existence — and distinguish a policy denial from a **`not_found_after_auth`** outcome so authorization never leaks resource existence through error shape.
- Object/resource-scoped authorization beyond v1 operation-level checks.
- **Capability-centric auth-assurance test corpus (harvested from the retired `spec-tap-auth-assurance-v0.md`).** A described, schema-validated, machine-legible allow/deny **test matrix** — actor/persona × capability × operation → expected decision + reason code — driving a **fail-closed generated pytest harness** (refuse-green if an enabled capability/method lacks its cases), plus reusable described persona/resource catalogs. This is the one un-landed ambition of the retired assurance spec worth reviving: its *enforcement* half already shipped capability-centrically (`req-tap-auth-policy-9` lint, `req-tap-auth-orm-read-backstop`, `req-tap-auth-write-batch-routing`, the `unguarded_operation`/Flaw taxonomy, denial logging); what remains is the *positive test corpus*. It MUST be re-scoped **capability-centric, not surface-centric** — no surface registry / markers / runtime surface-context / surface-delegation (the rejected spine). First instance is the passkey method's own assurance cases (`spec-tap-auth-passkey-v0.md` `req-tap-auth-passkey-assurance`). Optional sub-note: an offline adapter could export the corpus into an OPA-style input for external policy analysis (no OPA runtime dependency).
- **Minor auth-assurance remainders (harvested from the retired `spec-tap-auth-assurance-v0.md`; low priority).** (a) A *formal described exemption registry* — reason / owner / scope / expiration / review-note — as a governance upgrade over today's inline escape hatches (`unguarded_read()`/`unguarded_write()`, `# TAP-WRITE-COV`, `# noqa: TAP-LOG-ID`). (b) *Full decision records* — logging successful authorizations (not only denials) with a `policy_version` derived from the capability-registry hash — for forensics, composing with the decision-as-grid-intent idea (`grid-intent triggering`) rather than emitting every decision to the graph by default.
- AI delegation mechanics in `tap_ai`.
- Capability-gated service-layer introspection of internal registries. Once the policy gate exists, TAP's internal registries and "shape" surfaces (capabilities, section handlers, entity/edge/panel registries, provider/collector inventories) can be exposed through gated service-layer read APIs — each behind an appropriate capability (e.g. `auth.read_capabilities`) — so operators and future AI/Paladin actors query system shape through an authorized surface rather than code access. Direct extension of the real-`Capability`-table decision (`req-tap-auth-capabilities`) and the declarative-shapes / satellite-agents-without-code-access direction. Wait for a concrete consumer (management UI, Paladin, satellite agent) before building.
- JSON structured logging sink and OpenTelemetry correlation.

## Approved Dependencies

This spec approves adding django-allauth for the AuthN implementation path, subject to implementation-time version selection and ordinary dependency review.

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed | Requirement has been designed but not yet accepted for implementation. |
| Approved for Development | Requirement is accepted and ready to be implemented. |
| In Development | Actively being worked on. |
| Implemented | Has been written. |
| Verified | Has met the acceptance criteria. |
| Refactoring | In the process of being re-worked. |
| Deprecating | In the process of being deprecated. |
| Deprecated | No longer part of the current architecture. |
