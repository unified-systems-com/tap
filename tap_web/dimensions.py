"""The dimension stamp that puts web artifacts in their own graph partition.

TAP-IMPLEMENTS: req-web-page-dim@8520a04984b4/08c16715b9ad (derivation) — the one spelling of the
web partition's dimension key/value; every tap_web node type and web-origin edge type
reads it from here rather than restating the literal.

This is a leaf module rather than a constant in ``tap_web.models`` because
``TapWebConfig.edge_types`` needs the value in its *class body*, which Django evaluates
while populating app configs — before the model registry is ready. An import of
``tap_web.models`` from ``tap_web.apps`` at that point raises ``AppRegistryNotReady``.

Consumers that merge caller-supplied dimensions over this one all copy first
(``dict(...)``), so exporting a single shared mapping is safe.
"""

from typing import Final

WEB_DIMENSIONS: Final[dict[str, str]] = {"tap.graph": "web"}
