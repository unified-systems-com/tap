# TAP Development Guide 

Instance context (keystone — read before asking)
    To learn what THIS instance is, what it's for, or where its data came from, read the keystone(s)
    on the grid before asking the user: `MATCH (k:keystone) RETURN k ORDER BY k.created_at ASC` and
    read the OLDEST first (foundational context; newer ones layer on). Each keystone ships human prose
    plus context_json + the JSON Schema documenting it (context_schema_json). Spec: tap_grid/specs/spec-grid-keystone.md.

Roadmap (on-path authority)
    Before planning or implementing substantial work, read the active step in plan/road-rampart.md
    (the Rampart roadmap, governed by specs/spec-roadmap.md). Judge the work against that step's
    Objective / Done-Test / Non-Goals. The roadmap Doctrine section is the standing strategic filter.

Strategic discipline (feedback_center_of_gravity_champion)
    When the work turns toward early adopters, pricing, productization, or launch strategy, act as
    a steady center of gravity. Keep George anchored in the next concrete path to getting in front
    of real people: approach early adopters, collaborate with them, guide toward trials, then
    sales/purchases. The current world is full of high-energy signals that can pull attention into
    fantasy, tangents, premature scaling, or overbuilt future-state thinking. Move methodically,
    with haste; keep the critical path visible; and favor grounded conversations with real teams
    over speculative optimization.

Security posture (standing filter)
    specs/spec-security-posture.md is the security-engineering center of gravity. When work touches a
    surface where a foundational defensive edge could be laid at near-zero marginal cost — especially
    while already rewriting that surface — lay it, even speculatively: the cost is asymmetric (cheap
    now, expensive/impossible to retrofit later) and over-restriction relaxes cheaply while omission
    retrofits expensively. Take the cheap, foundational, build-once edges; let the expensive ones wait
    for demand; and name the risks deliberately left open rather than implying completeness.

AI integration posture (standing filter — build for Player 3)
    specs/spec-ai-integration.md is the center of gravity for AI. The system is no longer just
    code + humans: build for the third player — the internal / integrated / external AI assistants
    that observe, guide, and (later) operate TAP. When building any surface, ask how an AI helper
    observes, operates, and reasons about it, alongside the human question. Prefer machine-legible
    signals and declarative, described, queryable metadata over human-only prose or state that needs
    code-reading; name the AI consumer of any for-AI surface; author operational procedures as
    AI-operable skills. This is the cheap-edge discipline (security posture) applied to AI-legibility —
    lay it while the surface is open, especially as the plugin system wraps. v0 AI is read-only: it
    reads/summarizes/suggests and must not write core graph state; any future write rides the service
    layer under a named delegated actor, never a bypass.

FIPS posture (standing filter)
    specs/spec-fips.md is the center of gravity for FIPS — everything TAP does around FIPS 140-3 and
    cryptographic-provider provenance reads from that one spec (with doc-fips-assessment-record.md as
    the detailed decision/lessons/verification record). FIPS is default-ON (ARG TAP_FIPS=1). The
    invariant: every cryptographic PROVIDER that can execute in the deployed artifact is the validated
    module (system OpenSSL #4282) or that ecosystem's validated equivalent — or is proven unreached, or
    explicitly named out-of-boundary. OpenSSL is only what Python uses; a Go binary, a Rust crate on
    ring/aws-lc-rs, a libsodium/pynacl wheel, or a JVM's BouncyCastle each carries its OWN crypto that
    ignores OPENSSL_CONF and silently runs non-FIPS — so the audit is "account for every crypto
    provider," not "grep for MD5" (the crypto Bill-of-Materials, req-fips-crypto-bom). When work adds a
    dependency, a native binary, or a plugin, keep it FIPS-clean (build against system OpenSSL, not a
    bundled one — cryptography/psycopg are --no-binary/[c]) or account for it: the crypto-BOM gate
    fails-closed on an unclassified provider, and it must EXECUTE crypto + observe a refusal, never
    inspect files (the config is the boundary, not the modules dir). Plugins follow declare-vs-decide:
    the author DECLARES posture in the manifest [fips] table (verified by the scan), the system ENFORCES
    globally in FIPS mode, and only the OPERATOR waives — per-plugin, in the boot profile, with a
    mandatory reason — a plugin can never exempt itself.

Technology Stack
    Backend: Django 6+ with Django Ninja for API
    Database: PostgreSQL
    Async Tasks: Django Tasks (used sparingly in v0; primarily for ingestion and long-running read-only analysis)
    Containerization: Docker with docker-compose for development

Key Directories - each are their own Django app, this is also the scaffolding priority order for v0
1. tap_grid - Core data model - we define entity and edge tables connecting to standard ORM data tables and decide how to best structure where that standardized logic lives, including service-layer decisions that touch multiple tables
2. tap_plugins - plugin management - minimal implementation designed to seed data types for testing / implementation, this will grow and evolve, shooting bare minimum to add data objects, edges to prove core is working properly
3. tap_api - Manages API versioning, auth, and global API behavior, building out django ninja so there's an api layer that is minimal and effective and decide how to refactor plugins to support adding api endpoints in a sane way
4. tap_web - Assets and helpers for building expressive dashboards and UIs which plugins will extend, once this is baked we can refactor the plugin from built in step 2 to include some pages to see things
5. tap_viz - Visualization - present views of the data in visual graphical format (cytoscape), once we can see web pages we'll add cool visuals that will be a joyful thing to see
6. tap_ai - Initial RAG / LLM Surfaces - read-only graph traversal, summarization, and suggestion helpers, the super-awesome stretch goal which takes this whole project to the next level

TAP Core Architectural Rules
    Specifications are the canonical source of truth; this guide is a high-level operational summary and must be kept aligned with the specs.
    Derive a fact once: when a fact is needed in two places, call one function — never copy the logic or re-derive from another source. Where a structural boundary forces an intentional duplicate (settings-free vs in-Django, stage-0 host tools), tag EVERY site with `TAP-KNOWN-DUPE(<group-id>)` naming why and where the partner is, and document the group in the owning spec (specs/spec-tap-known-dupes.md; guard-enforced). Editing one member of a group means putting eyes on its partners. Untagged duplication is a defect.
    Entity is the graph spine and cross-cutting metadata layer for TAP-managed nodes and edges; typed BaseModel tables hold domain-specific data.
    ORM models refer to entity via foreign key relationships
    Use a BaseModel for all domain ORM models (excluding Entity, Edge, Grid and Django auth models) so every TAP-managed node has a backing Entity on the spine.
    The TAP service layer is the canonical path for TAP-managed node and edge reads and writes.
    Any application code, plugin code, or background task that mutates TAP-managed node or edge data must do so through the service layer rather than direct ORM writes.
    Direct ORM access is acceptable only for migrations, intentional low-level/model tests, and explicitly out-of-scope admin/infrastructure behavior.
    Dimensions live on Entity and are the current implemented scoping/partitioning model for TAP-managed graph data.
    FLIP and provenance integrate with the service layer and caller context; do not invent parallel mutation APIs.
    History, FLIP, and future perspectives are core grid concepts, not separate architectural product domains; implementation modules should not be treated as independent system boundaries.
    TAP-managed node and edge types should publish discoverable schemas and capabilities through the registry-backed service-layer discovery system.
    
TAP Plugin Rules
    Plugins may register API routers only under a namespaced prefix controlled by tap_api (e.g. /api/v1/plugins/<plugin_slug>/...)
    Plugins expose API routers via an explicit registration interface; tap_api is responsible for discovery, mounting, and lifecycle management.

TAP AI Rules
    tap_ai must not write to core graph state in v0.

Code Quality Standards
    Formatting: black
    Linting: ruff with Django-specific rules
    Type Checking: mypy with mostly-strict settings and Django plugin
    Docstrings: Google-style docstrings for public interfaces and non-trivial functions
    Coverage: High coverage is encouraged; critical paths must be tested
    Avoid Any where practical:  Allow it at system boundaries and plugin interfaces with justification
    Use early returns:  Avoid nested conditionals
    Prefer composition over inheritance
    Use double quotes for Python strings
    Sort imports with isort
    Use f-strings for string formatting

Logging Conventions (Option A — see specs/spec-tap-logging.md)
    Use `logger = logging.getLogger(__name__)` at module top — never hardcode a logger name. The logger name IS the callsite path: derived, never authored.
    Every committed log call at EVERY level (DEBUG through CRITICAL, plus exception) starts with a bare 4-hex site token `[<hex>]` — no slug, no prefix.
    Mint the hex with `scripts/log-site-id` (never hand-pick one). It only has to be unique within its file; the module path namespaces it.
    `# noqa: TAP-LOG-ID` on the same line is the narrow, review-visible escape hatch (e.g. tight high-volume loops).
    Use `%s` placeholders, not f-strings, in log message arguments — the formatter needs structured args for future JSON output.
    `tap/logging.py` builds settings.LOGGING and runs the site-token scanner (format + within-file hex uniqueness, baseline-ratchet) enforced by tap/tests/test_log_site_ids.py; see specs/spec-tap-logging.md for the full convention.

Testing Framework
    pytest with Django integration
    Factory-based test data generation
    Separate functional and unit test suites
    Write unit tests for new features where behavior is well-defined
    Test both positive and negative scenarios
    Tests should accompany new functionality where behavior is clear.
    Test behavior, not implementation
    Application-level tests for TAP-managed node/edge behavior should prefer service-layer setup over direct ORM writes.
    Direct ORM setup in tests is appropriate only when intentionally testing model-level or below-service-layer behavior.

Django Best Practices
    Follow Django's "batteries included" philosophy - use built-in features before third-party packages
    Prioritize security and follow Django's security best practices
    Prefer ORM for standard operations and data models; use raw SQL or CTEs where graph traversal or performance requires it.
    Use Django signals sparingly, require approval before writing them, and document them well.
    Background tasks must not silently mutate core graph state in v0; all graph mutations must remain explicit and auditable.
    For TAP-managed graph data, prefer the service layer over ad hoc ORM mutation even when the ORM would be simpler in the moment.

Authentication & Authorization
    Use Django’s built-in authentication system
    Use a custom User model extending AbstractUser
    Do not implement custom authentication logic without explicit instruction
    Authorization should use Django permissions or explicit checks; avoid ad-hoc logic

Templates
    Use template inheritance with base templates
    Use template tags and filters for common operations
    Use static files properly with {% load static %}
    Implement CSRF protection in all forms

Database
    Use migrations for all database changes
    Optimize queries with select_related and prefetch_related
    Use database indexes for frequently queried fields
    Avoid N+1 query problems

Development Environment
    Python 3.14+ required
    UV for dependency management (use uv add/uv remove - NEVER use pip directly)
    Single Docker for all services (Django, Postgresql)
    Virtual environment automatically created in .venv/
    Follow PEP 8 with 120 character line limit
    Use environment variables in a single settings.py file
    Never commit secrets to version control

Development Commands
    # Images: spawn (the single entry point; stand-up.sh retired 2026-08-09) PULLS the
    # published ghcr.io/unified-systems-com/tap-web + tap-db
    # (anonymous, multi-arch, pre-compiled wheel cache inside — no local compile). Rebuild locally
    # only when changing the Dockerfiles: scripts/dc build web (this shadows the published
    # tag on your host until the next scripts/dc pull web). See publish-images.yml.
    # The base compose file is PULL-ONLY: `up` hard-fails on a missing pinned tag instead of
    # silently building. Building is opt-in via the docker-compose.build.yml overlay, which
    # `scripts/dc build` stacks automatically (`up -d --build` no longer builds TAP images).

    # Start all services
    docker compose up

    # Start services in background
    docker compose up -d

    # Stop services
    docker compose down

    # Run Django management commands
    docker compose exec web uv run python manage.py <command>

    # Run tests — use the parallel lanes (scripts/test), NOT bare pytest.
    scripts/test              # FULL lane (-n auto, incl. gryphon corpus + coverage guards); the promote gate, ~9-10 min
    scripts/test --fast       # INNER-LOOP lane (skips the gryphon corpus)
    scripts/test <args...>    # extra args pass through to pytest, e.g. scripts/test --fast tap_web
    # Single-test debugging: bare (serial) pytest avoids the xdist worker/DB startup tax:
    scripts/dc exec web uv run pytest tap/tests/test_x.py::test_y

    # Linting and formatting
    docker compose exec web uv run black .
    docker compose exec web uv run ruff check --fix .
    docker compose exec web uv run mypy .

    # Create migrations
    docker compose exec web uv run python manage.py makemigrations

    # Apply migrations
    docker compose exec web uv run python manage.py migrate

    # Seed plugin data (required after migrate — plugins no longer auto-import in ready();
    # see req-tap-plugin-load-v0-ready-readonly. Spawn script does this automatically.)
    docker compose exec web uv run python manage.py import_plugin_grift --all

    # Create superuser
    docker compose exec web uv run python manage.py createsuperuser

    # Open Django shell
    docker compose exec web uv run python manage.py shell

    # View logs
    docker compose logs -f web

Multi-session worktrees
    Worktrees under /Users/george/tap-sessions/<label>/ are isolated Compose stacks.
    Per-session config lives in .env.local (COMPOSE_PROJECT_NAME, WEB_PORT, POSTGRES_PORT, TAP_GRID_ID).
    Always use `scripts/dc` instead of `docker compose` directly — it merges .env + .env.local
    so commands target this session's containers, not the primary `tap` stack on 8000/5432.
    Lifecycle scripts (canonical implementations of the multi-session workflow):
        scripts/spawn-session.sh          — create a new session worktree + Compose stack
        scripts/despawn-session.sh        — tear it down
        scripts/promote-to-main.sh        — promote this session via PR (pre-push merge + local fast lane + PR + server gate incl. CI boot gates + auto-merge + main sync); direct atomic push survives only as the bootstrap/skip-hatch path
        scripts/promote-all-sessions.sh   — run promote-to-main.sh across every session in the registry
    When the user says "consolidate sessions", "ship the sessions", or otherwise asks to advance
    origin/main from session branches, run the promote scripts rather than retyping the git steps.
    AI-REVIEW TRIAGE: every PR gets an automatic Copilot review ~2 min after open; whoever opens a
    PR runs scripts/pr-review-triage <pr> [--wait] and reads the feedback (INCLUDING suppressed
    findings) before calling the work done — fix-worthy findings push onto the PR branch, noise is
    dismissed consciously (req-dev-multisession-push-workflow).
    SECOND ROAD (since the main-required-checks ruleset): a change whose only consumer is a
    pending gated PR (Renovate bounds/config, dep baselines) should be pushed onto THAT PR's
    branch — one gate pass instead of three serialized ones. See "The second road" in
    spec-dev-multisession.md (req-dev-multisession-push-workflow).
    DOCS/SPECS SHORTCUT (2026-08-10): every change rides a PR; the change tier decides the
    battery (scripts/change-tier, req-dev-validation-product-line-lanes-7). Docs-tier PRs
    (docs/, plan/, root *.md) gate in ~1 min (no lanes, no boot); specs-tier adds only the
    test_all lane. The old docs-only direct FF push is RETIRED as an everyday path
    (req-dev-multisession-push-workflow-7) — direct push is bootstrap/skip-hatch only.
    See spec-dev-multisession.md for port bands, spawn/despawn, and the push workflow.
    Advancing origin/main is gated on validation (req-dev-multisession-promote-gate ↔
    req-dev-validation-promote-hook): the dev-validation gate runs after the pre-push merge,
    before the atomic push; red aborts the promote. spec-dev-validation.md is the center of
    gravity for validation tracking — its Validation Map is the authoritative inventory of
    every validation surface + honest guard status; adding a validation surface anywhere
    requires adding its Map row in the same change. The gate is LIVE server-side (2026-08-10):
    cold-boot + lean-boot run as REQUIRED CI jobs under the `gate` check (product-lines.yml);
    the promote's local boot-gate runs are optional fast feedback (TAP_PROMOTE_LOCAL_BOOT_GATES=1,
    automatic when the server gate is inactive).

Contribution & security policy (DCO, SECURITY.md, OpenSSF — 2026-08-10 wave)
    SECURITY.md (repo root) is the published vulnerability policy: private reporting via GitHub
    PVR, 7-day ack / 14-day assessment, coordinated disclosure. The org-wide default lives in
    unified-systems-com/.github; PVR is enabled on every active org repo. The first product
    release MUST update its supported-versions statement (req-cicd-product-releases-2).
    DCO sign-off: .githooks/prepare-commit-msg auto-appends the committer's Signed-off-by to
    every non-merge commit (hooksPath is wired at spawn). Leave the trailer in place; merge
    commits are exempt; never hand-author a sign-off for someone else — it certifies the human
    committer. scripts/check-dco verifies trailers (REPORT-ONLY today) in the promote's local
    gates and the product-lines `dco` CI job; bot-authored dependency commits (renovate/
    dependabot) are exempt — a maintainer certifies those at squash-merge. Enforcement
    (TAP_DCO_ENFORCE=1 in both invokers) flips in the SAME change that lands CONTRIBUTING.md +
    the DCO file at repo root (in legal review as of 2026-08-10). Do not flip it early.
    OpenSSF Best Practices: bestpractices.dev project 14019, badge in the README. The criteria
    decisions are spec canon — req-cicd-dco-signoff, req-cicd-product-releases,
    req-tap-test-accompaniment — keep them aligned when touching those surfaces.

Developer token tools (use these instead of hand-rolling identifiers)
    scripts/uuid7 [N]          — mint UUIDv7(s) (e.g. record_* call-site IDs, entity IDs)
    scripts/log-site-id [N]    — mint collision-checked `[<hex>]` log site token(s)
                                 (req-tap-logging-site-ids). Run this when adding any
                                 logger.* call rather than guessing a hex by hand.
    scripts/implements-tag <rid> [role]
                               — mint an implementation claim declaring that a function IS
                                 the authoritative derivation of a requirement's fact
                                 (req-tap-traceability-minting). Roles: derivation |
                                 enforcement | surface. Claims fingerprint BOTH ends
                                 (@<spec-hash>/<code-hash>); mint emits a code-hash
                                 placeholder — paste, then --resync <path> stamps it (an
                                 unstamped claim fails the guard). Also --check (list
                                 malformed / unresolvable / stale / drifted claims) and
                                 --resync <path> (re-stamp after a reviewed spec or code
                                 change). Never hand-type a hash.

Documentation (specs ↔ docs alignment)
    Specs (specs/, <app>/specs/) are authoritative for behavior. Docs (docs/) are derived how-to surfaces.
    See specs/spec-docs.md for the full documentation system contract.

    Naming:
        Doc files: docs/doc-<system>-<name>.md (doc- prefix on the filename)
        Doc-owning specs: specs/spec-<system>-<doc-name>-doc.md (-doc suffix on the spec filename)

    Drift prevention — when editing a SPEC:
        1. Search docs/ for any reference to the requirement RID(s) you are changing:
               grep -r "req-example-name" docs/
        2. Read each hit. If the doc no longer matches behavior, update the doc in the same PR.
        3. Doc-only commits when the doc change is independent of behavior; bundled commits when paired with a behavior change.

    Drift prevention — when editing a DOC:
        1. Read its frontmatter `spec:` and skim its `covers:` list.
        2. Confirm the procedure / claims still match what the linked specs require.
        3. If a referenced requirement has changed, update the doc; if the doc-spec's `update-triggers:` list is incomplete, expand it.

    Versioning:
        last-edited and version are derived from git (git log -1 --format=%cI / %h <file>); never store these in a doc.
        last-reviewed is NOT used; the git log is the source of truth.

    See req-docs-drift-conventions and req-docs-change-history in specs/spec-docs.md.
