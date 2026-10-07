# tap_api Design

## Purpose

tap_api owns the Django Ninja API instance, the core read endpoints (entity types, searches, Gryphon), plugin router discovery, and authentication. No models — pure routing and presentation.

## Key Decisions

**NinjaAPI lives in `api.py`.** Single assembly point: creates the API, mounts core routers, discovers plugin routers. Mounted at `/api/v1/` in urls.py.

**Unversioned `/api/` alias.** Path-preserving redirect to `/api/v1/`. When v2 ships, change the redirect target. Explicit-version clients keep working.

**ModelSchema for output schemas.** `EntityTypeOut` derives from its Django model — eliminates drift between models and API responses. Input schemas are hand-written since they intentionally differ from model shape.

**Core routers = graph reads.** EntityType, Search and Gryphon endpoints work for all types; the graph UI (`tap_viz`) and plugin projections call `searches/{id}/execute` and `gryphon/execute`, and the readiness probe calls `entity-types`. There are no generic entity or edge endpoints: they wrote through helpers that skipped the write pipeline and nothing called them, so they were removed (Issue# 957 - tap). A graph write over HTTP, when something needs one, is a new endpoint built on the pipeline verbs. Plugin routers are for domain-specific operations.

**Plugin router discovery.** `TapPluginConfig.get_api_router()` returns a `ninja.Router` or `None`. `TapApiConfig.ready()` iterates all app configs, finds TapPluginConfig subclasses, and mounts their routers at `/plugins/<label>/...`. Lazy imports in `get_api_router()` prevent circular dependencies.

**Session auth for v0.** Global `django_auth` on the NinjaAPI instance. Log in via `/admin/`, session cookie carries to API. `tap_api/auth.py` is the single evolution point when token auth is needed.

**All mutations go through the write pipeline.** An endpoint that writes calls a `tap_grid.services` pipeline verb (`write_batch` and the verbs built on it), never an ORM write, so every write carries its batch, provenance and history. The API layer handles validation, HTTP concerns, and response formatting.

## What Lives Here vs Other Apps

- **tap_api**: NinjaAPI instance, schemas, routers, auth, plugin router discovery
- **tap_grid**: Models, service layer (mutation logic), EntityType registry
- **tap_plugins**: `TapPluginConfig` base class with `get_api_router()` hook
- **Plugins**: Override `get_api_router()` to expose domain-specific endpoints

## Backlog

**Headless API disable.** Support standing up an instance with the **API surface mounted off entirely** — for web-only or minimal deployments, and the reciprocal of the web-disable toggle (`tap_web` `req-web-rendering-headless`). Today `/api/v1/` (plus the unversioned `/api/` alias) is mounted unconditionally in `tap/urls.py`, and `TapApiConfig.ready()` always discovers and mounts plugin routers. A headless-API toggle makes both conditional on a settings flag, ultimately driven by the boot profile (`spec-tap-boot-v0`, config-as-code), so a profile can declare "no API surface" — e.g. the minimal `boot/gryphon.boot.json` playground, which only needs to exercise the Gryphon engine, not serve an API. The flag is a shared **surface-toggle** mechanism living in settings / `tap` and consumed where surfaces mount — not `tap_api` depending on `tap_web` or vice-versa (`avoid tap_* app interdependencies`). Web-disable and API-disable are independent: either surface can be off without the other.
