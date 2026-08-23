"""`manage.py boot` — the canonical TAP standup (req-boot-app).

TAP-IMPLEMENTS: req-boot-app@45a8b458c10d/d72931f0fdba (surface) — the one canonical standup
    command; dev and customer deployments both enter here.

One explicit command stands a fresh, migrated database up to a populated, usable
instance by applying a boot profile in fixed phases (auth → population). It is the
same path in dev (`spawn-session.sh`, req-boot-spawn-bridge) and in a customer
deployment — dog-fooded continuously before any customer relies on it.

Profile resolution: ``--profile`` > ``$TAP_BOOT_PROFILE``. A profile is **required
by default** — a missing one fails loud, so a deployment never silently starts
empty (req-boot-profile-5). The single escape hatch is ``--allow-empty``, an
explicit opt-in to an auth-only, no-outbound standup (req-boot-profile-4).

Boot is zero-touch: no prompts, ever (req-boot-trust). Migrations are a precondition
(run by the container entrypoint), not a boot phase. Per-collector await timeouts
are declared on each fire-collector step (default 90s).

Spec: specs/spec-tap-boot-v0.md.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from tap.logging import abort
from tap_auth.sync import AuthSyncError
from tap_boot.orchestrator import BootError, check_profile, run_boot
from tap_boot.profile import BootProfileError, load_profile
from tap_boot.record import maybe_boot_record

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Stand a TAP instance up from a boot profile (auth → population). See specs/spec-tap-boot-v0.md."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--profile",
            default=None,
            help="Profile id (basename of boot/<id>.json). Overrides $TAP_BOOT_PROFILE.",
        )
        parser.add_argument(
            "--allow-empty",
            action="store_true",
            default=False,
            help="Permit an auth-only standup with no profile (req-boot-profile-4). "
            "Without it, a missing profile fails loud (req-boot-profile-5).",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            default=False,
            help="Resolve-only preflight: validate every enabled step against the "
            "registries (seed-plugin slugs/bundles, fire-collector keys) and exit — "
            "no auth sync, no DB writes, no collector firing. The per-profile "
            "cold-boot smoke uses this to catch a rotted profile offline.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        profile_id = (options["profile"] or os.environ.get("TAP_BOOT_PROFILE") or "").strip()

        profile = None
        if profile_id:
            try:
                profile = load_profile(profile_id)
            except BootProfileError as exc:
                # Even a run that dies at profile load leaves its record
                # (req-boot-obs-record-1) — the evidence must exist when things broke.
                maybe_boot_record(profile_id).finish_aborted("boot", f"profile load failed: {exc}")
                abort(logger, "boot", f"profile load failed: {exc}")
                raise CommandError(str(exc)) from exc
        elif not options["allow_empty"]:
            raise CommandError(
                "A boot profile is required: pass --profile <id> or set $TAP_BOOT_PROFILE. "
                "To stand up auth-only with no profile on purpose, pass --allow-empty "
                "(refusing to start empty-but-apparently-healthy by default — req-boot-profile-5)."
            )

        if options["check"]:
            try:
                check_profile(profile, echo=self.stdout.write)
            except BootError as exc:
                logger.error("[0db7] boot --check failed: %s", exc)
                raise CommandError(str(exc)) from exc
            self.stdout.write(self.style.SUCCESS("boot --check ok (profile resolves)"))
            return

        # The durable per-run boot record (req-boot-obs-record): run_boot finalizes
        # it on both the success and abort paths.
        record = maybe_boot_record(profile.profile_id if profile else None)
        try:
            run_boot(profile, echo=self.stdout.write, record=record)
        except (BootError, AuthSyncError) as exc:
            # The ABORT signal's structured data carries the failing step + its
            # failing self-test checks (req-boot-obs-abort-detail-2); the rendered
            # TAP-ABORT console line stays the one-line sentinel.
            abort(logger, "boot", str(exc), detail=getattr(exc, "detail", None) or None)
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("boot complete"))
