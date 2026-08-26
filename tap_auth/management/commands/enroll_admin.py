"""`manage.py enroll_admin` — genesis: mint the first admin's passkey invitation.

The root-of-trust bootstrap for a passwordless, zero-IdP instance: on a fresh install
there is no human who can log in, so there is no capability-holding caller to authorize
minting an invitation. Genesis therefore sits BELOW the capability gate — exactly like
:func:`tap_auth.sync.ensure_initial_admin`, which creates today's first admin with
direct ORM and no ``authorize`` (auth bootstrap is a sanctioned out-of-scope exception,
the same class as migrations). This command calls the UNGUARDED ``_mint_invitation``
impl, attributing ``issued_by`` to the existing ``tap_bootloader`` program actor for a
truthful audit trail — attribution, not authority: the bootloader does NOT (and must
not) hold ``auth.manage_users`` (req-tap-auth-passkey-genesis).

The minted invitation is an ``enroll_first`` grant of ``tap_admin``. The operator opens
the printed one-time link, registers a passkey, and is logged in as the admin. The
secret rides the URL *fragment* and is emitted to stdout only under ``--print-token``;
it is never accepted or echoed as an argv value (process listings are world-visible).

Example (fresh instance):
    manage.py migrate && manage.py sync_auth
    manage.py enroll_admin --email me@example.com --print-token
    # → open the printed http://<host>/auth/enroll/<public-id>#<secret> link
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from tap_auth.actors import BOOTLOADER, get_builtin_actor
from tap_auth.boot import read_profile_kind
from tap_auth.errors import MissingActor
from tap_auth.invitations import GENESIS_TTL, UsernameTaken, _mint_invitation
from tap_auth.models import InvitationAction, User, UserKind
from tap_auth.passkey.dev_record import (
    DEV_RECORD_RELPATH,
    DevImportNotAllowed,
    DevRecordError,
    assert_dev_import_allowed,
    import_dev_admin,
    load_dev_record,
)
from tap_auth.roles import ADMIN_ROLE


class Command(BaseCommand):
    help = "Genesis: mint the first admin's passkey enrollment invitation (below the capability gate)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--email",
            default="",
            metavar="EMAIL",
            help="Contact email recorded on the invitation (NOT identity — a label only). "
            "Required for the mint path; ignored by --import-dev-passkey.",
        )
        parser.add_argument(
            "--display-name",
            default="",
            metavar="NAME",
            help="Optional display name for the passkey / account.",
        )
        parser.add_argument(
            "--username",
            default="",
            metavar="NAME",
            help=(
                "Pin the created user's username instead of deriving it from --email. Create-only: "
                "an existing username fails loud (never a silent additive mint). Used by the dev "
                "bootstrap so register-once and replay agree on one account."
            ),
        )
        parser.add_argument(
            "--base-url",
            default="",
            metavar="URL",
            help="Origin for the enrollment link (default: TAP_PASSKEY_ORIGIN). Must match it — the ceremony compares origins exactly.",
        )
        parser.add_argument(
            "--print-token",
            action="store_true",
            help="Emit the one-time enrollment link INCLUDING its secret fragment to stdout.",
        )
        parser.add_argument(
            "--import-dev-passkey",
            action="store_true",
            help=(
                "DEV ONLY: skip minting an invitation and instead bind a previously-exported dev "
                "passkey record directly onto the admin (register-once → replay). Permitted ONLY "
                "under an explicitly 'dev_local' boot profile; refused (fail closed) otherwise."
            ),
        )
        parser.add_argument(
            "--dev-passkey-record",
            default="",
            metavar="PATH",
            help=(
                "Path to the exported dev passkey record for --import-dev-passkey "
                f"(default: $TAP_SECRETS_ROOT/{DEV_RECORD_RELPATH})."
            ),
        )
        parser.add_argument(
            "--profile",
            default="",
            metavar="NAME",
            help=(
                "Boot profile whose profile_kind gates --import-dev-passkey "
                "(default: $TAP_BOOT_PROFILE). Must classify as 'dev_local' to permit import."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["import_dev_passkey"]:
            self._handle_dev_import(options)
            return

        if not options["email"]:
            raise CommandError("--email is required when minting an enrollment invitation.")

        # Resolve the bootloader actor for the audit attribution. If it is absent, auth
        # sync has not run — refuse loudly rather than mint an unattributable invitation.
        try:
            bootloader = get_builtin_actor(BOOTLOADER)
        except MissingActor as exc:
            raise CommandError(
                "the tap_bootloader actor is missing — run `manage.py migrate` then "
                "`manage.py sync_auth` before genesis enrollment."
            ) from exc
        # The built-in bootloader IS a concrete User (AUTH_USER_MODEL) at runtime;
        # narrow the AbstractUser annotation so it types as the issued_by attribution.
        assert isinstance(bootloader, User)

        self._warn_if_admins_exist()

        try:
            invitation, secret = _mint_invitation(
                action=InvitationAction.ENROLL_FIRST,
                email=options["email"],
                display_name=options["display_name"],
                username=options["username"],
                grants=[ADMIN_ROLE],
                issued_by=bootloader,
                ttl=GENESIS_TTL,
            )
        except UsernameTaken as exc:
            raise CommandError(str(exc)) from exc

        path = reverse("passkey_enroll", args=[invitation.public_id])
        base_url = self._resolve_base_url(options["base_url"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Minted genesis admin invitation {invitation.public_id} "
                f"(expires {invitation.expires_at.isoformat()}, grants tap_admin)."
            )
        )
        if options["print_token"]:
            self.stdout.write("")
            self.stdout.write("One-time enrollment link (contains the secret — share over a secure channel):")
            self.stdout.write(f"  {base_url}{path}#{secret}")
        else:
            self.stdout.write(
                f"Public id: {invitation.public_id}. Re-run with --print-token to reveal the "
                "one-time enrollment link (the secret is shown once and never stored)."
            )

    def _handle_dev_import(self, options: dict[str, Any]) -> None:
        """Bind an exported dev passkey record onto the admin — the gated replay path.

        Two guards are the entire trust basis (:mod:`tap_auth.passkey.dev_record`): the
        profile-kind ALLOWLIST (permit only under an explicitly ``dev_local`` profile,
        checked FIRST so a wrong profile never even reads the record) and the record's own
        schema + integrity check. Below the capability gate like genesis — it binds an admin
        credential with no ceremony, so both guards are load-bearing."""
        profile_id = options["profile"] or os.environ.get("TAP_BOOT_PROFILE", "")
        profile_kind = read_profile_kind(profile_id)
        # Checked here so a wrong profile never even READS the record (and the operator gets
        # the refusal before any file I/O). `import_dev_admin` re-asserts it internally and
        # is the load-bearing gate (req-…-dev-bootstrap-15); this one is the early-out.
        try:
            assert_dev_import_allowed(profile_kind)
        except DevImportNotAllowed as exc:
            raise CommandError(str(exc)) from exc

        record_path = self._resolve_record_path(options["dev_passkey_record"])
        try:
            record = load_dev_record(record_path)
            user = import_dev_admin(record, profile_id=profile_id)
        except DevImportNotAllowed as exc:  # pragma: no cover — the early-out above fires first
            raise CommandError(str(exc)) from exc
        except DevRecordError as exc:
            raise CommandError(f"dev passkey import failed: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported dev passkey onto admin '{user.username}' from {record_path} "
                f"(profile '{profile_id}' = {profile_kind}). Log in with the passkey — no ceremony needed."
            )
        )

    def _resolve_record_path(self, override: str) -> Path:
        """Where to read the record: the explicit ``--dev-passkey-record`` path, else the
        default under the operator's secrets mount. Refuse loudly if it is not a file."""
        if override:
            path = Path(override)
        else:
            # settings.TAP_SECRETS_ROOT is the canonical in-Django lookup
            # (req-tap-cares-secrets-root-resolution) — never re-read the env here.
            path = Path(settings.TAP_SECRETS_ROOT) / DEV_RECORD_RELPATH
        if not path.is_file():
            raise CommandError(
                f"dev passkey record not found at {path} — run `manage.py export_dev_passkey` from a "
                "session that has registered a passkey and redirect it there first."
            )
        return path

    def _resolve_base_url(self, override: str) -> str:
        """The enrollment link's base URL: the ceremony's own origin, or a matching override.

        No fallback chain (req-tap-auth-passkey-enrollment-9): a link minted at
        anything other than TAP_PASSKEY_ORIGIN cannot complete the ceremony, so
        both the unset case and a mismatched --base-url fail here, loudly, with
        an actionable message — instead of handing over a dead link.
        """
        from django.core.exceptions import ImproperlyConfigured

        from tap_auth.passkey import config as passkey_config

        try:
            if override:
                passkey_config.assert_enrollment_origin(override)
                return override.rstrip("/")
            return passkey_config.enrollment_base_url().rstrip("/")
        except ImproperlyConfigured as exc:
            raise CommandError(str(exc)) from exc

    def _warn_if_admins_exist(self) -> None:
        """Genesis targets an empty instance; if a live admin already exists this is a
        deliberate additional-admin mint. Note it (not fatal — manage.py access is the
        root of trust) so an accidental re-run is visible."""
        from django.contrib.auth import get_user_model

        existing = (
            get_user_model()
            .objects.filter(
                is_active=True,
                deactivated_at__isnull=True,
                user_kind=UserKind.HUMAN,
                groups__name=ADMIN_ROLE,
            )
            .count()
        )
        if existing:
            self.stdout.write(
                self.style.WARNING(
                    f"Note: {existing} active human tap_admin already exist(s); minting an additional "
                    "admin enrollment invitation."
                )
            )
