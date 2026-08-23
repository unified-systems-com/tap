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
