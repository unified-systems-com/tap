"""Database alias names — the one spelling of each non-default connection alias.

Stdlib-only leaf: imported by ``tap/settings.py`` at settings-evaluation time (so it
must not touch Django or any app module) and by the ``tap_grid`` search/Gryphon
modules, collapsing what were five independent spellings of the same string.

The stakes are why this file exists: ``SEARCH_READONLY`` names the least-privilege
search connection (``default_transaction_read_only=on`` + the ``tap_gryphon_ro``
role + resource GUCs, req-grid-search-readonly.sec / req-grid-search-readonly-role.sec).
A typo'd alias falls through to Django's writable ``default`` connection — so the
alias is derived here once, never restated.
"""

from __future__ import annotations

# The read-only, least-privilege search/Gryphon connection (req-grid-search-readonly.sec).
SEARCH_READONLY = "search_readonly"

#: Every alias `tap/settings.py` configures, in one place, so a count of them can be
#: DERIVED rather than typed. The connection budget multiplies by this count
#: (`tap.serving.connection_budget`, req-tap-serving-connection-budget-1), and a budget
#: computed from a hand-typed "2" would keep its old answer the day a third alias lands.
#: `tap/tests/test_connection_budget.py` asserts this tuple IS the configured alias set,
#: so the tuple cannot become a declaration that is merely present.
ALL_ALIASES: tuple[str, ...] = ("default", SEARCH_READONLY)
