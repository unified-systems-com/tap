"""Model-version guard — a type's definition does not change without its version (and the spine's likewise).

`req-grid-entity-model-version` rules 5 and 7, `req-grid-entity-spine-version` rule 7. An authored
version is forgotten: a field is added, the number is not raised, and a document written by the
new code states the old version for a definition that version never had. This guard computes each
of core's node and edge types' definitions, and the spine's, and compares them with the record
committed in the owning app (`<app>/<app>.model_versions.json`):

- a definition that changed while its version did not fails, naming the type;
- an entry of an earlier version that was edited after it was recorded fails;
- a declared version with no entry, and a type with no record at all, fail.

It covers core's types only. A plugin's types are checked the same way, by the same code, in the
plugin's own repository by plugin validation (`tap_plugins.validate`), so an installed plugin with
no record cannot fail core's guard. Extend a record with `manage.py model_versions --record`.

A hard check with no baseline: every core type was recorded at version 1 when this landed.
"""

from __future__ import annotations

from typing import ClassVar

from tap.guards.base import Guard


def core_problems() -> list[str]:
    """Every disagreement between core's types as defined now and their committed records."""
    from tap_grid.model_definition import (
        app_record_path,
        core_states,
        entries_for,
        load_record,
        type_problems,
        unrecorded,
    )

    problems: list[str] = []
    for owner, states in sorted(core_states().items()):
        path = app_record_path(owner)
        try:
            record = load_record(path)
        except ValueError as error:
            problems.append(str(error))
            continue
        for state in states:
            problems.extend(f"{owner}: {problem}" for problem in type_problems(state, entries_for(record, state)))
        problems.extend(
            f"{owner}: {state.label} has no committed entry in {owner}/{path.name}. Record it "
            "(manage.py model_versions --record)"
            for state in unrecorded(states, record)
        )
    return problems


class ModelVersionGuard(Guard):
    slug: ClassVar[str] = "model-version-fingerprint"
    map_row: ClassVar[str] = "Model and spine version fingerprints"
    rid: ClassVar[str] = "req-grid-entity-model-version"
    description: ClassVar[str] = (
        "Fails when the definition of one of core's node or edge types, or of the spine, changed while "
        "its authored version did not, or when a committed entry of an earlier version was edited. "
        "Without it a forgotten version bump lets one version number name two definitions, and an "
        "import cannot tell which one wrote the records it reads."
    )

    def check(self) -> None:
        problems = core_problems()
        if problems:
            raise AssertionError(
                f"{len(problems)} type definition(s) out of step with their committed version record:\n  "
                + "\n  ".join(problems)
            )
