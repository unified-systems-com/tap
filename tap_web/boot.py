"""Web boot section — settings-time reader for the boot profile's ``web`` section (req-boot-web-section).

Mirrors ``tap_auth/boot.py``: reads ``boot/<profile>.boot.json`` with NO Django model
imports so ``tap/settings.py`` can fold the operator's landing decision into
``TAP_WEB_LANDING`` at import time. One declarative source (the profile) feeds both the
running server's settings and the boot command's post-population verification
(``tap_boot.orchestrator._phase_web``), which calls ``landing_from_section`` on the
profile it is booting rather than trusting the process's own settings.

The pair — ``landing_entity_id`` (identity) + ``landing_slug`` (asserted check) — rides
the boot-variable ladder key by key (env > profile > absent), so the result carries a
per-key provenance the boot record and the ``web.landing`` health probe report.
Contract: ``tap_web/specs/spec-web-page.md`` ``req-web-page-landing``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tap.boot_naming import profile_path
from tap.jsonfiles import JsonFileError, load_json_file
from tap.preboot import resolve_var

logger = logging.getLogger(__name__)

SECTION = "web"
KEY_ENTITY_ID = "landing_entity_id"
KEY_SLUG = "landing_slug"


def _profile_path(profile_id: str) -> Path:
    # Computed from this file's location (repo_root/tap_web/boot.py -> repo_root/boot/)
    # rather than settings.BASE_DIR: this runs DURING tap.settings import, where the
    # lazy settings object is still mid-initialization (the tap_auth precedent).
    repo_root = Path(__file__).resolve().parent.parent
    return profile_path(repo_root / "boot", profile_id)


def read_web_section(profile_id: str) -> dict[str, Any]:
    """Return the raw ``web`` section of ``boot/<profile_id>.boot.json`` ({} if absent).

    Tolerant by design — a malformed profile is the boot command's problem to surface
    loudly (schema validation there is the strict guard); settings-time reading must
    not crash the process on a bad file. Returns {} on any read/parse problem (logged).
    """
    if not profile_id:
        return {}
    path = _profile_path(profile_id)
    if not path.is_file():
        return {}
    try:
        data = load_json_file(path)
    except JsonFileError as exc:
        logger.warning("[d93a] could not read web section from %s: %s", path, exc)
        return {}
    section = data.get(SECTION)
    return section if isinstance(section, dict) else {}


def landing_from_section(section: dict[str, Any] | None) -> dict[str, Any] | None:
    """Resolve the landing pair through the env > profile ladder; None when undeclared.

    TAP-IMPLEMENTS: req-boot-web-section@bbc87dcd549e/7d87ccd2c77d (derivation) — the one place the
        profile's `web` pair becomes an effective value with provenance; settings and the
        boot's web phase both call it, so the running server and the verification cannot
        disagree about what was declared.

    Returns ``{"entity_id", "slug", "source": {"entity_id": <env|profile>, "slug": ...}}``.
    A pair with only one key present is returned as-is (the other value None) so the
    resolver reports it as *malformed* rather than this reader silently dropping it.
    """
    entity_id = resolve_var(SECTION, KEY_ENTITY_ID, profile_section=section, default=None)
    slug = resolve_var(SECTION, KEY_SLUG, profile_section=section, default=None)
    if entity_id.value is None and slug.value is None:
        return None
    return {
        "entity_id": entity_id.value,
        "slug": slug.value,
        "source": {"entity_id": entity_id.source, "slug": slug.source},
    }


def landing_for_settings(profile_id: str) -> dict[str, Any] | None:
    """``TAP_WEB_LANDING`` for ``tap/settings.py``: the resolved pair with provenance, or None."""
    return landing_from_section(read_web_section(profile_id) or None)
