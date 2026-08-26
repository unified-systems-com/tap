# Panel Client State Spec

## Spec Status: Backlog

**Held 2026-05-05 pending the Dominant Class design.** This spec captures a generic browser-side preference mechanism (cookies, registry, JS module, server-side opt-in API). It was drafted as the foundation for the FedRAMP 20x KSI class preference. While drafting we identified a load-bearing UX flaw: a per-browser preference produces inconsistent shared experiences when one user shares a link to an indicator with another user — the friend opens the page at the registered default class, not the sender's class, and discussions about "look at indicator X under class C" silently de-sync.

The right shape for the FedRAMP class problem is a **dominant-class** concept living on the Grid (or the system being audited), not a per-viewer preference. Panels read the dominant class from a graph object, not from a cookie. A per-viewer preference may still earn its keep eventually for *non-shared-context* preferences (UI density, color theme, timezone) but the FedRAMP class is not one of them, and pushing this spec through now would lock in the wrong default for the v0 demo and force a migration when the dominant-class concept lands.

**This spec — and the dependent `spec-fedramp-20x-ksi-class-preference.md` — are Backlog until the Dominant Class spec is drafted and we know whether a separate per-viewer preference layer is justified on top of it.** When the Dominant Class spec lands, this spec is revisited with one of three outcomes:

1. **Subsumed.** The dominant-class object covers all v0 needs; this spec is rewritten or deprecated.
2. **Re-scoped.** Per-viewer preferences are still useful for non-shared-context values; this spec narrows to that set and ships without `fedramp.class` as a consumer.
3. **Resurrected as-is.** Dominant class handles compliance-context values; per-viewer preferences handle UX values; both ship side by side and this spec returns to `Approved for Development` after a re-review.

All requirements and ACIDs in this spec are status `Backlog`. The previously-drafted touch-ups to `spec-web-page.md`, `spec-web-panel.md`, `spec-fedramp-20x-ksi-compliance-view.md`, `spec-fedramp-20x-ksi-indicator-profile.md`, and `spec-fedramp-20x-ksi-finding-profile.md` have been reverted; those existing specs will receive amendments only when this spec is unparked.

---

## Philosophy

Panels make small "what does this user care about right now?" decisions during render — which class variant of a KSI requirement to surface, which density to use for a list, which color theme is in effect, what timezone to display dates in. These choices need to:

- **Survive across pages and sessions.** A user working in FedRAMP 20x Class C should not have to re-pick "C" on every indicator they open.
- **Be visible to the server during render.** Server-rendered panels should produce the right HTML on first paint — no flicker, no hydration round-trip, no two-stage render.
- **Stay out of URL state and out of the data graph.** This is a UX preference layer, not a shareable-link layer and not something that belongs in `Entity` rows.

This spec adds a **panel client-state** mechanism to `tap_web`: a small, registry-validated, cookie-backed key/value store with a JS-first client API and a server-side read API that panels opt into when they need it.

The mechanism is deliberately narrow:

- **Cookies, not `localStorage`.** Cookies are the on-the-wire format and the source of truth. Cookies preserve the option to read server-side without any storage migration when a panel needs it. v0 ships JS-readable cookies (the registry's `js_readable` flag defaults to `True`); server-only HttpOnly cookies are designed-in for a future preference whose value the server must read but the client must not (rare; documented under `req-web-cstate-cookie`).
- **JS-first, server-side opt-in by rule.** The default reading path is `window.TAP.clientState.get/set/subscribe` running in the browser. Panels opt into the server-side `tap_web.client_state.get(request, ns, key)` API only when one of three documented criteria applies (first-paint correctness, server-side query parameter, non-panel surface) — see `req-web-cstate-when-server-side`. v0 does not ship middleware that injects state into every panel context; the server API is a per-panel call.
- **Registry-validated.** Every preference declares its `namespace`, `key`, `allowed_values`, `default`, `description`, `version`, and `js_readable`. Reads and writes both validate. Garbage values (corrupt cookie, mismatched version, browser-extension shenanigans) are dropped and the registered default takes over.
- **Per-browser in v0.** Preferences are not bound to a user account. Per-grid and per-user scopes are explicit Future work — the boundary is called out in `req-web-cstate-scope-boundary` so we don't paint ourselves into a corner.

### Preferences vs. Session State — Two Mechanisms, Not One

Preferences are typed UX choices with allow-lists and defaults. Session state — drafts, last-visited-page tracking, in-flight wizard data, opaque per-session blobs — is a different shape and deserves its own mechanism. This spec is **only** about preferences. A future `spec-web-session-state.md` will own session state, built on Django's session framework, with its own `request.session_state` accessor. The two mechanisms are intentionally separate; conflating them would force preferences to absorb session-shaped escapes (untyped, free-form values) and force session state to carry preference-shaped overhead (typed registry, allow-list validation) that doesn't fit it. This boundary is captured in `req-web-cstate-vs-session-state`.

This spec lives in `tap_web` because the mechanism is platform-wide: the registry, the cookie format, the server API, the JS module, and the Preference Switcher panel type are all owned here. Plugin-specific preferences (like the FedRAMP 20x KSI class) are declared by the consuming plugin during its `AppConfig.ready()` and their wiring is documented in plugin-side specs (the first one being `spec-fedramp-20x-ksi-class-preference.md`).

### Relationship To Other Page-Level State

TAP already specifies two adjacent state mechanisms — see `spec-web-page.md` (`req-web-page-params`, `req-web-page-local`) — and a third specified by this spec:

| Mechanism | Spec | Storage | Lifetime | Shareable | Server-Visible |
| --- | --- | --- | --- | --- | --- |
| Page Variables (`tap_page_vars`) | `spec-web-page.md` `req-web-page-params` | URL query params | Single navigation | Yes (URL is the share unit) | Yes |
| Page Persistent Variables (`tap_page_persistent_vars`) | `spec-web-page.md` `req-web-page-local` | In-memory (page-coordinator) | Single page lifetime | No | No |
| **Panel Client State** (this spec) | `spec-web-panel-client-state.md` | Cookies (per-browser) | Persistent across pages and sessions | No (preferences are user-local) | Yes (via `request.COOKIES`) |

The three are complementary. URL state is "the share-this-link layer." Page-persistent state is "the in-page cache layer." Client state is "the cross-page preference layer." Panel authors choose the layer that matches the lifetime and visibility of the value they're storing.

### Touch-Ups To Existing Specs

The following existing specs receive amendments alongside this one (tracked under `req-web-cstate-spec-touchups`):

- `spec-web-page.md` — adds Panel Client State as the third state dimension in the page system, with a back-reference to this spec. No change to existing page-variable behavior.
- `spec-web-panel.md` — `req-web-panel-inputs` (or its successor) is amended to note that panels MAY opt into reading client state via `tap_web.client_state.get(request, ns, key)` per the rule in `req-web-cstate-when-server-side`. The amendment makes clear that v0 does NOT inject state into every panel context — server-side reads are a per-panel call, not a pipeline-injected parameter.
- `spec-fedramp-20x-ksi-compliance-view.md` (fedramp_20x_ksi plugin repo) — its class-select requirement is updated: the existing ad-hoc `localStorage` key (`tap-ksi-class-selection`) is replaced by the platform mechanism via the `fedramp.class` preference. Greenfield rollout — the legacy localStorage value is not preserved (TAP has one user today). The compliance view stays JS-only and does NOT read `request.client_state`.
- `spec-fedramp-20x-ksi-indicator-profile.md` (fedramp_20x_ksi plugin repo) — its statement and header requirements are amended: the initial active class follows the `fedramp.class` preference. The indicator profile is the v0 panel that opts into the server-side read API per `req-web-cstate-when-server-side` criterion 1 (first-paint correctness).
- `spec-fedramp-20x-ksi-finding-profile.md` — adds a Future Work bullet noting that any future class-scoped rollups inside the finding profile will consume the same `fedramp.class` preference. No v0 behavior change.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Lightweight        | One `tap_web` Python module, one small JS module, one cookie per registered preference |
| 2. | Panel-Native       | `Panel.get_view_context(panel, request)` receives the active preferences as a `client_state` mapping |
| 3. | Server-Aware       | Server-side panels render with the active preference applied on first paint |
| 4. | Cross-Plugin       | Any plugin can register preferences and any panel can read them without touching `tap_web` |
| 5. | Registry-Validated | Allowed values, defaults, and per-key versions declared centrally; invalid values fall back to default |
| 6. | JS-Reactive        | Client JS can read, write, and subscribe to changes; setters either trigger HTMX refresh or in-place DOM updates |
| 7. | Evolvable          | Storage backend can move to per-user server-side without changing the panel-side API |
| 8. | Explicit Boundary  | Per-browser scope is documented; per-grid and per-user are Future, with the migration path called out |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-cstate-registry | [Preference Registry](#preference-registry) | Backlog | Python registry of declared client-state keys, namespaced and versioned |
| req-web-cstate-cookie | [Cookie-Backed Storage](#cookie-backed-storage) | Backlog | One cookie per preference; cookie-vs-localStorage rationale |
| req-web-cstate-version | [Per-Key Versioning](#per-key-versioning) | Backlog | Each registered key carries a `version`; mismatched cookies are dropped |
| req-web-cstate-server-api | [Server-Side Read API](#server-side-read-api) | Backlog | `tap_web.client_state.get(request, namespace, key)` — opt-in per `req-web-cstate-when-server-side` |
| req-web-cstate-when-server-side | [When To Use The Server-Side Read API](#when-to-use-the-server-side-read-api) | Backlog | The decision rule for opting into server-side reads vs JS-only |
| req-web-cstate-vs-session-state | [Preferences vs Session State](#preferences-vs-session-state) | Backlog | Documents the boundary with the future session-state mechanism |
| req-web-cstate-js | [Client-Side JS Module](#client-side-js-module) | Backlog | `window.TAP.clientState.get / set / subscribe` |
| req-web-cstate-bridge | [Registry Discovery Bridge](#registry-discovery-bridge) | Backlog | Embedded JSON exposes the registry to client JS for write-time validation |
| req-web-cstate-refresh-htmx | [Declarative HTMX Refresh](#declarative-htmx-refresh) | Backlog | `data-tap-cstate-bind` attribute triggers panel refresh on change |
| req-web-cstate-refresh-subscribe | [Client-Side Subscription Refresh](#client-side-subscription-refresh) | Backlog | Panels can `subscribe()` and re-render in place from already-loaded data |
| req-web-cstate-switcher-panel | [Preference Switcher Panel Type](#preference-switcher-panel-type) | Backlog | Standard `tap_web` panel type renders a labeled selector for any registered key |
| req-web-cstate-scope-boundary | [Scope Boundary And Migration Path](#scope-boundary-and-migration-path) | Backlog | Documents per-browser scope and how a future per-user backend slots in |
| req-web-cstate-spec-touchups | [Existing-Spec Touch-Ups](#existing-spec-touch-ups) | Backlog | Tracks the amendments to `spec-web-page.md`, `spec-web-panel.md`, and the KSI specs |
| req-web-cstate-sanitize.sec | [Cookie Input Sanitization](#cookie-input-sanitization) | Backlog | Strict allow-list validation; raw cookies never echoed to template context |

---

### Preference Registry
----
RID: `req-web-cstate-registry`
Status: `Backlog`

A Python registry of typed client-state preferences, populated during `AppConfig.ready()` so any consumer can declare its own without modifying `tap_web`.

#### Implementation
- Module path: `tap_web/client_state.py`.
- Dataclass:
  ```python
  @dataclass(frozen=True, slots=True)
  class ClientStatePref:
      namespace: str          # e.g. "fedramp"
      key: str                # e.g. "class"
      allowed_values: tuple[str, ...]
      default: str
      version: int            # bump when allowed_values shape changes
      js_readable: bool = True  # if False, cookie is HttpOnly (server-only)
      description: str = ""   # human-readable; reserved for future settings UI
  ```
  - The canonical addressable key is `<namespace>.<key>` (e.g. `fedramp.class`).
  - `default` MUST be in `allowed_values`.
  - `version` is a positive integer; v0 starts at `1`.
  - `js_readable=True` (the default) writes the cookie without the `HttpOnly` flag, exposing it to `window.TAP.clientState`. This is the right setting for almost every preference — UX choices the user controls. v0 ships exactly one registered preference (`fedramp.class`) and it is `js_readable=True`.
  - `js_readable=False` writes the cookie with `HttpOnly` set; the JS module cannot read or write it. Used for server-only preferences where the client should never need (or be allowed) to know the value. None are registered in v0; the field exists so the door stays open without a future schema migration.
  - `description` is intended for human display in a future settings UI.
- Registry instance: `client_state_registry: ScopedRegistry[ClientStatePref]` modeled on `tap_grid.registry.ScopedRegistry[T]` (see `spec-grid-registry.md`). The scope is the `namespace`; the key inside the scope is `key`. This naturally enforces that a `(namespace, key)` pair is unique.
- Public Python API:
  - `register_pref(pref: ClientStatePref) -> None` — adds to the registry; raises `ClientStateRegistrationError` if `(namespace, key)` is already registered or if `default` is not in `allowed_values`.
  - `get_pref(namespace: str, key: str) -> ClientStatePref | None` — registry lookup.
  - `iter_prefs() -> Iterable[ClientStatePref]` — used by the discovery bridge.
- Plugins/apps register their preferences in their `AppConfig.ready()`. `tap_web` itself ships zero registered prefs in v0; the FedRAMP 20x KSI plugin's `Fedramp20xKsiConfig.ready()` registers `fedramp.class` (see `spec-fedramp-20x-ksi-class-preference.md`).
- Re-registration of the same `(namespace, key)` is a hard error — surfaces duplicate plugin imports during boot rather than silently overwriting at runtime.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-cstate-registry-1 | Typed Pref Declaration | Backlog | Each registered preference declares `namespace`, `key`, `allowed_values`, `default`, `version`, `js_readable`, `description`. | |
| req-web-cstate-registry-2 | Default In Allowed Values | Backlog | Registration rejects entries whose `default` is not in `allowed_values`. | |
| req-web-cstate-registry-3 | Plugin-Driven Registration | Backlog | Plugins/apps register their preferences in their own `AppConfig.ready()`; `tap_web` carries no plugin-specific registrations. | |
| req-web-cstate-registry-4 | Duplicate Registration Rejected | Backlog | Re-registering the same `(namespace, key)` raises `ClientStateRegistrationError`. | |

---

### Cookie-Backed Storage
----
RID: `req-web-cstate-cookie`
Status: `Backlog`

Each preference is stored in its own browser cookie. Cookies are the source of truth; server and client both read and write the same flat `name → value` mapping.

#### Implementation
- Cookie name shape: `tap_cs_<namespace>__<key>` — e.g. `tap_cs_fedramp__class`. The `tap_cs_` prefix scopes platform cookies; `<namespace>__<key>` keeps them collision-free with the underscore separator chosen because `.` is not legal in cookie names.
- Cookie value shape: `v<version>:<value>`. Example: `v1:c`. The version prefix is what enables `req-web-cstate-version`; the value after the colon is one of `allowed_values`.
- Cookie attributes (set on every write):
  - `Path=/` — the same preference applies to every page in the app.
  - `SameSite=Lax` — matches the project default; see `spec-web-panel-security.md`.
  - `Secure` — added when the request is HTTPS. The Django session middleware's `SESSION_COOKIE_SECURE` setting is the source of truth for the production decision; the JS-write path mirrors it via `location.protocol === "https:"`.
  - `HttpOnly` — driven by the registered `js_readable` flag. `js_readable=True` (the default in v0) → `HttpOnly` is **not** set, the JS module can read and write. `js_readable=False` → `HttpOnly` is set, the cookie is server-only and the JS module returns `null` on reads and refuses writes. The flag fixes the cookie's substrate per-pref and is enforced at registration time (the JS write path consults the discovery bridge before issuing `document.cookie`).
  - `Max-Age` ≈ 1 year (`31536000` seconds). Long enough to feel "remembered," short enough that abandoned browsers don't carry stale prefs forever.
- Cookie size: each cookie is bounded to a few bytes by the registry (allowed-value tokens are short). Total per-domain cookie footprint scales linearly with the number of registered preferences. v0 ships exactly one (`fedramp.class`); the budget for the foreseeable future is well under the 4 KB browser limit.
- One cookie per preference avoids the "multiple writers clobber each other in a JSON map" failure mode a single-cookie design would invite.

#### Cookies vs `localStorage` — rationale

This was an explicit design decision for v0. Both are vulnerable to XSS-driven read or write — neither stops a hostile script running on the same origin from manipulating the values. The trade-offs that drove the cookie choice:

| Concern | Cookie | localStorage |
| --- | --- | --- |
| Server-readable on first paint | Yes (via `request.COOKIES`) | No (requires hydration round-trip or out-of-band sync) |
| `SameSite` / `Secure` / `Max-Age` controls | Yes | No |
| Storage size | 4 KB total per domain | 5–10 MB |
| Auto-transmitted with every request | Yes (small bandwidth cost) | No |
| Server-side write API path | Direct (`response.set_cookie`) | Requires shadow cookie or new endpoint |

For panel preferences — small enum values that need to influence first-paint server rendering — cookies are the better fit. The bandwidth cost is negligible (≤ ~30 bytes per cookie), and the cookie attributes give a baseline of platform-enforced isolation that `localStorage` can't match. If a future preference needs to store more than a kilobyte (e.g. a complex UI layout), this is the trigger to revisit; until then, cookies-only.

#### Threat model

- **JS-readable cookies (`js_readable=True`)** are exposed to any script running on the same origin. The cookie value is a UI preference, not a credential — losing it to XSS does not enable session theft, account takeover, or privilege escalation. The strict `allowed_values` validation on both the server and client (`req-web-cstate-sanitize.sec`) prevents malicious values from reaching template context or being persisted.
- **HttpOnly cookies (`js_readable=False`)** are unreachable from JS by browser policy. They're the right substrate for server-side-only preferences whose value is not the user's to twiddle from a `console.log` or a hostile extension. v0 has none registered; the option is documented so the first such preference doesn't have to introduce a new mechanism.
- **CSRF** — `SameSite=Lax` provides modest baseline protection. A successful CSRF write would do no more than change a UI preference; the impact is bounded by the same `allowed_values` validation.
- **Cookie tampering** — server-side validation never trusts the cookie value. Anything outside `allowed_values` (or with a mismatched version, see `req-web-cstate-version`) is treated as missing and the registered default is used.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-cstate-cookie-1 | One Cookie Per Pref | Backlog | Preferences are stored in separate cookies, one per `(namespace, key)`. | |
| req-web-cstate-cookie-2 | Path-Wide Visibility | Backlog | Cookies are written with `Path=/`. | |
| req-web-cstate-cookie-3 | Versioned Value Format | Backlog | Cookie values are `v<n>:<value>` strings; reads parse and validate the version. | Pairs with `req-web-cstate-version` |
| req-web-cstate-cookie-4 | Bounded Lifetime | Backlog | Cookies carry `Max-Age` ≈ 1 year; expired cookies fall back to the registered default. | |
| req-web-cstate-cookie-5 | Cookie Attributes | Backlog | Cookies are written with `SameSite=Lax` and `Secure` over HTTPS. `HttpOnly` follows the registered `js_readable` flag — set when `js_readable=False`, unset (the v0 default) when `js_readable=True`. | Documented in the threat-model section |
| req-web-cstate-cookie-6 | js_readable Substrate Switch | Backlog | Registering a pref with `js_readable=False` causes the cookie to carry `HttpOnly`; the JS module returns `null` on reads and refuses writes for that pref. | Pairs with `req-web-cstate-registry-1` |

---

### Per-Key Versioning
----
RID: `req-web-cstate-version`
Status: `Backlog`

Each registered preference carries a `version` integer. Cookies whose version prefix does not match the current registered version are discarded; the registered default takes over. This gives consumers a clean break path when they need to change a key's allowed values, semantics, or shape.

#### Implementation
- Cookie value format: `v<version>:<value>` (e.g. `v1:c`). Reads parse this on the server and on the client.
- Mismatch handling:
  - Server: `tap_web.client_state.get()` returns the registered default and emits a `client_state.version_mismatch` log event (DEBUG level, with `namespace`, `key`, `cookie_version`, `registered_version` so production analytics can spot stale rollouts).
  - Client: `TAP.clientState.get()` returns `null`; subscribers are not notified. The mismatched cookie is overwritten on the next `set()` call (which will write the current version).
- A consumer that needs to change a key's shape (e.g. expanding `fedramp.class` allowed values from `["a","b","c","d"]` to also include `"e"` is a value-set expansion that does NOT need a version bump; renaming `fedramp.class` → `fedramp.cert_class` IS a version bump because the cookie name changes too — except in that case the new key is simply registered fresh).
- Version bumps are rare. v0 starts every key at version `1`. The mechanism is here to absorb future shape changes without leaking stale state.
- A garbage-collection helper (Future) can sweep `tap_cs_*` cookies whose `(namespace, key)` is unregistered or whose version is mismatched, removing them from the browser. Out of v0 scope; documented under Future Work.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-cstate-version-1 | Versioned Read | Backlog | Server and client APIs both parse the `v<n>:` prefix and discard mismatched values in favor of the registered default. | |
| req-web-cstate-version-2 | Versioned Write | Backlog | Every write emits the current registered version in the cookie value. | |
| req-web-cstate-version-3 | Mismatch Logging | Backlog | Version mismatches log a structured event so rollouts can be observed. | |

---

### Server-Side Read API
----
RID: `req-web-cstate-server-api`
Status: `Backlog`

A small Python API panels and views call to resolve the active value of a preference at render time. Server-side reads are **opt-in per panel** per `req-web-cstate-when-server-side`; v0 does not inject state into every panel context.

#### Implementation
- Public functions in `tap_web.client_state`:
  ```python
  def get(
      request: HttpRequest,
      namespace: str,
      key: str,
      *,
      default: str | None = None,
  ) -> str:
      """Return the validated client-state value for *(namespace, key)*. Falls back
      to the explicit *default* (if provided) or the registered default when the
      cookie is missing, has a mismatched version, or has a value not in
      *allowed_values*."""

  def get_many(
      request: HttpRequest,
      keys: Sequence[tuple[str, str]],
  ) -> dict[tuple[str, str], str]:
      """Bulk read for panels that consume multiple preferences."""
  ```
- Resolution order for `get()`:
  1. Cookie present, version matches, value in `allowed_values` → return value.
  2. Cookie absent / version mismatch / value invalid → return explicit `default` if provided, else registered default.
  3. `(namespace, key)` not registered → raise `UnknownClientStateKeyError` (caller bug, not a runtime fallback).
- Server-side **write** is *not* in v0. Cookies are set by the JS module. A future helper (`set_response_cookie(response, namespace, key, value)`) can land when a server-driven settings UI shows up; v0 keeps server reads cheap and contention-free.
- The API is import-safe — registry access is lazy so plugin-registered prefs from later-loaded apps aren't a concern.
- For `js_readable=False` (HttpOnly) preferences, this server-side API is the **only** way to read the value — by definition the JS module cannot. The same `get()` call works for both substrates; the underlying cookie attribute is determined at registration time, not read time.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-cstate-server-api-1 | Validated Read | Backlog | `get()` returns the cookie value only when it parses, version matches, and value is in `allowed_values`; otherwise the registered default. | |
| req-web-cstate-server-api-2 | Default Override | Backlog | An explicit `default` argument overrides the registered default when the cookie resolution fails. | |
| req-web-cstate-server-api-3 | Unknown Key Raises | Backlog | Calling `get()` with an unregistered `(namespace, key)` raises `UnknownClientStateKeyError`. | |
| req-web-cstate-server-api-4 | Bulk Read | Backlog | `get_many()` resolves a list of `(namespace, key)` tuples in one call. | |
| req-web-cstate-server-api-5 | Substrate-Agnostic | Backlog | The server-side API works identically for `js_readable=True` and `js_readable=False` preferences; for `False` it is the only read path. | |

---

### When To Use The Server-Side Read API
----
RID: `req-web-cstate-when-server-side`
Status: `Backlog`

The default reading path is JS — `window.TAP.clientState.get/set/subscribe` running in the browser. The server-side `tap_web.client_state.get(request, ns, key)` API is a per-panel call panels make only when one of three documented criteria applies. v0 does not ship middleware that injects state into every panel context; pay for the server-side read only on the panels that need it.

#### Implementation
A panel opts into server-side reads when **any one** of the following applies:

1. **First-paint correctness matters.** The panel renders different HTML based on the preference and the wrong-default-then-fix flicker is user-visible on a primary content surface. Calling `tap_web.client_state.get(request, ns, key)` in `get_view_context()` produces the correct first paint with no client-side swap.
   - *Example (yes):* the indicator profile renders one specific class-variant statement as its primary content. Painting a wrong-class statement and then JS-swapping it would be visible.
   - *Example (no):* the compliance view embeds every class variant in its panel payload up-front and toggles in place; first paint always shows the right thing because the JS toggle runs synchronously on the in-DOM data.

2. **The preference influences a server-side query.** The panel uses the value to build a database query, gryphon search, or data-fetch parameter, and round-tripping through JS would be wasteful or incorrect.
   - *Example (yes, future):* a "preferred dimension scope" preference that filters which entities a search returns.
   - *Example (no):* a UI density preference that only affects CSS classes.

3. **The preference must be visible to a non-panel surface** (e.g. a Django view rendering an audit log, an exported PDF, an email template). Rare; documented case-by-case.

If none of the three apply, **JS-only is the right call.** Panels MUST NOT reach for `tap_web.client_state.get()` to "be consistent" or to keep two code paths in sync — the registry's discovery bridge already keeps the JS module's understanding aligned with the server's.

#### Development
- Panel authors should be able to defend their choice in code review with one of the three criteria above. If they can't, the panel uses JS-only.
- Adding server-side reads later is cheap (it's a single function call); removing them is also cheap. The decision is reversible per panel.
- v0 has exactly one panel using the server-side path: the FedRAMP indicator profile (per the indicator-profile requirement of `spec-fedramp-20x-ksi-class-preference.md`, fedramp_20x_ksi plugin repo). The compliance view, the Preference Switcher, and any future panels register their choice and the criterion that justifies it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-cstate-when-server-side-1 | Three Criteria Documented | Backlog | The spec enumerates exactly three opt-in criteria for server-side reads. | |
| req-web-cstate-when-server-side-2 | JS-Only Default | Backlog | Panels not meeting a criterion use the JS-only path; the spec explicitly forbids "consistency"-driven adoption. | |
| req-web-cstate-when-server-side-3 | Per-Panel Decision | Backlog | The opt-in is a per-panel decision; v0 does not inject state into every panel context. | |

---

### Preferences vs Session State
----
RID: `req-web-cstate-vs-session-state`
Status: `Backlog`

This requirement formally documents the boundary between this spec (preferences) and a future session-state spec, so future authors know which mechanism to reach for and don't bend either one out of shape.

#### Implementation
| | Preferences (this spec) | Session State (future spec) |
| --- | --- | --- |
| Lifetime | Persistent (months / years) | Ephemeral (minutes to hours) |
| Owner intent | "How I want things shown" | "Where I am in the flow" |
| Ergonomics | Registry of typed keys with allow-lists and defaults | Free-form key/value, often opaque blobs |
| Auth coupling | Useful when bound to user, but works fully anonymous | Almost always bound to a session/user |
| Storage v0 | Cookie | Django session framework (`django.contrib.sessions`) |
| Storage future | Per-user DB column when auth lands | Per-session DB row (already provided by Django) |
| Validation | Allow-list per key; mismatches drop to default | Trust whoever wrote it |
| API | `TAP.clientState.{get,set,subscribe}` / `tap_web.client_state.get(request, ns, key)` | `request.session_state` (future); built on `request.session` |

Examples of values that belong in **preferences** (this spec):
- Preferred FedRAMP class (`fedramp.class`).
- Preferred timezone, density, color theme.
- Preferred dimension scope filter.

Examples of values that belong in **session state** (future):
- Last visited page (for "Resume where you left off").
- Draft form values still being typed.
- "You have unread X" indicators.
- In-flight wizard state across multiple form steps.
- Recently-viewed entity history.

The two mechanisms are intentionally separate. The preference registry's allow-list-per-key shape is *wrong* for session state (you can't enumerate every possible draft form value). The session framework's free-form blob shape is *wrong* for preferences (no validation, no defaults, no registry). The Future Work section of this spec already calls out the need for a separate session-state mechanism; this requirement makes the boundary itself a first-class element of the spec rather than a Future bullet.

#### Development
- When in doubt about which mechanism a value belongs in, ask: "Will the value be enumerable up front?" If yes (a small set of allowed values, a default, a name in the registry) → preferences. If no (free-form, opaque, "whatever the user typed") → session state.
- A future `spec-web-session-state.md` will own the session-state mechanism. This spec links to it from the Philosophy section. Preferences code MUST NOT reach into `request.session` to bridge the two mechanisms; if a value needs both behaviors, that's a design smell and the spec author should split the value.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-cstate-vs-session-state-1 | Boundary Documented | Backlog | The spec carries an explicit table comparing preferences and session state. | |
| req-web-cstate-vs-session-state-2 | Decision Heuristic | Backlog | The spec offers a one-line heuristic (enumerable → preference; free-form → session state). | |
| req-web-cstate-vs-session-state-3 | No Cross-Reaching | Backlog | Preferences code MUST NOT read or write `request.session` to bridge the two mechanisms. | |

---

### Client-Side JS Module
----
RID: `req-web-cstate-js`
Status: `Backlog`

A small JS module exposed at `window.TAP.clientState` for reading, writing, and subscribing to preference changes from the browser.

#### Implementation
- Static asset path: `tap_web/static/tap_web/js/client-state.js`. Loaded in the base template head so panel-level scripts can rely on it.
- Public surface:
  - `TAP.clientState.get(namespace, key) -> string | null` — reads the cookie, parses the version prefix, validates against `allowed(namespace, key)`. Returns `null` when missing, version-mismatched, invalid, or registered with `js_readable=False`.
  - `TAP.clientState.set(namespace, key, value) -> boolean` — validates against `allowed(namespace, key)` AND that the key is `js_readable=True`. On success: writes the cookie (with the current registered version), dispatches a `tap:cstate-change` `CustomEvent` on `document` with `{detail: {namespace, key, value}}`, and notifies per-key subscribers. Returns `true` on success, `false` when the value was rejected or the key is `js_readable=False` (with a `console.warn`).
  - `TAP.clientState.subscribe(namespace, key, callback) -> unsubscribe` — registers `callback(value)` to fire when *that key* changes; returns an unsubscribe function. Subscriptions to `js_readable=False` keys never fire (the value can only change on the server).
  - `TAP.clientState.allowed(namespace, key) -> string[] | null` — returns the registered allowed values from the discovery bridge (see `req-web-cstate-bridge`). Returns `null` for unregistered keys.
  - `TAP.clientState.version(namespace, key) -> number | null` — returns the registered version from the bridge.
  - `TAP.clientState.isJsReadable(namespace, key) -> boolean | null` — convenience accessor on top of the discovery bridge.
- Cookie attributes when writing: `path=/; max-age=31536000; samesite=lax`. `Secure` is added when `location.protocol === "https:"`.
- The module avoids polluting the global scope beyond `window.TAP.clientState`. (A future companion module under `window.TAP.*` is acceptable.)
- No dependency on jQuery, HTMX, or any framework — pure DOM + cookie API.
- The module is idempotent on re-load (HTMX swaps that pull in the asset again don't re-bind subscribers).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-cstate-js-1 | Public Surface | Backlog | The module exposes `get`, `set`, `subscribe`, `allowed`, `version` on `window.TAP.clientState`. | |
| req-web-cstate-js-2 | Validated Write | Backlog | `set()` rejects values not in the allowed list, logs a warning, and returns `false`. | |
| req-web-cstate-js-3 | Change Event Dispatch | Backlog | A successful `set()` dispatches a `tap:cstate-change` CustomEvent and notifies per-key subscribers. | |
| req-web-cstate-js-4 | Cross-Listener Isolation | Backlog | Subscribers to one key are not invoked when an unrelated key changes. | |
| req-web-cstate-js-5 | Idempotent Reload | Backlog | Re-loading the asset does not duplicate subscribers or rebind multiple times. | |
| req-web-cstate-js-6 | Honors js_readable | Backlog | For keys registered with `js_readable=False`, `get()` returns `null`, `set()` returns `false` with a `console.warn`, and `subscribe()` callbacks never fire. | Pairs with `req-web-cstate-cookie-6` |

---

### Registry Discovery Bridge
----
RID: `req-web-cstate-bridge`
Status: `Backlog`

The client API needs the registry's `allowed_values` and `version` for each key so it can validate writes without an HTTP round-trip.

#### Implementation
- A small JSON payload — `{"<namespace>.<key>": {"allowed": [...], "default": "...", "version": N, "js_readable": true|false}}` — is rendered into a `<script type="application/json" id="tap-client-state-registry">` element in the base template.
- A context processor (`tap_web.context_processors.client_state_registry`) builds the dict from `iter_prefs()` and exposes it as a template variable. Already-registered context processors are the established pattern (see `spec-web-rendering.md`).
- The JS module reads the payload during initialization and caches it. Subsequent registry changes (rare; only on app reload) will not be picked up until the next page load.
- The payload includes only the metadata needed for client-side validation, not the human-readable description (which is reserved for the future settings-UI work and can be fetched on demand).
- Memory budget: with one registered key in v0 the payload is < 100 bytes; the design tolerates dozens of registered keys without measurable bloat.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-cstate-bridge-1 | Embedded JSON Payload | Backlog | The base template renders the registry payload into `#tap-client-state-registry` on every page. | |
| req-web-cstate-bridge-2 | Allowed Values Available | Backlog | `TAP.clientState.allowed(ns, key)` returns the array sourced from the embedded payload. | |
| req-web-cstate-bridge-3 | Version Available | Backlog | `TAP.clientState.version(ns, key)` returns the integer sourced from the embedded payload. | |
| req-web-cstate-bridge-4 | Context Processor | Backlog | A context processor exposes the registry to templates without per-view plumbing. | |
| req-web-cstate-bridge-5 | js_readable Available | Backlog | `TAP.clientState.isJsReadable(ns, key)` returns the boolean sourced from the embedded payload. | |

---

### Declarative HTMX Refresh
----
RID: `req-web-cstate-refresh-htmx`
Status: `Backlog`

A declarative way for a panel to say "when this preference changes, re-fetch me from the server." Saves every panel that wants server-side reactivity from rolling its own change → refetch wiring.

#### Implementation
- A panel root element opts in by adding `data-tap-cstate-bind="<namespace>.<key>[,<namespace>.<key>...]"`.
- A small piece of JS (in `client-state.js` or a sibling `panel-cstate-binding.js`):
  - On `DOMContentLoaded` and `htmx:afterSettle`, walks every element with `data-tap-cstate-bind`.
  - For each element, subscribes to each named key. On change, calls `htmx.trigger(el, "tap:cstate-refresh")`.
  - Panel templates that opt in declare `hx-trigger="load, tap:cstate-refresh from:closest [data-tap-cstate-bind]"` (or equivalent) so the refresh actually fires the panel's existing `hx-get`.
- This complements `req-web-cstate-refresh-subscribe` (the in-place client-side path); a panel author chooses one or the other (or both) per panel.
- The KSI indicator profile is the canonical use case for this requirement: it renders one class-variant statement server-side, and benefits from a refresh when the user picks a different class so the new statement appears with full server-side processing.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-cstate-refresh-htmx-1 | Declarative Attribute | Backlog | `data-tap-cstate-bind="<ns>.<key>"` on a panel root subscribes that panel to refresh on change. | |
| req-web-cstate-refresh-htmx-2 | Multi-Key Bindings | Backlog | A comma-separated list subscribes a panel to refresh when any listed key changes. | |
| req-web-cstate-refresh-htmx-3 | HTMX-After-Settle Rebind | Backlog | Panels swapped in via HTMX get their bindings re-applied automatically. | |

---

### Client-Side Subscription Refresh
----
RID: `req-web-cstate-refresh-subscribe`
Status: `Backlog`

For panels that already have all the data they need on the client, the change event drives an in-place DOM re-render — no server round-trip.

#### Implementation
- Panel-side JS subscribes via `TAP.clientState.subscribe(ns, key, callback)` and updates the DOM when the callback fires.
- The KSI compliance view is the canonical use case: the embedded subgraph payload already carries every class variant; switching classes is purely a DOM filter / text-swap operation. This was the original behavior backed by the ad-hoc `localStorage` key, and the migration (the class-preference spec's compliance-view migration requirement, fedramp_20x_ksi plugin repo) keeps the in-place path while moving the storage to the platform mechanism.
- Panel authors choose between this requirement and `req-web-cstate-refresh-htmx` based on whether the necessary data is already in the DOM. The decision is per-panel.
- Both paths can coexist on the same page: one panel using HTMX refresh, another using in-place subscription, both reacting to the same `tap:cstate-change` event.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-cstate-refresh-subscribe-1 | Subscribe API | Backlog | `TAP.clientState.subscribe(ns, key, cb)` fires the callback on every successful `set()` of that key. | |
| req-web-cstate-refresh-subscribe-2 | Unsubscribe Returned | Backlog | `subscribe()` returns a function that, when called, removes the subscriber. | |
| req-web-cstate-refresh-subscribe-3 | Coexistence With HTMX Path | Backlog | Subscription-based panels and HTMX-refresh panels can coexist on the same page without interference. | |

---

### Preference Switcher Panel Type
----
RID: `req-web-cstate-switcher-panel`
Status: `Backlog`

A standard `tap_web` panel type that renders a labeled selector for any registered preference. Drop it into a page layout and you have UI for free; no plugin-specific JS needed.

#### Implementation
- Panel type slug: `client-state-switcher`. Lives in `tap_web/panels/client_state_switcher/`.
- `Panel.config` schema:
  - `namespace: str` (required) — the preference namespace.
  - `key: str` (required) — the preference key.
  - `label: str` (optional) — display label; defaults to the registered `description`.
  - `style: "pills" | "dropdown"` (optional, default `"pills"`) — render mode.
  - `value_labels: dict[str, str]` (optional) — overrides for individual value labels (e.g. `{"a": "Class A", "b": "Class B", ...}`); falls back to the raw value if absent.
- Render flow:
  1. `get_view_context()` resolves the active value via `request.client_state[ns][key]`.
  2. Returns `{"active": active, "options": [{"value": v, "label": labels.get(v, v)} for v in pref.allowed_values], "label": display_label, "style": style}`.
- Template renders a horizontal pill row (default) or a `<select>` (when `style="dropdown"`). Each option is wired to call `TAP.clientState.set(ns, key, value)` on click / change.
- The panel is registered by `tap_web` itself in `TapWebConfig.ready()`, like the other standard panel types.
- Plugins reference the panel type from grift — they don't subclass it. The KSI plugin uses one instance for `fedramp.class` (see the class-preference spec's switcher-placement requirement, fedramp_20x_ksi plugin repo).
- Visual vocabulary mirrors the existing class-badge styling on the indicator profile so the switcher feels consistent with the panels it controls. The KSI plugin can ship a small CSS overlay if it wants stronger visual identity, but the default look is intentionally generic.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-cstate-switcher-panel-1 | Standard Panel Type | Backlog | The Preference Switcher is registered by `tap_web` as a standard panel type. | |
| req-web-cstate-switcher-panel-2 | Config-Driven | Backlog | A switcher instance is configured by `Panel.config.{namespace, key, label, style, value_labels}` with no plugin code. | |
| req-web-cstate-switcher-panel-3 | Active Value Highlighted | Backlog | The currently active value is visually highlighted on render. | |
| req-web-cstate-switcher-panel-4 | Click Writes Cookie | Backlog | Clicking an option calls `TAP.clientState.set()`, which writes the cookie and fires the change event. | |
| req-web-cstate-switcher-panel-5 | Pills + Dropdown Styles | Backlog | Both `pills` and `dropdown` render styles are supported via config. | |

---

### Scope Boundary And Migration Path
----
RID: `req-web-cstate-scope-boundary`
Status: `Backlog`

Documents the intentional v0 boundary at per-browser scope and the migration path for moving to per-grid or per-user storage in a future iteration.

#### Status Details
This requirement is documentation-only — no code lands under it. It exists so future work has an anchor.

#### Implementation
- **Per-browser scope is the v0 boundary.** A preference set on a desktop browser does not follow the user to a phone, a different machine, or a different browser profile.
- **Per-grid scope is not v0.** A user toggling "Class C" on Grid A does not affect their preferences on Grid B (each Grid runs in its own deployment with its own domain → cookie scope is naturally per-domain).
- **Per-user scope is Future work.** When Grid users have stable identity (post-auth roll-out), the natural progression is:
  1. Add a server-side `UserClientState(BaseModel)` table keyed on `(user, namespace, key)` storing the validated value, version, and `updated_at`.
  2. On login, migrate any cookie-resident values into the user row (server reads cookie once, writes to DB, clears the cookie). Subsequent reads come from the DB.
  3. `tap_web.client_state.get()` becomes auth-aware: anonymous requests still resolve via the cookie path; authenticated requests resolve via the user row.
  4. Writes from the JS module flow through a new `POST /api/v1/_internal/client-state/set` endpoint when authenticated; the cookie path remains for the anonymous case.
- This migration is intentionally additive — the panel-side `request.client_state[ns][key]` API stays identical; only the storage layer changes underneath. Plugin code does not need to be updated for the migration.
- The `version` field in the registry continues to do its job through the migration: a per-user row whose version doesn't match the registered version is treated as missing, exactly as a mismatched cookie is.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-cstate-scope-boundary-1 | Per-Browser Scope Documented | Backlog | This spec explicitly states per-browser scope as the v0 boundary. | |
| req-web-cstate-scope-boundary-2 | Migration Path Documented | Backlog | The migration to per-user server-side storage is enumerated, with explicit guarantees that the panel-side API is unchanged. | |

---

### Existing-Spec Touch-Ups
----
RID: `req-web-cstate-spec-touchups`
Status: `Backlog`

This requirement tracks the amendments made to existing specs alongside this one, so reviewers and downstream readers can find every spec affected by the introduction of the panel client-state mechanism.

#### Implementation
- **`spec-web-page.md`** — A short "Page-Scoped State Dimensions" subsection (or addition to the Philosophy section) describing the three state layers (URL params, page-persistent vars, client state) with cross-references. No new requirement RID; this is a documentation-only edit because the existing page requirements (`req-web-page-params`, `req-web-page-local`) already cover what they need to.
- **`spec-web-panel.md`** — `req-web-panel-inputs` is amended to note that panels MAY opt into reading client state via `tap_web.client_state.get(request, ns, key)` per `req-web-cstate-when-server-side`. A new ACID is added asserting that the opt-in is per-panel and v0 does not inject state into every panel context.
- **`spec-fedramp-20x-ksi-compliance-view.md`** (fedramp_20x_ksi plugin repo) — its class-select requirement is amended: the implementation reads/writes via `TAP.clientState.get/set("fedramp", "class")` instead of the ad-hoc `localStorage` key `tap-ksi-class-selection`. The dead `tap-ksi-class-selection` localStorage entry is removed unconditionally on first load; its prior value is not preserved. The compliance view stays JS-only and does not consume the server-side API.
- **`spec-fedramp-20x-ksi-indicator-profile.md`** (fedramp_20x_ksi plugin repo) — its statement and header requirements are amended: the initial active class follows the `fedramp.class` preference (default `b`). The indicator profile is the v0 panel that opts into the server-side read API. New ACIDs assert the initial-class behavior. The existing per-row JS toggle still works on top of that initial value.
- **`spec-fedramp-20x-ksi-finding-profile.md`** — Adds a Future Work bullet noting that any future class-scoped rollups inside the finding profile will consume the same `fedramp.class` preference. No v0 behavior change.
- **`spec-fedramp-20x-ksi-class-preference.md` (new)** — Owns the FedRAMP-side wiring details (default rationale, switcher placement above the compliance view, panel-by-panel consumption). Cross-referenced from this spec under `req-web-cstate-spec-touchups-2` so the platform spec stays the discoverable entry point.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-cstate-spec-touchups-1 | Page Spec Touch-Up | Backlog | `spec-web-page.md` documents the three state layers with cross-references. | |
| req-web-cstate-spec-touchups-2 | Panel Spec Touch-Up | Backlog | `spec-web-panel.md` documents the per-panel opt-in for server-side reads via `tap_web.client_state.get()`, not a pipeline-injected mapping. | |
| req-web-cstate-spec-touchups-3 | KSI Compliance View JS-Only Adoption | Backlog | `spec-fedramp-20x-ksi-compliance-view.md` documents the JS-only adoption of the platform mechanism; the legacy `tap-ksi-class-selection` localStorage key is removed unconditionally on first load with no value preservation. | |
| req-web-cstate-spec-touchups-4 | KSI Indicator Profile Initial-Class | Backlog | `spec-fedramp-20x-ksi-indicator-profile.md` documents the initial-class behavior, including the indicator profile's opt-in to the server-side read API per `req-web-cstate-when-server-side` criterion 1. | |
| req-web-cstate-spec-touchups-5 | KSI Finding Profile Future Bullet | Backlog | `spec-fedramp-20x-ksi-finding-profile.md` carries a Future bullet for class-scoped rollups. | |
| req-web-cstate-spec-touchups-6 | KSI Class Preference Spec Lands | Backlog | `spec-fedramp-20x-ksi-class-preference.md` lands in the KSI plugin specs alongside this spec. | |

---

### Cookie Input Sanitization
----
RID: `req-web-cstate-sanitize.sec`
Status: `Backlog`

Cookie values arrive untrusted. The server API must never pass them through to template rendering or downstream code without validation.

#### Implementation
- `tap_web.client_state.get()` always validates the cookie value's version prefix and value against the registered `allowed_values` list before returning. Anything outside the allowed set, or with a mismatched version, is treated as missing and falls back to the registered default.
- Validation is exact-match against the `allowed_values` tuple — no regex, no normalization, no substring matching, no case-folding.
- Cookies whose name matches the `tap_cs_*` prefix but whose `(namespace, key)` is not registered are ignored on the server. The client's idempotent-load step removes them on next page load to clean up stale state from previous installs.
- The server **never echoes** the cookie value back into HTML or JSON without going through the same validation. Templates and panel code consume the value via `request.client_state[ns][key]` (or `client_state[ns][key]` in templates), not from `request.COOKIES.get(...)` directly.
- The client API similarly validates before writing — invalid values are dropped with a `console.warn` rather than persisted.
- Defense-in-depth: even a malicious browser plugin setting wild cookie values cannot reach template context — the validation gate stops them at the server boundary.
- Cross-references: `spec-web-panel-security.md` for the broader panel-side input-handling discipline; `spec-grid-entity.md` for the project-wide entity validation idiom.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-cstate-sanitize-1.sec | Allow-List Read Validation | Backlog | The server-side read API validates against `allowed_values` and falls back to default on mismatch. | |
| req-web-cstate-sanitize-2.sec | Versioned Read Validation | Backlog | The server-side read API rejects cookies whose version prefix does not match the registered version. | |
| req-web-cstate-sanitize-3.sec | Allow-List Write Validation | Backlog | The client-side write API rejects values not in `allowed_values` for that key. | |
| req-web-cstate-sanitize-4.sec | No Raw Cookie Echo | Backlog | Templates and client code consume the validated mapping, never the raw cookie. | |
| req-web-cstate-sanitize-5.sec | Stale Cookie Cleanup | Backlog | Cookies named `tap_cs_*` whose `(namespace, key)` is not registered are ignored by the server and removed by the client when noticed. | |

---

## Future Work

- **Session State as a separate mechanism.** A future `spec-web-session-state.md` will own the ephemeral, free-form, session-scoped state described in `req-web-cstate-vs-session-state` — built on `django.contrib.sessions`, exposed via `request.session_state`, with no allow-list-per-key validation. The two mechanisms intentionally stay separate; the boundary is documented in this spec so a future author has a clear pointer rather than reaching to bend preferences into a session-shaped shape.
- **Per-user storage backend for preferences.** When auth-bound user accounts land, preferences migrate to a server-side `UserPreference(BaseModel)` table keyed on `(user_id, namespace, key)` per `req-web-cstate-scope-boundary`. The panel-side API (`tap_web.client_state.get(request, ns, key)`) stays the same; the cookie path becomes the anonymous fallback.
- **Always-on context injection.** v0 ships per-panel server-side reads. If a future iteration finds many panels each calling `tap_web.client_state.get()` for the same keys repeatedly per request, a per-request cache (or a middleware-injected `request.client_state` mapping) becomes a cheap optimization. v0 does not pay for this prematurely; the request-attribute API stays open for future use.
- **Server-side write API.** A `set_response_cookie(response, namespace, key, value)` helper for views that want to set a preference programmatically (e.g. a settings form submit, or a server-driven setter triggered by a workflow event). Held until a real settings UI demands it. Required for `js_readable=False` preferences whose write path cannot live in JS.
- **First HttpOnly preference.** v0 ships `js_readable=True` for every registered preference. The first concrete `js_readable=False` preference will exercise the substrate-switching path (cookie attribute, JS module behavior, server-side write API requirement above). The implementation needs to be exercised end-to-end before the first `js_readable=False` value is registered; a follow-on spec amendment will track that.
- **Settings UI.** A dedicated page (or topbar dropdown) listing every registered preference with its description and a value picker. v0 lets each consumer plugin own its own UI surface; a global page becomes worth the lift once 5+ preferences exist.
- **Cross-tab sync.** Use `BroadcastChannel("tap-client-state")` (or storage events on a shadow `localStorage` key) so changes in one tab propagate to other open tabs without waiting for a navigation. Held — single-tab users are the dominant case for now.
- **Typed values.** v0 stores plain strings. If a preference ever needs a list, integer, or complex shape, extend `ClientStatePref` to declare a `parser` / `serializer` pair and make the server / client APIs type-aware.
- **Per-page overrides.** A per-page preference scope so a page can opt out of a global preference for some specific reason (e.g. a "compare classes side-by-side" page that ignores `fedramp.class`). Likely a `data-tap-cstate-override` attribute that scopes a panel's reads to a different value without writing the cookie.
- **Stale-cookie sweeper.** A periodic JS housekeeping pass that removes `tap_cs_*` cookies whose `(namespace, key)` is unregistered or whose registered version no longer matches. v0 handles this lazily on the read path; a sweep is cheap insurance.
- **Preference-change audit.** When a preference change has compliance implications (e.g. a user records *which* class they were operating in when they reviewed an indicator), capture the change to an audit log. Out of v0 scope; the cookie is a UX preference, not a record of intent.
- **Plugin-scoped sub-registries.** If preference name collisions across plugins ever become a real concern, formalize per-plugin sub-registries and inheritance rules (mirroring `ScopedRegistry[T]` patterns from `tap_grid`).

## Status Vocabulary

| Status States |  |
| --- | --- |
| Backlog |  |
| Backlog | Requirement is accepted and ready to be implemented |
| Backlog |  |
| Backlog |  |
| Backlog |  |
| Backlog |  |
| Deprecating |  |
| Deprecated | Not part of the current architecture and should not be implemented |

## RID Format

`req-<application>-<specification>-<feature>-<sub-feature>[.sec]`

## Requirements Format

`RID: `...``
`Status: `...``

| Sub-Sections | (as needed) |
| --- | --- |
| Status Details |  |
| Implementation |  |
| Development |  |
| Acceptance Criteria |  |
| Future |  |
