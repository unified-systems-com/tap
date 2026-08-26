"""Auth boot section — config-time readers + boot-phase application (req-tap-auth-boot).

Two responsibilities, deliberately split by when they run:

  * **Settings-time readers** (``providers_for_settings`` / ``initial_admins_for_settings``
    / ``local_password_enabled_from_profile``) read the boot profile's ``auth``
    section from disk with NO Django model imports, so ``tap/settings.py`` can
    populate ``TAP_AUTH_PROVIDERS`` etc. at import time. One declarative source
    (the profile) feeds both the running server's settings and the boot command.

  * **Boot-phase application** (``apply_auth_boot_section``) runs inside the boot
    ``auth`` phase (after capabilities/groups/actors/initial-admin sync): it
    validates the section against tap_auth's schema fragment, runs each provider's
    self-tests (live for a deploy boot — req-tap-auth-providers-6), enforces the
    Django deploy posture, and enforces the last-admin invariant (boot must not
    converge to zero active human tap_admin unless break-glass is declared).

Secrets are never in the profile — providers reference an auth-scoped secret by
key (req-tap-auth-providers-3).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from django.conf import settings

from tap.boot_naming import profile_path
from tap.jsonfiles import JsonFileError, load_json_file, validate_json

logger = logging.getLogger(__name__)

Echo = Callable[[str], None]

_FRAGMENT_PATH = Path(__file__).resolve().parent / "schemas" / "auth-boot-section.schema.json"


class AuthBootError(Exception):
    """Raised when the auth boot section is invalid or its application must abort."""


# --------------------------------------------------------------------------- #
# settings-time readers (no model imports)
# --------------------------------------------------------------------------- #


def _profile_path(profile_id: str) -> Path:
    # Computed from this file's location (repo_root/tap_auth/boot.py →
    # repo_root/boot/) rather than settings.BASE_DIR: the settings-time readers
    # run DURING tap.settings import, where the lazy django.conf.settings object
    # is still mid-initialization and BASE_DIR is not yet accessible through it.
    # This also keeps the module a clean settings-time dependency with no reach
    # into tap_boot.
    repo_root = Path(__file__).resolve().parent.parent
    return profile_path(repo_root / "boot", profile_id)


def read_auth_section(profile_id: str) -> dict[str, Any]:
    """Return the raw ``auth`` section of ``boot/<profile_id>.boot.json`` ({} if absent).

    Tolerant by design — a malformed profile is the boot command's problem to
    surface loudly; settings-time reading must not crash the process on a bad
    file. Returns {} on any read/parse problem (logged).
    """
    if not profile_id:
        return {}
    path = _profile_path(profile_id)
    if not path.is_file():
        return {}
    try:
        data = load_json_file(path)
    except JsonFileError as exc:
        logger.warning("[2f1e] could not read auth section from %s: %s", path, exc)
        return {}
    section = data.get("auth")
    return section if isinstance(section, dict) else {}


def providers_for_settings(profile_id: str) -> list[dict[str, Any]]:
    """Provider config dicts for ``TAP_AUTH_PROVIDERS`` from the profile's auth section."""
    providers = read_auth_section(profile_id).get("providers")
    return providers if isinstance(providers, list) else []


def initial_admins_for_settings(profile_id: str) -> list[str]:
    """Initial-admin emails for ``TAP_AUTH_INITIAL_ADMINS`` from the profile."""
    admins = read_auth_section(profile_id).get("initial_admins")
    return admins if isinstance(admins, list) else []


# The role a bare ``initial_admins`` email is sugar for (kept as a literal here so
# this settings-time reader needs no import of the role registry, which pulls in
# Django/capabilities and is not safe mid-settings-import — mirrors the providers
# split). The schema enum + boot-phase validation are the real grantable guard.
# TAP-KNOWN-DUPE(admin-role): the in-Django source is tap_auth/roles.py ADMIN_ROLE —
# this settings-time copy exists because of the import boundary above. Every other
# site in this module derives from THIS constant, never the bare literal.
_ADMIN_ROLE = "tap_admin"


def initial_grants_for_settings(profile_id: str) -> dict[str, list[str]]:
    """Effective email -> roles grant map for ``TAP_AUTH_INITIAL_GRANTS``.

    Reads the profile's ``initial_grants`` and folds ``initial_admins`` into it as
    ``{email: ["tap_admin"]}``, so the two declarative sources collapse to ONE map
    the adapter applies at login. Emails are normalized (stripped + lowercased);
    roles for an email that appears in both sources are unioned (order-stable).

    Tolerant by design (settings-time): malformed entries are skipped, not fatal —
    the boot command validates the section against the schema and enforces the
    grantable-role guard loudly. No role-registry import here (see ``_ADMIN_ROLE``).
    """
    return merge_initial_grants(read_auth_section(profile_id))


def merge_initial_grants(section: dict[str, Any]) -> dict[str, list[str]]:
    """Pure merge of an auth section's ``initial_grants`` + ``initial_admins`` into
    one normalized email -> roles map (the testable core of
    :func:`initial_grants_for_settings`). Emails stripped + lowercased; roles
    unioned order-stably; malformed entries skipped (tolerant — boot validates)."""
    merged: dict[str, list[str]] = {}

    def _add(email: object, role: object) -> None:
        if not isinstance(email, str) or not isinstance(role, str):
            return
        key = email.strip().lower()
        if not key:
            return
        roles = merged.setdefault(key, [])
        if role not in roles:
            roles.append(role)

    raw_grants = section.get("initial_grants")
    if isinstance(raw_grants, dict):
        for email, role_list in raw_grants.items():
            if isinstance(role_list, list):
                for role in role_list:
                    _add(email, role)
    raw_admins = section.get("initial_admins")
    if isinstance(raw_admins, list):
        for email in raw_admins:
            _add(email, _ADMIN_ROLE)
    return merged


def local_password_enabled_from_profile(profile_id: str) -> bool:
    """Whether local password auth is enabled (default True when unset)."""
    return bool(read_auth_section(profile_id).get("local_password_enabled", True))


def read_profile_kind(profile_id: str) -> str | None:
    """Return the profile's top-level ``profile_kind`` classification, or ``None``.

    ``None`` when the profile id is empty, the file is absent/unreadable, or the field
    is unset — i.e. **unclassified**. Fail-closed guards (the dev-passkey import gate,
    req-tap-auth-passkey-dev-bootstrap-4) treat ``None`` and any non-``dev_local`` value
    as "not permitted" and refuse; only an EXPLICIT allowlisted value permits.

    Reads the profile JSON directly (no ``tap_boot`` import — this stays a leaf-level
    reader, mirroring :func:`read_auth_section`, and avoids a sideways app dependency).
    Tolerant: any read/parse problem yields ``None`` (fail closed), logged.
    """
    if not profile_id:
        return None
    path = _profile_path(profile_id)
    if not path.is_file():
        return None
    try:
        data = load_json_file(path)
    except JsonFileError as exc:
        logger.warning("[3821] could not read profile_kind from %s: %s", path, exc)
        return None
    kind = data.get("profile_kind")
    return kind if isinstance(kind, str) else None


# --------------------------------------------------------------------------- #
# boot-phase application
# --------------------------------------------------------------------------- #


def validate_auth_section(section: dict[str, Any]) -> None:
    """Validate an auth section against the tap_auth schema fragment. Raises
    AuthBootError on any violation (malformed config fails boot loudly)."""
    try:
        validate_json(section, _FRAGMENT_PATH, source="auth section")
    except JsonFileError as exc:
        raise AuthBootError(str(exc)) from exc


def apply_auth_boot_section(section: dict[str, Any], *, deploy: bool, echo: Echo) -> None:
    """Validate and apply the auth boot section (req-tap-auth-boot).

    ``deploy`` (True when not DEBUG) selects the strict posture: live provider
    self-tests + the Django deploy-security gate are enforced and FAIL aborts
    boot; a dev boot relaxes both but logs loudly. Always enforces the
    last-admin invariant.
    """
    from tap_auth.providers import ProviderConfig, get_provider

    validate_auth_section(section)
    _validate_initial_grants(section)

    if deploy:
        _check_deploy_posture(echo)

    providers = section.get("providers") or []
    for raw in providers:
        config = ProviderConfig.from_dict(raw)
        provider = get_provider(config.type)  # unknown type → UnknownProviderType (fails boot)
        try:
            secrets = provider.resolve_secrets(config)
        except Exception as exc:  # noqa: BLE001 - resolution failure is a boot-fatal config error
            if config.critical_for_boot:
                raise AuthBootError(f"provider '{config.id}': secret resolution failed: {exc}") from exc
            logger.warning("[7c4a] non-critical provider %s: secret resolution failed: %s", config.id, exc)
            secrets = {}
        results = provider.self_test(config, secrets, live=deploy)
        fails = [r for r in results if not r.ok]
        for r in results:
            echo(f"  [auth] provider {config.id}: {r.status.value.upper():4} {r.phase.value:<7} {r.check}: {r.message}")
        if fails and config.critical_for_boot:
            raise AuthBootError(
                f"provider '{config.id}' self-test FAILED: {[r.check for r in fails]}; "
                "critical_for_boot — aborting boot."
            )
        if fails:
            logger.warning("[3b6d] non-critical provider %s self-test FAILED: %s", config.id, [r.check for r in fails])

    _enforce_last_admin_invariant(
        allow_lockout=bool(section.get("allow_admin_lockout", False)),
        declared_admin_path=_declares_admin_path(section),
        echo=echo,
    )
    echo("Auth phase: auth section applied (providers validated, last-admin invariant enforced).")


def _declares_admin_path(section: dict[str, Any]) -> bool:
    """Whether the section declares a path to a human ``tap_admin`` on first login —
    a non-empty ``initial_admins`` OR any ``initial_grants`` entry granting
    ``tap_admin``. Either satisfies the last-admin invariant (req-tap-auth-boot)."""
    if section.get("initial_admins"):
        return True
    grants = section.get("initial_grants")
    if isinstance(grants, dict):
        return any(isinstance(r, list) and _ADMIN_ROLE in r for r in grants.values())
    return False


def _validate_initial_grants(section: dict[str, Any]) -> None:
    """Boot-fatal guard: every role named in ``initial_grants`` must be a defined,
    HUMAN-assignable role (req-tap-auth-roles).

    The schema enum already constrains the role values; this is defense-in-depth
    against schema/registry drift (an enum that outlives a role rename, or a role
    whose ``assignable_to`` dropped ``human``) and gives a precise boot failure
    rather than a silent grant the adapter would later refuse. Importing the role
    registry is safe here — boot phase, not settings-import time."""
    grants = section.get("initial_grants")
    if not isinstance(grants, dict):
        return
    from tap_auth.roles import HUMAN_ASSIGNABLE_ROLES

    offending: set[str] = set()
    for role_list in grants.values():
        if isinstance(role_list, list):
            offending.update(r for r in role_list if r not in HUMAN_ASSIGNABLE_ROLES)
    if offending:
        raise AuthBootError(
            f"auth.initial_grants names non-human-grantable or unknown role(s): {sorted(offending)}. "
            f"Only human-assignable roles may be granted at login: {sorted(HUMAN_ASSIGNABLE_ROLES)}."
        )


def _check_deploy_posture(echo: Echo) -> None:
    """Enforce the Django deployment-security posture before serving an
    auth-enabled deploy boot (req-tap-auth-boot). FAIL aborts."""
    problems: list[str] = []
    if not settings.SECRET_KEY or settings.SECRET_KEY == "dev-secret-key-change-me":
        problems.append("SECRET_KEY is unset or the dev default")
    if settings.DEBUG:
        problems.append("DEBUG is True")
    hosts = [h for h in (settings.ALLOWED_HOSTS or []) if h]
    if not hosts or "*" in hosts:
        problems.append("ALLOWED_HOSTS is empty or a wildcard")
    if not getattr(settings, "SESSION_COOKIE_SECURE", False):
        problems.append("SESSION_COOKIE_SECURE is False")
    if not getattr(settings, "CSRF_COOKIE_SECURE", False):
        problems.append("CSRF_COOKIE_SECURE is False")
    if problems:
        raise AuthBootError("deploy security posture check failed: " + "; ".join(problems))
    echo("Auth phase: deploy security posture OK.")


def _pending_admin_invitation_exists() -> bool:
    """Whether a live (pending, unexpired) first-enrollment invitation grants
    ``tap_admin`` — the genesis ``enroll_admin`` path to a human admin on first login
    (req-tap-auth-passkey-genesis-3). Uses the JSONB ``grants`` containment operator."""
    from django.utils import timezone

    from tap_auth.models import Invitation, InvitationAction, InvitationStatus

    return Invitation.objects.filter(
        status=InvitationStatus.PENDING,
        action=InvitationAction.ENROLL_FIRST,
        expires_at__gt=timezone.now(),
        grants__contains=[_ADMIN_ROLE],
    ).exists()


def _enforce_last_admin_invariant(*, allow_lockout: bool, declared_admin_path: bool, echo: Echo) -> None:
    """Boot must not converge to zero active human tap_admin (req-tap-auth-boot).

    Satisfied when ANY of: an active human admin already exists; the profile
    declares ``initial_admins`` (a path to admin on first login — not a lockout);
    or ``allow_admin_lockout`` break-glass is set. Otherwise a hard boot failure
    (recovery via the out-of-band management/shell floor).
    """
    from django.contrib.auth import get_user_model

    from tap_auth.models import UserKind

    user_model = get_user_model()
    active_human_admins = user_model.objects.filter(
        is_active=True,
        deactivated_at__isnull=True,
        user_kind=UserKind.HUMAN,
        groups__name=_ADMIN_ROLE,
    ).count()

    if active_human_admins > 0:
        echo(f"Auth phase: last-admin invariant OK ({active_human_admins} active human admin(s)).")
        return
    if declared_admin_path:
        echo("Auth phase: last-admin invariant OK (initial_admins declared — admin on first login).")
        return
    if _pending_admin_invitation_exists():
        # A genesis `enroll_admin` invitation is an unredeemed path to admin — exactly
        # like initial_admins, but via the passkey enrollment chokepoint. Boot should
        # not lock out just because the operator has minted but not yet redeemed it
        # (req-tap-auth-passkey-genesis-3).
        echo("Auth phase: last-admin invariant OK (pending tap_admin enrollment invitation).")
        return
    if allow_lockout:
        logger.warning("[5e22] admin lockout permitted by break-glass: zero active human tap_admin")
        echo("Auth phase: WARNING — zero active human admin, permitted by allow_admin_lockout.")
        return
    raise AuthBootError(
        "applying this profile would leave NO active human tap_admin, and neither initial_admins "
        "nor allow_admin_lockout is set. Declare an initial admin (auth.initial_admins + a login) "
        "or set allow_admin_lockout for a deliberate headless standup. Aborting."
    )
