# Grid Service Error Specification

## Philosophy

The TAP service layer should present errors through a stable, expressive contract that is useful to humans, bots, APIs, and admin tooling without leaking raw Django or ORM internals to ordinary callers.

## Goals

|    |                  |                                                                                 |
| :---: | ---           | ---                                                                             |
| 1. | Stable            | Errors use a defined taxonomy rather than ad hoc exception leakage              |
| 2. | Safe              | Public responses avoid exposing sensitive framework internals                   |
| 3. | Useful            | Humans and bots can understand what failed and how to investigate further       |


## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-service-errors-taxonomy | [Stable Error Taxonomy](#stable-error-taxonomy) | Implemented | ServiceError codes + exception classes defined |
| req-grid-service-errors-safe | [Safe Public Error Surface](#safe-public-error-surface) | Implemented | Django errors wrapped; safe messages in pipeline |
| req-grid-service-errors-diagnostic | [Diagnostic References](#diagnostic-references) | Implemented | ServiceError.detail + correlation_id fields |


### Stable Error Taxonomy
----
RID: `req-grid-service-errors-taxonomy`

Status: `Implemented`

The service layer should define a stable family of service exceptions and error codes instead of leaking arbitrary framework exceptions to callers.

#### Status Details
`ServiceError.code` is a Literal of stable values; the current taxonomy is enumerated below. Matching exception classes exist in `tap_grid/exceptions.py`.

#### Implementation
The taxonomy distinguishes:

- `validation_error` — `ServiceValidationError`: schema or model validation failure
- `constraint_violation` — `ServiceConstraintError`: graph constraint violation
- `authz_failure` — `ServiceAuthzError`: authorization check failure
- `not_found` — `ServiceNotFoundError`: target entity not found
- `conflict` — `ServiceConflictError`: operation would create a conflict
- `unsupported_operation` — `ServiceUnsupportedOperationError`: requested operation not supported
- `internal_error` — unhandled exception (outer try/except in pipeline)
- `hotlink_validation_failed` — pre-commit consistency phase detected a hotlink mismatch (`req-grid-hotlink-deferred`)
- `entity_version_conflict` — `ServiceVersionConflictError`: a write operation declared `entity_expected_version` but the local `Entity.version` did not match (`req-grid-service-batch-occ`)
- `entity_expected_version_not_allowed_on_create` — `ServiceValidationError` subtype: caller passed `entity_expected_version` to a create verb, where no prior version exists (`req-grid-service-write-occ`)

Every public-facing service error carries a stable code string in `ServiceError.code`.

The `entity_version_conflict` code carries a structured `detail` payload with `{entity_expected_version, actual_entity_version, entity_id}` so callers can implement retry-or-surface logic without scraping the message string. `actual_entity_version` is `null` when the target entity was deleted out from under the operation.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-errors-taxonomy-1 | Stable Service Exceptions | Implemented | Public service operations fail through a documented set of service exception types. | |
| req-grid-service-errors-taxonomy-2 | Stable Error Codes | Implemented | Public service errors include stable machine-usable error codes. | |
| req-grid-service-errors-taxonomy-3 | Core Failure Categories Covered | Implemented | The error taxonomy distinguishes validation, constraint, authz, not found, conflict, unsupported, and internal failures. | |
| req-grid-service-errors-taxonomy-4 | Optimistic Concurrency Errors Covered | Approved for Development | The error taxonomy includes `entity_version_conflict` (verb-level OCC mismatch) and `entity_expected_version_not_allowed_on_create` (caller misuse of OCC on a create verb). | Detail payload includes `entity_expected_version`, `actual_entity_version`, `entity_id`. |

#### Future
Decide whether the stable error code namespace should also be versioned independently of exception class names.


### Safe Public Error Surface
----
RID: `req-grid-service-errors-safe`

Status: `Implemented`

Public-facing service responses should expose safe error information while preventing accidental leakage of sensitive Django/ORM/framework details.

#### Status Details
`_django_errors_to_service_errors()` in `tap_grid/services.py` converts Django `ValidationError` instances into `ServiceError` instances. The outer try/except in `_execute_write_pipeline` wraps unhandled exceptions as `internal_error` with only the `str()` message exposed.

#### Implementation
When lower-level exceptions occur, the service layer:

- captures them
- maps them to the stable error taxonomy
- exposes a safe public message
- preserves deeper internal details only for controlled diagnostics and admin follow-up

Raw framework exceptions are not the normal public contract.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-errors-safe-1 | Safe Public Messages | Implemented | Service errors expose safe human-readable messages suitable for ordinary callers. | |
| req-grid-service-errors-safe-2 | Framework Errors Wrapped | Implemented | Django/ORM/framework exceptions are wrapped into service-layer errors rather than exposed directly by default. | |
| req-grid-service-errors-safe-3 | Sensitive Detail Not Leaked | Implemented | Internal exception detail is not surfaced directly in ordinary public responses. | |

#### Future
Specify how much safe detail is appropriate per response mode once the admin and observability stories are implemented.


### Diagnostic References
----
RID: `req-grid-service-errors-diagnostic`

Status: `Implemented`

The error contract should still support deep investigation by admins, bots, and tooling.

#### Status Details
`ServiceError` carries `detail: dict | None` for structured machine-usable context and `correlation_id: str | None` for a debug reference.

#### Implementation
Error envelopes support:

- stable error code (`ServiceError.code`)
- safe human-readable message (`ServiceError.message`)
- optional field name (`ServiceError.field`)
- structured machine detail payload (`ServiceError.detail`)
- correlation/debug reference (`ServiceError.correlation_id`)

Verbose result mode in write responses exposes additional non-sensitive context for admin or bot follow-up.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-errors-diagnostic-1 | Correlation Or Debug Reference | Implemented | Errors can include a structured reference that supports deeper investigation. | `ServiceError.correlation_id` |
| req-grid-service-errors-diagnostic-2 | Machine Detail Payload | Implemented | Errors can include structured machine-usable details alongside the safe message. | `ServiceError.detail` |
| req-grid-service-errors-diagnostic-3 | Verbose Results Support Investigation | Implemented | Verbose response mode can expose additional non-sensitive diagnostic references for admins and bots. | via WriteResult verbose mode |

#### Future
Integrate these references with whichever logging/observability mechanism TAP standardizes on.


## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed |  |
| Approved for Development | Requirement is accepted and ready to be implemented |
| In Development |  |
| Implemented |  |
| Verified |  |
| Refactoring |  |
| Deprecating |  |
| Deprecated | Not part of the current architecture and should not be implemented |
