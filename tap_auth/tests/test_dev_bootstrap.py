"""Dev bootstrap passkey replay — register once, replay forever (req-tap-auth-passkey-dev-bootstrap).

Driven end-to-end against the REAL ``py_webauthn`` via the vendored
:class:`VirtualAuthenticator`: a passkey registered in one "session" is exported as a
PUBLIC record and re-bound in a fresh session with NO ceremony, and the same authenticator
then completes a real assertion as admin. That proves the whole replay contract at once —
public-only replay (dev-bootstrap-1), the password-bridge replacement (2),
one-passkey-many-sessions (3), the real assertion path (5). The prod fail-closed allowlist
(4) is exercised both directly and through :func:`read_profile_kind` against the shipped
profiles; the exact-origin policy (6), schema (7), and integrity (8) round it out.

The entire trust basis of import is exactly two guards — the ``dev_local`` allowlist gate and
the record integrity check — so both get negative cases here, not just the happy path.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from tap_auth.boot import read_profile_kind
from tap_auth.invitations import GENESIS_TTL, _mint_invitation, redeem_invitation
from tap_auth.models import Invitation, InvitationAction, WebAuthnCredential, WebAuthnUserHandle
from tap_auth.passkey import ceremony
from tap_auth.passkey import config as passkey_config
from tap_auth.passkey.dev_record import (
    DevImportNotAllowed,
    DevRecordError,
    assert_dev_import_allowed,
    build_dev_record,
    import_dev_admin,
    load_dev_record,
)

from .virtual_authenticator import VirtualAuthenticator

User = get_user_model()

# A shipped profile classified `dev_local` — the one classification that permits import.
# Passed EXPLICITLY at every import call site: the gate now lives inside `import_dev_admin`
# (req-…-dev-bootstrap-15), so a test that omitted it would be leaning on whatever
# `TAP_BOOT_PROFILE` happens to hold, and would silently stop exercising the gate if that
# ambient value ever changed.
_DEV_PROFILE = "core_dev"


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _make_authenticator(**kwargs) -> VirtualAuthenticator:
    origin = passkey_config.expected_origins()[0]
    return VirtualAuthenticator(rp_id=settings.TAP_PASSKEY_RP_ID, origin=origin, **kwargs)


def _register_admin(authenticator: VirtualAuthenticator, *, email: str = "op@example.com"):
    """Enroll an admin against `authenticator` (session A) and return the created user."""
    invitation, secret = _mint_invitation(
        action=InvitationAction.ENROLL_FIRST,
        email=email,
        grants=["tap_admin"],
        ttl=GENESIS_TTL,
    )
    assert isinstance(invitation, Invitation)
    user_handle = secrets.token_bytes(64)
    _options_json, challenge = ceremony.registration_options(
        user_handle, user_label="op", display_name="op", exclude_credential_ids=[]
    )
    credential = authenticator.register(challenge)
    return redeem_invitation(
        invitation.public_id,
        secret,
        credential=credential,
        expected_challenge=challenge,
        user_handle=user_handle,
    )


def _record_for(user) -> dict[str, Any]:
    """Export the PUBLIC dev record for `user`'s sole credential (the operator's one-time export)."""
    credential = WebAuthnCredential.objects.get(user=user)
    return build_dev_record(user_handle_hex=user.webauthn_handle.handle, credential=credential)


def _free_credential_and_handle(user) -> None:
    """Release the globally-unique credential id + user handle so a subsequent import can
    re-bind them onto a fresh admin — modeling a new spawn WITHOUT deleting the User (a
    User.delete() cascades through the simple-history signal machinery and is fragile under
    the full lane; see test_passkey_assurance.test_concurrent_redeem's note)."""
    WebAuthnCredential.objects.filter(user=user).delete()
    WebAuthnUserHandle.objects.filter(user=user).delete()


def _assert_authenticates(authenticator: VirtualAuthenticator, user):
    """Drive a REAL usernameless assertion for `user` and return the resolved user."""
    _options_json, challenge = ceremony.authentication_options()
    assertion = authenticator.authenticate(challenge, user_handle=bytes.fromhex(user.webauthn_handle.handle))
    return ceremony.authenticate(assertion, challenge)


# --------------------------------------------------------------------------- #
# The full replay: register (session A) → export → import (session B) → assert #
# --------------------------------------------------------------------------- #


@pytest.mark.spec("req-tap-auth-passkey-dev-bootstrap-1")
@pytest.mark.django_db
def test_public_record_carries_no_private_key():
    authenticator = _make_authenticator(uv=True, be=True, bs=True)
    user = _register_admin(authenticator)
    record = _record_for(user)

    # Only the public credential fields travel — no private-key material, ever.
    assert set(record["credential"]) == {
        "credential_id",
        "public_key",
        "sign_count",
        "aaguid",
        "transports",
        "device_type",
        "backed_up",
    }
    blob = json.dumps(record).lower()
    assert "private" not in blob and "secret" not in blob


@pytest.mark.spec("req-tap-auth-passkey-dev-bootstrap-3")
@pytest.mark.django_db
def test_one_passkey_replays_into_a_fresh_session_as_admin():
    """The headline: a passkey registered once, exported, and re-imported into a fresh
    session binds the SAME credential onto admin with no ceremony, and the original
    authenticator completes a real assertion as that admin (dev-bootstrap-2/3/5)."""
    authenticator = _make_authenticator(uv=True, be=True, bs=True)
    session_a_user = _register_admin(authenticator, email="sessiona@example.com")
    record = _record_for(session_a_user)

    # Simulate a fresh spawn: free the credential id + handle (the unique keys import
    # re-binds). We drop only these plain off-spine rows, NOT the User — a User.delete()
    # cascades through the simple-history signal machinery and is fragile under the full
    # lane (see the note in test_passkey_assurance.test_concurrent_redeem).
    _free_credential_and_handle(session_a_user)
    assert not WebAuthnCredential.objects.exists()

    imported = import_dev_admin(record, profile_id=_DEV_PROFILE)
    # (2) an admin that authenticates with a passkey, not a password bridge.
    assert imported.groups.filter(name="tap_admin").exists()
    assert not imported.has_usable_password()
    assert WebAuthnCredential.objects.filter(user=imported).count() == 1

    # (5) the REAL assertion path resolves back to the imported admin — no cookie mint.
    resolved = _assert_authenticates(authenticator, imported)
    assert resolved.pk == imported.pk


@pytest.mark.spec("req-tap-auth-passkey-dev-bootstrap-3")
@pytest.mark.django_db
def test_import_is_idempotent_across_repeated_spawns():
    """Re-importing the same record (each spawn re-runs it) converges: one admin, one
    credential, still authenticating — a reboot does not fork the account."""
    authenticator = _make_authenticator(uv=True)
    user = _register_admin(authenticator, email="sessiona@example.com")
    record = _record_for(user)
    _free_credential_and_handle(user)

    first = import_dev_admin(record, profile_id=_DEV_PROFILE)
    second = import_dev_admin(record, profile_id=_DEV_PROFILE)
    assert first.pk == second.pk
    assert User.objects.filter(username="admin").count() == 1
    assert WebAuthnCredential.objects.filter(user=second).count() == 1
    assert _assert_authenticates(authenticator, second).pk == second.pk


# --------------------------------------------------------------------------- #
# Prod fail-closed allowlist (dev-bootstrap-4)                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.spec("req-tap-auth-passkey-dev-bootstrap-4")
def test_allowlist_permits_only_explicit_dev_local():
    assert_dev_import_allowed("dev_local")  # the one permitted value
    # Everything else fails closed — absent, customer/deploy, unknown, case/typo variants.
    for refused in (None, "", "customer", "deploy", "dev", "DEV_LOCAL", "local", "prod"):
        with pytest.raises(DevImportNotAllowed):
            assert_dev_import_allowed(refused)


@pytest.mark.spec("req-tap-auth-passkey-dev-bootstrap-15")
@pytest.mark.django_db
def test_direct_import_call_is_gated_without_any_caller_cooperation():
    """The gate is structural, not a caller convention (dev-bootstrap-15).

    This calls `import_dev_admin` the way a careless future caller would — directly, with a
    valid record, having never touched `assert_dev_import_allowed`. Under a deployable
    (unclassified) profile it MUST refuse, and MUST NOT have written a user or credential.
    Before the gate moved inside, this call bound an admin credential with zero
    proof-of-possession."""
    user = _register_admin(_make_authenticator(uv=True), email="sessiona@example.com")
    record = _record_for(user)
    _free_credential_and_handle(user)

    with pytest.raises(DevImportNotAllowed):
        import_dev_admin(record, profile_id="core")  # a real, deployable, unclassified profile

    assert not User.objects.filter(username="admin").exists()
    assert not WebAuthnCredential.objects.exists()


@pytest.mark.spec("req-tap-auth-passkey-dev-bootstrap-15")
@pytest.mark.django_db
def test_import_refuses_when_no_profile_is_resolvable(monkeypatch):
    """An absent `TAP_BOOT_PROFILE` classifies as `None` — unclassified — and refuses.
    Fail closed on ambiguity, never fail open on absence."""
    user = _register_admin(_make_authenticator(uv=True), email="sessiona@example.com")
    record = _record_for(user)
    _free_credential_and_handle(user)
    monkeypatch.delenv("TAP_BOOT_PROFILE", raising=False)

    with pytest.raises(DevImportNotAllowed):
        import_dev_admin(record)  # no profile_id, no env var → unclassified → refused

    assert not WebAuthnCredential.objects.exists()


@pytest.mark.spec("req-tap-auth-passkey-dev-bootstrap-4")
def test_shipped_profiles_classification_matches_allowlist():
    """The dev/CI stacks are dev_local (import permitted); the deployable profiles are
    unclassified, so import fails closed against them.

    samsite left this set with its re-home (req-boot-bootstrap-samsite-rehome-2): the
    profile now ships in tap-plugin-samsite and reaches boot/ only as a staged record —
    the gate still classifies it from the staged file at run time, but it is no longer
    a SHIPPED profile this test can enumerate."""
    for dev_profile in ("core_dev", "core_ci", "soak", "test_all"):
        assert read_profile_kind(dev_profile) == "dev_local"
    for deployable in ("core", "operator_sso"):
        kind = read_profile_kind(deployable)
        assert kind != "dev_local"
        with pytest.raises(DevImportNotAllowed):
            assert_dev_import_allowed(kind)


@pytest.mark.spec("req-tap-auth-passkey-dev-bootstrap-4")
@pytest.mark.django_db
def test_command_refuses_import_under_unclassified_profile(tmp_path):
    """The command-level gate: even with a valid record on disk, an unclassified profile
    is refused before the record is read."""
    record = {"placeholder": True}
    record_path = tmp_path / "rec.json"
    record_path.write_text(json.dumps(record))
    with pytest.raises(CommandError, match="dev_local"):
        call_command(
            "enroll_admin",
            "--import-dev-passkey",
            "--profile",
            "core",  # unclassified → None → refused
            "--dev-passkey-record",
            str(record_path),
        )
    assert not User.objects.filter(username="admin").exists()


# --------------------------------------------------------------------------- #
# Exact-origin policy (dev-bootstrap-6)                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.spec("req-tap-auth-passkey-dev-bootstrap-6")
@pytest.mark.django_db
def test_record_encodes_exact_origin_policy_not_a_baked_origin():
    """The shared record carries the POLICY (each session enforces its own exact origin),
    never a concrete origin — a baked-in origin would be the relay-attack footgun."""
    user = _register_admin(_make_authenticator(uv=True))
    record = _record_for(user)
    assert record["rp_id"] == "localhost"
    assert record["origin_policy"] == "per_session_localhost_exact"
    # No concrete origin string is anywhere in the record.
    assert "http://" not in json.dumps(record)


# --------------------------------------------------------------------------- #
# Record schema + integrity (dev-bootstrap-7, 8)                              #
# --------------------------------------------------------------------------- #


@pytest.mark.spec("req-tap-auth-passkey-dev-bootstrap-7")
@pytest.mark.django_db
def test_valid_record_round_trips_through_the_schema(tmp_path):
    user = _register_admin(_make_authenticator(uv=True))
    record = _record_for(user)
    path = tmp_path / "rec.json"
    path.write_text(json.dumps(record))
    loaded = load_dev_record(path)
    assert loaded["credential"]["credential_id"] == record["credential"]["credential_id"]


@pytest.mark.spec("req-tap-auth-passkey-dev-bootstrap-7")
def test_malformed_record_refused(tmp_path):
    """A record missing a required field fails schema validation (shape) → refused."""
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"version": 1, "rp_id": "localhost"}))  # missing required keys
    with pytest.raises(DevRecordError):
        load_dev_record(path)


@pytest.mark.spec("req-tap-auth-passkey-dev-bootstrap-8")
@pytest.mark.django_db
def test_tampered_record_refused(tmp_path):
    """Swapping in an attacker credential id without recomputing the digest is caught —
    the self-digest binds the content (corruption/casual-tamper detection)."""
    user = _register_admin(_make_authenticator(uv=True))
    record = _record_for(user)
    record["credential"]["credential_id"] = "QVRUQUNLRVI"  # attacker-controlled, digest now stale
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(record))
    with pytest.raises(DevRecordError, match="integrity"):
        load_dev_record(path)


@pytest.mark.spec("req-tap-auth-passkey-dev-bootstrap-8")
@pytest.mark.django_db
def test_tampered_record_never_binds_a_credential(tmp_path):
    """The integrity failure must abort import BEFORE any user/credential is written."""
    user = _register_admin(_make_authenticator(uv=True), email="sessiona@example.com")
    record = _record_for(user)
    _free_credential_and_handle(user)
    record["user_handle"] = "ff" * 8  # mutate a field, leave the stale digest
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(record))

    # The integrity failure raises at load, before import_dev_admin writes anything.
    with pytest.raises(DevRecordError):
        import_dev_admin(load_dev_record(path), profile_id=_DEV_PROFILE)
    assert not User.objects.filter(username="admin").exists()
    assert not WebAuthnUserHandle.objects.filter(handle="ff" * 8).exists()
