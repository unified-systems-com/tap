# Multi-Session Dev Environment — Smoke Test

## Philosophy

After a developer follows the onboarding procedure in [spec-dev-multisession.md](spec-dev-multisession.md) and attaches a Claude Code session inside the new worktree, that session needs a fast, deterministic way to verify the environment is healthy: namespaced correctly, reachable on the assigned ports, migrated, seeded, and not colliding with the primary stack. This spec captures the smoke test as an ordered set of checks with exact commands and expected output. The attached Claude session (or developer) runs them top-to-bottom; any failure halts and is reported.

The smoke test is also the regression harness for `req-dev-multisession-compose-parameterized-3` (two stacks coexist) and the future spawn-script's success criterion.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Detect Misconfig | Catch wrong project namespace, wrong host ports, missing env vars, or broken `.env.local`. |
| 2. | Prove Isolation | Confirm the new stack does not share containers, networks, volumes, or ports with the primary stack. |
| 3. | Prove Data Pipeline | Confirm migrations applied and plugin data seeded. |
| 4. | Fast Feedback | Whole suite runs in under a minute on a warm machine. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-dev-multisession-smoketest-runtime | [Runtime Reachability](#runtime-reachability) | Proposed | Stack up + responsive |
| req-dev-multisession-smoketest-isolation | [Isolation](#isolation) | Proposed | No collision with primary |
| req-dev-multisession-smoketest-data | [Data Plane](#data-plane) | Proposed | Migrations + seed |
| req-dev-multisession-smoketest-admin | [Admin Bootstrap](#admin-bootstrap) | Proposed | Superuser created and credentials file present |

### Runtime Reachability
----
RID: `req-dev-multisession-smoketest-runtime`

Status: `Proposed`

The new session's stack must be running with the namespace and ports declared in `.env.local`, and Django must respond both on the direct `WEB_PORT` (port-binding proof) and on the labeled `<TAP_SESSION_LABEL>.tap.localhost:<WEB_PORT>` URL (browser-disambiguation convention from `req-dev-multisession-browser-disambiguation`). The labeled form is the canonical URL to point a browser at — it makes the active session visible in the address bar — and the smoke test verifies it works end-to-end (DNS resolution + Django `ALLOWED_HOSTS`).

#### Procedure

Run from inside the new worktree (`~/tap-sessions/<name>`):

```bash
# 1. Resolve the override layer correctly.
scripts/dc config | grep -E '^(name:|        published:)' | head -5
```

Expected: `name:` matches your `COMPOSE_PROJECT_NAME` (e.g. `tap_cli`), and the two `published:` lines match your `WEB_PORT` and `POSTGRES_PORT`.

```bash
# 2. Both services are running and healthy.
scripts/dc ps
```

Expected: 2 services (`db`, `web`), `db` shows `(healthy)`, `web` shows `running`.

```bash
# 3. Web responds on the assigned host port (direct form — proves port binding).
WEB_PORT=$(grep ^WEB_PORT .env.local | cut -d= -f2)
curl -sI http://localhost:${WEB_PORT}/ | head -1
```

Expected: an HTTP status line (200/302/etc — any response proves the port is bound and Django is serving).

```bash
# 4. Web responds on the labeled URL (canonical form for browsers).
LABEL=$(grep ^TAP_SESSION_LABEL .env.local | cut -d= -f2)
curl -sI http://${LABEL}.tap.localhost:${WEB_PORT}/ | head -1
```

Expected: same HTTP status line as step 3. This proves the OS resolves `*.localhost` to 127.0.0.1 and Django's `ALLOWED_HOSTS` accepts the subdomain — i.e. the canonical browser URL `http://<session>.tap.localhost:<port>/` works end-to-end. A connection-refused or `400 Bad Request: Invalid HTTP_HOST` here means either the resolver doesn't map `*.localhost` (rare on macOS/modern Linux) or `ALLOWED_HOSTS` was overridden without `.localhost`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-smoketest-runtime-1 | Override resolved | Proposed | `scripts/dc config` shows the project name and ports from `.env.local`. | |
| req-dev-multisession-smoketest-runtime-2 | Services up | Proposed | `scripts/dc ps` shows `db` healthy and `web` running. | |
| req-dev-multisession-smoketest-runtime-3 | Direct URL responds | Proposed | `curl http://localhost:${WEB_PORT}/` returns an HTTP status line. | |
| req-dev-multisession-smoketest-runtime-4 | Labeled URL responds | Proposed | `curl http://${TAP_SESSION_LABEL}.tap.localhost:${WEB_PORT}/` returns an HTTP status line. | Verifies `req-dev-multisession-browser-disambiguation` end-to-end. |

### Isolation
----
RID: `req-dev-multisession-smoketest-isolation`

Status: `Proposed`

The new stack must not share containers, networks, volumes, or host ports with the primary `tap` stack. If the primary is up, both must be up simultaneously without conflict; if the primary is down, that's fine — the check is about absence of collision artifacts.

#### Procedure

```bash
# 1. Container names are namespaced (prefixed with COMPOSE_PROJECT_NAME).
docker ps --format '{{.Names}}' | grep -E '^(tap-|tap_)'
```

Expected: at least one row prefixed with your `COMPOSE_PROJECT_NAME` (e.g. `tap_cli-web-1`); no other project's container names overlap.

```bash
# 2. Volumes are namespaced.
docker volume ls --format '{{.Name}}' | grep -E '^(tap_|tap-)'
```

Expected: `<project>_postgres_data`, `<project>_venv`, and `<project>_uv_cache` volumes for your project. If the primary `tap` stack is also up, you'll see the primary stack's separate `tap_*` volumes as separate rows.

```bash
# 3. Host ports do not collide.
PROJECT=$(grep ^COMPOSE_PROJECT_NAME .env.local | cut -d= -f2)
docker compose -p "$PROJECT" port web 8000
docker compose -p "$PROJECT" port db 5432
```

Expected: each prints `0.0.0.0:<your-port>`. The reported ports must match your `.env.local`.

```bash
# 4. If the primary is up, confirm both projects coexist with distinct ports.
docker compose -p tap ps 2>/dev/null && docker compose -p "$PROJECT" ps
```

Expected (if primary is up): both project listings show 2 services each, with non-overlapping host ports.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-smoketest-isolation-1 | Containers namespaced | Proposed | Container names carry the project prefix. | |
| req-dev-multisession-smoketest-isolation-2 | Volumes namespaced | Proposed | Postgres, container venv, and uv cache volume names are project-scoped. | |
| req-dev-multisession-smoketest-isolation-3 | Ports match `.env.local` | Proposed | `docker compose port` returns the configured host ports. | |
| req-dev-multisession-smoketest-isolation-4 | Coexistence with primary | Proposed | When primary is up, both projects run simultaneously. | Skip if primary is down |

### Data Plane
----
RID: `req-dev-multisession-smoketest-data`

Status: `Proposed`

Migrations must be applied and plugin seed data loaded.

#### Procedure

```bash
# 1. No unapplied migrations.
scripts/dc exec web uv run python manage.py migrate --check
```

Expected: exits 0 with no "would apply" output. Non-zero means migrations are pending — return to onboarding step 5.

```bash
# 2. Seed data present (Entity table non-empty).
scripts/dc exec web uv run python manage.py shell -c \
  "from tap_grid.models import Entity; print(Entity.objects.count())"
```

Expected: a positive integer (typically dozens to thousands depending on what plugins are installed). Zero means seed didn't run — return to onboarding step 6. Note: `Entity` is the spine and is not a `BaseModel` subclass, so it has no `all_objects` manager — use `Entity.objects` directly. Tombstoned entities still count.

```bash
# 3. TAP_GRID_ID is the value from .env.local (not the default).
scripts/dc exec web env | grep ^TAP_GRID_ID=
EXPECTED=$(grep ^TAP_GRID_ID .env.local | cut -d= -f2)
echo "Expected: $EXPECTED"
```

Expected: the two values match. Mismatch means the override didn't apply — most likely `.env.local` is missing or `scripts/dc` wasn't used.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-smoketest-data-1 | Migrations applied | Proposed | `migrate --check` exits 0. | |
| req-dev-multisession-smoketest-data-2 | Seed loaded | Proposed | `Entity.all_objects.count()` > 0. | |
| req-dev-multisession-smoketest-data-3 | Grid ID matches override | Proposed | Container env `TAP_GRID_ID` matches `.env.local`. | |

### Admin Bootstrap
----
RID: `req-dev-multisession-smoketest-admin`

Status: `Proposed`

The session must have a Django admin superuser created and a `.dev-credentials` file present. The credentials in the file must match what's in the database.

#### Procedure

```bash
# 1. .dev-credentials file exists with all required keys.
test -f .dev-credentials
grep -E '^(DJANGO_SUPERUSER_USERNAME|DJANGO_SUPERUSER_PASSWORD|DJANGO_SUPERUSER_EMAIL|SESSION_NAME|GENERATED_AT)=' .dev-credentials | wc -l
```

Expected: file exists; grep returns `5` (all five keys present).

```bash
# 2. .dev-credentials is gitignored.
git check-ignore .dev-credentials
```

Expected: command exits 0 and prints `.dev-credentials` (file is ignored).

```bash
# 3. The admin user exists in the database.
scripts/dc exec web uv run python manage.py shell -c \
  "from django.contrib.auth import get_user_model; U = get_user_model(); print(U.objects.filter(username='admin', is_superuser=True).count())"
```

Expected: prints `1` (exactly one admin superuser exists).

```bash
# 4. The credentials in the file actually log in.
# NOTE: do not name these vars USERNAME — zsh treats USERNAME as a special
# parameter mapped to the OS login name, so a local assignment is silently
# ignored and the admin auth check will spuriously FAIL.
ADMIN_USER=$(grep ^DJANGO_SUPERUSER_USERNAME= .dev-credentials | cut -d= -f2)
ADMIN_PASS=$(grep ^DJANGO_SUPERUSER_PASSWORD= .dev-credentials | cut -d= -f2-)
scripts/dc exec web uv run python manage.py shell -c \
  "from django.contrib.auth import authenticate; u = authenticate(username='$ADMIN_USER', password='$ADMIN_PASS'); print('OK' if u and u.is_superuser else 'FAIL')"
```

Expected: prints `OK`. `FAIL` means the credentials file and the DB are out of sync — re-run admin bootstrap (step 7 of the onboarding doc).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-smoketest-admin-1 | Credentials file complete | Proposed | `.dev-credentials` exists with all five keys. | |
| req-dev-multisession-smoketest-admin-2 | Credentials file gitignored | Proposed | `git check-ignore .dev-credentials` exits 0. | |
| req-dev-multisession-smoketest-admin-3 | Admin user exists | Proposed | Exactly one `admin` superuser is present in the session DB. | |
| req-dev-multisession-smoketest-admin-4 | Credentials log in | Proposed | The username/password from `.dev-credentials` authenticates as a superuser. | |

## Status Vocabulary

Standard TAP states: `Proposed`, `Approved for Development`, `In Development`, `Implemented`, `Verified`, `Refactoring`, `Deprecating`, `Deprecated`.
