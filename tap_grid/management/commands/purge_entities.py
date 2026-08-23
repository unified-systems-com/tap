"""Hard-delete entities of a registered type. DEBUG-only.

Usage:
    docker compose exec web uv run python manage.py purge_entities \\
        --entity-type ksi_indicator --all-of-type --reason "dev reset"

    docker compose exec web uv run python manage.py purge_entities \\
        --entity-type ksi_indicator --entity-id <uuid1> --entity-id <uuid2> \\
        --reason "fixing a bad import"

See `req-grid-service-purge` in `tap_grid/specs/spec-grid-service-delete.md`.
Hard-delete is the narrow exception to TAP's tombstone-by-default delete
contract; this command is the operator-facing surface for the dev-reset use
case. Production purge use cases (GDPR erasure, bad-ingest rollback) require
their own spec work and remain out of scope for v0.
"""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Hard-delete entities of the named type. DEBUG-only escape hatch."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--entity-type",
            dest="entity_type",
            required=True,
            help="The registered entity type slug (e.g. ksi_indicator).",
        )
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--all-of-type",
            dest="all_of_type",
            action="store_true",
            default=False,
            help=(
                "Purge every entity of --entity-type currently on the grid "
                "(live and tombstoned). Reads as 'purge every <type> entity', "
                "NOT 'purge everything in the database'."
            ),
        )
        group.add_argument(
            "--entity-id",
            dest="entity_ids",
            action="append",
            default=[],
            help=(
                "Specific entity UUID to purge. Repeatable; each ID must match "
                "--entity-type or the run aborts before any writes."
            ),
        )
        parser.add_argument(
            "--reason",
            dest="reason",
            required=True,
            help=(
                "Required free-form description of why this purge is happening. "
                "Captured in the application log alongside each purged entity."
            ),
        )

    def handle(self, *args, **options) -> None:
        from django.conf import settings

        from tap_grid.exceptions import (
            ServiceConflictError,
            ServiceNotFoundError,
            ServiceValidationError,
        )
        from tap_grid.models import Entity
        from tap_grid.services import purge_edge, purge_node

        # Fail fast with an operator-friendly error before any reads.
        if not settings.DEBUG:
            raise CommandError(
                "purge_entities is permitted only when DEBUG=True (purge_refused_production). "
                "See req-grid-service-purge."
            )

        entity_type: str = options["entity_type"]
        all_of_type: bool = options["all_of_type"]
        raw_entity_ids: list[str] = options["entity_ids"] or []
        reason: str = options["reason"]

        if not reason.strip():
            raise CommandError("--reason must be a non-empty string.")

        # Resolve target entity_ids.
        if all_of_type:
            target_ids = list(Entity.objects.filter(entity_type=entity_type).values_list("pk", flat=True))
            if not target_ids:
                self.stdout.write(self.style.WARNING(f"No entities of type {entity_type!r} found; nothing to purge."))
                return
        else:
            try:
                target_ids = [uuid.UUID(eid) for eid in raw_entity_ids]
            except ValueError as exc:
                raise CommandError(f"--entity-id is not a valid UUID: {exc}") from exc
            # Validate every supplied id exists AND matches --entity-type before
            # touching anything. Mismatches abort the run with zero writes per
            # req-grid-service-purge-8.
            found = {
                str(e["pk"]): e["entity_type"]
                for e in Entity.objects.filter(pk__in=target_ids).values("pk", "entity_type")
            }
            missing = [str(tid) for tid in target_ids if str(tid) not in found]
            if missing:
                raise CommandError(f"Entities not found: {missing}. Aborting before any writes.")
            mismatched = [(eid, etype) for eid, etype in found.items() if etype != entity_type]
            if mismatched:
                raise CommandError(
                    f"--entity-id / --entity-type mismatch: {mismatched}. "
                    f"Expected entity_type={entity_type!r}. Aborting before any writes."
                )

        # Drive the purge per-entity. Each call is its own transaction inside
        # the verb; one failure does not undo earlier purges in this run, but
        # it does abort the run. Edge targets route to purge_edge; everything
        # else routes to purge_node, per req-grid-service-purge-edge-7.
        purge_fn = purge_edge if entity_type == "edge" else purge_node
        successes = 0
        for tid in target_ids:
            try:
                result = purge_fn(tid, reason=reason)
            except (ServiceNotFoundError, ServiceValidationError, ServiceConflictError) as exc:
                raise CommandError(
                    f"{purge_fn.__name__} failed for {tid}: {type(exc).__name__}: {exc}. "
                    f"Stopped after {successes} successful purge(s)."
                ) from exc
            self.stdout.write(
                f"purged: {result.purged_entity_type} {result.purged_entity_id} " f"(+{len(result.purged_edges)} edges)"
            )
            successes += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Purged {successes} entit{'y' if successes == 1 else 'ies'} of type "
                f"{entity_type!r}. Reason: {reason!r}."
            )
        )
