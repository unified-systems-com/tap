"""Domain-article coverage ratchet — `specs/spec-domain-articles.md` (`req-domain-articles-coverage`).

Every node type and edge type a plugin registers owes a domain article, every article
owes the required sections, and — the tooth that matters — every key in a model's
`FIELD_CRUD_SCHEMA` owes a per-field explanation. A field added without a paragraph
reds the build, so the article cannot silently fall behind the model it describes.

A ratchet rather than a hard lint: this layer is new, the concepts already modelled
predate it, and a guard that reds every existing plugin on the day it lands gets
disabled instead of drained. Each owner records its debt in **its own** baseline
(`<plugin>/guards/baselines/domain_articles.txt`), so the number is visible and
shrinking — a backlog with a count attached is worked, one without is not — and so a
plugin carries its debt into its wheel and takes it away on eviction rather than
stranding rows in a central file (`req-tap-plugin-validation-distribution-principle`).

Measurement lives in `tap.domain_articles`; this is only the compare-and-report.
"""

from __future__ import annotations

from tap.domain_articles import baseline_path_for, finding_key, findings_for_root, plugin_roots
from tap.guards.base import REPO_ROOT, Guard
from tap.ratchet import RatchetError, ratchet_ceiling, read_baseline_set
from tap.source_scan import first_party_source_roots

_NEW_HINT = (
    "Write (or extend) the domain article beside the model: `<owner>/domain/<concept>.md`, or "
    "`<owner>/domain/dimensions/<key>.md` for a dimension. "
    "It says what the concept IS in the world and why we modelled it this way — link the spec "
    "for what we require of it, never restate it. Required sections: Blurb, Purpose, Goals, "
    "Identity, Boundaries, Neutrality, Observability, Authoritative Source, Prior Art, and "
    "Fields (nodes), Endpoints (edges) or Values (dimensions). A dimension article must name "
    "every value any model or edge gives that key. Authoritative Source pins `Source` / `Version` / "
    "`Retrieved` so 'this standard revised — which models does it touch?' is one grep. Write "
    "Observability from an executed call, not from the vendor's documentation. Last resort: "
    "record the gap in the owning plugin's baseline."
)


class DomainArticleGuard(Guard):
    """Ratchets each plugin's unmet domain-article obligations toward zero."""

    slug = "domain-article-coverage"
    map_row = "Domain-article coverage"
    rid = "req-domain-articles-coverage"
    description = (
        "A model whose concept is explained nowhere forces every later reader — maintainer, outside "
        "contributor, or AI assistant — to re-derive it from the vendor's API reference, and the "
        "facts that cost the most to rediscover (what a credential can actually see, which natural "
        "key is load-bearing, what the model deliberately excludes) are exactly the ones no spec or "
        "docstring has a home for. Field coverage is the load-bearing half: without it the article "
        "drifts from the model silently, which is worse than absent because it reads as current."
    )

    def check(self) -> None:
        """TAP-IMPLEMENTS: req-domain-articles-coverage@fd16b80d52ea/2aac2383ccdb (enforcement) — the one
        build-time assertion that every registered node/edge type has a conforming, field-complete article.
        """
        failures: list[str] = []
        plugins = set(plugin_roots(REPO_ROOT))
        for root in first_party_source_roots(REPO_ROOT):
            # A `tap_*` app owes articles for the dimension vocabulary it declares, but
            # not for its node types: those model TAP's own furniture (pages, panels,
            # batches), which their specs already define and about which there is no
            # outside world to research.
            is_plugin = root in plugins
            baseline_path = baseline_path_for(root)
            current = {finding_key(f, REPO_ROOT) for f in findings_for_root(root, types=is_plugin)}
            if not current and not baseline_path.exists():
                continue
            try:
                ratchet_ceiling(
                    current=current,
                    baseline=read_baseline_set(baseline_path),
                    surface=f"{self.map_row} — {root.name}",
                    baseline_path=baseline_path,
                    new_hint=_NEW_HINT,
                )
            except RatchetError as exc:
                failures.append(str(exc))
        if failures:
            raise RatchetError("\n\n".join(failures))
