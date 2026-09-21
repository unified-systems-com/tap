"""Provider-type registry (req-tap-auth-providers).

Maps a provider ``type`` string to its implementation. Unknown types fail
immediately and loudly (req-tap-auth-providers: "Unknown provider types fail
immediately") — a typo'd or unsupported type is a configuration error, never a
silently-skipped provider.
"""

from __future__ import annotations

from tap_auth.providers.base import Provider
from tap_auth.providers.github_oauth import GitHubOAuthProvider
from tap_auth.providers.google_oidc import GoogleOidcProvider

# The set of supported provider types. New types register here.
_PROVIDERS: dict[str, Provider] = {
    GoogleOidcProvider.type: GoogleOidcProvider(),
    GitHubOAuthProvider.type: GitHubOAuthProvider(),
}


class UnknownProviderType(Exception):
    """Raised when a provider config names a type with no implementation."""


def get_provider(provider_type: str) -> Provider:
    """Return the implementation for ``provider_type`` or raise UnknownProviderType."""
    try:
        return _PROVIDERS[provider_type]
    except KeyError:
        known = ", ".join(sorted(_PROVIDERS)) or "<none>"
        raise UnknownProviderType(f"unknown provider type '{provider_type}'; supported types: {known}") from None


def provider_types() -> list[str]:
    """All registered provider type names, sorted."""
    return sorted(_PROVIDERS)
