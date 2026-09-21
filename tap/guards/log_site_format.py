"""Log-site token format guard — `spec-tap-logging.md` (`req-tap-logging-site-id-scanner`).

Every committed `logger.*` call must open with a bare 4-hex `[<hex>]` site token
(no slug, no prefix).
"""

from __future__ import annotations

from tap.guards._log_site_scan import key, scan
from tap.guards.base import Guard


class LogSiteFormatGuard(Guard):
    slug = "log-site-format"
    map_row = "Log-site tokens"
    rid = "req-tap-logging-site-id-scanner"
    description = (
        "A malformed site token ([<not-4-hex>]) breaks the structured-logging contract the future JSON "
        "formatter depends on. Every committed log call must open with a bare 4-hex [<hex>] token; this "
        "flags any that don't."
    )

    def check(self) -> None:
        malformed = scan().malformed_ids
        assert not malformed, (
            "Malformed log-site token(s) — must be a bare 4-hex `[<hex>]` (e.g. `[a8f3]`), no slug or "
            "prefix. Mint one with `scripts/log-site-id`:\n  " + "\n  ".join(key(s) for s in malformed)
        )
