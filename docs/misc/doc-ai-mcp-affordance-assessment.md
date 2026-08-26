---
spec: ../../specs/spec-ai-integration.md
audience: [developer, llm]
covers:
  - ../../specs/spec-ai-integration.md
  - req-ai-roles
  - req-ai-machine-legible
  - req-ai-readonly-v0
update-triggers:
  - The demand signal arrives (an adopter asks to point their assistant at TAP) — this doc becomes the plan skeleton
  - tap_api grows token auth — re-check the auth section, it is the load-bearing gap
  - req-ai-surface (internal Claude surface) starts building — align the two so they share the service-layer read path
---

# MCP affordance assessment — a first-class outside-AI surface for TAP

**Status: ASSESSMENT ONLY (2026-08-25, George's ask, ahead of the demand signal). Nothing here
is built or scheduled; this is the thinking, banked.**

## Where the application is (the relevant inventory)

- **Service layer is the canonical read path**, capability-gated under `policy.can`, with caller
  context and named actors. Reads are already authorization-shaped for a non-human principal.
- **`grid.discover` exists**: registry-backed discovery publishing schemas and capabilities for
  every TAP-managed node/edge type. This is the machine-legible affordance
  (`req-ai-machine-legible`) that makes an MCP surface cheap — tool definitions can be
  **derived from discovery, not hand-authored**, so new plugin types appear as tools with zero
  MCP-side code.
- **Gryphon** gives structured, safe graph search (compiled to ORM, hardened: field-path
  allowlist, least-priv role, resource GUCs) — a ready-made "query the graph" tool that is
  already defended against hostile query shapes.
- **`tap_api`** mounts versioned Ninja routers; plugins register under
  `/api/v1/plugins/<slug>/`. **Auth is session-only**; `tap_api/auth.py` names token auth as
  its single evolution point. This is the one real gap (below).
- **`tap_ai` is unbuilt** (the sixth scaffolding app; `req-ai-surface` Proposed). Canon already
  names the external role: "a partner's AI reaching TAP through an API/MCP surface — named;
  deferred" (`req-ai-roles`). This assessment is that deferred branch, thought through.
- **Doctrine already decided the hard questions**: `req-ai-readonly-v0` (In Force) — no writes;
  named actor, never `User=None`; bounded capability set, no god-bit; fine-grained-capabilities
  standard; email-is-not-identity.

## What the affordance is

An MCP (Model Context Protocol) server presenting TAP to any MCP-speaking assistant (Claude,
IDE agents, adopters' own tooling) as typed tools + resources. The natural v0 tool set, all
read-only:

| Tool | Backing surface | Note |
| --- | --- | --- |
| `discover_types()` / `describe_type(name)` | `grid.discover` | The self-describing entry point; everything else hangs off it |
| `search(query)` | Gryphon | Already hardened for untrusted query shapes |
| `get_entity(id)` / `get_edges(entity, ...)` | service-layer reads | Dimension/capability-scoped like any caller |
| `get_spec(rid)` / `list_requirements(...)` | specs + traceability index | The same derivation the AI-review context design wants (parked spec section awaiting review — tap#164; build tracked in tap#161) — build once, two consumers |
| `health()` | tap_health | Read-only operational picture |

Resources (MCP's document-shaped side): spec files, docs, boot profiles — the already-public,
already-reviewed canon.

## Recommended shape: thin server, API client, packaged as a plugin

Three candidate architectures, one clear winner:

- **(A) In-process MCP mounted inside Django** — shortest path to a demo, worst trust story:
  the MCP layer sits inside the app with ambient access, and every capability boundary has to
  be re-proven inside the mount.
- **(B) Thin standalone MCP server that is an ordinary TAP API client** — RECOMMENDED. It
  holds a scoped token for a named machine actor and calls the same `/api/v1/...` endpoints
  every human and script uses. The outsider doctrine applied to machines: the AI gets no
  special path, so the API's authz, rate limits, and audit trail all apply automatically, and
  anything the MCP server can't do through the API is a *gap in the API*, found early.
  Packaged as a TAP plugin repo (`tap-plugin-mcp` or similar) for distribution/versioning,
  runnable as `stdio` (local assistant) or streamable-HTTP (remote) — the transport is
  config, not architecture.
- **(C) Build it inside `tap_ai`** — conflates the internal Claude-backed reasoning surface
  (`req-ai-surface`, TAP calls a model) with the external affordance (a model calls TAP).
  They share the service-layer read path but are opposite directions; keeping them separate
  keeps both honest.

## The load-bearing gap: machine credentials

Everything above exists or is derivable **except** the token. `tap_api` is session-auth only,
and the IdP is passkey-primary for humans. An MCP server needs:

1. A **named machine actor** (program principal, not a shadow human) with a bounded read-only
   capability set — the `req-ai-readonly-v0` actor made real.
2. A **token mint + revoke affordance** at `tap_api/auth.py`'s named evolution point (bearer
   token bound to that actor; scoped, expiring, revocable; a `/manage-secret` conversation and
   a spec amendment, not just code).

This is roughly half the total effort and ALL of the security review. It is also generically
valuable — the first machine credential story serves CI consumers, partner integrations, and
the internal AI surface alike. If pre-building anything ahead of demand, build this seam.

## Feasibility and effort

George's guess ("pretty straightforward") is right, with the auth caveat:

- **Token/machine-actor story**: 1–2 sessions + security review. The hard, load-bearing half.
- **MCP server itself**: 1–2 sessions. The Python MCP SDK makes the server trivial; the
  discovery-derived tool list is the only interesting code, and it's a loop over
  `grid.discover` output.
- **Spec + docs + a get-started skill** (AI-operable per `req-ai-operable-procedures`): 1 session.

Call it ~4 focused sessions end-to-end, half of which (auth) is reusable infrastructure.

## Benefit

- **The demand-signal answer**: when an adopter asks "can I point Claude at my TAP?", the
  answer is a config block, not a project. The ask will arrive suddenly (Sam-shaped or
  prospect-shaped); this doc converts it from research into execution.
- **Player-3 made tangible**: TAP's differentiator is machine-legible declarative metadata;
  MCP is the standard socket that lets the outside world *feel* that. `discover_types` →
  every registered type self-describes to any assistant — that demo writes itself.
- **Internal reuse**: the AI-review context work (scoped-retrieval phase of the parked context spec, tap#161/tap#164) wants
  `get_spec(rid)`; the verdict-ledger names an internal-security-AI consumer; the radar's
  grid-representation blast-radius tools want graph queries. One affordance, several named
  consumers — `req-ai-name-the-consumer` satisfied in plural.
- **Dogfood asymmetry**: cheap-edge doctrine says lay the read-only affordance while the API
  surface is still small; retrofitting AI-legibility after the API grows is the expensive path.

## Risks, named

- **Injection/read-abuse**: an assistant wired to TAP reads attacker-influenceable graph data
  (collector-ingested content). Read-only scoping caps blast radius at disclosure;
  per-dimension capability scoping caps disclosure at the actor's grant. The MCP server adds
  no write path in v0 by canon (`req-ai-readonly-v0`).
- **Token hygiene**: a leaked machine token = read access at the actor's scope. Mitigations
  are the standard ones (scoped, expiring, revocable, secrets-subsystem storage) — and the
  reason auth is the half that needs the review.
- **Surface drift**: derived-from-discovery tools can't drift; hand-authored extras can. Keep
  hand-authored tools to the named few (search, spec reads, health).
- **v0 scope pressure**: the first "can it also create...?" request must route to the named
  future (service-layer writes under a delegated actor, `req-ai-agentic-future`), not into
  the MCP server.

## Verdict

High-feasibility, high-leverage, cleanly aligned with standing canon — and correctly parked
until the demand signal. The one seam worth building speculatively ahead of demand is the
machine-credential story at `tap_api/auth.py`, because it is the long pole, it needs the
security conversation, and every future machine consumer (not just MCP) rides it.
