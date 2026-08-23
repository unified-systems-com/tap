"""`manage.py bootstrap_dev_passkey` — the guided dev passkey onboarding command.

The single implementation of dev passkey onboarding (req-tap-auth-passkey-dev-bootstrap-9).
`scripts/spawn-session.sh` and the `bootstrap-dev-passkey` skill are its two CALLERS; neither
reimplements this logic, so there is one place to be correct and one place an AI operator can
drive (spec-ai-integration.md).

It resolves exactly one state, then acts on it:

    not_dev             the boot profile is not explicitly `dev_local` → refuse every action
    ready               a record exists AND schema-validates AND its digest verifies → import
    needs_registration  no record, or one that is absent/empty/truncated/corrupt/tampered

**Readiness is validation, never a stat** (req-…-dev-bootstrap-10). `[[ -f record ]]` is true
of a zero-byte file, which is exactly what a failed `> record` redirect leaves behind (the
shell truncates the target before the command runs). Only `load_dev_record` — shape plus
integrity digest — can distinguish *present* from *usable*, and the diagnostic says which
of the two failed.

**Stream discipline** (req-…-dev-bootstrap-11): narration, prompts, and the enrollment URL go
to stderr. The record JSON goes to stdout under `--emit-record`. Machine state goes to stdout
under `--json`. Nothing else is ever written to stdout, so redirecting it is always safe and
never captures the one-time enrollment secret.

**This command never writes the record** (req-…-dev-bootstrap-12). The secrets root is
mounted read-only into the container on purpose — that mount is a real integrity control for
a file whose integrity is load-bearing. The host caller owns placement and MUST write to a
temp file then `rename(2)` it into place, `chmod 600`.

**Waiting is opt-in** (req-…-dev-bootstrap-13). `--wait` blocks for a human at a browser, so
the caller decides whether a human is present: `docker compose exec -T` strips the TTY, so an
`isatty()` check *inside* the container would answer for the wrong process. Spawn tests
`[[ -t 0 ]]` on the host and only then passes `--wait`. Without it, this command prints the
next command and exits 0 — CI, `scripts/gate-lean`, and throwaway stacks are never blocked.

Typical guided first run, driven by the host:

    manage.py bootstrap_dev_passkey --register --wait --emit-record > record.tmp
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from tap_auth.errors import MissingActor
from tap_auth.invitations import GENESIS_TTL, UsernameTaken, mint_below_gate_as_bootloader
from tap_auth.models import InvitationAction, User, WebAuthnCredential
from tap_auth.passkey.dev_record import (
    DEV_ADMIN_USERNAME,
    DEV_RECORD_RELPATH,
    DevImportNotAllowed,
    DevRecordError,
    assert_dev_import_allowed,
    build_record_for_user,
    import_dev_admin,
    load_dev_record,
    resolve_profile_kind,
)
from tap_auth.roles import ADMIN_ROLE

logger = logging.getLogger(__name__)

STATE_NOT_DEV = "not_dev"
STATE_READY = "ready"
STATE_NEEDS_REGISTRATION = "needs_registration"

_POLL_SECONDS = 2
_DEFAULT_TIMEOUT = 300


class Command(BaseCommand):
    help = "Guided dev passkey onboarding: resolve state, register once, replay forever."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print the resolved state object to stdout and exit. No side effects.",
        )
        parser.add_argument(
            "--register",
            action="store_true",
            help="Mint a one-time enrollment link for the dev admin and print it to stderr.",
        )
        parser.add_argument(
            "--wait",
            action="store_true",
            help=(
                "After --register, block until the passkey is registered (or --timeout elapses). "
                "Only pass this when a human is at a browser; the caller owns that decision."
            ),
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=_DEFAULT_TIMEOUT,
            metavar="SECONDS",
            help=f"Bound on --wait (default: {_DEFAULT_TIMEOUT}). A walk-away times out, never hangs.",
        )
        parser.add_argument(
            "--emit-record",
            action="store_true",
            help="Print the dev admin's PUBLIC passkey record as JSON to stdout (redirect it; see --help).",
        )
        parser.add_argument(
            "--import",
            dest="do_import",
            action="store_true",
            help="Bind the on-disk record onto the dev admin (the every-spawn replay path).",
        )
        parser.add_argument(
            "--record",
            default="",
            metavar="PATH",
            help=f"Dev passkey record path (default: $TAP_SECRETS_ROOT/{DEV_RECORD_RELPATH}).",
        )
        parser.add_argument(
            "--profile",
            default="",
            metavar="NAME",
            help="Boot profile whose profile_kind gates every action here (default: $TAP_BOOT_PROFILE).",
        )
        parser.add_argument(
            "--base-url",
            default="",
            metavar="URL",
            help="Origin for the enrollment link (default: TAP_PASSKEY_ORIGIN). Must match it — the ceremony compares origins exactly.",
        )

    # ----------------------------------------------------------------- state

    def _record_path(self, override: str) -> Path:
        if override:
            return Path(override)
        # settings.TAP_SECRETS_ROOT is the canonical in-Django lookup
        # (req-tap-cares-secrets-root-resolution) — never re-read the env here.
        return Path(settings.TAP_SECRETS_ROOT) / DEV_RECORD_RELPATH

    def _resolve_state(self, profile_id: str, record_path: Path) -> dict[str, Any]:
        """Classify the world. The profile decision defers to `assert_dev_import_allowed`,
        the single allowlist authority — a second gate here could drift from it."""
        profile_kind = resolve_profile_kind(profile_id or None)
        try:
            assert_dev_import_allowed(profile_kind)
        except DevImportNotAllowed as exc:
            return {"state": STATE_NOT_DEV, "profile_kind": profile_kind, "detail": str(exc)}

        # Validation, not a stat: a zero-byte or corrupt record is NOT `ready`.
        if not record_path.exists():
            return {"state": STATE_NEEDS_REGISTRATION, "profile_kind": profile_kind, "detail": "no record on disk"}
        try:
            load_dev_record(record_path)
        except DevRecordError as exc:
            return {
                "state": STATE_NEEDS_REGISTRATION,
                "profile_kind": profile_kind,
                "detail": f"record present but unusable: {exc}",
            }
        return {"state": STATE_READY, "profile_kind": profile_kind, "detail": "record validates"}

    # --------------------------------------------------------------- actions

    def handle(self, *args: Any, **options: Any) -> None:
        profile_id = options["profile"] or os.environ.get("TAP_BOOT_PROFILE", "")
        record_path = self._record_path(options["record"])
        state = self._resolve_state(profile_id, record_path)
        state["record_path"] = str(record_path)
        state["username"] = DEV_ADMIN_USERNAME

        if options["json"]:
            # The state object IS the machine payload — stdout carries nothing else.
            self.stdout.write(json.dumps(state, indent=2, sort_keys=True))
            return

        # `--wait` counts as an action in its own right: a flag that silently no-ops when
        # passed alone is worse than one that errors, and "wait for a passkey to appear" is
        # a legitimate standalone step (a second terminal watching a registration).
        acting = options["register"] or options["do_import"] or options["emit_record"] or options["wait"]
        if state["state"] == STATE_NOT_DEV and acting:
            raise CommandError(state["detail"])

        if not acting:
            self._report(state)
            return

        if options["do_import"]:
            self._do_import(record_path, profile_id)
        if options["register"]:
            self._do_register(state, options)
        if options["wait"]:
            self._do_wait(options["timeout"])
        if options["emit_record"]:
            self._do_emit_record()

    def _report(self, state: dict[str, Any]) -> None:
        """No action flags: say where we are and what to run next. Always exit 0 — a
        status read is never a failure, and spawn calls this on every boot."""
        self.stderr.write(f"State: {state['state']} ({state['detail']})")
        if state["state"] == STATE_NOT_DEV:
            self.stderr.write("Dev passkey onboarding is refused outside an explicitly 'dev_local' profile.")
            return
        if state["state"] == STATE_READY:
            self.stderr.write("Run with --import to bind the recorded passkey onto the dev admin.")
            return
        self.stderr.write(
            "Run with --register --wait --emit-record > record.tmp to register a passkey once, "
            "then move record.tmp into place with 0600 perms."
        )

    def _do_import(self, record_path: Path, profile_id: str) -> None:
        try:
            record = load_dev_record(record_path)
            user = import_dev_admin(record, profile_id=profile_id or None)
        except (DevRecordError, DevImportNotAllowed) as exc:
            raise CommandError(f"dev passkey import failed: {exc}") from exc
        self.stderr.write(self.style.SUCCESS(f"Dev passkey bound onto '{user.username}'. Log in with your passkey."))

    def _do_register(self, state: dict[str, Any], options: dict[str, Any]) -> None:
        """Mint a one-time enrollment link for the dev admin.

        Two shapes, one outcome — `admin` ends up holding a passkey:

        * the account does not exist (a truly fresh instance) → `enroll_first` with the
          username PINNED to `DEV_ADMIN_USERNAME`, so register-once and replay agree on one
          account (req-…-dev-bootstrap-14);
        * the account exists (the usual case — spawn's password bridge already created it)
          → `add_credential` targeting it by internal id. Keep-and-add: no new user, no
          re-grant. Pinning `enroll_first` here would (correctly) refuse as create-only.
        """
        existing = User.objects.filter(username=DEV_ADMIN_USERNAME).first()
        try:
            if existing is None:
                invitation, secret = mint_below_gate_as_bootloader(
                    action=InvitationAction.ENROLL_FIRST,
                    email="",
                    display_name=DEV_ADMIN_USERNAME,
                    username=DEV_ADMIN_USERNAME,
                    grants=[ADMIN_ROLE],
                    ttl=GENESIS_TTL,
                )
                logger.info("[c878] dev passkey onboarding minted enroll_first for a fresh dev admin")
            else:
                invitation, secret = mint_below_gate_as_bootloader(
                    action=InvitationAction.ADD_CREDENTIAL,
                    target_user=existing,
                    display_name=DEV_ADMIN_USERNAME,
                    ttl=GENESIS_TTL,
                )
                logger.info("[2a08] dev passkey onboarding minted add_credential for the existing dev admin")
        except UsernameTaken as exc:
            raise CommandError(str(exc)) from exc
        except MissingActor as exc:
            raise CommandError(
                "the tap_bootloader actor is missing — run `manage.py migrate` then `manage.py sync_auth` first."
            ) from exc

        base_url = self._resolve_base_url(options["base_url"])
        path = reverse("passkey_enroll", args=[invitation.public_id])
        # stderr: this URL carries the one-time secret in its fragment. It must never land
        # in a file a caller redirected stdout into (req-…-dev-bootstrap-11).
        self.stderr.write("")
        self.stderr.write(self.style.SUCCESS("Open this link and register your passkey (Touch ID / security key):"))
        self.stderr.write(f"  {base_url}{path}#{secret}")
        self.stderr.write(f"  (one-time, expires {invitation.expires_at.isoformat()})")
        self.stderr.write("")

    def _do_wait(self, timeout: int) -> None:
        """Poll until the dev admin holds a credential. Bounded: a developer who walks away
        gets a clear timeout, never a hung spawn (req-…-dev-bootstrap-13)."""
        self.stderr.write(f"Waiting up to {timeout}s for the passkey registration to complete…")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if WebAuthnCredential.objects.filter(user__username=DEV_ADMIN_USERNAME).exists():
                logger.info("[b6b4] dev passkey onboarding observed a registered credential")
                self.stderr.write(self.style.SUCCESS("Passkey registered."))
                return
            time.sleep(_POLL_SECONDS)
        logger.warning("[9c10] dev passkey onboarding timed out waiting for registration")
        raise CommandError(
            f"timed out after {timeout}s waiting for a passkey on '{DEV_ADMIN_USERNAME}'. "
            "Nothing was written. Re-run --register --wait when you are ready to register."
        )

    def _do_emit_record(self) -> None:
        try:
            record = build_record_for_user(DEV_ADMIN_USERNAME)
        except DevRecordError as exc:
            raise CommandError(str(exc)) from exc
        logger.info("[767b] dev passkey record emitted to stdout for %s", DEV_ADMIN_USERNAME)
        self.stderr.write(self.style.SUCCESS("Record emitted on stdout. Move it into place with 0600 perms."))
        # stdout carries ONLY the record.
        self.stdout.write(json.dumps(record, indent=2, sort_keys=True))

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
