"""Record-site within-file uniqueness guard — `req-tap-cares-collector-job-model-15`.

No file may reuse a `record_*` site hex within itself (cross-file reuse is
namespaced-safe by the module path).
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from tap.guards.base import REPO_ROOT, Guard
from tap.source_scan import is_excluded_dir

# Beyond the shared default: build outputs, where generated files can carry
# stale copies of a site constant.
_EXTRA_SKIP_DIRS = frozenset({"static", "build", "dist"})

_HEX = r"[0-9a-f]{4}"
# A `_SITE_<NAME> = "<hex>"` module/class constant assignment.
_SITE_CONST = re.compile(r"^\s*_SITE_[A-Z0-9_]+\s*=\s*[\"'](" + _HEX + r")[\"']\s*$", re.MULTILINE)
# An inline first-positional string literal to a record_* call.
_RECORD_INLINE = re.compile(r"record_(?:info|warn|error)\s*\(\s*[\"'](" + _HEX + r")[\"']", re.DOTALL)

# This scanner defines the regexes it looks for — exclude it from its own scan.
_SELF_REL = Path("tap_cares/guards/record_site.py")


def _iter_repo_python_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*.py"):
        if is_excluded_dir(path.relative_to(REPO_ROOT), extra=_EXTRA_SKIP_DIRS):
            continue
        files.append(path)
    return files


class RecordSiteUniquenessGuard(Guard):
    slug = "record-site-uniqueness"
    map_row = "`record_*` site tokens"
    rid = "req-tap-cares-collector-job-model-15"
    description = (
        "Collectors tag observations with a 4-hex record_* site token whose callsite path is the module, so "
        "the hex only has to be unique within its file. Reusing one within a file (copy-paste without "
        "bumping it) collapses two callsites into one indistinguishable token. This flags any such reuse."
    )

    def check(self) -> None:
        offenders: list[str] = []
        for path in _iter_repo_python_files():
            rel = path.relative_to(REPO_ROOT)
            if rel == _SELF_REL:
                continue
            try:
                text = path.read_text()
            except OSError, UnicodeDecodeError:
                continue

            seen: dict[str, list[int]] = defaultdict(list)
            for match in _SITE_CONST.finditer(text):
                seen[match.group(1)].append(text.count("\n", 0, match.start()) + 1)
            for match in _RECORD_INLINE.finditer(text):
                seen[match.group(1)].append(text.count("\n", 0, match.start()) + 1)

            for hex_tok, lines in sorted(seen.items()):
                if len(lines) > 1:
                    offenders.append(f"  {rel}: '{hex_tok}' at lines {sorted(lines)}")

        assert not offenders, (
            "Duplicate record_* site hex within a file:\n"
            + "\n".join(offenders)
            + "\n\nEach site token must be unique within its file (cross-file reuse is namespaced-safe). "
            "Mint fresh ones with `scripts/log-site-id`."
        )
