"""Below the gate: the gateway's one handle on the backend (`req-tap-files-gateway-5`).

The handle lives here and not in the gateway module, so the gateway carries no ungated attribute:
`from tap_files.services import get_store` would otherwise hand a caller the backend with no
capability check and no record. Importing this `_` module from outside the package is refused by
the import-encapsulation guard, and importing a non-export from the gateway by files-backend-reach.
"""

from __future__ import annotations

from tap_files.store import get_store
from tap_files.store.local import LocalBackend


def backend() -> LocalBackend:
    return get_store()
