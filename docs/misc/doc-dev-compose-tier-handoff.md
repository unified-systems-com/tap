---
title: Compose Tier — Image-Native Standup Handoff
date: 2026-08-10
status: handoff
audience:
  - llm
  - developer
related_docs:
  - docs/misc/doc-dev-multisession-onboarding.md
  - docs/misc/doc-plugin-boot-install-handoff.md
related_specs:
  - specs/spec-tap-boot-bootstrap.md
  - specs/spec-tap-boot-v0.md
  - specs/spec-dev-multisession.md
  - specs/spec-fips.md
---

# Compose Tier — Image-Native Standup Handoff

Handoff from a strategy conversation (2026-08-10, session samsite). No code changed; this
records an assessment of a proposed distribution tier so a later session can build it against
a clean context budget, when demand shows up.

**The proposal:** with the GHCR-published images, ship a "compose tier" — a TAP instance that
stands up from the published `tap-web`/`tap-db` images plus a boot profile passed at launch,
with plugins git-installed from their own repos at boot. No repo clone, no spawn-session.
Getting the latest core = pull the new image and cycle the web container in place; the
database volume persists. End state: a plugin repo ships its **own** `docker-compose.yml`
that pulls the published images and boots directly — the file you send an early adopter
instead of "clone our repo."

## Assessment: ~90% of this already exists

Verified against `Dockerfile`, `docker/entrypoint.sh`, `docker-compose.yml`, and
`boot/samsite.boot.json` as of 2026-08-10:

- The published `tap-web` image bakes the **full source tree** (`COPY . .`), the lockfile,
  and the pre-compiled wheel-cache seed (`/opt/uv-cache-seed`). The "50MB dependency hit"
  is already gone: the entrypoint's `uv sync` builds the venv from cached wheels in seconds.
- The **entrypoint already runs the whole standup in-container**: seed uv cache → `uv sync`
  → FIPS self-check → **pre-boot** (`tap/preboot.py` reads the boot profile as plain JSON
  and git-installs its declared plugins; idempotent — a reboot is a fast no-op, no re-pull)
  → FIPS crypto-BOM scan of what actually got installed → pre-migrate snapshot (defaults on
  outside dev) → migrate → serve.
- The DB is a separate container on the `postgres_data` named volume. **Cycle-in-place
  works as imagined**: pull new image, recreate web, migrations run on the way up, data
  persists. The `requires_tap` floor / boot-record-as-BOM contract (the "two mains" model)
  is exactly the compatibility check for "new core under pinned plugins."
- Plugin installs land in the venv, which is a **named volume** — they survive container
  cycles, and `uv sync` + idempotent pre-boot reconcile it against a new image on the way up.
- The samsite boot record ships **in the plugin repo** (`req-boot-bootstrap-records-in-package`)
  with `required_secrets` riding the record so preflight provisioning works wherever it is
  fetched from (`req-boot-required-secrets-6`). The record's install entries are all
  pinned immutable tags from the plugins' own public repos.

## The four gaps (the actual work of the tier)

1. **Dev bind mount vs. baked code.** The dev compose bind-mounts `.:/app` (and the
   entrypoint) over the baked source — that's what makes it a dev tier. The compose tier is
   a compose variant that **omits the source + entrypoint bind mounts** so the image's baked
   code runs. The image needs nothing new.
2. **Stage-0 pointer fetch is host-side.** `spawn --from` resolves the bootstrap pointer,
   verifies the declared sha256, and stages the record into the worktree's `boot/`
   (`spec-tap-boot-bootstrap.md`). Without a worktree, this moves in-container — e.g. a
   `TAP_BOOT_POINTER` env var the entrypoint resolves before pre-boot — **or** the record is
   bind-mounted from the plugin repo checkout that carries the compose file (which sidesteps
   the gap entirely for the plugin-ships-compose case).
3. **Population is host-side.** `manage.py boot` (GRIFT seed + fire collectors) runs at
   spawn time, not in the entrypoint (deliberate; see the entrypoint comment). A
   self-contained container needs it in the startup path (idempotence guard required) or as
   a documented one-time `exec` step.
4. **Cache-seed refresh is first-boot-only.** The wheel seed copies into the `uv_cache`
   volume only when that volume is **empty**. After an image update the old cache persists,
   so wheels new to the updated lock download from the network instead of the fresh seed.
   Cosmetic (slower first cycle after an update, needs network) — but don't promise
   "instant" cycles until the seed-refresh logic compares versions instead of testing
   emptiness.

What does NOT carry over from spawn: worktrees, port bands, session registry, branch
hygiene, host-readiness battery — all dev-multisession machinery that has no meaning in this
model. What DOES still need a home: secrets preflight UX (`/provision-secrets` flow), and
first-login passkey bootstrap. Those are the pieces a "clone nothing, just
`docker compose up`" adopter experience needs containerized or wrapped in one small script.

## Ecosystem comparison (what's standard out there)

Three patterns dominate plugin-based open-core projects shipped on Docker:

- **Declare-at-launch, runtime install.** Grafana is canonical
  (`GF_INSTALL_PLUGINS=a,b,c`, downloaded at container start into a volume); Nextcloud,
  Mattermost, n8n community nodes, Home Assistant/HACS all live here. Fast and flexible;
  weak reproducibility (unpinned drift) and a boot-time network dependency.
- **Derived-image bake.** Keycloak (provider JARs + `kc build`, ship your own image),
  Airflow/Superset (extend the image with pip installs), Backstage (compiled in).
  **Discourse is the most instructive**: a declarative `app.yml` listing plugin *git repos*
  and a launcher that rebuilds the image from it — the closest existing analog to the TAP
  boot record. Immutable and supply-chain-auditable; every plugin change is an image build.
- **Plugin-as-container.** Airbyte connectors. Heavier isolation than TAP needs.

Consensus mechanics TAP already matches: stateless app container, DB on its own volume,
migrations run by the entrypoint on start. The industry arc: mature projects start at
pattern 1 and push production users toward pattern 2 for reproducibility.

**TAP's position is a defensible middle**: runtime install, but from pinned tags, through
a sha256-verified pointer, with the boot record as an explicit BOM and the FIPS crypto-BOM
gate scanning what actually got installed. That recovers most of what normally forces the
bake. (Honesty note: the install entries' tags are immutable by *policy*, not proof — a
git tag can be re-pointed. `req-boot-bootstrap-install-commit-pin` in
`specs/spec-tap-boot-bootstrap.md` is the named fix: a `commit` field beside the tag that
preboot installs from (so a re-pointed tag cannot change the code) and reports tag drift
against as a security Flaw — built 2026-09-17, tap#512 — and that becomes mandatory
(tap#514) by the time this tier ships.) The plugin-repo-ships-compose idea is itself the standard third-party dev
pattern — Grafana's `create-plugin` scaffold generates exactly that (a compose file pulling
the stock vendor image with the plugin wired in).

## Deferred, demand-driven follow-on

An optional **bake path** — boot record → derived image (Discourse-launcher-shaped) — for
airgapped / FedRAMP-strict deployments. It also makes the FIPS artifact statically
auditable: with runtime install, the deployed artifact's crypto providers vary per boot and
the crypto-BOM gate covers it dynamically; a baked image fixes them at build. Do not build
this until a deployment demands it.

Also deferred: a migration lock / single-runner story for entrypoint-run migrations if the
tier ever runs multiple web containers against one DB. Fine as-is for single-container.

**Required before this tier ships** (not merely deferred):
`req-boot-bootstrap-install-commit-pin` — commit-pinned install entries. The compose tier
installs plugins from records fetched over the network with no developer in the loop, which
is exactly when a mutable tag ref is most dangerous. Installing by `commit` is built
(tap#512); what this tier still needs is `commit` required on every entry (tap#514).

## Sequencing (center-of-gravity note)

The compose tier is the right **next** increment on the adopter path, not the current one.
The two proven spawn commands (2026-08-10, samsite pointer pinned @v0.2.2) already serve the
live adopter conversation. Build the compose tier **when a real adopter balks at the repo
clone**, and let their friction decide how much of population / secrets preflight / passkey
bootstrap moves in-container — rather than speculatively building the full self-contained
runtime. The minimal first cut is small: a runtime-mode compose file in the samsite repo
(no bind mounts, record bind-mounted from the checkout, volumes + secrets mount declared)
plus containerized population.
