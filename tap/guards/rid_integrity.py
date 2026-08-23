"""Referenced-RID integrity ratchet — `spec-docs.md` (`req-docs-rid-integrity`).

TAP-IMPLEMENTS: req-docs-rid-integrity@9633efb7b6ee/55d3fc8f1180 (enforcement) — the guard
    that fails a `req-*` citation resolving to no defined requirement.

Every `req-*` token cited in a living surface — a first-party Python docstring or comment,
a spec cross-reference, a non-archival doc, an agent guide — must resolve to a requirement
or acceptance criterion actually defined in the specs.

Why this is a defect and not a cosmetic nit: TAP's documentation system is held together by
`req-*` cross-references, and the reader most harmed by a dangling one is **Player 3**
(`spec-ai-integration.md`). AI sessions ground themselves by chasing RIDs, so a stale
citation quietly poisons an agent's grounding — a machine-legibility defect.

Ratcheted rather than hard: the corpus carries pre-existing strays of two honest kinds —
citations left behind by a rename (the demand signal), and references to requirements that
left the repo with an evicted plugin. Both are recorded in the baseline and driven down;
neither may grow.

Archival corpora (`docs/aar/`, postmortems, handoffs) are **excluded by rule**
(`req-docs-rid-integrity-3`): they describe the past, so a retired RID there is a record,
not drift. That exclusion lives in `tap.spec_trace`, stated once.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from tap.guards.base import REPO_ROOT, CeilingRatchet


class RidIntegrityRatchet(CeilingRatchet):
    slug = "rid-reference-integrity"
    map_row = "Referenced RID integrity"
    rid = "req-docs-rid-integrity"
    description = (
        "A `req-*` citation that resolves to nothing strands the reader — and Player 3 grounds "
        "itself by chasing RIDs, so a dangling reference silently poisons an AI session's context."
    )
    baseline_path: ClassVar[Path] = Path(__file__).resolve().parent / "baselines" / "rid_refs.txt"
    new_hint = (
        "Fix the citation to name a requirement that exists (check for a rename — the dotted "
        "`.sec` facet convention retitled several), or drop the reference if the requirement is gone."
    )

    def measure(self) -> set[str]:
        from tap.spec_trace import citation_key, dangling_citations

        return {citation_key(c, REPO_ROOT) for c in dangling_citations(REPO_ROOT)}
