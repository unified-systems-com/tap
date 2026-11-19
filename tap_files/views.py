"""The download route: a logged-in user takes a copy of a held file, as an attachment.

`specs/spec-tap-file-store.md`, `req-tap-files-download` (ruled 2026-11-16 and 2026-11-17). The route
reads the `tap_file` through the grid service layer as the requesting user and the bytes through the
gateway's `open_file`, so the capability checks and the read's log record are the gateway's own. It
serves the version the node records and no other: the caller cannot name one, and the store's head
is never consulted.

Each request that reaches the view leaves exactly one `FILE_OPERATION` record
(`req-tap-files-logging-1`): the gateway's, carrying the route, once `open_file` is called; the
route's own, in the same shape, when it refuses before that.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseServerError
from django.http.response import HttpResponseBase
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_http_methods

from tap_auth.enforcement import authorized
from tap_auth.errors import AuthzError
from tap_files.holding import identifier_for
from tap_files.models import TapFile
from tap_files.services import open_file
from tap_files.services.contract import FILE_OPERATION_CODE, FILES_READ, FileIntegrityError, StoredFileNotFound
from tap_grid.caller_context import get_caller_context
from tap_grid.exceptions import ServiceNotFoundError, ServiceValidationError
from tap_grid.services import get_node

logger = logging.getLogger(__name__)

ROUTE = "GET /files/<identifier>/download"
# A media type of plain token characters (RFC 9110 tchar), no parameters: anything else could
# carry a second header or a charset the browser would act on (`req-tap-files-download-9`).
_TCHAR = r"[!#$%&'*+.^_`|~0-9A-Za-z-]+"
_MEDIA_TYPE = re.compile(rf"{_TCHAR}/{_TCHAR}")
_FALLBACK_TYPE = "application/octet-stream"


def content_type_for(media_type: Any) -> str:
    """The node's media type when it is well formed, else ``application/octet-stream``."""
    if isinstance(media_type, str) and _MEDIA_TYPE.fullmatch(media_type):
        return media_type
    return _FALLBACK_TYPE


def disposition_for(name: str) -> str:
    """``attachment`` with the logical name, quoted or RFC 5987-encoded as RFC 6266 describes.

    Django quotes a name of printable ASCII and percent-encodes anything else, a newline or a
    non-ASCII letter included, so the value is always one header line (`req-tap-files-download-6`).
    """
    return content_disposition_header(as_attachment=True, filename=name) or "attachment"


def _logged(identifier: str) -> str:
    """The identifier as a log may carry it: a UUID as is, anything else as its repr."""
    try:
        return str(uuid.UUID(identifier))
    except ValueError:
        return repr(identifier)


def _route_record(identifier: str, outcome: str, reason: str) -> None:
    """The record for a download refused before the gateway is asked, in the gateway's own shape."""
    user = getattr(get_caller_context(), "user", None)
    identifier = _logged(identifier)
    data = {
        "operation": "download",
        "identifier": identifier,
        "actor": None if user is None else str(user.pk),
        "actor_kind": getattr(user, "user_kind", None),
        "outcome": outcome,
        "reason_class": reason,
        "route": ROUTE,
    }
    logger.log(
        logging.WARNING if outcome == "refused" else logging.ERROR,
        "[8f16] files: download %s %s (actor %s, %s)",
        outcome,
        identifier,
        data["actor"],
        reason,
        extra={"message_code": FILE_OPERATION_CODE, "message_data": data, "entity_id": None},
    )


def _live_file(identifier: str) -> TapFile | None:
    """The live `tap_file` with this id, read as the requesting user, or ``None``.

    A user without `grid.read` is refused by `get_node` before it looks the id up, so that refusal
    does not depend on whether the file exists either.
    """
    try:
        node = get_node(identifier)
    except ServiceNotFoundError, ServiceValidationError, ValueError:
        # get_node's id coercion raises a bare ValueError for a malformed id, not the
        # ServiceValidationError its docstring names.
        return None
    if not isinstance(node, TapFile) or node.entity.deleted_at is not None:
        return None
    return node


@require_http_methods(["GET", "HEAD"])
def download(request: HttpRequest, identifier: str) -> HttpResponseBase:
    """Serve the version the `tap_file` records, verified against the node, as an attachment.

    TAP-IMPLEMENTS: req-tap-files-download@d3d0e97245a1/d8fc3aac2a2e (enforcement) — the node's version only, checked
        against the node before the first byte, always an attachment, and refused alike whether
        or not the file exists when the user may not read it.
    """
    # Query parameters are never read: no request chooses a version (`req-tap-files-download-12`).
    try:
        # `files.read` first, so a user without it is refused the same way for any identifier.
        with authorized(get_caller_context(), FILES_READ, operation="download"):
            pass
        node = _live_file(identifier)
    except AuthzError as exc:
        _route_record(identifier, "refused", type(exc).__name__)
        raise PermissionDenied from None
    if node is None:
        _route_record(identifier, "refused", "NotFound")
        raise Http404("No such file.")
    if not node.file_version or node.file_version < 1:
        # A malformed node: serving the head would serve exactly the unrecorded bytes this rule
        # keeps out (`req-tap-files-download-13`).
        _route_record(identifier, "failed", "NoFileVersion")
        logger.error("[05d4] files: tap_file %s records no file_version; nothing served", node.entity_id)
        return HttpResponseServerError("This file's node records no file_version.", content_type="text/plain")

    file_id = identifier_for(node.entity_id)
    try:
        # The gateway checks the bytes against the node before returning, so a disagreement is
        # recorded as the failed read it is (`req-tap-files-download-11`).
        opened = open_file(
            file_id, node.file_version, route=ROUTE, expected_digest=node.sha256, expected_size=node.size_bytes
        )
    except AuthzError:
        raise PermissionDenied from None
    except StoredFileNotFound:
        raise Http404("No such file.") from None
    except FileIntegrityError:
        return HttpResponseServerError("The file could not be served.", content_type="text/plain")

    response: HttpResponseBase
    if request.method == "HEAD":
        opened.close()
        response = HttpResponse(b"")  # nosemgrep — an empty body: HEAD sends the headers alone
    else:
        response = FileResponse(opened.stream)
    response["Content-Type"] = content_type_for(node.media_type)
    response["Content-Disposition"] = disposition_for(node.name)
    response["Content-Length"] = str(opened.size)
    response["X-Content-Type-Options"] = "nosniff"
    response["ETag"] = f'"{opened.digest}"'
    response["Cache-Control"] = "private, no-store"
    return response


__all__ = ["ROUTE", "content_type_for", "disposition_for", "download"]
