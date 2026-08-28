# TAP — The Analogy Platform

[![gate](https://github.com/unified-systems-com/tap/actions/workflows/product-lines.yml/badge.svg?branch=main)](https://github.com/unified-systems-com/tap/actions/workflows/product-lines.yml)
[![License](https://img.shields.io/github/license/unified-systems-com/tap)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.14%2B-blue)](pyproject.toml)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14019/badge)](https://www.bestpractices.dev/projects/14019)

TAP is a general-purpose platform for mastering the systems you are responsible
for — accounts, pipelines, fleets, data flows, the organization
itself — by modeling each as a live, queryable, visual representation called **the grid**:
nodes and edges fused with dimensions, batches, history, and field-level provenance,
so the model stays explainable as it changes.  
  
[TAP in two pages](docs/doc-tap-intro.md) is the fastest way in.

The grid is designed for humans and AI agents working together.  
  
The system lives in the battle-tested PostgreSQL database, is queried through
**Gryphon** (TAP's grid query language), data is exchanged as **GRIFT** files (its JSON graph
format), and functionality can be extended  through **plugins** — core speaks no domain language;
every vocabulary arrives as a plugin. 


> **Read this before you build on it.** TAP is maintained by one person. It runs
> daily against real infrastructure, so it works — but for you that means
> features arrive when they serve that use, issues are read but not always
> answered quickly, and more proposals are declined than accepted. That is not
> reluctance; it is the honest review capacity of a project this size. If you need
> a vendor with a queue behind it, this is not that yet. If you want to use it
> anyway, or push on it, that is genuinely wanted —
> [open an issue](../../issues), and read [CONTRIBUTING.md](CONTRIBUTING.md)
> first, because it starts with an issue.

## Get it running

You need **git**, **Docker** (Desktop on macOS; Engine + the Compose v2 plugin on
Linux), and any **python3** on the host. 
  
  Linux users: read
[Host prerequisites (Linux)](docs/misc/doc-dev-multisession-onboarding.md#host-prerequisites-linux)
first — it covers the docker group, ports, and two known papercuts.

```bash
mkdir -p ~/tap-sessions
git clone <this repository> ~/tap-sessions/main
cd ~/tap-sessions/main
scripts/spawn-session.sh dev        # any session name you like
```

That's the whole procedure — first boot and every later session are the same
command. The script checks your host, creates an isolated session worktree at
`~/tap-sessions/dev`, pulls the published images (anonymous, multi-arch, with the
FIPS-validated OpenSSL provider and pre-compiled Python wheels baked in — offline or
unpublished it falls back to a local build, which compiles those from source in
10–20 minutes), boots the instance, and prints your URL and admin credentials.
Sign in with the password from the worktree's `.dev-credentials`, then enroll a
passkey from your session if you want one. Your next concurrent session is just
`scripts/spawn-session.sh <another-name>`.

The `~/tap-sessions/main` location matters: sessions are git worktrees beside it,
and the tooling standardizes on that layout (the script checks, and tells you how
to adopt it if you cloned somewhere else).

Profiles that pull live data declare the credentials they need
(`required_secrets` in the boot profile), and the boot preflight checks the
declarations in seconds — naming exactly what's missing or dead before anything
expensive runs, with the verdict persisted to `logs/boot/latest.boot-record.json`.
Your AI assistant closes the gaps with `/provision-secrets`, which reads the same
declaration and routes each credential to its plugin's canonical setup docs. The
default `core_dev` profile needs no credentials at all.

**The easier way: let your AI assistant drive.** Open an AI coding assistant in the
clone (Claude Code, or anything that reads this repo) and ask it to get TAP running —
the `/get-started` skill walks it through host prep, the choices, the run, and the
first login, and it can diagnose anything that goes wrong. This repo treats AI
assistants as first-class operators: skills under `*/skills/` are step-by-step
procedures written for them.

Day to day: 
- `scripts/dc up -d`
-  `scripts/dc down`
-  `scripts/dc logs -f web`.
  
All of these run from inside a session worktree (`~/tap-sessions/<name>`).
To pick up new code, spawn a fresh session from the updated main
(`git -C ~/tap-sessions/main pull`, then `scripts/spawn-session.sh <new-name>`) —
sessions are cheap and disposable (`scripts/despawn-session.sh <name>`).

## Build your own plugin

Everything domain-specific in TAP is a plugin — node and edge types, collectors that
pull real data in, pages and panels that show it. Ask your assistant to run
`/new-plugin`, or start from `tap_plugins/specs/spec-tap-plugin-external-development.md`,
which is the contract for developing plugins against this repo as your harness.
Boot profiles (`boot/*.boot.json`) declare which plugins an instance runs and where
they install from; a plugin can also ship its own boot records and be stood up
directly from its repository with `spawn-session.sh --from <pointer>` — each such
plugin's README is the front door for running it.

## What TAP is not

We put as much thought into what this excludes as into what it includes.

- **Not a SIEM or a log pipeline.** The grid holds structure, state, and how they changed. It
  is not built to swallow event streams at volume.
- **Not an agent you install on hosts.** TAP observes by collecting from APIs it is given
  credentials for. Nothing is deployed into what it watches.
- **Not a remediation tool.** TAP does not act on your accounts. Reconciling an absence is a
  grid-side operation — a node is marked gone in the model, and nothing is deleted anywhere else.
- **Not a GRC system.** TAP models systems and can produce evidence about them. It is not a
  policy library, a control catalogue, or an audit workflow. Compliance products built *on* TAP
  are products; none of that vocabulary belongs in core.
- **Not a CMDB you maintain by hand.** Everything in the grid arrived from an observation with
  provenance attached. There is no form to fill in.
- **Not domain-aware.** Core speaks no domain language and never will. AWS, GitHub, and
  everything else arrive as plugins — including ours.
- **Not multi-tenant SaaS.** You run it. It is yours.
- **Not a general-purpose graph database.** Gryphon queries the grid. It is not competing with
  Neo4j for arbitrary graph workloads.

## Versioning

TAP is pre-1.0 and will stay there for a while. That is not a statement about quality — it runs
daily against real infrastructure. It is a statement about which surfaces are still moving.

**The care taken over a breaking change is proportional to how much real use the surface has, not
to the version number.** A change that would break a known adopter is handled carefully whether or
not the major version says it may be.

Surface by surface:

- **Your grid data survives.** Every schema change ships with a migration.
- **GRIFT and Gryphon are the most stable things here.** They are vocabulary, and vocabulary is
  the asset that compounds while being copied. Breaking either is a last resort and gets a
  deprecation cycle.
- **Plugin interfaces move.** Manifest shape, registration, lifecycle hooks. Plugins declare what
  they were built against via `requires_tap`, so a plugin that pins honestly refuses to boot
  rather than failing strangely.
- **Internal Python APIs are not an API.** Anything not documented as an interface can change
  without notice.

Breaking changes carry `!` in the commit and appear in [CHANGELOG.md](CHANGELOG.md). 1.0 arrives
when the plugin interface has gone a full release cycle without one — a condition, not a date.

## Contributing

Issues and pull requests are welcome — [CONTRIBUTING.md](CONTRIBUTING.md) covers the
process, the contribution terms (this project uses the
[Developer Certificate of Origin](DCO), not a CLA — sign off with `git commit -s`), and
the test and code-quality bar every change is held to. Found a security problem? Do not
open a public issue — follow [SECURITY.md](SECURITY.md).

How decisions get made — and what to do if you disagree with one — is in
[GOVERNANCE.md](https://github.com/unified-systems-com/.github/blob/main/GOVERNANCE.md).
Participation is governed by our
[Code of Conduct](https://github.com/unified-systems-com/.github/blob/main/CODE_OF_CONDUCT.md).
Both are org-wide: they live in `unified-systems-com/.github` and apply to every
repository in the organization, this one included.

## Interfaces

Each of TAP's external interfaces carries reference documentation:

- **HTTP API** — the interactive OpenAPI reference is generated from the code and
  served by every running instance at `/api/v1/docs` (machine-readable spec at
  `/api/v1/openapi.json`).
- **GRIFT**, the JSON graph exchange format — defined by its JSON Schema,
  [`tap_grid/schemas/grift-document.schema.json`](tap_grid/schemas/grift-document.schema.json),
  with behavior contracts in `tap_grid/specs/spec-grift-*.md`.
- **Gryphon**, the grid query language — the formal grammar is
  [`tap_grid/gryphon/grammar.lark`](tap_grid/gryphon/grammar.lark); its behavior
  contracts live in `tap_grid/specs/`.

## Finding your way

| Where | What |
| --- | --- |
| [`docs/doc-tap-intro.md`](docs/doc-tap-intro.md) | TAP in two pages — start here |
| `architecture.md` | The architectural contract behind it |
| `AGENTS.md` / `CLAUDE.md` | Orientation for AI assistants working in this repo |
| [`GOVERNANCE.md`](https://github.com/unified-systems-com/.github/blob/main/GOVERNANCE.md) | Who decides what, how a decision becomes binding, and what happens when the maintainer stops (org-wide) |
| [`CODE_OF_CONDUCT.md`](https://github.com/unified-systems-com/.github/blob/main/CODE_OF_CONDUCT.md) | Expected conduct, and where to report a problem (org-wide) |
| `specs/`, `<app>/specs/` | Behavior contracts — the canonical source of truth |
| `tap_grid/` | The graph core: entity spine, edges, service layer, Gryphon, GRIFT |
| `boot/` | Boot profiles — what an instance installs and seeds |
| `*/skills/` | AI-operable procedures (get started, provision secrets, add a model, build a collector, …) |

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
