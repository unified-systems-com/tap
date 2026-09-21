"""Log-site within-file uniqueness guard — `spec-tap-logging.md`.

No hex site token may be reused inside a single module (cross-file reuse is
namespaced-safe by the module path).
"""

from __future__ import annotations

from tap.guards._log_site_scan import scan
from tap.guards.base import Guard


class LogSiteUniquenessGuard(Guard):
    slug = "log-site-within-file-uniqueness"
    map_row = "Log-site tokens"
    rid = "req-tap-logging-site-id-scanner"
    description = (
        "Two log calls sharing a hex within one module make a token ambiguous — you can't tell which "
        "call site a log line came from. Usually copy-paste. This flags any hex reused within a file."
    )

    def check(self) -> None:
        from tap.logging import find_within_file_duplicates

        dups = find_within_file_duplicates(scan().well_formed)
        assert not dups, (
            "Duplicate log-site hex within a file (likely copy-paste) — regenerate one with "
            f"`scripts/log-site-id`:\n  {dups}"
        )
