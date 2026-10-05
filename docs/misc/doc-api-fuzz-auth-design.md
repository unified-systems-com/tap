# Design memo — authenticated `api-fuzz`: boot profile + credential path

Status: **BUILT 2026-08-10** — the design below is implemented as specced in the
`api-fuzz` job (.github/workflows/product-lines.yml), with George's three risk decisions
(2026-08-10) folded in: **viewer-role differential pass → deferred, named in the spec
tail** (not built); **schemathesis → PINNED in the job** (@4.24.3, both passes — the
"unpinned uvx" open risk in §6 is thereby closed); **minted-session-bypasses-login-audit
→ ACCEPTED** (throwaway CI stack). Target requirement: `req-dev-validation-api-fuzz-3`
"Authenticated surface" (specs/spec-dev-validation.md) — flipped Implemented with this
change. Line numbers below were verified against origin/main as of 2026-08-10.

## 1. Problem

The CI `api-fuzz` job (.github/workflows/product-lines.yml:312-381) boots a `core_dev`
stack and runs `uvx schemathesis run` against `/api/v1/openapi.json` with
`--checks not_a_server_error,response_schema_conformance --max-examples 20 --workers 2`
(lines 372-374). Every mounted router carries `auth=session_auth` (tap_api/api.py:28-32,
plugin routers at :122); only `GET /api/v1/` is `auth=None` (api.py:45). So the fuzz
exercises the auth wall (401/403 must not 500) and almost nothing behind it. fuzz-3 wants
the authorized surface fuzzed with a throwaway credential.

George's framing — "a boot profile that supports static credentials" — needs one
correction from the verified code: **credentials deliberately never live in boot
profiles**. The admin credential path is env-based by design (`DJANGO_SUPERUSER_*` →
boot's auth phase; "never from the boot profile, so no secret value lives in
config-as-code (req-boot-secrets)" — tap_auth/sync.py:338-341). The profile's `auth`
section only carries providers / initial-admin emails / toggles
(boot/operator_sso.boot.json:4-21; readers in tap_auth/boot.py:85-97). Consequence: the
right design touches **no profile at all** — `core_dev` already suffices.

## 2. Verified findings

**What `session_auth` accepts.** `tap_api/auth.py:7-9`: `session_auth = ninja.security.django_auth`.
In the pinned django-ninja (>=1.5, pyproject.toml:39; inspected live in the container),
`django_auth = SessionAuth()`, an `APIKeyCookie` keyed on the `sessionid` cookie that
accepts any request whose Django session resolves to an authenticated user
(ninja/security/session.py). **Load-bearing detail:** `APIKeyCookie.__init__(csrf=True)`
runs Django's CSRF check on every non-exempt operation and raises `HttpError(403, "CSRF
check Failed")` on failure (ninja/security/apikey.py:44-53 → ninja/utils.py:check_csrf).
So an authenticated fuzz of POST/PUT/PATCH/DELETE needs **both** a `sessionid` cookie
**and** a `csrftoken` cookie + matching `X-CSRFToken` header, or every write op collapses
to 403 and the "authenticated" pass is authenticated in name only. (Over plain http
Django only checks `Origin` when the client sends one; curl/schemathesis don't — no
`CSRF_TRUSTED_ORIGINS` work needed.)

**Existing throwaway-credential machinery (zero new code needed):**
- Spawn resolves an admin password (`TAP_DEV_ADMIN_PASSWORD` → Keychain → random,
  scripts/spawn-session.sh:993-1002), writes `.dev-credentials` (:1006-1012), and passes
  `DJANGO_SUPERUSER_USERNAME/PASSWORD/EMAIL` env into `manage.py boot --profile <id>`
  (:1024-1028). `scripts/gate-lean:42` shows the CI-style non-interactive pattern:
  `TAP_DEV_ADMIN_PASSWORD="leanboot-throwaway-$$"`.
- Boot's auth phase (`ensure_initial_admin`, tap_auth/sync.py:333-400) is the single
  idempotent create-or-update of the admin from that env; it **refuses** an empty
  password (:363-371) and joins the user to the protected `tap_admin` group (grants
  flow through the service boundary; `is_superuser` is not a bypass, :344-347).
- **Session minting already exists**: `tap_web/skills/drive-browser/mint_session.py`
  creates a real DB session for an existing user via `manage.py shell < mint_session.py`
  and prints `SESSIONKEY=<key>`. It fail-closes unless `settings.DEBUG` is True
  (mint_session.py:33-38) — the same "structurally inert on hardened systems" discipline
  as the dev-passkey machinery. The drive-browser skill already uses exactly this to
  reach auth-walled pages.

**The CI stack's state.** The `api-fuzz` job only does `docker compose up -d` + a
`manage.py health` poll (product-lines.yml:340-353). The entrypoint runs pre-boot +
migrate + serve; `manage.py boot` (population **and the auth phase**) "still runs at
spawn time" (docker/entrypoint.sh:99-102) — i.e. **the fuzz stack currently has no users
at all**. Any authenticated design must run `manage.py boot` (or equivalent) in the job.
`DEBUG` is `"true"` in the stack (docker-compose.yml:175; the CI overlay
docker-compose.ci.yml doesn't touch it; settings default is also true,
tap/settings.py:44), so the DEBUG-gated mint works in CI. `core_dev` has no `auth`
section (boot/core_dev.boot.json), so `TAP_LOCAL_PASSWORD_ENABLED` defaults True
(tap_auth/boot.py:145-147) and `profile_kind` is `dev_local` (core_dev.boot.json:3).

**Profile-sprawl cost of a new shipped profile (verified, real):** every
`boot/*.boot.json` is auto-swept by `ProfileResolutionGuard` per-commit and by the
pre-boot/cold-boot gate per profile (tap_boot/guards/profile_resolution.py:1-14), plus
tap_boot's own shipped-profile tests (tap_boot/tests/test_shipped_profiles_resolve.py).
A new profile buys those costs forever.

**Map discipline:** the api-fuzz Map row is generated from the `DeclaredSurface` entry at
tap/guards/surfaces.py:157-163 (`render_map_markdown()` in tap/guards/report.py writes
the block between markers in spec-dev-validation.md; declared-surface RIDs are
machine-checked to resolve). Flipping fuzz-3 means editing surfaces.py text + the spec's
ACID table + regenerating, not hand-editing the Map.

**Orthogonal machinery, confirmed not applicable:** `bootstrap_dev_passkey` + the
3-layer dev-import defence gate *passkey credential import* on `profile_kind ==
"dev_local"` (tap_auth/boot.py:150-160) — a browser-ceremony path the headless fuzzer
never touches. `auth_sessions` is the invalidation banhammer, not a minting path.

## 3. Recommended design

**Auth method: minted DB session + CSRF cookie pair, carried as two static schemathesis
headers. Zero new auth code.**

1. **Mint the user via the real boot path** (mirrors spawn, exercises boot's auth phase
   in CI as a side benefit — req-boot-spawn-bridge's "same path everywhere"):
   in-job `PW="ci-fuzz-$(openssl rand -hex 16)"`, then
   `docker compose exec -T -e DJANGO_SUPERUSER_USERNAME=admin -e DJANGO_SUPERUSER_PASSWORD="$PW"
   -e DJANGO_SUPERUSER_EMAIL=admin@ci-fuzz.tap.localhost web uv run python manage.py boot --profile core_dev`.
   `core_dev` population is empty and plugins are pre-installed by the entrypoint, so
   this is cheap. The password is per-run garbage, never persisted, never echoed.
2. **Mint the session**: `docker compose exec -T web uv run python manage.py shell
   < tap_web/skills/drive-browser/mint_session.py` → `SESSIONKEY=…`. DEBUG-gated
   fail-closed; the established house mechanism (drive-browser skill).
3. **Mint the CSRF pair**: `curl -c jar "$base/auth/passkey/login/"` — the login page
   renders a form, so Django sets a `csrftoken` cookie; extract it. Header
   `X-CSRFToken: <that value>` + cookie `csrftoken=<same>` satisfies Django's
   double-submit check for the whole run (the secret is stable; no rotation mid-run —
   nothing in the API mutates the session or the user's password, so
   `_auth_user_hash` stays valid too).
4. **Canary before fuzzing (the honesty check)**: `curl -fsS -H "Cookie: sessionid=$KEY"
   "$base/api/v1/entity-types/"` must return 200 (it was `/api/v1/entities/` until that router was removed, Issue# 957 - tap). This is what prevents the silent failure
   mode this whole design worries about — an "authenticated" pass that is actually
   fuzzing 401s. Fail the step loudly if the canary isn't 200.
5. **Authenticated schemathesis pass** (in addition to, not instead of, the existing
   unauthenticated pass — the 401-must-not-500 property stays covered):
   `uvx schemathesis run "$schema" --checks not_a_server_error,response_schema_conformance
   --max-examples 20 --workers 2 -H "Cookie: sessionid=$KEY; csrftoken=$TOK"
   -H "X-CSRFToken: $TOK"` → `schemathesis-auth.log`, uploaded as a second artifact.
   (Verify the `-H/--header` spelling against whatever schemathesis version `uvx`
   resolves on the day of implementation; the job runs it unpinned — pre-existing risk,
   named below.)
6. **Profile: reuse `core_dev` unchanged.** No new profile, no profile edits, no new
   settings, no new Python.

**Why fuzzing as `tap_admin` is right for v0:** highest-capability actor ⇒ maximal
reachable surface ⇒ maximal 5xx-hunting coverage, and the service layer is still fully
engaged (superuser is not a bypass). A `tap_viewer` differential pass (writes must 403,
never 500/succeed) is a genuinely valuable *later* rung — name it in the spec tail,
don't build it now.

**Mutation care:** authenticated fuzz WILL create garbage entities/edges/searches.
The stack is job-scoped and discarded, and the job's step order puts both fuzz passes
last — nothing downstream reads the DB. Ordering within the job: run the unauth pass
*before* minting anything is unnecessary (an existing admin user doesn't change the
anonymous 401 surface); keep boot early so one health-wait covers everything. One real
self-interference risk: fuzz-created rows feed back into subsequent GET/list examples —
that's a feature (it hunts serialization 5xxs on adversarial stored data), and
`--max-examples 20` bounds the volume.

## 4. Alternatives rejected

- **New `api_fuzz.boot.json`** — rejected. Zero config delta vs `core_dev` (credentials
  can't live in profiles anyway, req-boot-secrets), while permanently joining
  `ProfileResolutionGuard`, cold-boot per-profile resolution, and the shipped-profile
  tests. Pure sprawl cost, no benefit. If a distinct fuzz posture ever emerges (e.g. a
  plugin-union fuzz under `test_all`), reuse *that* existing profile the same way.
- **Password login flow via curl (allauth `/auth/login/` form)** — workable with zero new
  code (`TAP_LOCAL_PASSWORD_ENABLED` defaults True) but strictly worse: CSRF-token HTML
  scraping, redirect handling, allauth rate-limit state, coupling CI to login-form
  markup. The login path has its own tests; the fuzzer doesn't need to re-prove it.
- **Dev-only token auth in tap_api** — rejected. tap_api/auth.py:4 explicitly reserves
  token auth as the single evolution point *when product demand arrives*; adding auth
  code to a production surface for a CI convenience inverts that, and every new accepted
  credential type on the API is attack surface (security-posture doctrine: this is not a
  cheap edge, it's a new door).
- **A new `mint_ci_session` management command** — not needed for v0; `mint_session.py`
  already exists, is DEBUG-fail-closed, and is exercised by the drive-browser skill. The
  one smell (CI depending on a file under `tap_web/skills/`) is worth fixing only if/when
  fuzz-2 flips this job into the required `gate` — promotion to a `manage.py` command
  (same DEBUG gate, INTERNAL_ONLY-style) is the named follow-up, not part of this change.
- **Pre-seeding a user via `manage.py shell` ORM writes instead of `manage.py boot`** —
  rejected; boot's auth phase is the canonical, idempotent, already-tested path
  (ensure_initial_admin), and running real boot in this lane adds CI coverage of a phase
  currently only exercised at spawn time.

## 5. Implementation sketch (ordered)

1. **Workflow: boot + credential step** (~15 lines YAML in the `api-fuzz` job): generate
   `PW`, run `manage.py boot --profile core_dev` with the three `DJANGO_SUPERUSER_*` envs,
   after the health wait. Effort: S (~30 min incl. one CI iteration).
2. **Workflow: session + CSRF mint step** (~15 lines): mint via
   `manage.py shell < tap_web/skills/drive-browser/mint_session.py`, parse `SESSIONKEY=`;
   curl the passkey login page into a cookie jar, extract `csrftoken`. Effort: S.
3. **Workflow: canary + authenticated pass** (~25 lines): 200-canary on
   `/api/v1/entity-types/` (fail loud), authed `uvx schemathesis run` with the two `-H`
   headers, tee to `schemathesis-auth.log`, second upload-artifact. Keep
   `continue-on-error: true` (report-only until fuzz-2). Effort: S/M (~1-2 h — CI
   iteration + verifying the current schemathesis CLI header flag).
4. **Spec + Map flip**: spec-dev-validation.md — fuzz-3 ACID row → Implemented, update
   the "As built" prose (:485-495) and the open tail (viewer-differential pass joins the
   tail); tap/guards/surfaces.py:157-163 — update the api-fuzz `DeclaredSurface`
   status/enforced_by text; regenerate the Map block. Effort: S (~30 min).
5. **Named follow-ups (not in scope)**: fuzz-2 gate flip after a track record;
   `tap_viewer` differential pass; promote mint_session to a management command if this
   becomes gate-load-bearing; pin the schemathesis version.

Total: about half a day including CI iterations. New Python code: **zero**.

## 6. Security notes + risks deliberately left open (req-sec-honest-risk)

- **No long-lived secret anywhere**: password is `openssl rand` per run, lives only in
  job-step memory/env; session key exists only in the throwaway DB (tmpfs, fsync off —
  it literally cannot survive the runner). Nothing lands in the repo, artifacts, or logs
  (don't echo `PW`/`SESSIONKEY`; GH won't mask them since they're not registered secrets).
- **Structural prod-unreachability of the mint**: `mint_session.py` refuses when
  `settings.DEBUG` is False (deployments run DEBUG=False), and using it at all requires
  `exec` into the container — an attacker with that access has already won. Same
  genesis-below-the-capability-gate posture as the bootstrap machinery: it's dev
  infrastructure below authz, fenced by the dev-mode signal, not by an invented actor.
- **Open: fuzzing only as `tap_admin`** — authz-differential correctness (viewer writes
  must 403) is NOT covered by this rung; named in the spec tail, deliberately deferred.
- **Open: minted sessions bypass the login audit path** — the session appears without a
  login event. Acceptable on a discarded CI stack; one more reason the management-command
  promotion (with a log line) is the right shape if this ever leaves report-only.
- **Open: unpinned `uvx schemathesis`** — supply-chain + CLI-drift risk, pre-existing in
  the job today; worth pinning when fuzz-2 makes the job required.
- **Open: authenticated fuzz volume** — 20 examples/op of admin-privilege writes is
  bounded today; raising `--max-examples` later changes both runtime and the amount of
  garbage the GET surface re-serializes. Revisit when measuring the `test_all` rung.
- **CSRF pair is not a weakening**: presenting cookie+header is exactly Django's
  double-submit contract; we hold the session, so we legitimately hold CSRF authority.

## TL;DR

1. No new profile and no new auth code: reuse `core_dev` + the env-based throwaway-admin path — credentials never live in profiles by design (req-boot-secrets), so "static credentials" = per-run `openssl rand` env, the gate-lean pattern.
2. The CI stack currently has zero users (entrypoint never runs `manage.py boot`); add an in-job `manage.py boot --profile core_dev` with `DJANGO_SUPERUSER_*` env — the same canonical path spawn uses.
3. Auth carrier: mint a real DB session with the existing DEBUG-fail-closed `tap_web/skills/drive-browser/mint_session.py`, grab a `csrftoken` from the login page, and pass both to schemathesis as static `Cookie` + `X-CSRFToken` headers — CSRF is load-bearing (ninja's `django_auth` 403s every write without it).
4. Keep the unauth pass, add a 200-canary (so "authenticated" can't silently mean fuzzing 401s), run the authed pass report-only with the same no-5xx + conformance checks; garbage writes are fine on the discarded tmpfs stack.
5. fuzz-3 flips Implemented via: the 3 workflow steps + spec ACID row + `tap/guards/surfaces.py:157` text + Map regen; named-open: admin-only fuzzing (no viewer differential), unpinned schemathesis, mint bypasses login audit. ~Half a day, zero new Python.
