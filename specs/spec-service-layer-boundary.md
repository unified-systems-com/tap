# Service Layer Boundary

## Philosophy

This spec is a standing **convention**: it defines the repeatable process by which a
TAP *service layer* is separated into a guarded public surface and below-gate
implementation, so the layer is a real trust boundary rather than a loose collection of
functions. It is owned here, at the top level, and **instantiated by consumers** — the
grid service layer (`tap_grid.services`) is the reference instance today; app service
layers (`tap_auth`) and plugin service layers are the next adopters. Each consumer
*applies* this convention; it does not re-derive it.

A "service layer" in TAP is the front door to something protected — the graph, an app's
data, a plugin's data. It's only a real *boundary* when two things are both true:

> **1. Public and private are split by file, not by habit.** The public operations live in
> the gateway; the implementation lives in `_`-prefixed modules the outside world can't
> reach. You can tell what's public by where it lives, not by reading every function.
> **2. Every public operation checks permission first.** Each operation the gateway
> exposes runs a capability check before it touches the resource — and that check sits on
> the gateway, in one place, so it can't be forgotten one call site at a time.

The rule that keeps this honest: **the boundary is enforced by structure, not by
vigilance.** Nobody should have to *notice* that a new function forgot its gate — the file
layout plus a mechanical guard make the omission fail the build. (Same instinct as
`spec-tap-callsite-identity.md` — trust a structural fact over a declaration you can pad —
and `spec-security-posture.md` — make the safe path the default.)

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | One Separation Process | Every guarded service layer separates the same way — public gateway + below-gate implementation, one-way import. |
| 2. | Contract At The Surface | Cross-cutting contracts (authz first) are asserted on every public entry point, not scattered per callsite. |
| 3. | Enforced By Structure | A mechanical, reusable guard fails a new ungated public entry — the boundary can't erode by omission. |
| 4. | Reusable, Not Copied | Consumers adopt one shared mechanism; the pattern does not fork per app. |

## Prior Art

A prior-art pass (2026-07) places this convention on established practice. The direct
analogs, and where TAP diverges:

- **Architectural fitness functions / boundary linters.** The reusable guard is a
  *fitness function* — an executable architecture rule that fails the build on violation.
  Ecosystem tools: **import-linter** (Python; architecture "contracts" in a central config
  file), **Tach** (Python; each module *declares its own public interface* + visibility),
  **ArchUnit** (Java), **dependency-cruiser** (JS), **NetArchTest** (.NET), **depguard**
  (Go). Two discovery models recur: a *central contract config* (import-linter) vs a
  *per-module marker declaring its interface* (Tach). TAP takes neither wholesale: it uses
  **convention-driven, fail-closed discovery** with a per-boundary zone marker
  (`req-service-boundary-discovery`), because an opt-in central list is forgettable and a
  forgotten entry silently unprotects a boundary.
- **`__all__` is a convention, not a lock.** Python's own guidance is explicit that
  `__all__` is a public-API *documentation/convenience* boundary — it governs `import *`
  and tooling, not reachability or access control. This is exactly why the export contract
  is **union, not substitution** (`req-service-boundary-export`): the enforcement floor is
  structural; `__all__` is the reviewable manifest layered on top, never the thing that
  decides what is enforced.
- **Authorization Facade / API-gateway edge authorization.** Centralizing authorization at
  a single facade or gateway — so downstream operations are not each individually
  responsible for access control — is a named pattern in microservice/API-gateway
  architecture. The guarded service layer is its **in-process** form: the gateway is the
  one place the capability check is asserted.
- **Capability-based security.** TAP's capability gates are capability-based access control
  (grant the specific capability an operation needs), which recent analysis notes suits
  agent-driven systems better than role-based control — apt for a codebase authored largely
  by agents.
- **Ports-and-adapters / hexagonal + facade.** The gateway is the *port* / facade; this
  convention is the security-hardened form, where the port also asserts authorization.
- **The grid gateway seed (concrete, in-repo).** `tap_grid.services`' 2026-07 refactor
  (public `__init__` gated, `_impl.py` below the gate, location-scoped lint) is the
  instance this spec lifts to a reusable convention. It exists because a too-narrow "does
  this look privileged?" heuristic let the Entity-spine reads ship ungated.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-service-boundary-model | [Guarded Service Boundary](#guarded-service-boundary) | Proposed | Three zones — gateway + public contract module + below-gate — with a one-way import |
| req-service-boundary-contract-surface | [Every Gateway Export Is Gated](#every-gateway-export-is-gated) | Proposed | Every name in the gateway's `__all__` is gated; non-operations go in the contract module |
| req-service-boundary-export | [Export As Contract](#export-as-contract) | Proposed | Everything in `__all__` is gated; nothing public escapes by being left off the list |
| req-service-boundary-below-gate | [Below-Gate Implementation](#below-gate-implementation) | Proposed | Helpers run post-authorization, carry no gate, and the gateway→impl import is one-way |
| req-service-boundary-guard | [Reusable Boundary Guard](#reusable-boundary-guard) | Proposed | One parameterized guard a consumer declares itself into; location/export, not heuristic |
| req-service-boundary-discovery | [Boundary Discovery](#boundary-discovery) | Proposed | How the guard computes its protected set — filesystem convention, fail-closed, not an opt-in list |
| req-service-boundary-inviolability | [Boundary Inviolability](#boundary-inviolability) | Proposed | Detecting *bypass* — the outward dual: import-encapsulation (owned here) + resource-reach (delegated to the resource owner) |
| req-service-boundary-adoption | [Consumers And Composition](#consumers-and-composition) | Proposed | Consumers instantiate the pattern; capabilities compose upward, never migrate down |
| req-service-boundary-family-b-surface | [Un-Gateable Family-B Surface](#un-gateable-family-b-surface) | Proposed | Pre-boot/boot run before the gate exists — no gating possible; defense is a minimal `__all__` frozen by a ceiling ratchet that only shrinks |

---

### Guarded Service Boundary
----
RID: `req-service-boundary-model`
Status: `Proposed`

A guarded service layer is a package split into three zones, separated structurally by
module (not by naming alone):

- a **public gateway** — the operations every external caller uses. Its `__all__` is a
  list of gated operations, nothing else;
- a **public contract module** (e.g. `types.py`) — the separate file for public exports
  that are *not* gated operations: dataclasses, result types, exceptions, constants,
  schemas. Callers import these from here; they are not in the gateway's `__all__`;
- **below-gate implementation** — the logic and implementation-only helper types that run
  only after the gateway has authorized the caller.

The import runs one-way: the gateway imports the contract module and the implementation;
implementation never imports the gateway. (That is the *internal* rule; the *external*
dual — no module outside the package imports the below-gate zone — is
`req-service-boundary-inviolability`.)

#### Status Details
`tap_grid.services` already instantiates the gateway/below-gate split
(`req-grid-service-gateway-gated`). The requirement is `Proposed` as a *general* convention
until a second consumer adopts it, the neutral contract module is a settled zone, and the
shared guard (`req-service-boundary-guard`) exists.

#### Implementation
- The **gateway** is the package `__init__.py` (plus any intentionally-public domain
  submodule). Its `__all__` lists the public operations, and every one is gated
  (`req-service-boundary-contract-surface`).
- The **contract module** (e.g. `types.py`) is the separate file for public exports that
  are *not* gated operations — dataclasses, result types, exceptions, constants, schemas.
  Callers import these from the contract module; they are **not** listed in the gateway's
  `__all__` (everything in that list is a gated operation).
- **Below-gate implementation** lives in `_`-prefixed modules (e.g. `_impl.py`). It runs
  only after a gateway function has authorized the caller, so it carries no gate and the
  guard doesn't scan it. Implementation-only helper types live here.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-service-boundary-model-1 | Three Zones | Proposed | A guarded layer separates a public gateway, a neutral public contract module, and below-gate implementation — structurally (by module), not by naming alone. | |
| req-service-boundary-model-2 | One-Way Import | Proposed | The gateway imports the contract module and the implementation; the implementation never imports the gateway. | |
| req-service-boundary-model-3 | Contract Types Are Placed, Not Hidden | Proposed | Public non-operation exports live in the contract module (imported from there, not in the gateway `__all__`); implementation-only helper types live below the gate. | |

---

### Every Gateway Export Is Gated
----
RID: `req-service-boundary-contract-surface`
Status: `Proposed`

Every name the gateway exports in `__all__` carries a capability gate. Full stop — there is
no "is this one sensitive enough to gate?" judgment. In `tap_grid/services/__init__.py`,
every name in `__all__` resolves to a `def` decorated with `@requires_capability(...)` (or
the narrow `@gates_per_operation` marker). A name in `__all__` with no gate is a build
failure.

That is the whole point: the guard reads `__all__`, checks each entry has a gate, and fails
on the first that doesn't. It never decides whether an export "looks operational" — putting
a name in the gateway's `__all__` *is* the declaration that it's a guarded operation.

If you need to expose something that is **not** a gated operation — a dataclass, an
exception, a result type, a constant, a schema — it does not go in the gateway's `__all__`.
It goes in the separate contract module (`req-service-boundary-model`) and callers import it
from there. So the gateway's `__all__` stays a clean list of guarded actions and nothing
else.

#### The gate
The gate is `@requires_capability(<cap>, ...)`, naming the capability the operation needs —
`grid.read` for a read, `grid.write` for a write, and so on. One narrow exception: an
operation whose required capability varies per call (a batch that mixes writes and deletes)
uses the reviewed `@gates_per_operation` marker instead of a single static gate. A static
gate is always preferred; the marker is the one spot a gate can't be read straight off the
decorator, so it stays rare (`spec-security-posture.md` `req-sec-honest-risk`).

#### Other promises on the same surface
Authorization is the gate the guard checks. It isn't the only promise the gateway makes —
it's also where the layer takes responsibility for threading caller context
(`req-grid-service-pipeline-context`), validating input against its schemas, and returning
transport-safe results. "Takes responsibility" is the point: the gateway function owns these
promises, but the actual work can run in the shared pipeline below the gate — it doesn't
have to be written out on the public function itself.

#### Classes
Don't gate a class just because Python lets you call the class object. Data classes, result
types, and exceptions go in the contract module, not the gateway `__all__`. Avoid public
service classes with operational methods — a plain gated function is easier to export and
the guard can check it straight off `__all__`. If you truly need an operational class, gate
each public method that does protected work, and keep the constructor free of protected work
(if `__init__` does real work, it's an operation in disguise — make it a gated function).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-service-boundary-contract-surface-1 | Everything In `__all__` Is Gated | Proposed | Every name in a gateway's `__all__` carries `@requires_capability` or `@gates_per_operation`; an ungated entry is a build failure. | No per-export judgment. |
| req-service-boundary-contract-surface-2 | Non-Operations Go In The Contract Module | Proposed | Exports that aren't gated operations (types, exceptions, constants, schemas) live in the contract module, not the gateway `__all__`. | |
| req-service-boundary-contract-surface-3 | Classes Are Not Blanket-Gated | Proposed | Data/result/exception classes live in the contract module; an operational class gates each protected method and keeps its constructor free of protected work. | |
| req-service-boundary-contract-surface-4 | Marker Is Narrow | Proposed | `@gates_per_operation` is used only where a static capability can't express the requirement; a static gate is preferred. | |
| req-service-boundary-contract-surface-5 | Surface Owns, Pipeline May Execute | Proposed | The gateway owns the caller-context / schema / transport promises; their execution may run in the shared pipeline below the gate. | |

---

### Export As Contract
----
RID: `req-service-boundary-export`
Status: `Proposed`

The gateway's `__all__` is its list of public operations, and every one is gated
(`req-service-boundary-contract-surface`). Two plain rules keep that list honest:

- **Everything in `__all__` is gated.** The guard reads `__all__` and fails on any entry
  without a gate. If a type or constant slips into `__all__`, it has no gate, so it fails —
  and the fix is to move it to the contract module. That failure is the forcing function
  that keeps `__all__` operations-only.
- **Nothing public escapes by being left off the list.** `__all__` is not a lock: a
  function left out of it is still importable (`from pkg.services import it`). So the guard
  also fails on any ungated public (non-`_`) function defined in a gateway module — in or
  out of `__all__`. `__all__` advertises the surface; it can never *shrink* what is enforced.

Together: every public operation is gated whether or not it's listed, and `__all__` is the
clean advertised list. (Python's own guidance is that `__all__` is a documentation
convenience, not access control — which is exactly why we don't let it decide what's
enforced.)

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-service-boundary-export-1 | Everything In `__all__` Is Gated | Proposed | Every `__all__` entry has a gate; an ungated entry fails the build and must move to the contract module. | |
| req-service-boundary-export-2 | Nothing Escapes The List | Proposed | No ungated public (non-`_`) function exists in a gateway module, whether or not it is in `__all__`. | |
| req-service-boundary-export-3 | `__all__` Advertises, Never Shrinks | Proposed | `__all__` is the advertised public list, never the thing that decides what is enforced. | Python: `__all__` is not a lock. |

---

### Below-Gate Implementation
----
RID: `req-service-boundary-below-gate`
Status: `Proposed`

Below-gate modules hold pure logic and machinery that runs *after* a gateway function has
authorized the caller. They present no service surface, so they carry no capability gate,
and the guard does not scan them.

#### Implementation
- Below-gate code lives in `_`-prefixed modules; the guard skips them.
- It carries no gate precisely because it is unreachable except through an
  already-authorized gateway call — gating it again would be redundant and would blur
  where the boundary is.
- **Narrow exception:** a gated helper that must call back into a gateway function (so
  moving it below the gate would violate the one-way import) may stay in the gateway zone
  `_`-prefixed *and* keep its gate. This is the exception that proves the rule (the grid
  layer's internal write cluster), not a general license.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-service-boundary-below-gate-1 | Post-Auth, No Gate | Proposed | Below-gate modules run only after gateway authorization and carry no capability gate. | |
| req-service-boundary-below-gate-2 | Exception Is Bounded | Proposed | A gated helper kept in the gateway zone to preserve the one-way import is a named, reviewed exception, not a pattern. | |

---

### Reusable Boundary Guard
----
RID: `req-service-boundary-guard`
Status: `Proposed`

The separation is enforced by a **single reusable guard**, parameterized by which package
is a guarded service boundary, that a consumer declares itself into — not a per-app copy.
The guard enforces by **location/export**, never by a "does this look privileged?"
heuristic (the heuristic's narrowness is what let the Entity-spine reads ship ungated).

#### Implementation
- The mechanism lives in the guard harness (`tap/guards`, discovered filesystem-wide per
  `spec-dev-validation.md`), so it runs pre-boot and repo-wide and composes *downward* —
  no consumer app depends on another (`avoid-tap-app-interdependencies`).
- It uses TAP's existing **DIY-AST shape**, not import-linter: the same `ast.parse` +
  visitor approach as the other tree-scanners (authz-coverage, direct-write, log-site,
  service-gateway), on the shared primitives in `tap/source_scan.py`
  (`first_party_source_roots`, `CallSite`/`CallsiteIdentity`). Reading `__all__` and a
  `def`'s decorators is a definition-level check import-linter — an import-graph tool —
  can't do anyway. The "one shape" work is to fold the AST mechanics currently duplicated
  across guards (e.g. `_decorator_name` in two places, copy-pasted scope-walks) into one
  shared helper.
- The guard checks two plain things per boundary: (a) every name in the gateway's `__all__`
  carries a gate; (b) no ungated public (non-`_`) function exists in a gateway module, in or
  out of `__all__`. It never classifies an export as "operational" — an ungated public
  function is a failure, and a non-operation belongs in the contract module, not `__all__`.
- It is a **hard lint**: no baseline, no allowlist. A new ungated operation entry point
  fails immediately; a security boundary does not grandfather ungated exports.
- The guard learns its protected set — which packages, and the zones within each — by
  **discovery**, not by hardcoded paths (`req-service-boundary-discovery`). Today the guard
  is hardcoded to `tap_grid/services/` and keys on non-`_` top-level defs; generalizing it
  to convention-driven discovery and the operation-vs-contract distinction is the work this
  requirement names.
- The guard is a callsite scanner: when its findings feed SARIF, its finding identity
  follows `spec-tap-callsite-identity.md` (a drift-proof anchor, not `name:lineno`). It is
  the `service-gateway` row of that spec's conformance ledger.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-service-boundary-guard-1 | One Shared Guard | Proposed | Boundary coverage is one parameterized guard consumers declare into, not per-app copies. | Mechanism home: `tap/guards`. |
| req-service-boundary-guard-2 | Location Not Heuristic | Proposed | The guard enforces by gateway-module location/export, never by a privilege-shape heuristic. | |
| req-service-boundary-guard-3 | Verifies Both Halves | Proposed | The guard checks that every `__all__` entry is gated AND no ungated public function exists in a gateway module — no operational-vs-contract classification. | |
| req-service-boundary-guard-4 | Hard Lint | Proposed | No baseline, no allowlist — a new ungated operation entry point fails immediately. | |
| req-service-boundary-guard-5 | Findings Follow Callsite Identity | Proposed | When guard findings feed SARIF, they use the drift-proof identity of `spec-tap-callsite-identity.md`. | |

---

### Boundary Discovery
----
RID: `req-service-boundary-discovery`
Status: `Proposed`

The guard has to know *which* files to check. It finds them by walking the filesystem, not
by reading a list someone maintains by hand — because the worst failure here is a whole
service layer with no gate coverage that still shows green because nobody added it to the
list. So discovery is **fail-closed**: found-and-checked is the default, and leaving
something out has to be a deliberate, reviewed choice.

#### Implementation
- **How it finds boundaries.** A guarded boundary is a `services/` package under a
  first-party source root, enumerated by the existing `first_party_source_roots()` walk
  (`<app>/services/`, `plugins/<slug>/…/services/`). Discovery is filesystem-based,
  pre-boot, and Django-registry-independent — the same primitive every TAP tree-scanner
  and `discover_guards()` already use. Default state is *discovered and protected*; a
  `services/` package that is deliberately **not** a guarded boundary carries a reviewed
  opt-out marker — opt-*out* is explicit, opt-*in* is never required.
- **How it reads the zones inside a boundary.** The guard resolves the three zones by
  AST/convention (no import, so it runs pre-boot): `__init__.py` plus non-`_`
  non-contract modules are the **gateway** (operation entry points, must be gated),
  `_`-prefixed modules are **below-gate** (skipped), and the **contract module(s)** are
  named by a package-level constant in `__init__.py` — `__tap_contract_modules__` (a tuple
  of module names, e.g. `("types",)`) — read by AST, never imported. Its absence means the
  boundary declares no contract module (all non-`_` gateway symbols are operations); its
  presence exempts exactly those modules' symbols *by placement*, so the guard can tell a
  contract DTO from an ungated operation. This mirrors per-module public-interface
  declarations in tools like Tach, kept AST-only for the pre-boot constraint.
- **Catching a half-built boundary.** A companion check asserts every discovered
  `services/` package is a well-formed boundary (has the required structure / a valid zone
  declaration); a malformed or half-declared boundary fails the build rather than being
  skipped. The guard **reports what it protects** (which boundaries, which gateway modules)
  so an undiscovered boundary is *visible*, not silent — the honest-status discipline of
  `spec-dev-validation.md`.

#### Development
The alternative — a central opt-in registry of protected packages (the import-linter
model) — is rejected as the *primary* mechanism precisely because it is forgettable:
adding a service layer and forgetting the registry entry yields a silently-unprotected
boundary. A central list may serve only as the reviewed *opt-out* record, never as the
thing that decides what is protected.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-service-boundary-discovery-1 | Discovered, Not Listed | Proposed | The protected set is computed by filesystem walk (`first_party_source_roots()`), not a hand-maintained opt-in registry. | |
| req-service-boundary-discovery-2 | Fail Closed | Proposed | An undiscovered or malformed boundary fails the build; a non-boundary `services/` package is an explicit reviewed opt-out. | Default is protected. |
| req-service-boundary-discovery-3 | Zones Without Import | Proposed | Gateway / contract / below-gate zones are resolved by AST and convention pre-boot, without importing the package. | |
| req-service-boundary-discovery-4 | Protected Set Reported | Proposed | The guard surfaces which boundaries and modules it protects, so an undiscovered boundary is visible, not silent. | |

---

### Boundary Inviolability
----
RID: `req-service-boundary-inviolability`
Status: `Proposed`

The gateway guard (`req-service-boundary-guard`) locks the front door — the gateway's own
operations are gated. **Inviolability** is the other half: making sure nobody gets to the
protected resource *around* the door. A layer whose front door is locked but whose windows
are open isn't a boundary. There are two ways to go around the door, and they have
different owners:

#### Going around #1: importing past the gate (generic — owned here)
No module *outside* a boundary's package may import its below-gate (`_`) modules; outside
code gets the gateway's public exports and nothing else. This is the mirror image of the
one-way-import rule (`req-service-boundary-model`): that rule keeps the *inside* from
reaching up to the gateway; this keeps the *outside* from reaching down past it.

- Enforced by an **import-boundary guard** in the harness (`tap/guards`): a DIY AST
  import-walk that fails if any module outside the package imports its `_`-zone — same shape
  and pre-boot constraint as the other tree-scanners. (This is an import-graph check, the
  kind of thing import-linter does, but TAP stays DIY: one AST shape, no new dependency.
  Decided — not import-linter.)
- This is pattern-generic — it does not depend on what the protected resource is — so it
  lives in this convention, not in a consumer.
- **Status: a gap today.** Nothing enforces `external → _impl`; the current one-way-import
  statement covers only the internal `__init__ → _impl` direction. Building this guard is
  the work this requirement names.

#### Going around #2: touching the resource directly (resource-specific — delegated)
No code may reach the protected resource *directly* — a direct ORM write to a grid model, a
call to a privileged sink outside a gate — skipping the gateway entirely. What "touching
the resource" even means is something only the resource owner knows (which models, which
sinks, which backstops), so this detection is **supplied by the resource's own spec and
guards**, not by this convention. A guarded boundary MUST have this detection; the
convention requires it *exist* and names the owner, but can't implement it generically.

The grid instance (reference): `req-tap-auth-policy-9` — the `direct-write-coverage` and
`authz-coverage` static guards — plus the runtime backstops `tap_grid/write_guard.py` and
`read_guard.py`; `req-grid-service-scope` owns "identify mutation paths that bypass the
service layer." Defense-in-depth: static (authoring-time lint) and runtime (fail-closed
backstop) where the resource supports both.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-service-boundary-inviolability-1 | Below-Gate Is Private | Proposed | No module outside a boundary's package imports its below-gate (`_`-prefixed) zone; external callers use only the gateway's public exports. | Import-boundary guard; a gap today. |
| req-service-boundary-inviolability-2 | Reach Detection Is Owned By The Resource | Proposed | Direct-reach detection is supplied by the resource owner's spec/guards; this convention requires it exist and cites the instance rather than implementing it generically. | Grid: `req-tap-auth-policy-9` + `write_guard`/`read_guard`. |
| req-service-boundary-inviolability-3 | Static And Runtime Where Supported | Proposed | Resource-reach detection may be static (authoring-time lint) and/or runtime (fail-closed backstop); the grid provides both. | |

---

### Consumers And Composition
----
RID: `req-service-boundary-adoption`
Status: `Proposed`

Service layers *consume* this convention; they do not re-specify it. Where a layer sits
above another guarded layer, its capabilities **compose upward** — each layer gates its
own vocabulary — and never migrate down into a lower layer.

#### Implementation
- **Reference instance:** `tap_grid.services` (`spec-grid-service.md`
  `req-grid-service-gateway-gated`) — the grid boundary, gating `grid.*` type-agnostically.
- **Named adopters:** app service layers (`tap_auth`, `req-tap-auth-service-boundary`) and
  plugin service layers (`spec-tap-plugin-architecture.md`). An app layer gates its own `app.*`
  capability and composes *above* the grid layer by calling it — two gates, two owners,
  each authorizing only its own vocabulary. Capability **definition** stays centralized in
  the `tap_auth` registry; only **enforcement** lives in the owning layer's gateway. See
  `req-tap-auth-service-boundary` for the composition rule in full.
- A consumer's spec cites this convention for the *structure* (zones, export, guard) and
  owns only what is specific to its resource (which capabilities, which contracts beyond
  authz).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-service-boundary-adoption-1 | Consumers Cite, Not Copy | Proposed | A service layer's spec references this convention for the separation structure rather than re-specifying it. | |
| req-service-boundary-adoption-2 | Compose Up, Not Down | Proposed | A higher layer gates its own capability above a lower guarded layer; no capability's enforcement migrates down. | Detailed in `req-tap-auth-service-boundary`. |

---

### Un-Gateable Family-B Surface
----
RID: `req-service-boundary-family-b-surface`
Status: `Proposed`

The convention so far governs **Family A** — gate-able runtime boundaries, where the risk
is "public *but ungated*" and the fix is a gateway `__all__` of gated operations. There is
a second family. **Family B** is the *un-gateable* layers: pre-boot (`tap/preboot.py`) and
boot (`tap_boot`). They run *before the capability system exists* — pre-boot before Django
and settings, boot as the process that mints the capabilities themselves — so there is no
gate to put in front of them ("can't gate before the gate exists"). For these layers the
risk is not "public but ungated"; it is **public at all**. A large public surface on a
pre-auth layer is exactly the out-of-band reach an attacker or an accidental caller would
use, and no gate can intervene.

The defense is therefore *surface minimization*, mechanically enforced:

- Each un-gateable module declares a **minimal `__all__`** — only what an external module
  genuinely imports, plus the layer's CLI/orchestration entry and its error contract. Every
  other helper is `_`-sealed (a private module member).
- A **public-surface ceiling ratchet** (the inverse of the Family-A coverage guard) freezes
  the set of public (non-`_`) top-level `def`/`class` **not** listed in `__all__` — the
  *leaked surface* — and allows it only to shrink. A new public helper on these layers fails
  the guard; sealing one with a `_` prefix is the only motion. "Shrink first, then freeze":
  the baseline starts at the known residual, never a fresh debt ceiling.
- This is the static complement to the boot layer's **runtime** context self-check
  (`tap_boot.orchestrator`, a confirmed-positive tripwire): the ratchet keeps the surface
  small; the tripwire records any out-of-band call to what surface remains. Neither gates —
  because neither can — but together they shrink and observe the un-gateable reach.

#### Implementation
- **Guard:** `tap/guards/public_surface.py` (`PublicSurfaceCeilingGuard`), a `CeilingRatchet`
  over `tap/preboot.py`, `tap_boot/orchestrator.py`, `tap_boot/profile.py`. AST-only (these
  modules run pre-Django, so the guard must read them without importing). Baseline
  `tap/guards/baselines/public_surface.txt`.
- **Sealed:** all of pre-boot's internal orchestration helpers are `_`-prefixed; its `__all__`
  is the 4 genuinely-imported names + CLI entry + `PrebootError`. `tap_boot.orchestrator`
  exports only `BootError`/`check_profile`/`run_boot`; `tap_boot.profile` exports its profile
  contract. **Leaked surface is zero** — the baseline is empty and the ratchet holds it there.
  (The two helpers a parallel session was editing, `is_satisfied` / `uv_install_args`, were
  briefly held as a named baseline residual; once that work was consolidated onto this branch
  they were sealed with the rest.)

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-service-boundary-family-b-surface-1 | Minimal Declared Surface | Proposed | Each un-gateable Family-B module declares an `__all__` limited to genuinely-imported API, its CLI/orchestration entry, and its error contract; all other helpers are `_`-sealed. | pre-boot, `tap_boot.orchestrator`, `tap_boot.profile`. |
| req-service-boundary-family-b-surface-2 | Surface Ratchets To Zero | Proposed | A ceiling ratchet freezes the public (non-`_`) top-level def/class NOT in `__all__` (leaked surface) and permits only shrink; a new public helper fails. | `tap/guards/public_surface.py`. |
| req-service-boundary-family-b-surface-3 | Named Residual, Not Hidden | Proposed | Any helper left public for coordination is recorded in the baseline with the reason, not silently exempted. | None currently; the mechanism was exercised for `is_satisfied`/`uv_install_args` then cleared to zero. |

---

## Relationship To Other Specs

- **`spec-grid-service.md`** (`req-grid-service-gateway-gated`) — the reference consumer;
  the concrete instance this convention was lifted from. Its spec keeps the instance
  specifics (which modules, which `grid.*` caps) and cites this one for the general rules.
- **`spec-tap-auth-v0.md`** (`req-tap-auth-service-boundary`) — owns the capability
  vocabulary and the compose-up-not-down rule; the next adopter of this structural pattern.
- **`spec-tap-plugin-architecture.md`** — plugin service layers as future adopters.
- **`spec-dev-validation.md`** — owns the guard harness the reusable boundary guard lives
  in, and the Validation Map row it earns.
- **`spec-tap-callsite-identity.md`** — governs the boundary guard's finding identity when
  it feeds SARIF.
- **`spec-security-posture.md`** — the *why*: a guarded boundary is a cheap foundational
  edge taken while the surface is already being built, and its escape hatches are named,
  not hidden.

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed | Requirement has been designed but not yet accepted for implementation. |
| Approved for Development | Requirement is accepted and ready to be implemented. |
| In Development | Actively being worked on. |
| Implemented | Has been written. |
| Verified | Has met the acceptance criteria. |
| Refactoring | In the process of being re-worked. |
| Deprecating | In the process of being deprecated. |
| Deprecated | No longer part of the current architecture. |
