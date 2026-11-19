"""File node writer guard — `req-tap-files-node-8`.

`tap_file`, `tap_directory`, `CONTAINS_TAP_FILE` and `CONTAINS_TAP_DIRECTORY` are internal-only, so the
generic verbs and GRIFT refuse them. The trusted-internal path is a tripwire, not a wall: in-process
code holding a program actor could call it and write a `tap_file` whose bytes were never stored. So
outside `tap_files`, no call to a trusted-internal writer, and no `WriteOperation`, may name one of
the four. The holding helper is their only writer, and it stores the bytes first. Tests are exempt.
The scan sees literal names, not ones computed at run time; the check (`req-tap-files-check`)
reports any `tap_file` the store does not back, whoever wrote it.
"""

from __future__ import annotations

import ast

from tap.guards.base import REPO_ROOT, Guard
from tap.source_scan import call_name, first_party_source_roots, iter_parsed_sources

_NAMES = frozenset({"tap_file", "tap_directory", "CONTAINS_TAP_FILE", "CONTAINS_TAP_DIRECTORY"})
_WRITERS = frozenset(
    {
        "_create_node_internal",
        "_patch_node_internal",
        "_create_edge_internal",
        "_replace_edge_internal",
        "write_batch",
        "WriteOperation",
    }
)
_OWNER = "tap_files/"


def _named(call: ast.Call) -> set[str]:
    return {
        node.value
        for node in ast.walk(call)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in _NAMES
    }


class FilesInternalWritersGuard(Guard):
    slug = "files-internal-writers"
    map_row = "File and directory nodes written only by tap_files"
    rid = "req-tap-files-node"
    description = (
        "tap_file, tap_directory and their containment edges are written only by tap_files' holding helper, "
        "which stores the bytes first. A call outside tap_files to a trusted-internal writer or a "
        "WriteOperation naming one of them could write a file node with no bytes behind it."
    )

    def check(self) -> None:
        offenders: list[str] = []
        for parsed in iter_parsed_sources(first_party_source_roots(REPO_ROOT)):
            rel = parsed.path.relative_to(REPO_ROOT)
            if "tests" in rel.parts or rel.as_posix().startswith(_OWNER):
                continue
            for node in ast.walk(parsed.tree):
                if isinstance(node, ast.Call) and call_name(node) in _WRITERS:
                    offenders.extend(f"{rel}:{node.lineno} {call_name(node)} names {n}" for n in sorted(_named(node)))
        assert not offenders, (  # nosec B101
            f"File store nodes written outside tap_files ({len(offenders)}):\n  "
            + "\n  ".join(sorted(set(offenders)))
            + "\n\nHold files through tap_files.holding.hold_file (req-tap-files-node-8)."
        )
