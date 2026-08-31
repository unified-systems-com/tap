"""tap_auth models — TAP's canonical user / named-actor model.

`tap_auth.User` is TAP's `AUTH_USER_MODEL` (req-tap-auth-user-model). It is the
named-actor spine: every meaningful TAP operation resolves to a durable human or
program actor, and `User=None` is not valid at the service boundary
(req-tap-auth-actor-model). Protected built-in actors (the bootloader, scheduler,
collector, and the test actor) carry an immutable natural key `tap_builtin_key`
written by `tap_auth.sync` (req-tap-auth-builtins).

This module also holds the `Capability` table (the queryable DB projection of the
code capability registry) and `ProtectedGroup` metadata. The service-boundary
*enforcement* that consumes `authorize()` is wired in a later phase; see
tap_auth/specs/spec-tap-auth-v0.md.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class UserKind(models.TextChoices):
    """Actor kind vocabulary (req-tap-auth-actor-model).

    v1 supports two kinds; `program` covers every non-human actor (bootloader,
    test actor, service account, collector, scheduler, plugin runner, AI actor).
    """

    HUMAN = "human", "Human"
    PROGRAM = "program", "Program"


class User(AbstractUser):
    """TAP's canonical Django user and named actor.

    Extends Django `AbstractUser` with actor-kind, backend-managed context, and
    protected-built-in metadata. `is_active` (from AbstractUser) remains the
    login/enabled toggle; the `deactivated_*` fields record the auditable
    deactivation decision (reason, time, acting actor) layered on top.
    """

    user_kind = models.CharField(
        max_length=16,
        choices=UserKind.choices,
        default=UserKind.HUMAN,
        help_text="Actor kind: 'human' (a person) or 'program' (bootloader, collector, scheduler, AI, ...).",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Backend-managed operator/system context for this actor.",
    )
    description_json = models.JSONField(
        default=dict,
        blank=True,
        help_text="Backend-managed structured context, especially for program/AI actors.",
    )
    avatar_url = models.URLField(
        blank=True,
        default="",
        max_length=500,
        help_text="Provider profile photo URL (e.g. Google 'picture'), refreshed on login. "
        "Display-only; the UI falls back to an initial when empty.",
    )
    is_tap_builtin = models.BooleanField(
        default=False,
        help_text="True for TAP-managed protected built-in actors (req-tap-auth-builtins).",
    )
    tap_builtin_key = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        help_text=(
            "Immutable natural key for built-in actors (e.g. 'tap_bootloader'); "
            "null for ordinary users. Intended to be set only by tap_auth bootstrap/"
            "sync code; immutability is enforced at the application/save() layer."
        ),
    )
    deactivated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this actor was deactivated, if applicable.",
    )
    deactivated_reason = models.TextField(
        blank=True,
        default="",
        help_text="Why this actor was deactivated.",
    )
    deactivated_by_actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deactivations_performed",
        help_text="The actor that performed the deactivation, where known.",
    )

    class Meta:
        db_table = "tap_user"
        constraints = [
            # Bidirectional: a built-in actor MUST carry its natural key, and an
            # ordinary user MUST NOT (req-tap-auth-builtins-3). The reverse half
            # is security-relevant — without it an ordinary user could reserve a
            # built-in key (e.g. 'tap_bootloader') and be silently adopted into a
            # privileged built-in by the next bootstrap get_or_create().
            models.CheckConstraint(
                condition=(
                    models.Q(is_tap_builtin=True, tap_builtin_key__isnull=False)
                    | models.Q(is_tap_builtin=False, tap_builtin_key__isnull=True)
                ),
                name="tap_auth_builtin_key_iff_builtin",
            ),
        ]

    def clean(self) -> None:
        """App-level mirror of the bidirectional built-in-key constraint."""
        super().clean()
        if self.is_tap_builtin and not self.tap_builtin_key:
            raise ValidationError({"tap_builtin_key": "Built-in actors require a tap_builtin_key."})
        if not self.is_tap_builtin and self.tap_builtin_key:
            raise ValidationError({"tap_builtin_key": "Only built-in actors may carry a tap_builtin_key."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Enforce `tap_builtin_key` immutability once set (req-tap-auth-builtins).

        The key is set-once: a row may go from null to a value (bootstrap minting
        a built-in), but an existing non-null key can never be changed or cleared.
        This is an **application-layer** invariant enforced here in save(); a raw
        ``QuerySet.update()`` or SQL bypasses it, as with any model-level invariant
        — `tap_auth.sync` is the sole intended writer of built-in keys. DB
        uniqueness backs the per-key invariant independently.
        """
        if self.pk is not None:
            previous_key = type(self).objects.filter(pk=self.pk).values_list("tap_builtin_key", flat=True).first()
            if previous_key is not None and previous_key != self.tap_builtin_key:
                raise ValidationError({"tap_builtin_key": "tap_builtin_key is immutable once set."})
        super().save(*args, **kwargs)


class Capability(models.Model):
    """A TAP capability — the queryable DB projection of the code registry.

    The canonical source of truth is `tap_auth.capabilities.CAPABILITIES`; this
    table is hard-synced from it (req-tap-auth-capabilities-3). It is a real table
    (not a managed=False placeholder) so capability descriptions + risk metadata
    are queryable from the DB/service layer — the affordance a future AI/Paladin
    actor needs (req-tap-auth-capabilities-7).

    Each Capability projects a backing Django `auth.Permission` (the Capability
    model is that permission's content-type home), so Groups still hold standard
    Django permissions while the capability metadata lives queryably here. TAP
    authorization resolves by the public `name`; the Permission is the storage
    Groups attach to.
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Public TAP capability name, e.g. 'grid.read'.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Human-readable meaning of this capability.",
    )
    description_json = models.JSONField(
        default=dict,
        blank=True,
        help_text="Structured context for this capability (synced from tap_auth.capabilities.json), "
        "queryable alongside the prose description for AI/security reasoning.",
    )
    risk = models.CharField(
        max_length=16,
        default="medium",
        help_text="Risk/classification (low|medium|high|critical) from the registry.",
    )
    permission = models.OneToOneField(
        "auth.Permission",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tap_capability",
        help_text="The projected Django permission this capability is stored as.",
    )

    class Meta:
        db_table = "tap_capability"
        ordering = ["name"]
        verbose_name_plural = "capabilities"

    def __str__(self) -> str:
        return self.name


class ProtectedGroup(models.Model):
    """Metadata marking a Django `auth.Group` as a TAP-managed protected group.

    Django `Group` is not custom, so protected-group metadata lives here
    (req-tap-auth-builtins): a one-to-one to `auth.Group` plus an immutable
    natural `builtin_key` and an `is_protected` flag. Protected groups cannot be
    renamed/deleted/repurposed by ordinary user-management paths.
    """

    group = models.OneToOneField(
        "auth.Group",
        on_delete=models.CASCADE,
        related_name="tap_protected",
        help_text="The Django group this metadata protects.",
    )
    builtin_key = models.CharField(
        max_length=64,
        unique=True,
        help_text="Immutable natural key for the protected group, e.g. 'tap_admin'.",
    )
    is_protected = models.BooleanField(
        default=True,
        help_text="When true, the group is shielded from ordinary mutation/deletion.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Human-readable meaning of this role/group (synced from tap_auth.roles.json).",
    )
    description_json = models.JSONField(
        default=dict,
        blank=True,
        help_text="Structured context for this role (synced from tap_auth.roles.json), queryable "
        "alongside the prose description for AI/security reasoning.",
    )

    class Meta:
        db_table = "tap_protected_group"
        ordering = ["builtin_key"]

    def __str__(self) -> str:
        return self.builtin_key


class ExternalIdentityStatus(models.TextChoices):
    """Lifecycle of an external identity link (req-tap-auth-external-identity)."""

    ACTIVE = "active", "Active"
    DEACTIVATED = "deactivated", "Deactivated"


class ExternalIdentity(models.Model):
    """Links a provider-authenticated subject to a canonical TAP user.

    The durable identity key is ``(provider_id, subject)`` — for OIDC the
    provider's ``sub`` (req-tap-auth-external-identity). Email is a profile
    *snapshot* and reconciliation hint, never identity (it is mutable and may
    repeat across users). v1 stores explicit columns only — no raw claims, no
    ``safe_claims_json``. v1 account linking is disabled: a second provider
    presenting the same email as an existing user is denied
    (``identity_linking_disabled``), not auto-connected. This is a plain Django
    model (auth infrastructure), deliberately off the Entity/graph spine.
    """

    provider_id = models.CharField(
        max_length=64,
        help_text="Stable provider natural key, e.g. 'example-google'.",
    )
    provider_type = models.CharField(
        max_length=32,
        help_text="Provider type, e.g. 'google_oidc'.",
    )
    subject = models.CharField(
        max_length=255,
        help_text="Upstream durable subject (OIDC 'sub'). The identity key with provider_id; never logged in full.",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="external_identities",
        help_text="The canonical TAP user this external subject resolves to.",
    )
    email_snapshot = models.EmailField(
        blank=True,
        default="",
        help_text="Most recent provider-asserted verified email (profile snapshot / hint, NOT identity).",
    )
    display_name_snapshot = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Most recent provider-asserted display name.",
    )
    hosted_domain_snapshot = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Most recent returned hosted-domain (Google 'hd') the access decision matched on.",
    )
    first_seen = models.DateTimeField(
        auto_now_add=True,
        help_text="When this external identity was first provisioned.",
    )
    last_seen = models.DateTimeField(
        auto_now=True,
        help_text="When this external identity was last updated (any login touch).",
    )
    last_login = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this external identity last completed a successful login.",
    )
    status = models.CharField(
        max_length=16,
        choices=ExternalIdentityStatus.choices,
        default=ExternalIdentityStatus.ACTIVE,
        help_text="active | deactivated. Provider/domain removal deactivates affected identities by default.",
    )

    class Meta:
        db_table = "tap_external_identity"
        verbose_name_plural = "external identities"
        constraints = [
            # The durable identity key: a given upstream subject under a given
            # provider maps to exactly one row (req-tap-auth-external-identity).
            models.UniqueConstraint(
                fields=["provider_id", "subject"],
                name="tap_external_identity_provider_subject_unique",
            ),
        ]
        indexes = [
            # Email reconciliation/diagnostic lookups (email is non-unique here —
            # duplicate emails are allowed because email is not identity).
            models.Index(fields=["email_snapshot"], name="tap_extid_email_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.provider_id}:{self.redacted_subject}"

    @property
    def redacted_subject(self) -> str:
        """Provider id + a truncated/hashed subject for safe display/logging
        (req-tap-auth-external-identity: full subjects are not logged)."""
        digest = hashlib.sha256(self.subject.encode("utf-8")).hexdigest()[:12]
        return f"sub#{digest}"

    @staticmethod
    def generate_username(provider_id: str, subject: str) -> str:
        """Generate a stable, non-display login username from provider id +
        subject (req-tap-auth-external-identity). The UI shows email/display
        name, never this value; it exists only to satisfy Django's username
        field uniquely and deterministically."""
        digest = hashlib.sha256(f"{provider_id}:{subject}".encode()).hexdigest()[:24]
        return f"ext-{provider_id}-{digest}"[:150]


def _new_webauthn_user_handle() -> str:
    """A fresh opaque, non-PII WebAuthn user handle: 64 CSPRNG bytes, hex-encoded
    (req-tap-auth-passkey-webauthn-4). Never derived from email/username."""
    return secrets.token_bytes(64).hex()


class WebAuthnUserHandle(models.Model):
    """The opaque, stable WebAuthn user handle for a TAP user (req-tap-auth-passkey-webauthn-4).

    WebAuthn presents an opaque, <=64-byte, non-PII user handle at registration and
    returns it in every assertion — never email/username. TAP mints one 64-byte
    CSPRNG handle per user and binds it here; a discoverable assertion's returned
    ``userHandle`` is confirmed against the owning user's handle before
    authenticating (req-tap-auth-passkey-webauthn-10). Plain Django model (auth
    infrastructure), deliberately off the Entity/graph spine (like
    :class:`ExternalIdentity`).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="webauthn_handle",
        help_text="The TAP user this opaque handle identifies in WebAuthn ceremonies.",
    )
    handle = models.CharField(
        max_length=128,  # 64 bytes hex-encoded = 128 chars
        unique=True,
        default=_new_webauthn_user_handle,
        editable=False,
        help_text="Opaque, non-PII WebAuthn user handle: 64 CSPRNG bytes, hex. Never email/username.",
    )
    created = models.DateTimeField(auto_now_add=True, help_text="When this handle was minted.")

    class Meta:
        db_table = "tap_webauthn_user_handle"

    def __str__(self) -> str:
        return f"handle:{self.handle[:12]}… (user={self.user_id})"


class WebAuthnCredentialDeviceType(models.TextChoices):
    """Backup-Eligibility-derived device type (from ``py_webauthn``'s
    ``credential_device_type``). Device-bound credentials are the recovery
    single-point-of-failure the BE-aware nudge escalates on."""

    SINGLE_DEVICE = "single_device", "Single-device (device-bound)"
    MULTI_DEVICE = "multi_device", "Multi-device (backup-eligible / syncable)"


class WebAuthnCredential(models.Model):
    """A registered passkey bound to a TAP user (req-tap-auth-passkey-identity).

    A TAP-side, queryable projection of a stored WebAuthn credential — the server
    holds only PUBLIC material (public key + credential id), never the private key,
    which fits "TAP is its own identity authority". Plain Django model, off the
    Entity/graph spine (like :class:`ExternalIdentity`); design-referenced from
    ``django-otp-webauthn`` but dependency-free.

    The synced-vs-device-bound determination rides the reliable BE/BS flags
    (:attr:`device_type` / :attr:`backed_up`), NOT the AAGUID — which under
    ``attestation=none`` is best-effort and frequently all-zeros
    (``""`` = unknown here), so the recovery-risk queries hold even when it is
    zeroed (req-tap-auth-passkey-identity-2/4).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="webauthn_credentials",
        help_text="The TAP user who owns this passkey.",
    )
    credential_id = models.CharField(
        max_length=1400,  # base64url of up to ~1023 raw credential-id bytes
        unique=True,
        editable=False,
        help_text=(
            "Globally-unique WebAuthn credential id (base64url). A discoverable assertion "
            "resolves to exactly one credential/owner via this (req-tap-auth-passkey-webauthn-10)."
        ),
    )
    public_key = models.CharField(
        max_length=1024,
        editable=False,
        help_text="COSE public key (base64url). Public material only — the private key never leaves the authenticator.",
    )
    sign_count = models.PositiveBigIntegerField(
        default=0,
        help_text=(
            "Last verified signature counter; the new count is persisted after each assertion. "
            "A regression is a cloned-authenticator signal, hard-denied by py_webauthn "
            "(0/0 no-counter authenticators are exempt) (req-tap-auth-passkey-webauthn-8)."
        ),
    )
    aaguid = models.CharField(
        max_length=36,
        blank=True,
        default="",
        help_text=(
            "Authenticator model id (UUID string). Best-effort under attestation=none; '' or "
            "all-zeros '00000000-0000-0000-0000-000000000000' = unknown. NOT used for the "
            "synced-vs-device-bound determination (that rides BE/BS)."
        ),
    )
    transports = models.JSONField(
        default=list,
        blank=True,
        help_text="Client-reported transports (e.g. ['internal','hybrid','usb']). Advisory hint for the next ceremony.",
    )
    device_type = models.CharField(
        max_length=16,
        choices=WebAuthnCredentialDeviceType.choices,
        default=WebAuthnCredentialDeviceType.SINGLE_DEVICE,
        help_text=(
            "BE-derived (py_webauthn credential_device_type): single_device (device-bound, no "
            "sync safety net — nudge escalates) vs multi_device (backup-eligible/syncable). "
            "Reliable under attestation=none."
        ),
    )
    backed_up = models.BooleanField(
        default=False,
        help_text=(
            "BS flag (py_webauthn credential_backed_up): whether the credential is CURRENTLY "
            "backed up / synced. Mutable across assertions; reliable under attestation=none."
        ),
    )
    device_label = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Human-friendly device name (e.g. 'MacBook Touch ID'). Cosmetic; operator/UI-supplied.",
    )
    created = models.DateTimeField(auto_now_add=True, help_text="When this passkey was registered.")
    last_used = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this passkey last completed a successful assertion.",
    )

    class Meta:
        db_table = "tap_webauthn_credential"
        indexes = [
            models.Index(fields=["user"], name="tap_webauthn_cred_user_idx"),
        ]

    def __str__(self) -> str:
        return f"passkey:{self.redacted_credential_id} (user={self.user_id})"

    @property
    def redacted_credential_id(self) -> str:
        """A truncated/hashed credential id for safe display/logging — raw
        credential material is not duplicated into logs/UI (req-tap-auth-passkey-identity-5)."""
        digest = hashlib.sha256(self.credential_id.encode("utf-8")).hexdigest()[:12]
        return f"cred#{digest}"


class InvitationAction(models.TextChoices):
    """What redeeming an invitation does (req-tap-auth-passkey-enrollment / add-device)."""

    ENROLL_FIRST = "enroll_first", "Enroll first passkey (create user)"
    ADD_CREDENTIAL = "add_credential", "Add an additional passkey (existing user)"


class InvitationStatus(models.TextChoices):
    """Invitation lifecycle (req-tap-auth-passkey-enrollment)."""

    PENDING = "pending", "Pending"
    CONSUMED = "consumed", "Consumed"
    EXPIRED = "expired", "Expired"
    REVOKED = "revoked", "Revoked"


class Invitation(models.Model):
    """A one-time, hashed-at-rest enrollment token — the TAP-owned account-creation
    chokepoint that replaces the IdP's ``pre_social_login`` (req-tap-auth-passkey-enrollment).

    It carries an existing admin's cryptographic *vouch* for a human: redeeming it
    runs the WebAuthn registration ceremony and either creates a user + binds the
    first passkey (``enroll_first``) or binds an additional passkey to an existing
    user (``add_credential``, req-tap-auth-passkey-add-device). kubeadm public-id /
    secret split: the :attr:`public_id` is log-safe (lookup + revocation); the
    high-entropy secret is shown once at mint and stored ONLY as :attr:`secret_hash`.
    Consumed atomically at credential registration. Plain Django model, off the
    Entity/graph spine (like :class:`ExternalIdentity`).
    """

    public_id = models.CharField(
        max_length=32,
        unique=True,
        editable=False,
        help_text=(
            "Non-secret public id (kubeadm split): the log-safe lookup/revocation handle. "
            "Log-safety is enforced at the route, not assumed: the enrollment URLs accept "
            "this shape only (req-tap-auth-passkey-enrollment-7), so a forged value never "
            "reaches a logger. "
            "Redemption looks the row up by this, never by the secret (a by-secret query is a timing leak)."
        ),
    )
    secret_hash = models.CharField(
        max_length=128,  # sha-256 hex = 64, sha-512 hex = 128
        editable=False,
        help_text=(
            "Plain SHA-256/512 hex of the >=128-bit CSPRNG secret half, verified with a constant-time "
            "compare. Deliberately NOT a password KDF (full-entropy secret) and unsalted. Raw secret never stored."
        ),
    )
    action = models.CharField(
        max_length=16,
        choices=InvitationAction.choices,
        default=InvitationAction.ENROLL_FIRST,
        help_text="enroll_first (create a new user + first passkey) | add_credential (bind another passkey to an existing user, no new grants).",
    )
    email = models.EmailField(
        blank=True,
        default="",
        help_text="Intended identity for an enroll_first invite (profile snapshot, NOT identity). Empty for add_credential.",
    )
    display_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Intended display name for an enroll_first invite. Cosmetic.",
    )
    username = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text=(
            "Pinned username for an enroll_first redemption (req-tap-auth-passkey-enrollment-8). Empty (the "
            "default) derives it from the email via _unique_username. Set when a caller must land the user on an "
            "agreed-upon name — canonically the dev bootstrap's fixed `admin` (req-tap-auth-passkey-dev-bootstrap-14). "
            "Create-only: a name that already resolves to a User fails loud at mint AND at redeem, never silently "
            "becoming an additive mint. Confers no authority — username is a mutable display label, never an identity "
            "anchor and never an authorization key (the durable internal User id is the sole consequential selector)."
        ),
    )
    grants = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Human-assignable role names to apply on redemption (enroll_first only; empty for add_credential). "
            "Applied via is_login_grantable + group membership; taken from this server row, never client input."
        ),
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="incoming_invitations",
        help_text="For add_credential: the existing user the new passkey binds to (bound by stable internal id at mint). Null for enroll_first.",
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_invitations",
        help_text="The actor who minted this invitation (a human admin for runtime mints; tap_bootloader for genesis). Audit attribution.",
    )
    issued_at = models.DateTimeField(auto_now_add=True, help_text="When this invitation was minted.")
    expires_at = models.DateTimeField(
        help_text="Hard expiry (short bounded TTL with an enforced maximum). A redeem after this is refused.",
    )
    status = models.CharField(
        max_length=16,
        choices=InvitationStatus.choices,
        default=InvitationStatus.PENDING,
        help_text="pending -> consumed (successful bind) | expired | revoked. Consumed atomically at credential registration.",
    )
    consumed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this invitation was successfully consumed (a passkey bound).",
    )

    class Meta:
        db_table = "tap_invitation"
        indexes = [
            models.Index(fields=["status"], name="tap_invitation_status_idx"),
        ]
        constraints = [
            # add_credential MUST target an existing user; enroll_first MUST NOT
            # (it creates the user). Dual-layer with clean() below (house style).
            models.CheckConstraint(
                condition=(
                    models.Q(action="add_credential", target_user__isnull=False)
                    | models.Q(action="enroll_first", target_user__isnull=True)
                ),
                name="tap_invitation_target_iff_add_credential",
            ),
        ]

    def __str__(self) -> str:
        return f"invitation:{self.public_id} ({self.action}, {self.status})"

    def clean(self) -> None:
        """Mirror the DB CheckConstraint at the app layer (house dual-layer style)."""
        super().clean()
        if self.action == InvitationAction.ADD_CREDENTIAL and self.target_user_id is None:
            raise ValidationError("add_credential invitation requires a target_user.")
        if self.action == InvitationAction.ENROLL_FIRST and self.target_user_id is not None:
            raise ValidationError("enroll_first invitation must not have a target_user.")
