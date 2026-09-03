# Grid User Specification

## Philosophy

Users become necessary in TAP once graph behavior depends on a durable actor identity rather than only on request-local state. The user model should stay as close to standard Django authentication as possible while still leaving room for local accounts, SAML2, OIDC, API-driven access, and future user-scoped graph features such as current context, drafts, and permissions.

The guiding rule is: TAP should have one canonical application user record per person or service actor, and multiple authentication methods may attach to that same record without redefining the rest of the stack.

The first user-kind split should stay intentionally simple:

- `human`: a named actual person
- `programmatic`: a non-human actor such as an automation, integration worker, service account, or AI-driven agent

The line between "program" and "AI" is too blurry to justify separate top-level user kinds yet.

## Goals

|    |              |                                                                                 |
| :---: | ---       | ---                                                                             |
| 1. | Django-Native | TAP uses Django's standard auth/session model rather than inventing parallel user machinery |
| 2. | Canonical     | Each actor has one canonical TAP user record regardless of login source         |
| 3. | Surface-Agnostic | The same user concept works for web UI, API, and internal service calls      |
| 4. | Extensible    | The model leaves room for SAML, OIDC, local auth, and future user-scoped features |
| 5. | Honest        | Authentication source and user profile data are kept distinct from graph business logic |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-user-model | [Canonical Django User Model](#canonical-django-user-model) | Proposed | TAP uses a custom Django `AUTH_USER_MODEL` as the canonical actor record |
| req-grid-user-kind | [User Kind Classification](#user-kind-classification) | Proposed | Users are classified as `human` or `programmatic` |
| req-grid-user-identity | [Stable User Identity Surface](#stable-user-identity-surface) | Proposed | Core user identity fields remain small and durable |
| req-grid-user-description | [Backend-Managed User Description Fields](#backend-managed-user-description-fields) | Proposed | `description` and `description_json` provide system-managed user context |
| req-grid-user-authsource | [Authentication Source Separation](#authentication-source-separation) | Proposed | Login-source linkage is modeled separately from the core user record |
| req-grid-user-service | [Service-Layer Actor Contract](#service-layer-actor-contract) | Proposed | Grid services consume an authenticated actor through `CallerContext` |
| req-grid-user-authz | [Django Authorization Compatibility](#django-authorization-compatibility) | Proposed | Groups, permissions, and `is_active` remain first-class |

## Explanation

The TAP user concept should not be a graph-specific invention. Django already has the right primitives:

- a canonical user model
- authentication backends
- session handling
- permissions and groups

TAP should build on those directly.

The main architectural decision is to keep the canonical user record separate from external identity-provider linkage. That keeps the app aligned with Django and avoids baking SAML/OIDC assumptions into fields like `username`, `email`, or `first_name`.

### Canonical Django User Model
----
RID: `req-grid-user-model`

Status: `Proposed`

TAP should use a custom Django `AUTH_USER_MODEL` as its canonical user record and define it at the start of the product rather than postponing the substitution.

#### Status Details
The repo already defines `tap_grid.models.User` as a subclass of `AbstractUser`. This requirement formalizes that direction and treats it as the durable anchor for all future authentication work.

#### Implementation
The model contract should be:

1. TAP defines one custom `AUTH_USER_MODEL`.
2. The custom model subclasses `AbstractUser` unless a later requirement proves `AbstractBaseUser` is necessary.
3. The canonical TAP user record is the object attached to `request.user`, Django sessions, admin, and permissions.
4. Local username/password login remains compatible with the same user model even when SAML or OIDC are also enabled.
5. Future user-scoped features such as current context, preferences, draft ownership, and audit attribution reference this canonical user record.
6. The canonical user record supports both human and programmatic actors.

Using `AbstractUser` is the most Django-way first implementation because it preserves compatibility with admin, forms, permissions, and many ecosystem integrations while still allowing TAP to extend the model later.

#### Development
The big migration hazard in Django is deciding too late that a custom user model is needed. TAP already crossed that bridge by declaring one, so the spec should lean into it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-user-model-1 | Custom Auth User Exists | Proposed | TAP defines and uses a custom Django `AUTH_USER_MODEL` rather than the stock `auth.User`. | |
| req-grid-user-model-2 | AbstractUser First | Proposed | The first implementation subclasses `AbstractUser` to preserve standard Django compatibility unless a later requirement explicitly changes that contract. | |
| req-grid-user-model-3 | Canonical Actor Record | Proposed | Session auth, admin auth, and future external-auth flows all resolve to the same canonical TAP user record. | |

#### Future
If TAP later needs email-only login, immutable usernames, or service-principal-specific behavior, those changes should extend the custom user model rather than introducing a second canonical actor table.

### User Kind Classification
----
RID: `req-grid-user-kind`

Status: `Proposed`

Each TAP user should be classified by `user_kind`, with the initial supported values `human` and `programmatic`.

#### Status Details
Proposed to make the important human-versus-nonhuman distinction explicit without overfitting the model to today's blurry boundary between traditional automation and AI agents.

#### Implementation
The classification contract should be:

1. The canonical user model includes a `user_kind` field.
2. The first supported values are:
   - `human`
   - `programmatic`
3. `human` means a named actual person.
4. `programmatic` means a non-human actor such as a service account, automation, integration worker, or AI-driven agent.
5. TAP does not split `programmatic` into separate `program` and `ai` top-level kinds in the first implementation.

If future product behavior needs more nuance, TAP may later add structured subtype metadata under the programmatic umbrella rather than replacing the top-level `user_kind` contract.

#### Development
This keeps the model honest about an important distinction without pretending the "AI versus code bundle" line is stable enough to deserve first-class schema today.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-user-kind-1 | User Kind Field Exists | Proposed | TAP defines a `user_kind` field on the canonical user model. | |
| req-grid-user-kind-2 | Two Top-Level Kinds In V1 | Proposed | The first implementation supports exactly `human` and `programmatic` as the top-level user kinds. | |
| req-grid-user-kind-3 | AI Fits Under Programmatic | Proposed | AI-driven actors are represented as `programmatic` users unless a later requirement proves a distinct top-level kind is necessary. | |

#### Future
If AI agents later need distinct lifecycle, billing, or authorization semantics, TAP may add a subtype surface such as `programmatic_subkind` or structured metadata without invalidating the top-level `user_kind` contract.

### Stable User Identity Surface
----
RID: `req-grid-user-identity`

Status: `Proposed`

The core TAP user record should keep only durable actor identity and account lifecycle data, not every piece of IdP metadata.

#### Status Details
Proposed to keep the core user model small and stable while external identity integrations evolve.

#### Implementation
The canonical user record should be responsible for:

1. Django-required auth fields such as password, last login, staff/admin flags, and active state.
2. Actor classification via `user_kind`.
3. Durable human/account identity fields such as username, email, first name, and last name.
4. TAP-owned lifecycle fields added later if needed, such as display name, timezone, or preferred locale.
5. A stable primary key that internal TAP services and future foreign keys can depend on.

The canonical user record should not be the dumping ground for:

1. raw SAML assertions
2. per-provider subject identifiers
3. provider-specific group claims
4. every synchronized attribute from every upstream identity source

Those belong in external-identity linkage and sync metadata, not in the core user row.

#### Development
Keeping the user table small reduces churn when integrating multiple IdPs that disagree on claims, casing, naming, or required identifiers.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-user-identity-1 | Core Fields Stay Durable | Proposed | The canonical TAP user record stores durable actor/account data rather than raw provider payloads. | |
| req-grid-user-identity-2 | Provider Metadata Stays External | Proposed | Provider-specific identifiers and sync state are stored outside the core user model. | |
| req-grid-user-identity-3 | User Foreign Key Target | Proposed | User-scoped TAP features reference the canonical Django user record rather than external provider rows. | |

#### Future
Profile and preference models may be split out later if the user record begins to accumulate app-specific settings that are not part of authentication identity.

### Backend-Managed User Description Fields
----
RID: `req-grid-user-description`

Status: `Proposed`

The canonical user model should include backend-managed `description` and `description_json` fields so TAP can store system-authored context about a user.

#### Status Details
Proposed to give TAP a durable place to explain who a user is, especially for programmatic users, without depending on mutable usernames or external identity payloads.

#### Implementation
The descriptive-field contract should be:

1. The canonical user model includes:
   - `description`: optional free-text description
   - `description_json`: optional structured description metadata
2. These fields are backend-managed and are not directly user-modifiable through ordinary self-service profile editing.
3. The fields may be populated for both human and programmatic users.
4. For human users, the fields may hold operator/admin context.
5. For programmatic users, the fields may describe the system role, ownership, or nature of the actor, including AI-agent context when useful.
6. `description_json` should follow the same general structured-description philosophy used elsewhere in TAP, and may later adopt a stricter wrapper shape if the implementation standardizes one.

#### Development
These fields are especially valuable for programmatic users because a name like `scanner_prod_east` or `agent_research_01` is rarely enough context on its own.

The "not user-modifiable" rule matters because these are intended to be trustworthy backend-authored annotations, not profile-biography fields.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-user-description-1 | Description Field Exists | Proposed | TAP defines a backend-managed `description` field on the canonical user model. | |
| req-grid-user-description-2 | Description Json Field Exists | Proposed | TAP defines a backend-managed `description_json` field on the canonical user model. | |
| req-grid-user-description-3 | Not User-Self-Modifiable | Proposed | Ordinary users cannot directly edit their own `description` or `description_json` through standard self-service flows. | |
| req-grid-user-description-4 | Useful For Programmatic Actors | Proposed | The descriptive fields can be used to store system-authored context about programmatic users, including AI-backed actors. | |

#### Future
If TAP later needs richer machine-readable semantics for programmatic users, `description_json` may become the home for subtype or ownership metadata before any dedicated subtype columns are introduced.

### Authentication Source Separation
----
RID: `req-grid-user-authsource`

Status: `Proposed`

Authentication sources such as local password auth, SAML2, and OIDC should be modeled as ways to authenticate a TAP user, not as separate user concepts.

#### Status Details
Proposed as the key design rule that keeps future SAML and OIDC work compatible with one canonical user model.

#### Implementation
The separation contract is:

1. TAP has one canonical user model.
2. TAP may have zero or more linked external identity records for a given user.
3. Each external identity record identifies:
   - protocol/provider type
   - provider identifier
   - stable upstream subject/nameid
   - optional sync metadata
4. A user may authenticate locally, through SAML, through OIDC, or through another approved backend and still resolve to the same TAP user row.
5. Authentication backends are responsible for finding or creating the canonical TAP user, not for creating parallel actor concepts.
6. Different authentication methods may be more common for different `user_kind` values, but they still resolve to the same canonical user model.

#### Development
This is the core move that keeps "who the user is" distinct from "how they logged in today."

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-user-authsource-1 | One User Many Login Sources | Proposed | TAP can associate multiple authentication methods or provider identities with one canonical user record. | |
| req-grid-user-authsource-2 | External Identity Record Exists | Proposed | Provider-specific subject identifiers are stored in a dedicated linkage model or equivalent extension point. | |
| req-grid-user-authsource-3 | Backends Resolve Canonical User | Proposed | Auth backends log the caller into TAP as a canonical user rather than exposing provider-specific principals to application code. | |

#### Future
Later work may add explicit account-linking UX, provider-priority rules, or manual reconciliation workflows when multiple upstream records appear to represent the same person.

### Service-Layer Actor Contract
----
RID: `req-grid-user-service`

Status: `Proposed`

The grid service layer should consume actor identity through a typed caller context rather than by coupling itself directly to web request objects.

#### Status Details
The repo already has `CallerContext(user=..., batch_id=...)`. This requirement extends that direction into the user model architecture.

#### Implementation
The actor contract should be:

1. Public service-layer entry points accept or resolve a `CallerContext`.
2. `CallerContext.user` points to the canonical TAP user or is `None` for system/internal calls.
3. Web requests populate `CallerContext` from `request.user`.
4. API requests populate the same actor surface, whether they arrived through session auth, token auth, SAML-backed session auth, or future API credentials.
5. Service code should not need to care whether the actor authenticated locally or through an external IdP.

#### Development
This is the seam that makes your server-side current-context idea work cleanly across web UI and API surfaces.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-user-service-1 | Actor Enters Through CallerContext | Proposed | TAP services consume user identity through `CallerContext` or an equivalent typed execution context. | |
| req-grid-user-service-2 | Anonymous System Calls Are Explicit | Proposed | System/internal calls are represented explicitly as `user=None` rather than pretending to be a normal authenticated user. | |
| req-grid-user-service-3 | Surface-Independent Actor Semantics | Proposed | Web and API entry points both resolve to the same service-layer actor contract. | |

#### Future
If TAP later introduces service accounts or machine principals, they should fit into this same actor contract either as specialized users or as a clearly defined sibling principal model.

TAP will likely also need delegated users: a programmatic user acting on behalf of a human user with only a subset of that human's roles, permissions, or responsibilities. That delegation model is intentionally deferred to the future permissions specification, but the user architecture should avoid assumptions that would block it.

### Django Authorization Compatibility
----
RID: `req-grid-user-authz`

Status: `Proposed`

TAP should keep Django's native authorization model available rather than replacing it with a custom graph-specific permission system prematurely.

#### Status Details
Proposed as a default posture. TAP may eventually layer graph-aware authorization rules on top, but it should not discard Django's standard authz building blocks.

#### Implementation
The authorization baseline should preserve:

1. `is_active` for account enable/disable lifecycle.
2. `is_staff` and `is_superuser` for admin behavior.
3. Django groups and permissions for coarse-grained application authorization.
4. Compatibility with Django admin and any future auth middleware that expects standard user flags.

Graph-specific authorization, if added later, should build on this base rather than replacing it wholesale in v1.

#### Development
This avoids over-designing authz before the product has a clear permission matrix.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-user-authz-1 | Standard Django Flags Preserved | Proposed | TAP user behavior remains compatible with `is_active`, `is_staff`, and `is_superuser`. | |
| req-grid-user-authz-2 | Groups And Permissions Available | Proposed | TAP may use Django groups and permissions without requiring a custom authz framework first. | |
| req-grid-user-authz-3 | Graph Authz Is Additive | Proposed | Any future graph-aware authorization rules are layered on top of the canonical Django auth model rather than replacing it by default. | |

#### Future
If the product later needs object-level graph authorization, a dedicated spec should define how those rules compose with Django's built-in permission model.
