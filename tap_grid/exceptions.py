"""TAP Core exceptions."""


class InvalidEdgeError(Exception):
    """Raised when edge creation violates constraints."""

    pass


class EdgePropertyValidationError(Exception):
    """Raised when edge properties fail JSON Schema validation."""

    pass


class InvalidSearchDefinitionError(Exception):
    """Raised when a search definition is structurally invalid at execution time."""

    pass


class SearchRunnerNotFoundError(Exception):
    """Raised when a module runner_key cannot be resolved in the search runner registry."""

    pass


class SearchExecutionError(Exception):
    """Raised on hard failures during search execution (DB error, invalid result envelope, etc.)."""

    pass


class NoBatchContextError(Exception):
    """Raised when a FLIP-enabled model is saved without an active batch context."""

    pass


class NoCallerContextError(Exception):
    """Raised when request-scoped code asks for the active CallerContext and none is bound.

    A real request always carries one (`CallerContextMiddleware` binds a context for
    every request, `user=None` for anonymous), so this signals a route reached
    outside the middleware — a wiring bug, not a user error. Fails closed rather
    than letting the caller invent an identity (req-grid-service-pipeline-context).
    """

    pass


class ServiceValidationError(Exception):
    """Raised internally by the service layer when schema or model validation fails."""

    pass


class ServiceConstraintError(Exception):
    """Raised internally by the service layer when a graph constraint is violated."""

    pass


class ServiceNotFoundError(Exception):
    """Raised internally by the service layer when a target entity cannot be found."""

    pass


class ServiceAuthzError(Exception):
    """Raised internally by the service layer when an authorization check fails."""

    pass


class ServiceConflictError(Exception):
    """Raised internally by the service layer when an operation would create a conflict."""

    pass


class ServiceUnsupportedOperationError(Exception):
    """Raised internally by the service layer when a requested operation is not supported."""

    pass


class ServiceVersionConflictError(Exception):
    """Raised internally by the service layer when an OCC version check fails.

    Carries the structured detail payload the spec requires for the
    `entity_version_conflict` error code (req-grid-service-batch-occ).
    `actual_entity_version` is `None` when the target entity is missing
    entirely; this distinguishes "you expected version N but the entity
    is gone" from "you expected N but it has moved to M."
    """

    def __init__(
        self,
        *,
        entity_expected_version: int,
        actual_entity_version: int | None,
        entity_id: str,
    ) -> None:
        self.entity_expected_version = entity_expected_version
        self.actual_entity_version = actual_entity_version
        self.entity_id = entity_id
        if actual_entity_version is None:
            msg = (
                f"entity_version_conflict: caller expected version "
                f"{entity_expected_version} on entity {entity_id}, but the "
                "entity does not exist locally."
            )
        else:
            msg = (
                f"entity_version_conflict: caller expected version "
                f"{entity_expected_version} on entity {entity_id}, but local "
                f"Entity.version is {actual_entity_version}."
            )
        super().__init__(msg)

    def to_detail(self) -> dict[str, object]:
        """Return the structured detail payload for ServiceError.detail."""
        return {
            "entity_expected_version": self.entity_expected_version,
            "actual_entity_version": self.actual_entity_version,
            "entity_id": self.entity_id,
        }


class ServiceCascadeTooLargeError(Exception):
    """A contained cascade would retire more nodes than TAP_CASCADE_MAX_CLOSURE allows.

    Raised inside the write transaction, so nothing is written
    (req-grid-service-delete-cascade-11). The message names the cap, never the closure.
    """


class ServiceInvalidReasonError(Exception):
    """A delete reason outside the closed vocabulary, or metadata that cannot be recorded.

    Raised in the write pipeline before any write (req-grid-service-delete-reason-3), so
    the check holds for every caller — the public verbs AND a raw ``write_batch``
    operation — rather than only for the wrappers.
    """
