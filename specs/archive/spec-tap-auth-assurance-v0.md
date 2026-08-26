# TAP Auth Assurance v0 Specification

> # ⚰️ DEPRECATED / RETIRED (2026-07-08) — kept for posterity, NOT the contract, NOT a plan of record.
> # ARCHIVED (2026-08-20): moved to `specs/archive/`, which every scanner excludes. Do not cite,
> # load as canon, or build from anything below — for the archeologists only.
>
> The **surface-identity organizing model** of this spec — surface registry, surface markers,
> runtime surface-context, the surface-centric assurance matrix, and surface delegation — was
> **evaluated and rejected** for TAP's scale: every real auth issue was a forgotten/bypassed
> **capability** gate, and v1 auth is deliberately **capability-centric, not surface-centric**.
> Authoritative today: `spec-tap-auth-v0.md` + `docs/misc/doc-auth-per-app-standards.md`. This file
> is retained **only** as the record of that decision, so the surface apparatus is not re-proposed;
> nothing in it is actionable and none of its `req-tap-auth-assurance-*` requirements should be built.
>
> **Harvest pass (2026-07-08).** Its concrete, capability-compatible ideas already shipped elsewhere:
> `BaseModel.save()` last-ditch guard → `req-tap-auth-write-batch-routing`; multi-gate / chokepoint
> enforcement → `req-tap-auth-orm-read-backstop` + the write backstop; dangerous-pattern static scan
> → `req-tap-auth-policy-9` (Rules A/B); "internal defect ≠ user denial" outcome vocabulary →
> `unguarded_operation` + the Flaw taxonomy; structured decision/denial records → `req-tap-auth-policy`
> denial logging; per-app/plugin self-declaration of auth objects → the per-app actor-declaration
> backlog. The un-landed remainders were **carried into `spec-tap-auth-v0.md`'s Backlog**: the
> capability-centric assurance **test-matrix + generated fail-closed harness** (with persona/resource
> catalogs and an optional OPA-export adapter), the **`policy_metadata_read`** primitive +
> `not_found_after_auth` existence-non-leakage, a **formal described exemption registry**, and
> **full decision records** (allow-logging + `policy_version`). Nothing further is actionable here.

## Philosophy

Authentication and authorization cannot be validated by informal review alone. TAP needs an
auth assurance surface that turns every meaningful access path into a named, testable contract:

- who is acting,
- how the actor was authenticated,
- which surface they entered through,
- which action they attempted,
- which resource shape they touched,
- which policy decision was expected,
- and whether the implementation failed closed when anything was missing or malformed.

The core security rule is simple: **unknown auth is failed auth**. An unregistered surface, an
unguarded graph chokepoint, an unbound request actor, or an unapproved production bypass is not a
normal denial. It is a code flaw or startup defect, and TAP must refuse to treat it as acceptable
runtime behavior.

This spec makes auth assurance surface-centric. Capabilities still matter, but the first question
is "which exact surface is this?" because surfaces are the places where authn/authz assumptions
enter the system, where plugin extensions attach, and where bypasses usually hide.

## Goals

- Define a durable assurance model covering both AuthN and AuthZ.
- Require a registered auth surface for every graph-touching entrypoint and chokepoint.
- Provide a declarative, described, machine-validatable matrix of expected auth behavior.
- Allow plugins to register their own surfaces without being able to overwrite or masquerade as
  another app or plugin.
- Fail closed in tests, CI, startup, and production when auth coverage is missing.
- Reserve a future ABAC/dimensions policy shape without implementing dimensions authorization in
  this phase.
- Reduce "ask an agent to inspect auth" into a repeatable validation surface that agents can still
  review, extend, and reason about.

## Non-Goals

- Implementing TAP dimensions-based authorization in v0.
- Introducing OPA/Rego as a production runtime dependency in v0.
- Emitting a graph node for every authorization decision in v0.
- Solving every direct ORM read path with runtime manager guards in v0.
- Permitting production auth bypasses for convenience.
- Introducing multi-tenancy.

## Roadmap Alignment

The active Rampart roadmap names AuthN as critical path and AuthZ as parallel path. This spec is
part of making that path shippable: auth is not complete when login works; auth is complete when TAP
can prove that every protected surface has a registered policy expectation and every unregistered
access path fails closed.

## Prior Art

This spec intentionally borrows shapes from established security practice without copying code:

- **OWASP ASVS**: coverage should be requirement-driven and include authentication, session, access
  control, and secure failure behavior.
- **OWASP Web Security Testing Guide**: authorization testing should include direct object access,
  privilege changes, forced browsing, and bypass attempts, not just happy paths.
- **NIST SP 800-162 ABAC**: future dimensions authorization maps naturally to subject, action,
  resource, and environment attributes.
- **OPA/Rego**: TAP should borrow the input-document and policy-as-data discipline, but not adopt an
  OPA runtime dependency for v0.

## Relationship To Existing Specs

- `tap_auth/specs/spec-tap-auth-v0.md` defines the auth system, actors, capabilities, providers,
  and policy API.
- `specs/spec-security-posture.md` defines the safe-default doctrine that this spec enforces.
- `specs/spec-tap-flaw-v0.md` defines how code flaws such as unguarded auth surfaces are reported.
- `specs/spec-tap-testing.md` defines the test organization conventions this assurance harness
  follows.
- `specs/spec-tap-boot-v0.md` defines the boot actor and boot sequencing this spec relies on.
- Future TAP Cares specs must expand this matrix when emitters, receivers, actions, schedules, and
  other system actors become first-class auth participants.

## Requirements

| Requirement | Status | Summary |
| --- | --- | --- |
| `req-tap-auth-assurance-scope` | Proposed | Cover AuthN and AuthZ end to end. |
| `req-tap-auth-assurance-surfaces` | Proposed | Every protected entrypoint/chokepoint has a registered surface. |
| `req-tap-auth-assurance-markers` | Proposed | Surface markers live next to active code as searchable comments. |
| `req-tap-auth-assurance-matrix` | Proposed | Declarative surface-centric matrix drives expected decisions. |
| `req-tap-auth-assurance-personas` | Proposed | Persona and resource catalogs are described and reusable. |
| `req-tap-auth-assurance-context` | Proposed | Runtime auth decisions require active surface context. |
| `req-tap-auth-assurance-gates` | Proposed | Multiple runtime gates fail closed on missing auth coverage. |
| `req-tap-auth-assurance-base-save` | Proposed | Graph-managed `BaseModel.save()` is a last-ditch write guard. |
| `req-tap-auth-assurance-decisions` | Proposed | Decisions emit structured records with stable reason codes. |
| `req-tap-auth-assurance-plugins` | Proposed | Plugins contribute owned, validated surface files. |
| `req-tap-auth-assurance-authn` | Proposed | AuthN provider states are part of the matrix. |
| `req-tap-auth-assurance-static-scan` | Proposed | Scanners find unregistered dangerous access patterns. |
| `req-tap-auth-assurance-bypass` | Proposed | Exemptions are debug/test only in v0. |
| `req-tap-auth-assurance-delegation` | Proposed | Delegated authorization is explicit, narrow, and auditable. |
| `req-tap-auth-assurance-dimensions-future` | Proposed | Reserve future dimensions/ABAC shape without enabling it. |
| `req-tap-auth-assurance-rollout` | Proposed | Phase rollout from inventory to runtime enforcement. |

## Assurance Scope

### `req-tap-auth-assurance-scope`

TAP auth assurance MUST cover both authentication and authorization.

AuthN coverage includes:

- anonymous requests,
- authenticated sessions,
- missing sessions,
- logout/session absence,
- inactive users,
- deactivated actors,
- request middleware actor binding,
- current Django admin/session login behavior,
- local username/password provider behavior,
- and provider-specific claims once providers such as Google OIDC land.

AuthZ coverage includes:

- surface entry decisions,
- service-layer decisions,
- graph read/write/delete/purge decisions,
- direct graph ORM access detection,
- plugin-owned surfaces,
- boot/system actors,
- and failure behavior when auth coverage is absent.

Graph-touching means any path that reads or mutates TAP-managed graph state through one of:

- grid service-layer APIs,
- Search/Gryphon dispatch,
- Entity/Edge ORM access,
- graph-managed `BaseModel` subclass ORM access,
- GRIFT import/removal paths,
- plugin helpers that reach graph state,
- web/API/panel/task/management command surfaces that delegate to the above.

Acceptance:

- The matrix has both AuthN and AuthZ dimensions.
- A change to an auth provider can be reviewed against this spec.
- A change to a graph access path can be reviewed against this spec.
- An unregistered graph-touching path is treated as a security defect, not a missing test nicety.

## Surface Registry

### `req-tap-auth-assurance-surfaces`

Every protected TAP surface MUST be declared in an auth surface registry entry before it is allowed
to perform protected work.

A surface is a concrete entrypoint or chokepoint where TAP can attach a stable identity to an access
attempt. Examples include:

- API route,
- web view,
- panel,
- service function,
- graph chokepoint,
- management command,
- task,
- collector,
- plugin helper,
- middleware boundary.

Surface entries are stored in one file per app or plugin:

- core app: `<app_label>/auth_surfaces.json`
- plugin: `plugins/<plugin_label>/auth_surfaces.json`

The file path and surface IDs MUST agree:

- A core app file may only declare entries whose `owner_app` is the app label and whose
  `surface_id` begins with `<app_label>.`.
- A plugin file may only declare entries whose owner is the plugin label and whose `surface_id`
  begins with `plugins.<plugin_label>.`.
- A file MUST NOT declare, overwrite, shadow, or alias a surface owned by another app or plugin.
- Duplicate `surface_id` values are startup defects.

Surface IDs are stable review handles. They SHOULD be short enough for logs and code review, but
specific enough to locate the code quickly.

Examples:

- `tap_api.search.execute`
- `tap_web.object.view`
- `tap_grid.gryphon.raw_execute`
- `tap_boot.auth_sync`
- `tap_boot.seed_import`
- `plugins.samsite.panel.ksi_scoreboard`

Each surface entry MUST include at minimum:

- `surface_id`
- `description`
- `owner_app` or `owner_plugin`
- `category`
- `code_marker`
- `actions`
- `resources`
- `authn_required`
- `actors`
- `deny_order`
- `tests`

Every entry and nested action/resource/test case MUST include a human-readable `description`.

Acceptance:

- Installed app/plugin surface files are discovered at startup and test collection time.
- Invalid naming, missing descriptions, duplicate IDs, or owner/path mismatches fail validation.
- Production startup refuses invalid surface registries.
- Test collection refuses invalid surface registries.

## Surface Markers

### `req-tap-auth-assurance-markers`

Each concrete surface MUST have exactly one searchable marker placed next to the active code that
implements the surface.

The v0 marker format is a comment:

```python
# tap-auth-surface: <surface_id>
```

The marker is a review affordance and scanner anchor. It is not the runtime enforcement mechanism by
itself.

Rules:

- The marker MUST match a declared `surface_id`.
- The declared entry's `code_marker` MUST point back to the marker location.
- One concrete surface gets one marker.
- Multiple markers for one surface are not allowed in v0.
- The future multi-marker use case is backlogged until there is real demand.

Acceptance:

- A reviewer can search for a `surface_id` and land on the owning code.
- A scanner can detect declared surfaces whose marker disappeared.
- A scanner can detect markers that do not appear in the registry.

## Surface Categories

Surface category values are closed in v0:

- `api_route`
- `web_view`
- `panel`
- `service_function`
- `graph_chokepoint`
- `management_command`
- `task`
- `collector`
- `plugin_helper`
- `middleware`

Future TAP Cares work MUST expand the actor/surface matrix when emitters, receivers, actions,
schedules, and run records become separately authorized actors or surfaces.

## Assurance Matrix

### `req-tap-auth-assurance-matrix`

TAP MUST maintain a declarative, surface-centric auth assurance matrix.

The matrix answers:

- for this surface,
- with this AuthN state,
- for this actor/persona,
- attempting this action,
- against this resource shape,
- under this context,
- what should happen?

The matrix input shape SHOULD remain compatible with the common ABAC/OPA-style structure:

```json
{
  "subject": {},
  "action": {},
  "resource": {},
  "environment": {},
  "surface": {}
}
```

TAP does not adopt OPA/Rego as a runtime dependency in v0. The compatibility is design discipline,
not an implementation commitment.

Schema files for the assurance artifacts live under `tap_auth/schemas/`. Expected schemas include:

- `auth_surface_registry.schema.json`
- `auth_persona_catalog.schema.json`
- `auth_resource_catalog.schema.json`
- `auth_assurance_matrix.schema.json`

Each surface entry MUST declare:

- allowed actions,
- resource labels,
- expected actor/persona outcomes,
- expected AuthN outcomes,
- allow cases,
- deny cases,
- expected reason codes,
- `lookup_order`,
- and `deny_order`.

The default `lookup_order` is `auth_before_resource`. A surface that needs to resolve any resource
metadata before authorization MUST declare that exceptional behavior explicitly. In v0, broad
resource-before-auth behavior is discouraged; future metadata preflight should use the reserved
`policy_metadata_read` primitive instead of ad hoc lookup.

`deny_order` MUST be explicit enough that tests can distinguish:

- unauthenticated access,
- missing actor binding,
- inactive/deactivated actor,
- missing capability,
- resource-not-found after authorization,
- and internal auth defects.

Every surface SHOULD include at least one allow case and one deny case. If a surface is intentionally
never allowed in v0, it MUST declare `allow_cases: []` with a description explaining why the surface
exists and why no actor may use it yet.

Outcome vocabulary:

- `200_allowed`
- `401_unauthenticated`
- `403_unauthorized`
- `404_not_found_after_auth`
- `500_internal_defect`

Deny reason vocabulary:

- `unauthenticated`
- `missing_actor`
- `inactive_actor`
- `capability_denied`
- `resource_not_found_after_auth`
- `unregistered_surface`
- `unguarded_chokepoint`
- `exemption_not_allowed`
- `internal_authz_error`

Acceptance:

- Matrix entries are JSON, not code.
- Matrix entries validate against a JSON Schema before use.
- Matrix entries include descriptions at every review-relevant level.
- Expected outcomes distinguish user denials from internal auth defects.
- Missing matrix coverage fails tests, and later CI.

## Personas And Resources

### `req-tap-auth-assurance-personas`

The assurance harness MUST use described persona and resource catalogs.

Required v0 personas:

- `anonymous`
- `authenticated_no_caps`
- `ordinary_human`
- `tap_admin`
- `tap_bootloader`
- `tap_collector`
- `tap_scheduler`
- `inactive_actor`
- `deactivated_actor`
- `grid_read_only`
- `grid_write_only`
- `grid_delete_only`

The `tap_admin` persona represents TAP-granted administrative capability. Django `is_superuser`
alone MUST NOT be an allow condition for TAP service or graph access.

Each persona entry MUST include:

- stable persona ID,
- description,
- AuthN state,
- actor state,
- assigned capabilities/groups,
- expected use cases,
- and whether it is a human or system actor.

Resources are abstract labels backed by fixtures. Each resource entry MUST include:

- stable resource ID,
- description,
- resource kind,
- fixture construction rule,
- expected owner/scope attributes where relevant,
- and whether the resource exists, is missing, tombstoned, or intentionally inaccessible.

Acceptance:

- Matrix cases reference catalog IDs instead of inventing ad hoc actors/resources.
- Every persona and resource has a description.
- Resource labels can later gain dimensions attributes without changing the matrix shape.

## AuthN Coverage

### `req-tap-auth-assurance-authn`

AuthN behavior MUST be represented in the same assurance system as AuthZ behavior.

The v0 AuthN matrix MUST cover:

- anonymous request reaches protected surface,
- authenticated active user reaches protected surface,
- authenticated active user without TAP actor binding,
- authenticated inactive user,
- deactivated TAP actor,
- missing session,
- logout/session invalidation,
- middleware actor binding success,
- middleware actor binding failure.

For protected graph access, `anonymous` is an explicit AuthN state, not an implicit missing-user
fallback. An authenticated request with no TAP actor binding MUST be classified as `missing_actor`.
No protected path may treat `user=None`, missing actor context, or failed actor binding as a
permissive system actor.

Provider-specific assurance files MAY extend the core AuthN matrix. For example:

- `tap_auth/authn_providers.local_password.json`
- `tap_auth/authn_providers.google_oidc.json`

When Google OIDC lands, its provider assurance MUST include the provider's security-relevant claims
and failure modes, including hosted-domain handling based on provider-returned claims rather than
request-side hints.

Acceptance:

- AuthN failures feed expected `401_unauthenticated`, `403_unauthorized`, or internal defect outcomes
  as appropriate.
- Provider-specific tests cannot merge without provider-specific assurance entries.
- AuthN provider assurance is reviewed with the same seriousness as AuthZ policy changes.

## Surface Context

### `req-tap-auth-assurance-context`

Runtime authorization MUST require an active registered surface context.

TAP MUST introduce a surface context concept alongside caller/actor context. The runtime shape is
reserved as:

- `surface_id`
- `surface_kind`
- `entrypoint`
- `plugin`
- `request_id`
- `task_id`
- `declared_actions`

Entrypoints SHOULD use decorators where the surface is static. Dynamic context managers are allowed
where the current code shape requires them, including:

- generic dispatch,
- plugin panel dispatch,
- management command loops,
- task runners,
- collector execution,
- focused tests.

Dynamic context is not a bypass. It is still required to name a registered surface.

Graph chokepoints MUST fail closed if no active registered surface context exists, even when a caller
context or capability decision is present.

Nested surfaces are allowed only as recorded context transitions:

- `entry_surface_id` records the original entry surface,
- `current_surface_id` records the currently executing surface,
- delegated decisions record both surfaces.

Acceptance:

- Missing surface context at a protected graph chokepoint raises `unregistered_surface` or
  `unguarded_chokepoint`, not a normal denial.
- Direct service tests use an explicit test surface such as `tap_test.direct_service`.
- A valid actor alone is insufficient to touch graph state.

## Runtime Gates

### `req-tap-auth-assurance-gates`

TAP auth MUST use multiple gates. A single upper-layer check is not enough.

Required v0 gates:

- entrypoint surface registration,
- policy authorization decision,
- graph chokepoint surface verification,
- graph service-layer capability enforcement,
- Search/Gryphon dispatch enforcement,
- GRIFT import/removal enforcement,
- last-ditch graph-managed model write guard.

Static gates are also required:

- registry validation,
- marker validation,
- dangerous pattern scanner,
- matrix coverage tests.

Unknown graph access MUST fail closed in production. If an unregistered surface slips through tests,
runtime must still refuse the access or refuse boot.

Acceptance:

- A bypass of the web/API layer still hits graph chokepoint enforcement.
- A direct service call still requires caller and surface context.
- A direct graph-managed model write still hits the last-ditch save guard.
- Missing coverage never becomes a best-effort warning in production.

## BaseModel Save Guard

### `req-tap-auth-assurance-base-save`

Graph-managed `BaseModel.save()` MUST become a last-ditch write guard.

The guard applies to TAP graph-managed node and edge model classes, not to every Django model in the
project.

The guard MUST fail closed when a graph-managed model is saved without:

- a named actor/caller context,
- an active registered surface context,
- and an allowed system/migration context where applicable.

The guard is not the primary policy engine. It should catch unsafe writes that bypass service-layer
policy, not replace service-layer authorization.

Known exclusions in v0:

- auth management tables such as users, capabilities, and groups,
- migrations that are explicitly running under an approved system context,
- boot-time auth sync under `tap_bootloader`,
- debug/test-only explicitly approved bypass scopes.

Acceptance:

- `BaseModel.save()` cannot silently write graph-managed state from ambient code.
- Production bypass of this guard is not allowed in v0.
- The guard reports an auth flaw/defect rather than pretending the user merely lacks permission.

## Decision Records

### `req-tap-auth-assurance-decisions`

Every authorization decision MUST produce a structured decision record.

The v0 record target is logs plus test-captured records. TAP does not create graph nodes for every
decision in v0.

Required fields:

- `surface_id`
- `entry_surface_id`
- `current_surface_id`
- `actor_id`
- `persona_id` when test-generated,
- `action`
- `resource_ref`
- `decision`
- `reason`
- `policy_version`
- `delegated_from` when applicable
- `request_id` or `task_id` when available

`policy_version` is derived from the matrix hash plus the capability registry hash.

Decision values:

- `allow`
- `deny`
- `delegated_allow`
- `internal_defect`

Acceptance:

- Tests can assert decision records without scraping prose logs.
- Production logs include enough data to reconstruct why a protected access was allowed or denied.
- Delegated decisions are distinguishable from local policy decisions.

## Static Scan And Coverage

### `req-tap-auth-assurance-static-scan`

TAP MUST scan for graph-touching patterns that are likely to require registered surfaces.

The scanner MUST NOT silently invent surfaces. It may identify candidate unregistered access paths,
but a human/spec change must declare the surface.

Dangerous patterns include:

- direct `Entity` ORM access,
- direct `Edge` ORM access,
- direct graph-managed `BaseModel` subclass ORM access,
- direct Search/Gryphon execution,
- GRIFT import/removal calls,
- service-layer writes outside registered service surfaces,
- management commands touching graph state,
- tasks/collectors touching graph state.

The scanner MUST produce actionable locations and expected marker/surface remediation.

Acceptance:

- Unmarked graph-touching code fails tests.
- Future CI must fail on scanner errors.
- Scanner findings are distinct from runtime policy denials.

## Plugin Integration

### `req-tap-auth-assurance-plugins`

Installed plugins MUST be able to register their own auth surfaces and assurance cases.

Plugin rules:

- one `auth_surfaces.json` per plugin,
- surface IDs start with `plugins.<plugin_label>.`,
- entries cannot name or overwrite another plugin's surfaces,
- entries validate against the same schema as core app surfaces,
- installed plugin entries contribute pytest cases automatically,
- invalid installed plugin auth declarations refuse startup.

This is deliberately plugin-owned. A core TAP spec should not need to enumerate every plugin surface.
The core provides the schema, loader, scanner, and enforcement rules; plugins own their declarations.

Acceptance:

- Installing a plugin can increase auth assurance coverage without editing core TAP files.
- Removing a plugin removes its cases.
- A plugin cannot claim another plugin's auth namespace.

## Internal Bypass And Exemptions

### `req-tap-auth-assurance-bypass`

Production auth bypasses are forbidden in v0.

Allowed v0 exemption modes:

- DEBUG-only,
- test-only.

An exemption MUST declare:

- reason,
- owner,
- scope,
- allowed surfaces,
- allowed actions,
- expiration or review note,
- and why normal authorization cannot be used.

An exemption is a quarantine, not a hidden permission system. If an exemption is attempted in
production, TAP MUST fail closed with `exemption_not_allowed`.

Migration/system context is not the same as bypass. When a system process touches TAP data, it should
normally run as a named program actor through a named surface.

Required boot/system surfaces include:

- `tap_boot.auth_sync`
- `tap_boot.seed_import`
- `tap_boot.spawn_admin_bridge`
- `tap_system.migration`

The v0 system actor is `tap_bootloader`. The boot backlog SHOULD note that a dedicated
`tap_migrator` actor may be introduced later if real demand appears.

Acceptance:

- No production setting can silently disable auth enforcement.
- Debug/test bypasses are searchable, described, and scoped.
- Boot and migration paths are named surfaces, not ambient magic.

## Delegation

### `req-tap-auth-assurance-delegation`

Authorization delegation MUST be explicit, narrow, and recorded.

The default is no delegation. A lower-level surface MUST declare whether it accepts a decision made
by a higher-level surface. Some lower-level calls may never accept delegated decisions.

Delegation rules:

- decision ledger keys include `surface_id`, `actor_id`, `action`, and `resource_ref`;
- delegation may only apply to the same or narrower resource scope;
- lower-level surfaces must opt in to accepting specific higher-level decisions;
- delegated decisions record `delegated_from`;
- delegated decisions use `decision="delegated_allow"`;
- missing delegation metadata fails closed.

Globally non-delegable v0 actions:

- `grid.purge`
- `auth.manage_users`
- `auth.manage_providers`
- `auth.manage_capabilities`

Deletes SHOULD require local decisions unless a later focused design proves a safe delegation shape.

Nested surface authorization is a high-risk area. TAP MUST backlog a focused deep dive before
allowing broad nested delegation. V0 should allow nested delegation only for specific known,
registered, gated cases.

Acceptance:

- A high-level allow cannot accidentally authorize arbitrary lower-level graph access.
- Lower-level surfaces can refuse delegated authorization.
- Every delegated allow is visible in decision records.

## Dimensions And Future ABAC

### `req-tap-auth-assurance-dimensions-future`

TAP MUST reserve the shape for future dimensions authorization, but MUST NOT implement dimensions
AuthZ in v0.

Future dimensions AuthZ maps to ABAC-like resource attributes:

- subject attributes from actor/persona/capabilities,
- action attributes from requested operation,
- resource attributes from Entity metadata and dimensions,
- environment attributes from request/task/system context,
- surface attributes from the registered surface.

The matrix shape SHOULD include dormant fields for:

- `resource.attributes`
- `resource.dimensions`
- `environment`
- `surface`

Future policy may require reading minimal resource metadata before full authorization. This spec
reserves a future primitive named `policy_metadata_read`.

`policy_metadata_read` MUST be narrowly defined before use:

- exactly which fields may be read,
- which surfaces may use it,
- which actor context is required,
- how it avoids leaking existence or sensitive metadata,
- and how it composes with 404-after-auth behavior.

Acceptance:

- V0 schemas can carry dormant dimensions fields without enforcing them.
- No code path may claim dimensions authorization is implemented until a future spec says so.
- Future ABAC design has a reserved place instead of needing a matrix rewrite.

## Test Harness

The core dynamic test target is:

- `tap_auth/tests/test_auth_assurance_matrix.py`

The test harness MUST be generated at pytest collection time from validated JSON declarations. It
MUST NOT commit generated Python test files.

Harness behavior:

- load core app surface files,
- load installed plugin surface files,
- load persona catalog,
- load resource catalog,
- validate schemas,
- parametrize allow/deny/authn cases,
- capture decision records,
- assert expected outcomes and reasons,
- fail on unregistered markers,
- fail on markerless graph-touching candidates.

Acceptance:

- Adding a surface without adding matrix coverage fails tests.
- Adding a provider without provider assurance entries fails relevant tests.
- Installed plugin cases are exercised automatically.

## Rollout

### `req-tap-auth-assurance-rollout`

Rollout phases:

1. `inventory_only`
   - Surface files and markers exist.
   - Scanner reports findings.
   - Runtime does not yet enforce every chokepoint.

2. `test_enforced`
   - Matrix tests fail on missing coverage.
   - Marker and registry validation fail tests.
   - Plugin declarations contribute tests.

3. `runtime_enforced`
   - Graph chokepoints require registered surface context.
   - Missing surface context fails closed.
   - Production refuses invalid registry state.

4. `basemodel_guarded`
   - Graph-managed `BaseModel.save()` enforces last-ditch write guard.
   - Bypass attempts are debug/test only.

Future CI:

- CI MUST run the matrix tests and scanner.
- CI MUST block unregistered surfaces.
- CI SHOULD include a formal approval/review loop for auth surface, capability, provider, and
  delegation changes.

V0 Done-Test:

- Core app graph-touching surfaces are registered.
- Surface markers resolve to code.
- The persona/resource catalogs include descriptions.
- The matrix includes at least one allow and deny case for normal protected surfaces.
- Installed plugin surface files are discoverable and validated.
- Unknown graph-touching access fails tests.
- Runtime graph chokepoints fail closed when surface context is missing.
- Decision records are emitted and assertable in tests.
- Production bypasses are refused.
- Backlog notes exist for manager guards, multi-marker support, nested delegation deep dive, CI
  approval loop, TAP Cares actor expansion, and possible `tap_migrator`.

## Backlog

The following items are intentionally not v0 implementation requirements, but are security-relevant
and must remain visible:

- **Manager read guards**: investigate runtime manager/queryset guards for direct graph ORM reads.
  The investigation must distinguish policy metadata reads, migrations, auth sync, fixtures, tests,
  and normal user reads.
- **Nested delegation deep dive**: model bypass risks when higher-level surfaces authorize lower
  levels, especially across plugin and graph chokepoint boundaries.
- **Multi-marker surfaces**: revisit only if real code demand appears.
- **Dedicated `tap_migrator` actor**: consider if migration work needs identity separate from
  `tap_bootloader`.
- **TAP Cares actor expansion**: add emitters, receivers, actions, schedules, and other program
  actors when they become active auth participants.
- **CI approval loop**: once CI exists, require formal review/approval for changed auth surfaces,
  capabilities, providers, and delegation rules.
- **OPA adapter experiment**: consider an offline adapter that can export TAP matrix cases into an
  OPA-style input corpus for external policy analysis. Do not add OPA runtime dependency without a
  separate decision.
- **Decision graph nodes**: consider whether selected decision records should become graph objects
  for audit or forensics. Do not emit every decision to the graph by default.
