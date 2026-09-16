"""Backfill ``Entity.natural_key`` for keyed types (``req-grid-entity-natural-key``).

Three modes, and the default is the harmless one:

    --report   (default) compute and bucket, write nothing
    --apply    write the computed keys
    --check    recompute and compare against what is stored

``--check`` is the drift guard. A key document is part of the model definition, so
redefining one is a Django migration (``req-grid-entity-natural-key-8``) — but a
recipe edited *without* one leaves stored keys silently stale, and no stored marker
would reveal that. Recomputing and comparing does. It is also the tool for migrating
an existing instance by hand.

**Why this writes with ``bulk_update`` rather than through the service layer.**
Backfilling a derived field is not an observation of the object: it must not bump
``Entity.version``, write a history row, or stamp a batch. ``req-grid-history-version-2``
increments the version on every *canonical mutation*, and this is not one — the source
object did not change, TAP merely computed something it already knew. ``bulk_update``
issues plain UPDATEs and runs ``pre_save`` only for the named field, so ``updated_at``
(``auto_now``) is left alone too. Direct ORM access for migration and infrastructure
behaviour is what CLAUDE.md permits it for.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from tap_grid.models import Entity
from tap_grid.natural_key import Keyless, NaturalKeyError, natural_key
from tap_grid.registry import get_model_class, list_entity_types


class Command(BaseCommand):
    help = "Compute, apply or verify Entity.natural_key for keyed entity types."

    def add_arguments(self, parser: Any) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true", help="Write the computed keys.")
        mode.add_argument(
            "--check",
            action="store_true",
            help="Recompute and compare against stored keys; report drift. Writes nothing.",
        )
        parser.add_argument(
            "--type",
            dest="entity_type",
            default=None,
            help="Limit to one entity type. Omit to process every keyed type.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        apply_writes: bool = options["apply"]
        check: bool = options["check"]
        only: str | None = options["entity_type"]

        keyed = self._keyed_types(only)
        if not keyed:
            # A sweep that matched nothing must say so loudly rather than printing a
            # reassuring zero — an empty scan is the classic false green.
            raise CommandError(
                f"No keyed entity types to process{f' for {only!r}' if only else ''}. "
                "Either the type is keyless (which is most of core, by design) or it "
                "has not declared a natural key at all."
            )

        collisions_same_dims: list[str] = []
        shared_across_dims: list[str] = []
        no_key: list[str] = []
        drift: list[str] = []
        written = 0

        for entity_type, model in keyed:
            properties = model.NATURAL_KEY
            rows = list(model.objects.filter(entity__deleted_at__isnull=True).select_related("entity"))
            # (key, canonical dimensions) -> entity ids. Dimensions participate in the
            # COLLISION test but never in the key itself: req-grid-entity-natural-key-6
            # fails on two live rows sharing a key "in one dimension", while -3 permits
            # the same key across differing dimensions — that is the correlation property.
            seen: dict[tuple[str, str], list[str]] = defaultdict(list)
            pending: list[Entity] = []

            for row in rows:
                entity = row.entity
                try:
                    computed = natural_key(entity_type, {p: getattr(row, p, None) for p in properties})
                except NaturalKeyError as exc:
                    raise CommandError(f"{entity_type} {entity.id}: {exc}") from exc

                if computed is None:
                    no_key.append(f"{entity_type} {entity.id} — a constituting value is absent")
                    continue

                dims = repr(sorted((entity.dimensions or {}).items()))
                seen[(str(computed), dims)].append(str(entity.id))

                if check:
                    if entity.natural_key != computed:
                        drift.append(f"{entity_type} {entity.id} — stored {entity.natural_key}, recomputed {computed}")
                elif entity.natural_key != computed:
                    entity.natural_key = computed
                    pending.append(entity)

            by_key: dict[str, set[str]] = defaultdict(set)
            for (key, dims), ids in seen.items():
                if len(ids) > 1:
                    collisions_same_dims.append(f"{entity_type} key={key} dimensions={dims} rows={ids}")
                by_key[key].add(dims)
            for key, dim_shapes in by_key.items():
                if len(dim_shapes) > 1:
                    shared_across_dims.append(f"{entity_type} key={key} dimension shapes={len(dim_shapes)}")

            if apply_writes and pending:
                Entity.objects.bulk_update(pending, ["natural_key"])
                written += len(pending)

            self.stdout.write(f"{entity_type}: {len(rows)} live row(s), keyed on {properties}")

        self._report(collisions_same_dims, shared_across_dims, no_key, drift, written, apply_writes, check)

    def _keyed_types(self, only: str | None) -> list[tuple[str, Any]]:
        out = []
        for entity_type in sorted(list_entity_types()):
            if only and entity_type != only:
                continue
            # No try/except here on purpose. get_model_class raises KeyError only for
            # an UNREGISTERED type, and every type here came from list_entity_types(),
            # so it cannot. A swallowed exception would guard an impossible state while
            # hiding a real one — and a silently skipped keyed type is a backfill that
            # reports clean having not done its job.
            model = get_model_class(entity_type)
            declared = getattr(model, "NATURAL_KEY", None)
            if declared is None or isinstance(declared, Keyless):
                continue
            out.append((entity_type, model))
        return out

    def _report(
        self,
        collisions: list[str],
        shared: list[str],
        no_key: list[str],
        drift: list[str],
        written: int,
        apply_writes: bool,
        check: bool,
    ) -> None:
        for line in no_key:
            self.stdout.write(self.style.WARNING(f"  no key: {line}"))
        for line in shared:
            # Permitted by -3, and reported anyway: with one perspective today, the
            # likely cause is dimension NOISE rather than two genuine vantages, and
            # that is worth a human look before perspectives make it meaningful.
            self.stdout.write(self.style.WARNING(f"  shared key across dimensions (permitted): {line}"))

        if apply_writes:
            self.stdout.write(self.style.SUCCESS(f"  wrote {written} key(s)"))

        if drift:
            for line in drift:
                self.stdout.write(self.style.ERROR(f"  DRIFT: {line}"))
            raise CommandError(
                f"{len(drift)} row(s) have stored keys that disagree with a recompute. A key "
                "document changed without a migration, or a recipe was edited in place. "
                "Do not re-apply blindly — find out which."
            )

        if collisions:
            for line in collisions:
                self.stdout.write(self.style.ERROR(f"  COLLISION: {line}"))
            # req-grid-entity-natural-key-6: record both and fail loudly, never choose.
            # A thin key document and a carried duplicate have OPPOSITE remedies, so
            # picking one would destroy whichever reading was right.
            raise CommandError(
                f"{len(collisions)} collision(s): two live rows in one dimension compute one key. "
                "Either the key document is too thin to distinguish genuinely different "
                "objects (a design fix: add a constituting property) or the grid is carrying "
                "a duplicate (a data fix: retire one). This command will not choose."
            )

        if check:
            self.stdout.write(self.style.SUCCESS("  check clean — every stored key matches a recompute"))
