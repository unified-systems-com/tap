"""Small HTTP helpers shared by the tap_auth views.

One home for request-parsing edges the auth views share, so a hardening change
(a body-size cap, a content-type check) lands once instead of in each view
module — the enrollment and login views previously carried byte-identical
copies of :func:`read_json` (2026-08 code-clone sweep, finding S3), which is
exactly the shape where "we tightened it" quietly means "we tightened one".
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.http import HttpRequest


def read_json(request: HttpRequest) -> dict[str, Any]:
    """Parse a JSON request body into a dict, or ``{}`` when it is not one.

    Deliberately lenient: these endpoints answer malformed input with their own
    generic, non-enumerating responses (req-tap-auth-passkey-enrollment-6), so
    parsing never raises here.
    """
    try:
        data = json.loads(request.body or b"{}")
    except ValueError, TypeError:
        return {}
    return data if isinstance(data, dict) else {}
