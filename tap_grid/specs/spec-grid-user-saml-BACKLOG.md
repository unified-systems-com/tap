# Grid User SAML2 Specification

## Philosophy

SAML2 is an authentication source for TAP users, not a replacement for the TAP user model. A SAML login proves identity through an external Identity Provider, then resolves that identity into the same canonical Django user record the rest of the application already understands.

The design goal is to support enterprise SAML integrations in a way that feels normal for Django: authentication backends establish `request.user`, sessions carry the login forward, and the rest of the app continues to operate on ordinary TAP users and permissions.

## Goals

|    |              |                                                                                          |
| :---: | ---       | ---                                                                                      |
| 1. | Django-Way   | SAML integrates through Django auth backends and sessions rather than a parallel auth stack |
| 2. | Canonical    | SAML logins resolve to the same TAP user model used by local auth and future OIDC auth   |
| 3. | Enterprise-Ready | The model supports multiple IdPs, stable upstream subjects, and controlled provisioning |
| 4. | Safe Mapping | Attribute mapping and account linking are explicit and predictable                         |
| 5. | Extensible   | The design leaves room for future OIDC parity without coupling the core user model to SAML |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-usersaml-backend | [SAML Authentication Backend Integration](#saml-authentication-backend-integration) | Proposed | SAML participates through Django auth backend/session flow |
| req-grid-usersaml-linkage | [External SAML Identity Linkage](#external-saml-identity-linkage) | Proposed | SAML provider identifiers are stored separately from the core user |
| req-grid-usersaml-mapping | [Attribute Mapping Policy](#attribute-mapping-policy) | Proposed | SAML assertions map into TAP users through explicit field rules |
| req-grid-usersaml-provision | [Provisioning and Account Resolution](#provisioning-and-account-resolution) | Proposed | Login finds or creates the canonical TAP user under controlled rules |
| req-grid-usersaml-authz | [Post-Login Django Semantics](#post-login-django-semantics) | Proposed | After SAML login the app sees a normal Django user and permissions |
| req-grid-usersaml-multiidp | [Multiple Identity Providers](#multiple-identity-providers) | Backlog | Multi-IdP support is part of the long-term contract but may not ship first |

## Explanation

SAML should fit into TAP as one authentication backend among several:

- local username/password
- SAML2
- future OIDC
- future API-oriented auth

The key architectural rule is that SAML does not create a new kind of actor for the application. It authenticates a person through an external IdP, then logs them into TAP as a canonical user. Once that happens, `request.user`, `CallerContext.user`, Django permissions, admin checks, and user context all work the same way they do for any other authenticated user.

In practice, SAML is expected to be primarily a `human` user authentication path. Programmatic users remain part of the same canonical user model, but they will usually authenticate through different mechanisms.

### SAML Authentication Backend Integration
----
RID: `req-grid-usersaml-backend`

Status: `Proposed`

TAP should integrate SAML through Django's standard authentication backend and session mechanisms.

#### Status Details
Proposed as the most Django-native integration path and the cleanest way to keep the rest of the application protocol-agnostic.

#### Implementation
The SAML login flow should be:

1. The user is redirected from TAP to a configured SAML Identity Provider.
2. The IdP authenticates the user and posts a SAML assertion back to TAP.
3. A SAML authentication backend validates the assertion and resolves it to a canonical TAP user.
4. Django logs that user into the current session.
5. Subsequent requests see a normal authenticated `request.user`.
6. The first implementation primarily targets `human` users authenticating through enterprise identity providers.

The rest of TAP should not need to parse SAML assertions directly outside the authentication integration layer.

#### Development
This is the important mental model for the rest of the stack: after login, SAML largely disappears behind Django auth.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-usersaml-backend-1 | Uses Django Auth Backend | Proposed | SAML authentication is implemented through Django's auth backend/login flow rather than a parallel request identity mechanism. | |
| req-grid-usersaml-backend-2 | Session Produces Request User | Proposed | A successful SAML login results in a normal authenticated Django session and `request.user`. | |
| req-grid-usersaml-backend-3 | App Code Stays Protocol-Agnostic | Proposed | Ordinary application and service code do not need direct awareness of SAML assertions after authentication completes. | |

#### Future
Later work may add stateless API tokens or bearer flows for APIs, but those should still resolve to the same canonical TAP user model.

### External SAML Identity Linkage
----
RID: `req-grid-usersaml-linkage`

Status: `Proposed`

SAML-specific provider identity should be stored in dedicated linkage records rather than copied wholesale into the canonical user model.

#### Status Details
Proposed because enterprise SAML deployments frequently need durable upstream subject identifiers, provider metadata, and account-linking state that do not belong on the core user row.

#### Implementation
The linkage contract should support:

1. a foreign key to the canonical TAP user
2. a provider or IdP identifier
3. the stable upstream subject identifier, typically NameID or another immutable mapped identifier
4. optional issuer/entity ID metadata
5. optional timestamps for first login, last login, last sync, and link status

The unique identity for a SAML-linked account should be based on provider + stable upstream subject, not solely on mutable attributes such as email address.

#### Development
Email is useful for lookup and human recognition, but many enterprises treat it as mutable. The durable upstream subject should be the real linkage anchor.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-usersaml-linkage-1 | Separate Linkage Record | Proposed | TAP stores SAML provider identity in a dedicated linkage model or equivalent extension rather than only in the core user row. | |
| req-grid-usersaml-linkage-2 | Stable Upstream Subject Used | Proposed | Account linkage is anchored on a stable upstream SAML identifier rather than relying only on email or display name. | |
| req-grid-usersaml-linkage-3 | Canonical User Remains Primary | Proposed | SAML linkage records point to the canonical TAP user as the primary application actor. | |

#### Future
This same pattern should generalize cleanly to OIDC subject linkage so TAP does not need one-off identity tables per protocol forever.

### Attribute Mapping Policy
----
RID: `req-grid-usersaml-mapping`

Status: `Proposed`

SAML attributes should map into TAP user fields through explicit, provider-aware rules rather than implicit field overwrites.

#### Status Details
Proposed to reduce the usual surprises around claim names, required attributes, and mutable upstream profile data.

#### Implementation
The mapping policy should define:

1. which assertion attribute identifies the upstream subject
2. which attributes may map to TAP fields such as email, first name, and last name
3. which mapped fields are authoritative-on-login and may be refreshed
4. which fields are TAP-owned and should not be overwritten by each SAML login
5. normalization rules such as email casing and blank-value handling

Attribute mapping should be configured per provider when needed rather than assuming all IdPs emit the same names or semantics.

#### Development
This is where many integrations get messy. The spec should make provider-specific mapping a feature, not a workaround.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-usersaml-mapping-1 | Subject Mapping Explicit | Proposed | The attribute used as the durable upstream identity is explicitly configured. | |
| req-grid-usersaml-mapping-2 | Profile Field Mapping Explicit | Proposed | Email/name and similar profile fields are mapped through explicit configuration rather than assumed by convention alone. | |
| req-grid-usersaml-mapping-3 | TAP-Owned Fields Protected | Proposed | The mapping policy distinguishes between provider-managed profile fields and TAP-owned fields that should not be overwritten automatically. | |

#### Future
Later work may add per-field sync policies such as "write once," "sync always," or "sync if blank" once real provider diversity shows where the sharp edges are.

### Provisioning and Account Resolution
----
RID: `req-grid-usersaml-provision`

Status: `Proposed`

SAML login should resolve an assertion to an existing TAP user when possible and create a new TAP user only under explicit provisioning rules.

#### Status Details
Proposed because enterprise auth often needs more control than "auto-create any authenticated user forever."

#### Implementation
The account-resolution flow should be:

1. Attempt to find an existing linkage record by provider + stable upstream subject.
2. If none exists, optionally attempt controlled reconciliation to an existing TAP user using approved secondary identifiers such as email.
3. If reconciliation succeeds, create the linkage record and continue.
4. If reconciliation does not succeed, either:
   - create a new TAP user if auto-provisioning is enabled, or
   - reject login and require admin reconciliation if auto-provisioning is disabled.
5. Newly provisioned SAML users default to `user_kind=human` unless an explicit higher-trust backend flow defines otherwise.
6. Account disablement in TAP (`is_active=False`) must still prevent login even if the upstream IdP authenticated the user.

#### Development
This is where enterprise expectations vary most. The spec should support both permissive auto-provisioning and stricter admin-controlled provisioning.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-usersaml-provision-1 | Existing Linked Account Preferred | Proposed | SAML login first attempts resolution through an existing provider-linked identity record. | |
| req-grid-usersaml-provision-2 | Controlled Reconciliation | Proposed | Secondary matching such as email reconciliation happens only through explicit policy rather than hidden assumptions. | |
| req-grid-usersaml-provision-3 | Provisioning Policy Explicit | Proposed | TAP supports an explicit policy choice between automatic user creation and admin-controlled provisioning. | |
| req-grid-usersaml-provision-4 | SAML Defaults To Human Users | Proposed | SAML-provisioned users default to `user_kind=human` unless a more explicit trusted flow intentionally provisions a different kind. | |
| req-grid-usersaml-provision-5 | Local Disablement Still Applies | Proposed | A TAP user marked inactive cannot log in through SAML even if upstream authentication succeeds. | |

#### Future
Future enterprise work may add domain allowlists, JIT group assignment, or quarantine flows for ambiguous identity matches.

### Post-Login Django Semantics
----
RID: `req-grid-usersaml-authz`

Status: `Proposed`

Once a SAML assertion has been resolved to a TAP user and login succeeds, the rest of the system should treat that session like any other Django-authenticated session.

#### Status Details
Proposed as the key simplification that makes SAML support compatible with the rest of the planned user and context work.

#### Implementation
After login:

1. `request.user` is the canonical TAP user.
2. Django groups, permissions, and staff/superuser flags continue to govern authorization.
3. `CallerContext.user` resolves to the same canonical user for service calls.
4. User context, time travel defaults, and any future user-owned features are keyed to that canonical user, not to the SAML session payload.
5. Local app behavior should not branch on "was this user authenticated through SAML?" unless a specific audit or admin workflow requires that distinction.

#### Development
This is what keeps the product from growing separate "SAML user" and "local user" code paths everywhere.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-usersaml-authz-1 | Canonical User After Login | Proposed | Successful SAML login yields the same canonical TAP user object used by the rest of the app. | |
| req-grid-usersaml-authz-2 | Standard Authz Still Applies | Proposed | Django permissions, groups, and account flags continue to govern authorization after SAML login. | |
| req-grid-usersaml-authz-3 | User-Owned Features Remain Stable | Proposed | User context and other user-owned TAP features attach to the canonical user regardless of login source. | |

#### Future
If TAP later exposes last-auth-source or provider metadata in admin, that should be treated as informational metadata rather than a new application principal type.

### Multiple Identity Providers
----
RID: `req-grid-usersaml-multiidp`

Status: `Backlog`

TAP should reserve support for multiple SAML Identity Providers, but the first implementation may start with one configured provider.

#### Status Details
Deferred to backlog because many installations can start with a single IdP, but the data model should not assume that forever.

#### Implementation
The backlog-ready model should allow:

1. multiple configured SAML providers
2. provider-specific attribute mapping
3. uniqueness of linkage by provider + upstream subject
4. optional routing rules by domain, tenant, or explicit login choice

The first implementation does not need to ship all of this as UI or admin workflow, but it should avoid schema choices that block it.

#### Development
Even if only one IdP is configured on day one, assuming global uniqueness of a SAML subject without provider identity is an easy mistake to regret later.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-usersaml-multiidp-1 | Provider Identity Part Of Linkage | Backlog | The linkage design includes provider identity as part of the uniqueness contract. | |
| req-grid-usersaml-multiidp-2 | Single-Provider V1 Does Not Block Multi-Provider Future | Backlog | A first implementation with one IdP does not make schema or mapping assumptions that prevent later multi-IdP support. | |

#### Future
OIDC and SAML multi-provider administration may eventually want a shared "external auth provider" abstraction above protocol-specific details.
