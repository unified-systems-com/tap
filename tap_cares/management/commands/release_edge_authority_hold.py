"""Release a run's held edge-authority claims: the operator's decision (Issue# 920 - tap).

A claim that asserted none of a scope of three or more live edges is held by the reconcile verb
rather than applied (``req-grid-reconcile-edge-authority-13``): the shape of a read that silently came
back empty. A later run that reads the scope again supersedes the hold on its own. When the scope
really is empty, an operator releases it here, and the held removals go ahead, each re-locked and
re-fenced (``-14``).

Releasing is the same kind of act as arming, so ``--as`` names an operator who must hold
``cares.arm_reconcile``, as ``arm_reconcile`` does. As there, the shell is a trusted surface: ``--as``
is a claim, not an authentication; the capability check is real, and the run's record keeps both that
name and the OS user the shell ran as.

    manage.py release_edge_authority_hold <run batch id> --as <username>
    manage.py release_edge_authority_hold <run batch id> --claim <claim event id> --as <username>
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, CommandParser

from tap_auth.actors import acting_as
from tap_auth.errors import AuthzError
from tap_cares.services import release_edge_authority_hold
from tap_grid.models import Batch


class Command(BaseCommand):
    help = "Release a run's held edge-authority claims, as the named operator."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("run_batch_id", help="The collection run's lifecycle batch id, as its batch page shows.")
        parser.add_argument(
            "--claim", dest="claim_event_id", default=None, help="Release only this held claim (its claim event id)."
        )
        parser.add_argument(
            "--as", dest="operator", required=True, help="Username of the operator (must hold cares.arm_reconcile)."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        user_model = get_user_model()
        try:
            operator = user_model.objects.get(username=options["operator"])
        except user_model.DoesNotExist as exc:
            raise CommandError(f"no user {options['operator']!r}") from exc
        try:
            with acting_as(operator):
                result = release_edge_authority_hold(options["run_batch_id"], claim_event_id=options["claim_event_id"])
        except AuthzError as exc:
            raise CommandError(f"refused: {exc}") from exc
        except Batch.DoesNotExist as exc:
            raise CommandError(f"no batch {options['run_batch_id']!r}") from exc
        if not result["released_claims"]:
            self.stdout.write(f"run {result['run']}: nothing held to release")
            return
        counts = result["counts"]
        self.stdout.write(
            self.style.SUCCESS(
                f"run {result['run']}: released {len(result['released_claims'])} claim(s) as "
                f"{result['released_by']['operator']}: {counts['applied']} removed, "
                f"{counts['rejected_stale']} rejected stale, {counts['refused']} refused, {counts['gone']} gone"
            )
        )
