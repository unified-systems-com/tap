"""Dev passkey record — export / load / gated import (req-tap-auth-passkey-dev-bootstrap).

The dev-only "register once, replay forever" path. The operator registers a `localhost`
passkey once, exports the PUBLIC credential record (:func:`build_dev_record`), and every
freshly-spawned dev session binds that same passkey with no re-registration
(:func:`import_dev_admin`) — the one-gesture dev login that exercises the real passkey
path instead of a password bridge.

Two guards are the ENTIRE trust basis of import (it creates an admin + binds a credential
with zero proof-of-possession and no human interaction — there is no attestation and no
challenge-response at import):

* :func:`assert_dev_import_allowed` — the **allowlist** gate. Import is permitted ONLY
  under an explicitly ``dev_local``-classified boot profile; missing/unknown/customer/
  deploy all refuse (fail closed). Never keyed off ``DEBUG``; ``TAP_TEST_MODE`` is not an
  enabler here (req-tap-auth-passkey-dev-bootstrap-4). It runs **inside**
  :func:`import_dev_admin`, not in front of it (req-…-dev-bootstrap-15), so the guarantee
  is structural rather than a rule callers are asked to remember.
* :func:`load_dev_record` integrity check — schema validation (shape) PLUS a canonical
  self-digest (corruption detection). The load-bearing anti-tamper mitigation is the file
  living 0600 in an operator-owned dir; the same-uid residual is NAMED, not defended here
  (req-tap-auth-passkey-dev-bootstrap-8).

Confidentiality of the record is low-stakes (no private key); its INTEGRITY is what matters.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from django.contrib.auth.models import Group
from django.utils import timezone

from tap.boot_records import canonical_digest_bytes
from tap.jsonfiles import JsonFileError, load_json_file
from tap_auth.boot import read_profile_kind
from tap_auth.models import User, UserKind, WebAuthnCredential, WebAuthnCredentialDeviceType, WebAuthnUserHandle
from tap_auth.roles import ADMIN_ROLE, is_login_grantable

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "dev-passkey-record.schema.json"

# The one allowlisted profile classification that permits dev import. An EXPLICIT value —
# anything else (customer/deploy/unclassified/typo) fails closed (req-…-dev-bootstrap-4).
PROFILE_KIND_DEV_LOCAL = "dev_local"

# The dev admin the replayed passkey binds to. Matches the spawn password-bridge username
# so the dev passkey lands on the same familiar `admin` account (add-a-credential, not a
# second admin).
DEV_ADMIN_USERNAME = "admin"

#: Default on-disk location of the exported dev passkey record, relative to the
#: secrets root. One home: both `enroll_admin` and `bootstrap_dev_passkey` import
#: it rather than restating the path (2026-08 code-clone sweep, finding S2).
DEV_RECORD_RELPATH = "dev-passkey/admin.dev-passkey.json"

RECORD_VERSION = 1


class DevRecordError(Exception):
    """The dev passkey record could not be loaded, validated, or its integrity verified."""


class DevImportNotAllowed(Exception):
    """Dev passkey import was refused because the active profile is not explicitly
    ``dev_local`` (the `exemption_not_allowed` assurance class, req-…-dev-bootstrap-4)."""


# --------------------------------------------------------------------------- #
# Allowlist gate                                                              #
# --------------------------------------------------------------------------- #


def assert_dev_import_allowed(profile_kind: str | None) -> None:
    """Permit dev passkey import ONLY under an explicitly ``dev_local`` profile.

    Allowlist, not denylist: any missing/unknown/customer/deploy classification is
    refused (fail closed), so an unclassified or typo'd profile cannot slip through.
    Deliberately does NOT consult ``settings.DEBUG`` (legitimately True in non-test
    instances) and ``TAP_TEST_MODE`` is not an enabler — reaching this already required
    shell access, and the gate is re-evaluated on every invocation."""
    if profile_kind != PROFILE_KIND_DEV_LOCAL:
        raise DevImportNotAllowed(
            f"--import-dev-passkey is permitted only under an explicitly '{PROFILE_KIND_DEV_LOCAL}' "
            f"boot profile; active classification is {profile_kind!r} (refused, fail closed). "
            "Dev passkey replay is a developer-local affordance and must never run on a "
            "customer/deploy or unclassified profile."
        )


# --------------------------------------------------------------------------- #
# Integrity + (de)serialization                                              #
# --------------------------------------------------------------------------- #


def _integrity_digest(record: dict[str, Any]) -> str:
    """Canonical sha256 over the record with the ``integrity`` object removed — the one
    canonicalization definition (:func:`tap.boot_records.canonical_digest_bytes`), so a
    cosmetic reformat does not move the digest; only real content changes do."""
    without = {k: v for k, v in record.items() if k != "integrity"}
    # canonical_digest_bytes re-canonicalizes (sorted keys, tight separators), so any valid
    # JSON encoding of `without` hashes identically — plain json.dumps is enough here.
    return canonical_digest_bytes(json.dumps(without).encode("utf-8"))


def build_dev_record(*, user_handle_hex: str, credential: WebAuthnCredential) -> dict[str, Any]:
    """Serialize the PUBLIC dev passkey record from a registered credential + its handle.

    Captures the registration's user handle (replayed so every session's admin shares it)
    and the public credential material only — never any private key. Stamps the corruption-
    detection self-digest last."""
    device_type_value = getattr(credential.device_type, "value", credential.device_type)
    record: dict[str, Any] = {
        "version": RECORD_VERSION,
        "rp_id": "localhost",
        "origin_policy": "per_session_localhost_exact",
        "user_handle": user_handle_hex,
        "credential": {
            "credential_id": credential.credential_id,
            "public_key": credential.public_key,
            "sign_count": int(credential.sign_count),
            "aaguid": credential.aaguid or "",
            "transports": list(credential.transports or []),
            "device_type": str(device_type_value),
            "backed_up": bool(credential.backed_up),
        },
        "exported_at": timezone.now().isoformat(),
    }
    record["integrity"] = {"digest_alg": "sha256", "digest": _integrity_digest(record)}
    return record


class DevRecordUnavailable(DevRecordError):
    """The dev admin has no exportable passkey (no user, no handle, no/ambiguous credential)."""


def build_record_for_user(username: str = DEV_ADMIN_USERNAME, *, credential_id: str = "") -> dict[str, Any]:
    """Build the PUBLIC dev record for ``username``'s passkey. Shared by
    `export_dev_passkey` and `bootstrap_dev_passkey` so the two cannot drift on which
    credential they select. Refuses to guess when a user has several and none is named —
    export is a deliberate act, and silently picking one could replay the wrong key."""
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist as exc:
        raise DevRecordUnavailable(
            f"no user '{username}' — register a passkey against a running session first, then export it."
        ) from exc

    handle = WebAuthnUserHandle.objects.filter(user=user).first()
    if handle is None:
        raise DevRecordUnavailable(
            f"user '{username}' has no WebAuthn user handle — has this account ever registered a passkey?"
        )

    credentials = WebAuthnCredential.objects.filter(user=user)
    if credential_id:
        try:
            credential = credentials.get(credential_id=credential_id)
        except WebAuthnCredential.DoesNotExist as exc:
            raise DevRecordUnavailable(f"user '{username}' has no credential '{credential_id}'.") from exc
    else:
        found = list(credentials.order_by("-created")[:2])
        if not found:
            raise DevRecordUnavailable(f"user '{username}' has no registered passkey to export.")
        if len(found) > 1:
            raise DevRecordUnavailable(
                f"user '{username}' has multiple passkeys — pass --credential-id to choose which to export."
            )
        credential = found[0]

    return build_dev_record(user_handle_hex=handle.handle, credential=credential)


def load_dev_record(path: str | Path) -> dict[str, Any]:
    """Read + schema-validate + integrity-verify a dev passkey record. Fail-closed.

    Schema validation checks SHAPE; the self-digest catches corruption. Neither proves
    authenticity — that rests on the file's 0600 operator-owned integrity + the dev/local
    allowlist gate. Raises :class:`DevRecordError` on any problem."""
    path = Path(path)
    if not path.is_file():
        raise DevRecordError(f"dev passkey record not found: {path}")
    try:
        record = load_json_file(path, schema=_SCHEMA_PATH)
    except JsonFileError as exc:
        logger.warning("[14c3] dev passkey record failed schema validation path=%s: %s", path, exc)
        raise DevRecordError(f"dev passkey record is invalid: {exc}") from exc
    if not isinstance(record, dict):
        raise DevRecordError("dev passkey record must be a JSON object")

    declared = record["integrity"]["digest"]
    computed = _integrity_digest(record)
    if declared != computed:
        logger.warning("[28c6] dev passkey record integrity mismatch path=%s (corrupt/tampered)", path)
        raise DevRecordError(
            "dev passkey record integrity digest does not match its content "
            "(corrupted or tampered) — refusing to import."
        )
    return record


# --------------------------------------------------------------------------- #
# Import (below the capability gate)                                          #
# --------------------------------------------------------------------------- #


def resolve_profile_kind(profile_id: str | None = None) -> str | None:
    """Classify the ACTIVE boot profile, falling back to ``TAP_BOOT_PROFILE``.

    ``None`` (unclassified) whenever the id is empty/absent or the profile does not
    declare a ``profile_kind`` — which :func:`assert_dev_import_allowed` refuses. Fail
    closed at every step: an unset env var yields ``""`` yields ``None`` yields refused."""
    resolved = profile_id if profile_id is not None else os.environ.get("TAP_BOOT_PROFILE", "")
    return read_profile_kind(resolved)


def import_dev_admin(
    record: dict[str, Any],
    *,
    profile_id: str | None = None,
    username: str = DEV_ADMIN_USERNAME,
) -> User:
    """Bind the record's passkey onto the dev admin (idempotent), granting ``tap_admin``.

    Below the capability gate (root-of-trust bootstrap, like genesis): binds the credential
    directly with NO ceremony — import substitutes the already-verified record for the
    registration proof-of-possession. Get-or-creates the ``admin`` user, pins its
    WebAuthnUserHandle to the record's handle so future assertions resolve, and
    update-or-creates the credential (re-spawn just refreshes it). Grants ``tap_admin``
    fail-loud (a missing group would be a powerless admin).

    **The allowlist gate runs HERE, first, unconditionally** (req-…-dev-bootstrap-15). It
    used to live only at the `enroll_admin` call site, with a docstring instructing callers
    to invoke it — an instruction four test call sites already ignored. Since this function
    creates an admin and binds a credential with *zero proof-of-possession*, the most
    consequential rule in the passkey spec cannot rest on caller discipline: no caller,
    present or future, can now reach the bind without passing the gate. `profile_id`
    overrides the ambient ``TAP_BOOT_PROFILE`` (spawn passes its resolved profile); it can
    only ever select which profile is *classified*, never whether the gate runs."""
    assert_dev_import_allowed(resolve_profile_kind(profile_id))
    cred = record["credential"]

    user, created = User.objects.get_or_create(
        username=username,
        defaults={"email": "", "user_kind": UserKind.HUMAN},
    )
    if created:
        # A dev admin WE mint authenticates with the passkey only — no usable password
        # (mirrors the enrollment path's set_unusable_password honesty edge). Django treats
        # an empty password as usable, so this is not a no-op. We deliberately do NOT touch
        # an EXISTING account's password: when import binds onto the spawn password-bridge
        # admin, that fallback survives until password retirement is done globally.
        user.set_unusable_password()
        user.save(update_fields=["password"])
    # Pin the handle to the record's — all of the dev admin's credentials share it, and it
    # must equal the discoverable credential's userHandle for the assertion to resolve.
    WebAuthnUserHandle.objects.update_or_create(
        # TAP-CRED-BIND: dev-profile-gate — assert_dev_import_allowed ran at function top.
        user=user,
        defaults={"handle": record["user_handle"]},
    )
    device_type = (
        WebAuthnCredentialDeviceType.MULTI_DEVICE
        if cred["device_type"] == "multi_device"
        else WebAuthnCredentialDeviceType.SINGLE_DEVICE
    )
    credential_obj, _ = WebAuthnCredential.objects.update_or_create(
        # TAP-CRED-BIND: dev-profile-gate — zero-PoP replay, gated by assert_dev_import_allowed (top).
        credential_id=cred["credential_id"],
        defaults={
            "user": user,
            "public_key": cred["public_key"],
            "sign_count": cred["sign_count"],
            "aaguid": cred.get("aaguid", ""),
            "transports": list(cred.get("transports", [])),
            "device_type": device_type,
            "backed_up": bool(cred.get("backed_up", False)),
            "device_label": "dev-replay",
        },
    )
    _grant_admin(user)
    logger.info(
        "[eb22] dev passkey imported: user=%s cred=%s device_type=%s",
        user.pk,
        credential_obj.redacted_credential_id,
        device_type,
    )
    return user


def _grant_admin(user: User) -> None:
    """Ensure the dev admin holds ``tap_admin`` — fail loud if the group is missing (a
    silently-skipped grant would leave a powerless 'admin'; mirrors the genesis grant)."""
    if not is_login_grantable(ADMIN_ROLE):
        raise DevRecordError(f"role '{ADMIN_ROLE}' is not human-assignable")
    try:
        group = Group.objects.get(name=ADMIN_ROLE)
    except Group.DoesNotExist as exc:
        raise DevRecordError(f"role group '{ADMIN_ROLE}' does not exist (grant would be a no-op)") from exc
    user.groups.add(group)
