"""Settings-free git-source credential resolution for the pre-boot plugin install.

TAP-IMPLEMENTS: req-tap-plugin-arch-source-secret@37c1efb4a5b7/db790474e4b5 (derivation) — the spec's own
build note names this module as the implementation: resolve via ``tap/runtime_secrets``,
validate against the install-owned schema, feed ``git`` via ``GIT_ASKPASS``.

The private-repo half of the ``git`` source (`req-tap-plugin-arch-sources-2`): a
profile's ``install`` entry may name a source-scoped credential, which pre-boot
resolves and hands to ``git`` **via ``GIT_ASKPASS``, never in the URL** — a token
in the URL leaks into the venv's ``direct_url.json`` (`req-tap-plugin-arch-source-secret-4`).

Design constraints (why this lives in ``tap/`` next to ``runtime_secrets`` and
``preboot``, not in ``tap_plugins`` or ``tap_cares``):

- **Settings-free / no ``tap_*`` import** — pre-boot runs before Django is
  configured (`req-boot-preboot`). This module imports only stdlib +
  ``tap.runtime_secrets`` (the shared, app-neutral resolver) + ``tap.jsonfiles``.
- **Consumer-first scope ``tap_plugins.source``** (`req-tap-plugin-arch-source-secret-2`):
  the credential belongs to the install *system*, never to a plugin — a plugin
  must never resolve the credential that installs its siblings.
- **Conditional necessity** (`req-tap-plugin-arch-source-secret-5`): a credential is
  required only when a git source *declares* one — the ``credential`` key IS the
  declaration. An ``editable``/``path`` source, or a public git source with no
  ``credential``, needs none and resolves to ``None`` here. There is no implicit
  default key: a private repo names its credential explicitly, so the store never
  silently satisfies a source by file-presence.
- **Per-source selection** (`req-tap-plugin-arch-source-secret-6`): a git entry's
  optional ``credential`` names *which* secret key (under scope
  ``tap_plugins.source``) to use, so plugins can be pulled from different private
  repos/orgs in one profile — a repo's PAT never sees another repo.

The token is returned in memory only and never logged: :class:`GitCredential`'s
``__repr__`` omits it, and :func:`git_askpass_env` passes it to the child process
through the environment (owner-only ``/proc/<pid>/environ``), not through the
argument list preboot logs.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tap import git_invocation
from tap.jsonfiles import JsonFileError, validate_json
from tap.runtime_secrets import RuntimeSecretError, resolve_secret_envelope

# The install-system credential scope — owned by the install system, never a
# plugin (req-tap-plugin-arch-source-secret-2). Every source credential lives here.
# Flat (dot, not slash): `scope` is an opaque namespace label under the canonical
# scoped-token grammar (`tap.registry.SCOPED_TOKEN_PATTERN`), not a path. The `.`
# reads "the source subsystem of tap_plugins" with the same infra-not-a-plugin
# meaning, and stays a clean key the deferred least-privilege enforcement can bind
# to (`req-tap-cares-secrets-future-access-control`).
SOURCE_SECRET_SCOPE = "tap_plugins.source"

# The credential-shape constants and the GIT_ASKPASS mechanism live in the
# stdlib-only `tap.git_invocation` leaf, shared with the host-side tools that
# cannot import this module (they run before the container exists). Re-exported
# here so this module stays the install system's single import surface.
GITHUB_PAT_KIND = git_invocation.GITHUB_PAT_KIND
DEFAULT_HOST = git_invocation.DEFAULT_HOST
DEFAULT_USERNAME = git_invocation.DEFAULT_USERNAME

_DATA_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "github_pat_source_secret.schema.json"


class SourceAuthError(Exception):
    """A declared git-source credential could not be resolved or is malformed.

    Raised only when a git source *declares* a ``credential`` that cannot be honored
    (absent store, missing secret, wrong kind, malformed data). A git source with no
    ``credential`` is public and never raises (`req-tap-plugin-arch-source-secret-5`).
    """


@dataclass(frozen=True)
class GitCredential:
    """A resolved git HTTPS credential, fed to git via ``GIT_ASKPASS``.

    ``__repr__`` omits ``token`` so an instance interpolated into a log line or
    traceback cannot leak the secret.
    """

    token: str
    host: str
    username: str

    def __repr__(self) -> str:
        return f"GitCredential(host={self.host!r}, username={self.username!r}, token=<redacted>)"


def credential_ref_for_source(source: Mapping[str, Any]) -> str | None:
    """Return the credential KEY a git source declares, or ``None``.

    A git source with a ``credential`` key is private (that key is required). A git
    source without one is public (no auth); ``editable``/``path``/non-git sources
    never carry an install credential. There is no implicit default key — a private
    repo names its credential explicitly (`req-tap-plugin-arch-source-secret-6`).
    """
    if not isinstance(source, Mapping) or source.get("type") != "git":
        return None
    declared = source.get("credential")
    return str(declared) if declared is not None else None


def resolve_git_credential(secrets_root: Path | None, source: Mapping[str, Any]) -> GitCredential | None:
    """Resolve the credential for one install ``source``, honoring conditional necessity.

    Returns ``None`` when no auth applies — a non-git source, or a git source with no
    ``credential`` key (public repo). Raises :class:`SourceAuthError` when a declared
    credential cannot be honored: the store is absent, the secret is missing, or it is
    of the wrong kind / malformed data. The ``credential`` key IS the declaration that
    makes it required (`req-tap-plugin-arch-source-secret-5`).

    Args:
        secrets_root: The ``TAP_SECRETS_ROOT`` directory, or ``None`` when unset.
        source: One profile ``install`` entry's ``source`` mapping.
    """
    key = credential_ref_for_source(source)
    if key is None:
        return None

    if secrets_root is None:
        raise SourceAuthError(
            f"git source declares credential '{key}' but TAP_SECRETS_ROOT is not set; "
            f"mount the secrets store or remove the 'credential' field for a public repo"
        )

    try:
        envelope = resolve_secret_envelope(secrets_root, SOURCE_SECRET_SCOPE, key)
    except RuntimeSecretError as exc:
        raise SourceAuthError(
            f"git source declares credential '{key}' but it could not be resolved "
            f"(scope '{SOURCE_SECRET_SCOPE}'): {exc}"
        ) from exc

    if envelope.kind != GITHUB_PAT_KIND:
        raise SourceAuthError(
            f"source credential '{SOURCE_SECRET_SCOPE}:{key}' has kind '{envelope.kind}', "
            f"expected '{GITHUB_PAT_KIND}'"
        )

    try:
        validate_json(dict(envelope.data), _DATA_SCHEMA_PATH, source=envelope.source_path)
    except JsonFileError as exc:
        raise SourceAuthError(
            f"source credential '{SOURCE_SECRET_SCOPE}:{key}' has a malformed data block: {exc}"
        ) from exc

    data = envelope.data
    return GitCredential(
        token=str(data["token"]),
        host=str(data.get("host", DEFAULT_HOST)),
        username=str(data.get("username", DEFAULT_USERNAME)),
    )


@contextmanager
def git_askpass_env(cred: GitCredential) -> Iterator[dict[str, str]]:
    """Yield an env overlay that feeds ``cred`` to git via ``GIT_ASKPASS``.

    The typed convenience wrapper over :func:`tap.git_invocation.askpass_env`
    (the shared stdlib mechanism): the token rides in the child env only, never
    in the URL, argv, or the script body, and the short-lived owner-only script
    is deleted on exit.
    """
    with git_invocation.askpass_env(username=cred.username, token=cred.token, prefix="tap-askpass-") as overlay:
        yield overlay


__all__ = [
    "SOURCE_SECRET_SCOPE",
    "GITHUB_PAT_KIND",
    "DEFAULT_HOST",
    "DEFAULT_USERNAME",
    "SourceAuthError",
    "GitCredential",
    "credential_ref_for_source",
    "resolve_git_credential",
    "git_askpass_env",
]
