---
title: Plugin Dependency Management & Reporting Surface — Design Thoughts
date: 2026-07-02
status: design-note
audience:
  - llm
  - developer
related_docs:
  - docs/misc/doc-plugin-source-identity-deps-handoff.md
  - docs/misc/doc-plugin-boot-install-handoff.md
related_specs:
  - tap_plugins/specs/spec-tap-plugin-architecture.md
  - specs/spec-tap-boot-v0.md
---

# Plugin Dependency Management & Reporting Surface — Design Thoughts

> **Status: design note (2026-07-02), not a spec.** Forward-looking thinking captured after the
> package-mode migration sweep completed + promoted (all 9 samsite-set plugins on
> `tap_plugin.<slug>`; `gryphon_playground` still to migrate). It refines the two deferred threads
> from `doc-plugin-source-identity-deps-handoff.md` — `req-tap-plugin-arch-dependencies` (Tier-1/2
> `depends_on`, resolver) and `req-tap-plugin-arch-install-registry` (-3/-5, the registry/report surface).
> The point of the note is the **"what's free"** framing: most of both is legibility + cross-checking
> of facts already in hand, not new machinery — so most of it should ride the **validation + security
> focus-fire** as cheap-foundational edges, while the genuinely-new machinery stays demand-gated.

## The unifying insight

Both dependency management and the reporting surface are the **same move TAP already makes
everywhere**: *declare intent, derive the actual state from facts already in hand, cross-check the
two, fail closed on divergence.* That is the pre-boot reconciliation guard, the authz-coverage
scanner, the model-based reference oracle, the conformance gate — all one shape. Neither of these
threads is a new *machine*; they are mostly making already-present facts legible and checked. That is
why so much of it is free, and why it is the right kind of asymmetric edge (cheap now, expensive to
retrofit) to lay while we are already on these surfaces for validation + security work.

## 1. Dependency management

### Tiers (already spec'd, `req-tap-plugin-arch-dependencies`)

- **Tier 0 — package deps → `pyproject.toml`.** uv resolves the closure + diamonds, fail-closed.
  **Done and free** (PyYAML→github_core, boto3→aws_core, sigstore→sigstore_core all resolve through
  the pre-boot editable install).
- **Tier 1 — load/registration order → manifest `depends_on`** (slug edges, min-version, optional).
- **Tier 2 — seed/data order → mostly rides `depends_on`**; the runtime-*data* dependency
  (collector-produced nodes) stays explicit in the profile.

### What's free (and why)

- **The dependency graph is derivable, not authored.** Cross-plugin *code* dependencies **are**
  Python imports — `from tap_plugin.sigstore_core import …` in samsite literally *is* the edge
  samsite→sigstore_core. A static AST scan of each plugin package for `tap_plugin.<other>` imports
  yields the actual code-dependency graph, reusing the scanner muscle already built for
  `discover_scan_roots` / authz-coverage / log-site / json-file. **You don't declare the graph; you
  observe it.**
- **`depends_on` as a manifest field is near-zero authoring cost** and earns its keep as the *intent*
  statement — the AI- and security-readable "what this plugin expects present," which the observed
  graph is checked against. (Same principle as the JSON-structures-require-descriptions rule:
  declarations give something to verify actions against.)
- **The consistency gate is cheap because all three inputs already exist** — declared `depends_on`,
  observed imports, and profile install order. The gate is just:
  1. **declared ⊇ observed** — every real cross-plugin import has a matching `depends_on`, else fail
     closed. (An undeclared dependency is exactly the silent coupling that bites on extraction to a
     standalone repo.)
  2. **install order respects `depends_on`** — deps before dependents.
  3. **min-version satisfied.**
  This is a direct sibling of the reconciliation guard already on main — same file
  (`tap/preboot.py`), same fail-closed style.

### What's NOT free (correctly deferred)

- **The topological-sort resolver** — auto-deriving install order from `depends_on` so humans don't
  hand-order. The one genuinely new mechanism, and demand-gated: hand-ordering (samsite last) is fine
  at N=9, and the roadmap explicitly red-flags "comprehensive plugin dependency management." Build it
  when hand-ordering actually hurts (≈ Django's `topological_sort.py`, cycle-detecting, fail-closed).
- Anything beyond uv's existing one-version-fail-closed behavior.

### One honest boundary (do not conflate)

Import-derivation captures the **code** dependency (Tier 0 cross-plugin + Tier 1 load order). It does
**not** capture the **data** dependency — samsite's compliance_collector must run *after* the boto3 +
github collectors because it reads nodes they produce, and that is invisible to imports. Per spec that
stays **profile-explicit** (the fire-collector ordering) for auditability. So the free graph nails
code-dep validation; the data-dep stays authored + human-reviewed. The elegance of the import graph
must not tempt anyone into pretending it covers the data edges — it doesn't, and conflating them would
produce a confidently-wrong dependency picture.

### The security dividend

The import-derived graph **is** a supply-chain / blast-radius map — "if sigstore_core is compromised
or pulled, what breaks." One derivation, three payoffs: dependency validation, supply-chain
visibility, and the raw data for the reporting surface below. That is the asymmetric cheap-now /
expensive-later edge the security posture is about — and why this belongs in the security focus-fire.

### Cheapest concrete first cut

Manifest `depends_on` field + the import-graph scanner + the declared-⊇-observed boot consistency
gate. All three are validation guards in the family already on main — they slot into the
`spec-dev-validation` Validation Map, not a separate plugin-ecosystem push.

## 2. Reporting / viewing surface (`req-tap-plugin-arch-install-registry` -3/-5)

### What's free (and why)

The registry record is **already computed** — it just isn't captured. Pre-boot already knows, per
plugin: slug, source, enabled, discovered entry point, conformance result
(dist/entry-key/namespace/slug), reconciliation result, resolved `TAP_PLUGINS`. The manifest gives
declared surfaces (models/edges/editors/searches/grift). hatch-vcs gives version + commit. The
dependency scanner (§1) gives edges. **The report is a serialization of facts boot already has in
hand — not a computation.** The four-layer spec already names this the *canonical* inspection surface
(over the filesystem), whose job is "what TAP attempted, resolved, loaded, and why startup failed."

### Cheapest first cut — a read-model, not a system

A `manage.py plugins` (report) command emitting, per plugin: slug · dist · version/commit · source ·
mode · declared vs loaded surfaces · load health · dependency edges. Text for humans, `--json` for
machines/AI. It rides the existing `manage.py health` / `manage.py boot` shape, and it is
**read-only** — no graph writes, so it sidesteps the tap_ai v0 write constraint entirely. This is the
free 80%.

### The maturity ladder (each rung demand-gated)

1. **Now (free):** capture boot's facts → `manage.py plugins --json`. The audit/operator surface.
2. **Later, when a viewer need appears:** the plugins + their dependency edges become **nodes and
   edges on the grid** — a plugin genuinely *is* an entity with relationships, so this is natural, not
   forced. Once on the grid, the cytoscape **graph view is free** (tap_viz already renders node/edge
   projections), and the dependency graph becomes a visual "plugin map."
3. **Demand-gated:** enable/disable/rollback controls, signing status, a "marketplace" board — the
   roadmap Lower-priority ecosystem stuff. Do not build ahead of a real plugin author.

### Security/audit angle

The captured registry is the operator's ground-truth for provenance and load outcome — and you cannot
retrofit provenance you did not capture at boot. Capturing it now (cheap) is what makes a later "is
this instance running what we think it's running" answer possible.

## Sequencing recommendation

**Fold the free edges into the validation + security focus-fire — do not spin them up as a
plugin-ecosystem push.** Concretely, in that phase:

1. `depends_on` field + import-graph scanner + declared-⊇-observed consistency gate (validation
   guards + supply-chain map).
2. Boot-fact capture → `manage.py plugins --json` (validation/audit surface, Validation Map row).

**Explicitly defer (name the risk, don't build):** topo-sort resolver, the `index`/dumb-pypi source,
artifact signing, grid-node plugin model + cytoscape view, and any enable/disable/rollback UI. These
are demand-gated by a real external plugin author or field deployment — exactly what the roadmap says
to wait for.

**Net:** dependency management ≈ 80% free (declare + derive + check), the resolver is the only real
build and it waits; the reporting surface ≈ 80% free (serialize what boot already knows), the graph
view and controls wait.
