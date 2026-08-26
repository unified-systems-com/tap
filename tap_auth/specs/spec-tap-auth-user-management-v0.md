# TAP Auth — User Management Surface v0 Specification

## Philosophy

TAP needs a first-party way for an operator to **see who can act on an instance and change it** — view the roster of principals, inspect one, and run the everyday account-management actions (deactivate, grant/revoke a role, force logout, pre-authorize a new person). Today the only surfaces are Django admin (deliberately *not* TAP's long-term operator UX, `spec-administrivia-v0.md`) and hand-editing the boot profile's `auth.initial_grants`. This spec defines the proper surface.

Two doctrines shape it:

> **`tap_auth` owns the behavior; `administrivia` hosts the surface.** The read API, the control verbs, the capabilities, and the safety invariants are `tap_auth`'s and live here. The pages, panels, templates, routes, and navigation are `administrivia`'s (per the scope requirement of `spec-administrivia-v0.md`, in the administrivia plugin repo). This keeps account-management semantics next to the models and services that govern them while letting TAP grow one coherent operator UI.

> **Principals are off-grid; their management is service-layer.** Users, groups, and `ExternalIdentity` are Django auth + `tap_auth` management tables, **not** TAP-managed graph entities (CLAUDE.md; `spec-tap-auth-v0.md` Backlog "on-grid expression of users"). So this surface is **not** a Gryphon/graph panel: it reads through a capability-gated `tap_auth` service-layer API over the auth tables, and mutates through gated, audited service verbs — never direct ORM from a panel, never grid traversal.

Everything here is a management plane over off-grid state. The forward-looking note (`req-tap-auth-usermgmt-actions-as-intent`) keeps the door open to expressing the management *actions* as on-grid intents later, without putting the principal *records* on the grid.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | See Who Can Act | An operator can view the full principal roster and inspect any one principal without shell or Django admin. |
| 2. | Run The Everyday Verbs | Deactivate/reactivate, grant/revoke roles, force logout, and pre-authorize a person — the table-stakes account-management actions. |
| 3. | Safe By Construction | The surface cannot lock out the last admin, cannot grant a program-actor role to a person, and cannot edit a built-in program actor. |
| 4. | Gated And Audited | Reading the roster and every mutation are capability-gated and emit an audited security event. |
| 5. | TAP-Native, Not Django Admin | Built on TAP pages/panels + the `tap_auth` service layer, hosted by `administrivia`. |

## Roadmap Alignment

Supports `plan/road-rampart.md` launch-readiness: once a customer (or a guest like an early adopter) logs in, the operator needs to *manage* those accounts — admit, scope, and revoke — without editing config-as-code or dropping to a shell. Read-only roster first (cheap, high-value); control verbs second.

## Relationship to Other Specs

- `spec-tap-auth-v0.md` — owns the underlying primitives this surface drives: the canonical `User`/actor model (`req-tap-auth-actor-model`), roles and the human/program assignment boundary (`req-tap-auth-roles`), the `initial_grants` login path this surface is the runtime counterpart to (`req-tap-auth-boot`), session invalidation (`req-tap-auth-sessions`), the policy gate (`req-tap-auth-policy`), and the deferred on-grid-users decision (Backlog).
- `spec-administrivia-v0.md` (administrivia plugin repo) — hosts the pages/panels and carries the index entry pointing here (its Hosted Surface Spec Index requirement).

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-auth-usermgmt-ownership | [Ownership Split](#ownership-split) | Proposed | tap_auth owns behavior/API/caps; administrivia hosts panels/routes |
| req-tap-auth-usermgmt-offgrid-source | [Off-Grid Data Source](#off-grid-data-source) | Proposed | Reads/writes via gated tap_auth service layer over auth tables, not Gryphon |
| req-tap-auth-usermgmt-read-api | [Principal Read API](#principal-read-api) | Proposed | Gated `list`/`detail` returning the joined principal view; new `auth.read_users` cap |
| req-tap-auth-usermgmt-roster | [Roster Panel](#roster-panel) | Proposed | Searchable/sortable roster; kind/role/state columns; program actors distinct + read-only |
| req-tap-auth-usermgmt-detail | [Principal Detail Panel](#principal-detail-panel) | Proposed | One principal: identities, roles, sessions, action affordances, audit timeline |
| req-tap-auth-usermgmt-lifecycle | [Account Lifecycle + Banhammer](#account-lifecycle--banhammer) | Proposed | Deactivate/reactivate verbs; the one-click ban = deactivate + kill sessions |
| req-tap-auth-usermgmt-role-grants | [Role Grant/Revoke](#role-grantrevoke) | Proposed | Admin counterpart to initial_grants; honors the human-assignable boundary |
| req-tap-auth-usermgmt-sessions | [Session Control](#session-control) | Proposed | Force-logout one session / everywhere; reuses req-tap-auth-sessions |
| req-tap-auth-usermgmt-invite | [Invite / Pre-Authorize](#invite--pre-authorize) | Proposed | IdP-world "add user" = pre-authorize an email→role; pending-invite view |
| req-tap-auth-usermgmt-safeguards | [Safety Rails](#safety-rails) | Proposed | Last-admin, no self-lockout, program-actor read-only, destructive-action confirm |
| req-tap-auth-usermgmt-audit | [Audited Actions](#audited-actions) | Proposed | Every read/mutation an audited security event; surfaced in the detail timeline |
| req-tap-auth-usermgmt-actions-as-intent | [Actions As Grid Intent (Forward-Looking)](#actions-as-grid-intent-forward-looking) | Proposed | Verbs are request-agnostic so a future grid-intent consumer can drive them |

---

### Ownership Split
----
RID: `req-tap-auth-usermgmt-ownership`
Status: `Proposed`

`tap_auth` owns the user-management *behavior*; `administrivia` *hosts* the surface.

#### Implementation

- The read API, control verbs, capabilities, and safety invariants are defined and implemented in `tap_auth` and specified here.
- The pages, panels, templates, static assets, routes, and navigation live under `administrivia` (proposed `plugins/administrivia/tap_auth/panels/...`, route `/administrivia/users`), mirroring how `administrivia` already hosts the `tap_cares` operator panels.
- `administrivia` adds a Hosted Surface Spec Index row pointing at this spec (per that same requirement); it does not re-specify behavior.
- Django admin remains the out-of-band recovery floor (`spec-tap-auth-v0.md` Policy API recovery floor), not the operator UX for this.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-usermgmt-ownership-1 | Behavior In tap_auth | Proposed | The read API, verbs, capabilities, and invariants are tap_auth code/spec. | |
| req-tap-auth-usermgmt-ownership-2 | Surface In administrivia | Proposed | Pages/panels/routes live under administrivia and reference this spec. | |

---

### Off-Grid Data Source
----
RID: `req-tap-auth-usermgmt-offgrid-source`
Status: `Proposed`

The surface reads and writes principals through the `tap_auth` service layer over the Django auth + `tap_auth` tables — never Gryphon, never direct ORM from a panel.

#### Implementation

- Principals (`User`), groups/roles, `ExternalIdentity`, and sessions are off-grid (CLAUDE.md excludes auth models from the BaseModel/Entity spine). They are not queryable via Gryphon and have no entity nodes.
- Therefore the panel data path is **panel → gated tap_auth service API → auth tables**, not panel → Gryphon → grid. The render gate is the relevant `auth.*` capability (below), **not** `grid.read`.
- Mutations go through gated, audited service verbs (the same no-direct-ORM discipline TAP applies to grid mutations applies here to auth mutations).
- This is the runtime expression of the deferred "on-grid users" decision (`spec-tap-auth-v0.md` Backlog): records stay off-grid; only the *management actions* are a future grid-intent candidate (`req-tap-auth-usermgmt-actions-as-intent`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-usermgmt-offgrid-source-1 | No Gryphon For Principals | Proposed | Principal data is read via the tap_auth service API, not Gryphon/grid traversal. | |
| req-tap-auth-usermgmt-offgrid-source-2 | No Direct ORM From Panels | Proposed | Panels never read/write auth tables directly; they call gated service functions. | |

---

### Principal Read API
----
RID: `req-tap-auth-usermgmt-read-api`
Status: `Proposed`

A capability-gated `tap_auth` service-layer read API returns the joined principal view the surface renders.

#### Implementation

- `list_principals(...)` and `get_principal_detail(id)` return a composed view: display name + email, `user_kind` (human/program), role/group memberships, active vs. `deactivated_at` state (+ reason/actor), last login, linked external identities (`provider`, redacted subject, last seen), and live session count.
- Gated by a **new `auth.read_users` capability** (risk: medium). This splits **read** ("see who has access") from **manage** (`auth.manage_users`, high) so a read-only auditor role can hold the roster without account control — the standard read/write capability split. `auth.read_users` is added to the capability registry and to the appropriate roles when this is built.
- `list_principals` supports server-side filter/sort/pagination params (so the surface never fetches the whole table to filter in the panel — the same data-filtering-at-the-query-layer discipline the grid read backstop follows).
- Subjects/secrets are never returned in full (redaction consistent with `req-tap-auth-external-identity`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-usermgmt-read-api-1 | Gated Read | Proposed | The read API authorizes `auth.read_users` before returning principal data. | |
| req-tap-auth-usermgmt-read-api-2 | Read/Manage Split | Proposed | `auth.read_users` (view) is separable from `auth.manage_users` (mutate). | |
| req-tap-auth-usermgmt-read-api-3 | Joined Principal View | Proposed | The detail view composes identity, kind, roles, state, last login, providers, sessions. | |
| req-tap-auth-usermgmt-read-api-4 | Query-Layer Filtering | Proposed | Filter/sort/pagination are applied in the query, not post-fetch in the panel. | |

---

### Roster Panel
----
RID: `req-tap-auth-usermgmt-roster`
Status: `Proposed`

A roster panel lists every principal with the columns an operator needs to triage access at a glance.

#### Implementation

- Columns: display name/email, kind (human/program), roles, state (active / deactivated / no-roles), linked provider, last login. Search by email/name; filter by kind/role/state; sort; paginate.
- **Program actors** (`tap_bootloader`, `tap_cares.*`, `tap_test`) appear in the roster — honest, since they are real principals with authority — but are visually distinct and **read-only** (no action affordances; see `req-tap-auth-usermgmt-safeguards`).
- A "no roles / cannot act" state is surfaced explicitly (an authenticated user with no capabilities is a real, confusing state worth showing).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-usermgmt-roster-1 | Triage Columns | Proposed | Roster shows kind, roles, state, provider, last login, with search/filter/sort. | |
| req-tap-auth-usermgmt-roster-2 | Program Actors Read-Only | Proposed | Program actors are shown but carry no mutation affordances. | |

---

### Principal Detail Panel
----
RID: `req-tap-auth-usermgmt-detail`
Status: `Proposed`

A detail panel shows one principal in full and is the home for the management actions.

#### Implementation

- Shows: identity (display name, email, kind), linked external identities (provider + redacted subject + last seen), role memberships, active/deactivated state with reason and acting admin, live sessions, and an audit timeline of management actions taken on this principal (`req-tap-auth-usermgmt-audit`).
- Hosts the action affordances (lifecycle, role grant/revoke, session control) for human principals, each behind the relevant capability and a confirmation for destructive ones.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-usermgmt-detail-1 | Full Principal View | Proposed | Detail composes identities, roles, sessions, state, and an action timeline. | |
| req-tap-auth-usermgmt-detail-2 | Actions Live Here | Proposed | Lifecycle/role/session affordances are hosted on the detail panel, gated + confirmed. | |

---

### Account Lifecycle + Banhammer
----
RID: `req-tap-auth-usermgmt-lifecycle`
Status: `Proposed`

Deactivate and reactivate are gated, audited, request-agnostic service verbs; the one-click **ban** is the composite everyone reaches for.

#### Implementation

- `deactivate_principal(target, *, reason, actor)` / `reactivate_principal(target, *, actor)` — gated by `auth.manage_users`, audited, setting/clearing the full deactivation trio (`is_active`, `deactivated_at`, `deactivated_reason`, `deactivated_by_actor_id`) consistently with the "one definition of active" rule the built-in sync already enforces.
- **The banhammer** is a first-class composite action: deactivate the account **and** invalidate all its sessions in one operator gesture (`req-tap-auth-usermgmt-sessions`), so a banned user is both blocked from future login and kicked out of any live session immediately — the actual behavior an operator means by "ban this person."
- Deactivation never deletes — it is reversible and audited (no hard-delete of principals from this surface in v0; that is a separate, heavier decision).
- Verbs take no `HttpRequest` (see `req-tap-auth-usermgmt-actions-as-intent`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-usermgmt-lifecycle-1 | Gated Deactivate/Reactivate | Proposed | Lifecycle verbs require `auth.manage_users`, are audited, and set the full deactivation trio. | |
| req-tap-auth-usermgmt-lifecycle-2 | Banhammer Composite | Proposed | A single "ban" action deactivates AND invalidates all the target's sessions. | |
| req-tap-auth-usermgmt-lifecycle-3 | Reversible, Not Deleted | Proposed | Deactivation is reversible; no hard-delete of principals from this surface in v0. | |

---

### Role Grant/Revoke
----
RID: `req-tap-auth-usermgmt-role-grants`
Status: `Proposed`

Granting and revoking a principal's roles from the UI — the runtime, admin-driven counterpart to the boot-time `initial_grants` login path.

#### Implementation

- `grant_role(target, role, *, actor)` / `revoke_role(target, role, *, actor)` — gated by `auth.manage_users`, audited, add/remove the protected group for the role.
- **Honors the human/program assignment boundary** (`req-tap-auth-roles`): only `HUMAN_ASSIGNABLE_ROLES` may be granted to a person here — the admin UI can no more grant `tap_bootloader` to a human than `initial_grants` can. Reuses `is_login_grantable` / `HUMAN_ASSIGNABLE_ROLES`; an attempt to grant a non-human role is refused, not silently dropped.
- Roles offered in the UI are the human-assignable set (`tap_admin`, `tap_viewer`, future human roles), each shown with its role description so the operator grants from informed context.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-usermgmt-role-grants-1 | Gated Grant/Revoke | Proposed | Role verbs require `auth.manage_users` and are audited. | |
| req-tap-auth-usermgmt-role-grants-2 | Human-Assignable Only | Proposed | Only human-assignable roles are grantable to a person; program roles are refused. | |

---

### Session Control
----
RID: `req-tap-auth-usermgmt-sessions`
Status: `Proposed`

Force-logout surfaced in the UI, reusing the existing session-invalidation primitives.

#### Implementation

- Surfaces `req-tap-auth-sessions` invalidation as operator actions: "sign out everywhere" (all the principal's sessions) and "end this session" (one), gated by `auth.manage_sessions` (the existing incident-response banhammer capability, deliberately separable from `auth.manage_users` so an IR role can hold it without full account control).
- The account banhammer (`req-tap-auth-usermgmt-lifecycle`) composes this; it is also available standalone (kick someone out without deactivating — e.g. a shared-device logout).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-usermgmt-sessions-1 | Force Logout | Proposed | Operator can end one session or all of a principal's sessions, gated by `auth.manage_sessions`. | |

---

### Invite / Pre-Authorize
----
RID: `req-tap-auth-usermgmt-invite`
Status: `Proposed`

In an IdP-driven world there is no "create a password account" — **"add a user" means pre-authorizing an email so that person can log in and lands with the right role.**

#### Implementation

- An "invite / pre-authorize" action records an email → role(s) pre-authorization (the runtime, UI-driven equivalent of a profile `initial_grants` entry + the provider `allowed_emails` admission), so the next time that person completes IdP login they are admitted and granted the chosen human-assignable role(s).
- A **pending pre-authorizations** view shows emails that are authorized but have not yet logged in (so an operator can see "invited but not joined").
- Same boundary as role grants: only human-assignable roles; gated by `auth.manage_users`; audited.
- This does not send email in v0 (no mail dependency assumed); it establishes the authorization. Actual notification/email is a later nicety.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-usermgmt-invite-1 | Pre-Authorize An Email | Proposed | Operator can pre-authorize an email→role(s) so the person is admitted + granted on first IdP login. | |
| req-tap-auth-usermgmt-invite-2 | Pending View | Proposed | Pre-authorized-but-not-yet-joined emails are visible. | |

---

### Safety Rails
----
RID: `req-tap-auth-usermgmt-safeguards`
Status: `Proposed`

The guardrails everyone who manages users needs — the surface must make the dangerous mistakes impossible, not merely discouraged.

#### Implementation

- **Last-admin invariant (runtime).** The surface refuses to deactivate, ban, or admin-revoke the **last active human `tap_admin`** — the runtime counterpart to the boot-time invariant (`req-tap-auth-boot`). The action is blocked with a clear reason, not warned-then-allowed.
- **No self-lockout.** An operator cannot deactivate/ban themselves or revoke their own last admin role in a way that would lock them out; self-destructive actions are refused (or require an explicit, separate confirmation that still respects the last-admin invariant).
- **Program actors are read-only.** Built-in program actors (`tap_bootloader`, `tap_cares.*`, `tap_test`) cannot be deactivated, role-edited, or banned from this surface — they are hard-synced and protected (`req-tap-auth-builtins`); the surface offers no affordance to touch them.
- **Human-assignable boundary** on every role grant (`req-tap-auth-usermgmt-role-grants`).
- **Confirmation for destructive actions** (ban, deactivate, role revoke, sign-out-everywhere) — an explicit confirm step, since these are immediate and affect another person's access.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-usermgmt-safeguards-1 | Last Admin Protected | Proposed | The surface refuses any action that would remove the last active human admin. | |
| req-tap-auth-usermgmt-safeguards-2 | No Self-Lockout | Proposed | An operator cannot lock themselves out via self-deactivation/self-revoke. | |
| req-tap-auth-usermgmt-safeguards-3 | Program Actors Untouchable | Proposed | Built-in program actors have no mutation affordances on this surface. | |
| req-tap-auth-usermgmt-safeguards-4 | Destructive Confirm | Proposed | Ban/deactivate/revoke/sign-out-everywhere require explicit confirmation. | |

---

### Audited Actions
----
RID: `req-tap-auth-usermgmt-audit`
Status: `Proposed`

Every read and mutation is an auditable security event — managing access is exactly the activity an audit trail exists for.

#### Implementation

- Each control verb emits a structured security event (acting admin, action, target principal, role/reason, timestamp; subjects redacted), consistent with the rest of `tap_auth`'s actor-aware logging (`req-tap-auth-logging`).
- The principal detail panel surfaces the per-principal action timeline from these events ("deactivated by George on …; granted tap_viewer by …").
- Roster/detail **reads** of the principal API are themselves attributable (who viewed the roster), at minimum at the policy-gate log level.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-usermgmt-audit-1 | Mutations Audited | Proposed | Every control verb emits a structured, redacted security event. | |
| req-tap-auth-usermgmt-audit-2 | Per-Principal Timeline | Proposed | The detail panel shows the audited action history for that principal. | |

---

### Actions As Grid Intent (Forward-Looking)
----
RID: `req-tap-auth-usermgmt-actions-as-intent`
Status: `Proposed`

The management *actions* are a future candidate for the grid-intent pattern, even though the principal *records* stay off-grid.

#### Implementation

- Build the control verbs (`deactivate_principal`, `grant_role`, etc.) **request-agnostic** — no `HttpRequest` parameter, all inputs explicit — so the same verb is callable today by an `administrivia` web view and later by a grid-intent consumer.
- The deferred shape (`spec-tap-auth-v0.md` Backlog "on-grid expression of users — records vs. actions"): an operator proposes a management *intent* node on the grid ("deactivate user X", "grant Sam tap_viewer"), and a user-management service actor consumes it and performs the off-grid mutation — the same request/response shape as collector-job creation, giving admin actions grid history / FLIP / search / AI-legibility and the two-decision authZ split (capability to *propose* vs. bounded actor that *services*). This is **not** v0; the v0 obligation is only that the verbs be request-agnostic so this stays additive, not a rewrite.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-auth-usermgmt-actions-as-intent-1 | Request-Agnostic Verbs | Proposed | Control verbs take explicit inputs, no `HttpRequest`, so a web view or intent-consumer can drive them. | |

---

## Backlog

- **Bulk actions** — select multiple principals → deactivate / grant-role / sign-out, with the same safety rails applied per-target.
- **Impersonation / "view as"** — deliberately excluded from v0 (high blast radius); if ever added it is its own capability, heavily audited, and never bypasses the policy gate.
- **Email notification on invite** — v0 establishes authorization only; sending the invite email needs a mail dependency and is deferred.
- **Export / reporting** — CSV/JSON export of the roster behind `auth.read_users`.
- **Local password account management** — reset/resend for local users (mostly N/A in the IdP world; relevant only where local auth is enabled as the recovery floor, `req-tap-auth-local`).
- **Per-collector / per-plugin actor visibility** — once the plugin refactor lands distinct per-collector actors (`spec-tap-auth-v0.md` Backlog), the roster's program-actor view grows to show them with attribution.
- **On-grid management intents** — the full realization of `req-tap-auth-usermgmt-actions-as-intent`, gated on the grid-intent (`ask`/`action`/`emitter`) node concepts.

## Status Vocabulary

See `spec-tap-auth-v0.md` Status Vocabulary (shared across `tap_auth` specs).
