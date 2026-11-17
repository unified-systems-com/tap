"""Names: the object identifier, where an object lives, and what its content file is called.

`specs/spec-tap-file-store.md`, `req-tap-files-naming`. The object directory comes from the
identifier alone, by the OCFL community extension `0003-hash-and-id-n-tuple-storage-layout` with its
defaults; the stored filename carries the logical name's stem and extension, the identifier, the
version and the digest, so a file copied out of the store still says what it is.
"""

from __future__ import annotations

import hashlib
import re

from tap_files.store.errors import InvalidIdentifier, InvalidLogicalName

LAYOUT_EXTENSION = "0003-hash-and-id-n-tuple-storage-layout"
LAYOUT_CONFIG = {
    "extensionName": LAYOUT_EXTENSION,
    "digestAlgorithm": "sha256",
    "tupleSize": 3,
    "numberOfTuples": 3,
}
#: The extension caps an encoded identifier at 100 characters before it substitutes a digest.
_ENCODED_MAX = 100

_URN_PREFIX = "urn:uuid:"
_URN_RE = re.compile(r"^urn:uuid:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")
_SAFE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")

_STEM_MAX = 100
_EXT_RE = re.compile(r"^[A-Za-z0-9]{1,16}$")
_STEM_KEEP = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
_STORED_RE = re.compile(
    r"^(?P<stem>.*)\+(?P<uuid>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"\+v(?P<version>[1-9][0-9]*)\+(?P<digest>[0-9a-f]{64})(?:\.(?P<ext>[A-Za-z0-9]{1,16}))?$"
)
_NAME_MAX_BYTES = 255


def check_identifier(identifier: str) -> str:
    """Return the bare UUID of a ``urn:uuid:`` identifier, or raise :class:`InvalidIdentifier`."""
    match = _URN_RE.match(identifier) if isinstance(identifier, str) else None
    if not match:
        raise InvalidIdentifier(f"{identifier!r} is not urn:uuid: and a canonical lower-case UUID")
    return match.group(1)


def urn(uuid_text: str) -> str:
    """The object identifier for an entity UUID (`req-tap-files-naming-6`)."""
    identifier = _URN_PREFIX + str(uuid_text).lower()
    check_identifier(identifier)
    return identifier


def encode_identifier(identifier: str) -> str:
    """Percent-encode an identifier as the 0003 extension does: lower-case hex, all but ``[A-Za-z0-9_-]``."""
    encoded = "".join(ch if ch in _SAFE else "".join(f"%{b:02x}" for b in ch.encode("utf-8")) for ch in identifier)
    if len(encoded) > _ENCODED_MAX:
        digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
        encoded = f"{encoded[:_ENCODED_MAX]}-{digest}"
    return encoded


def object_path(identifier: str) -> str:
    """The object's directory, relative to the storage root, from the identifier alone.

    TAP-IMPLEMENTS: req-tap-files-naming@e155cc1759b0/f7bec37bab84 (derivation) — the one mapping from an
        identifier to its directory; neither the name nor the digest takes part.
    """
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    size, count = LAYOUT_CONFIG["tupleSize"], LAYOUT_CONFIG["numberOfTuples"]
    assert isinstance(size, int) and isinstance(count, int)  # nosec B101 — constants above
    tuples = [digest[i * size : (i + 1) * size] for i in range(count)]
    return "/".join([*tuples, encode_identifier(identifier)])


def check_logical_name(name: str) -> str:
    """Return *name* unchanged if it is one path element, or raise :class:`InvalidLogicalName`.

    Kept exactly: the store never repairs a logical name. Not empty, not ``.`` or ``..``, no ``/``,
    no control character, at most 255 bytes of UTF-8.
    """
    if not isinstance(name, str) or name in ("", ".", ".."):
        raise InvalidLogicalName(f"{name!r} is not a logical name")
    if "/" in name or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        raise InvalidLogicalName(f"{name!r} contains a separator or a control character")
    if len(name.encode("utf-8")) > _NAME_MAX_BYTES:
        raise InvalidLogicalName(f"logical name is longer than {_NAME_MAX_BYTES} bytes of UTF-8")
    return name


def stored_filename(name: str, identifier: str, version: int, digest: str) -> str:
    """``<stem>+<uuid>+v<N>+<sha256>.<ext>``: ASCII, at most 221 bytes plus the version's digits."""
    uuid_text = check_identifier(identifier)
    base, dot, suffix = name.rpartition(".")
    if dot and base and _EXT_RE.match(suffix):
        stem_source, extension = base, suffix
    else:
        stem_source, extension = name, ""
    stem = "".join(ch if ch in _STEM_KEEP else "_" for ch in stem_source).lstrip(".")[:_STEM_MAX]
    filename = f"{stem}+{uuid_text}+v{version}+{digest}"
    return f"{filename}.{extension}" if extension else filename


def parse_stored_filename(filename: str) -> tuple[str, int, str]:
    """Take a stored filename apart from the right: ``(uuid, version, digest)``."""
    match = _STORED_RE.match(filename)
    if not match:
        raise ValueError(f"{filename!r} is not a stored filename")
    return match.group("uuid"), int(match.group("version")), match.group("digest")


__all__ = [
    "LAYOUT_CONFIG",
    "LAYOUT_EXTENSION",
    "check_identifier",
    "check_logical_name",
    "encode_identifier",
    "object_path",
    "parse_stored_filename",
    "stored_filename",
    "urn",
]
