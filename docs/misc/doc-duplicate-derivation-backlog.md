---
spec: ../../specs/spec-tap-known-dupes.md
audience: [llm, developer]
covers:
  - ../../specs/spec-tap-known-dupes.md
  - ../../tap_grid/specs/spec-grid-security.md
  - ../../tap_cares/specs/spec-tap-cares-secrets.md
assumes:
  - Reader knows the derive-the-same-fact-twice guard (specs/spec-tap-known-dupes.md) — when a fact is needed in two places, call one function; where a structural boundary forces a duplicate, tag every site TAP-KNOWN-DUPE(<id>).
---

# Duplicate-Derivation Backlog

The open remainder of the 2026-08 duplicate-derivation cleanup: **~30 findings**, with
file:line, effort tier, and the collapse each one wants. Nothing here is an active
vulnerability. This is a shopping list, not an incident.

**How to work it:** batch by tier, not one at a time. The one-per-PR rhythm that cleared the
first wave is not time-efficient at this size — Tier 1 and 2 are mechanical enough to land as
single batched PRs with one lane run each. Reserve the discuss-first treatment for Tier 3,
where the fix needs a decision rather than an edit.

## Status

**Closed (2026-08-12/13, PRs #49, #52, #54, #55, #63 + one batch):** grid-table classification;
built-in actor keys; secrets-root resolution; request-identity (CallerContext); the
git-credential mechanism + stage-0 kind check; passkey enrollment origin; and a nine-item
mop-up (ungated `resolve_entity` de-export, dead `DEBUG`/`TAP_SECRETS_ROOT` getattrs,
`domain_not_allowed`, Tabulator bundle, `tap_test` key, `tap_plugin` namespace, `_read_json`,
search-role name) plus four wrong-way defaults (local-password kill switch, entrypoint
profile resolution, `crypto_bom` invented default, spawn writing the resolved profile).

Standing infrastructure that came out of it: `req-tap-known-dupes` + the `known-dupes` guard;
`req-grid-table-classification.sec`; `req-tap-cares-secrets-root-resolution`; the
host-runnable stdlib-only boundary test.

**Closed (2026-08-18, Tier 2 batch):** all seven findings below, with three corrections to the
proposed collapses — the `search_readonly` collapse could NOT import from the executor in the
settings direction (new stdlib-only leaf `tap/db_aliases.py` instead); `write_guard`'s frozenset
could NOT import `tap_auth.capabilities` at module scope (cycle through `tap_auth.enforcement` —
tagged `TAP-KNOWN-DUPE(write-scope-caps)` instead, and `grid.discover` was a 4th uncovered
literal); and the seven `_write_secret` test helpers turned out to be seven DIFFERENT helpers
sharing only the `.secret.json` suffix fact (collapsed to `SECRET_SUFFIX` imports; the helpers
deliberately kept). `tap_admin` gained `TAP-KNOWN-DUPE(admin-role)` for boot.py's settings-time
copy. Test families landed in `tap/pytest_harness.py` (`batch_ctx`, `make_admin_user`/
`make_admin_client`, `isolated_registry`) + `tap_cares/tests/conftest.py`; the collapse retired
4 baselined mypy `union-attr` debts carried by the old copies.

## Tier 1 — one-liners, no design needed

| Finding | Sites | Collapse |
| --- | --- | --- |
| `{"tap.graph": "web"}` dimension | `tap_web/models.py:21,121,179`; `tap_web/apps.py:30,63,71` | `WEB_DIMENSIONS` in `tap_web/models.py` |
| `"cytoscape:cose"` default placement | `tap_viz/panels/graph_panel/__init__.py:208,396`; `tap_web/synthetic.py:197,206,235,239`; `tap_web/views.py:485,493` | `DEFAULT_PLACEMENT` in tap_viz |
| `SECRET_SUFFIX = ".secret.json"` | `tap/boot_pointer.py:65`; `tap/runtime_secrets.py:46` | **Trap:** boot_pointer is stdlib-only, runtime_secrets reaches jsonschema. Needs a stdlib leaf **or** a `TAP-KNOWN-DUPE(secret-suffix)` tag — not a plain import |

## Tier 2 — small, a few files (CLOSED 2026-08-18 — see Status)

| Finding | Sites | Collapse |
| --- | --- | --- |
| `"tap_admin"` role/group name | `tap_auth/roles.py:35` (`ADMIN_ROLE`), `sync.py:42` (`GROUP_ADMIN`), `boot.py:97` (`_ADMIN_ROLE`) **+ bare literals at boot.py:245,306,327**, `passkey/dev_record.py:58`, `bootstrap_dev_passkey.py:77`, `enroll_admin.py:147,239` | `roles.ADMIN_ROLE` is the home. Note boot.py:327 is inside the **last-admin lockout check**; boot.py may keep one documented settings-time literal but ignores its own constant three times |
| `"search_readonly"` DB alias | `tap/settings.py:362`; `tap/test_settings.py:59-60`; `gryphon/executor.py:87` (`READONLY_DB_ALIAS`), `search.py:28` (`_SEARCH_DB_ALIAS`), `search_readonly_guard.py:45` (`_READONLY_ALIAS`) | Import `executor.READONLY_DB_ALIAS`. This alias carries `default_transaction_read_only=on`; a typo routes a Gryphon read onto the writable connection |
| Write-scope capability literals | `tap_grid/write_guard.py:54`; `tap_auth/capabilities.py:103-104` (**`grid.purge` and `grid.import_grift` have no constant at all**); `grid.read`/`write`/`delete` bare strings across `tap_grid/services/__init__.py` (~15 sites), `tap_api/routers/{entities,edges}.py`, `tap_web/panels/table_panel/__init__.py:393,395` | Add the two missing constants; build `write_guard`'s frozenset from them. Merges with the original audit's `"grid.read"` item |
| `direct_url.json` VCS provenance | `tap/preboot.py:215-220`; `tap_plugins/report.py:55-66` | One `installed_git_rev(dist)` in `tap/` |
| tap_web URL grammar | routes at `tap_web/urls.py:21-24`; hand-built f-strings at `apps.py:118`, `views.py:130`, `viewer_panel:157,163`, `editor_panel:130,185`, `synthetic.py:295`; `--` separator named once at `page.py:109`, inlined 4× | `object_url_id(slug, entity_id)` helper + `reverse()` |
| Test-helper families | `_write_secret` ×7 files; `_batch_ctx` ×5 (AST-identical); `_admin_client` ×4; registry-isolation ×8+4 | Per-app conftest fixtures |

## Tier 3 — needs a decision before editing

> **2026-08-20 evidence pass:** every row below re-verified read-only; several are wrong in
> load-bearing details (the uuid5 site, the digest-parse risk, the raw-reader count). The
> corrected evidence + per-row recommendations live in
> [doc-dev-dupes-tier3-decision-brief.md](doc-dev-dupes-tier3-decision-brief.md) — rule there,
> then edit. `TAP_LOCAL_PASSWORD_ENABLED` (last row) is **CLOSED by verification**: both halves
> read bare `settings.TAP_LOCAL_PASSWORD_ENABLED` (views_login.py:64); the 08-13 fix was complete.

| Finding | Sites | The decision |
| --- | --- | --- |
| Boot-profile file path | `tap/boot_records.py:49` (`RECORD_SUFFIX`), `tap/preboot.py:163-164,174`, `tap_auth/boot.py:56-57`, `tap/crypto_bom.py` (`_waivers_for_profile`), `tap_boot/profile.py:144,158,186` | Five+ spellings across three **security-load-bearing** readers (FIPS waivers, initial admins/grants, plugin install set), two of which parse the file **raw, unvalidated**. Wants one settings-free `profile_path(profile_id)`; the boundary shape decides where it lives |
| Boot-profile `enabled` default | `tap/preboot.py:188,197` (`False`); `tap_boot/profile.py:160` (`True`), `:172,181` (strict) | Opposite defaults on the same field, both readers raw. Latent (schema requires it; all shipped profiles set it). Validate in both, or one shared helper |
| ORM write-shape recognizers | `tap/direct_write_coverage.py:53-57,204,245` (7 methods, **no `update_or_create`**); `tap_auth/credential_bind_coverage.py:66-69,82,116` (8 methods) | **Already diverged** — the direct-write guard is blind to `update_or_create`. No live bypass today (the in-tree calls write `EntityType`, not a `BaseModel`). One `orm_write_shapes` module, parameterized |
| Scanner out-of-scope predicates | `tap/direct_write_coverage.py:297-306`; `tap_auth/credential_bind_coverage.py:170-178`; `tap/authz_coverage.py:~199`. **Plus:** `_EXCLUDE_DIRS` identical in `guards/known_dupes.py:22`, `guards/secret_leak.py:17`, `guards/secrets_root_resolution.py:17` but `tap/jsonfiles.py:201` is **missing `tap_secrets`** — the JSON-naming scanner walks the live secrets mount the leak scanners skip | `default_out_of_scope(path, extra=...)` in `tap/source_scan.py` (the `ScopeStackVisitor` substrate already exists for exactly this) |
| Boot-record digest parsing | `tap/boot_records.py:106`; `tap/boot_pointer.py:286` | Security-sensitive integrity gate; digest *computation* is already shared, only parsing is duplicated. Sub-shape: divergent `.get` defaults (`sha256` → `None` vs `""`) across boot_pointer:276-277, boot_records:112-117, `tap_plugins/manifest.py:457-483` |
| `scope:key` qualification | `tap/runtime_secrets.py:95-97`; `tap_cares/secrets/models.py:35-37`; `tap_boot/profile.py:80-82`; **hand-built f-string at `tap_cares/registry.py:125` feeding uuid5 collector identity** | **Trap:** route the uuid5 site through a shared `qualify()`, never change the derivation — see the uuid5 rename fallout |
| Callsite-identity recipe | `tap/authz_coverage.py:99-122`; `tap/direct_write_coverage.py:156-176`; `tap/logging.py:360-371`; `tap_auth/credential_bind_coverage.py` | Same `semantic_hash(...)` + `path::qualname::detail` anchor, differing only in tag/detail. Drift invalidates baselines — a mixin in `tap/guards/callsite.py`, applied carefully |
| `TAP_LOCAL_PASSWORD_ENABLED` | `tap_auth/auth_backends.py` (fixed 2026-08-13); `tap_auth/views_login.py:65` | The backend half is done. Confirm the views half reads the same source |

## Tier 4 — real refactor

- **GRIFT serialization across the three read engines.** Canonical `tap_grid/grift/subgraph.py:405-470`; re-rolled at `gryphon/executor.py:1263,1294,2725` and `orm_compiler.py:208,238` (executor/orm_compiler pairs are **AST-identical**). Against the one-grid-read-path north star. Export `serialize_node_list`/`serialize_edge_list` and have all three call them; validate with the Gridkin SQL snapshots. **Verified 2026-08-20: they do NOT differ** — all three call the same six leaf serializers from `subgraph.py`; only dispatch wrappers are duplicated (executor/orm_compiler pairs still byte-identical). Downgraded to hygiene; collapse = THREE exports (`serialize_node_list`, `serialize_typed_node_list`, `serialize_edge_list`) because executor's `_serialize_typed_nodes` has its own input contract. Gridkin snapshots are out-of-repo (gryphon_playground); validate in-tree with test_grift_subgraph.py + test_grift_envelope.py. Detail: [doc-dev-dupes-tier3-decision-brief.md](doc-dev-dupes-tier3-decision-brief.md).
- **3+ `tap-plugin.toml` parsers.** `tap/plugin_deps.py` + `tap/preboot.py` deliberately shadow `tap_plugins/manifest.py` (pre-Django boundary). Likely a `TAP-KNOWN-DUPE(manifest-parse)` tag rather than a collapse — but fix the real divergence: `DeclaredDep` drops the `note` field `DependencyEntry` keeps.
- **Entity types in-code vs DB catalog.** `list_entity_types()` vs `EntityType.objects.all()`. Conceptual (desired vs observed state), not a collapse.

## Not ours

`REPO_ROOT` derived **seven** ways — `tap/jsonfiles.py:28`, `boot_records.py:47`, `preboot.py:79`
(`REPO_ROOT`), `core_version.py:34` (`_REPO_ROOT`), `tap/settings.py:31` (`BASE_DIR`),
`guards/base.py:43` (`parents[2]` — a *different AST* for the same fact), and inline inside a
function at `tap_auth/boot.py:56`. Held by the sam-dev session as the demo case for the
requirement-traceability wave. **Constraint if it collapses to a module:** that module must be
stdlib-only and must NOT be `tap/jsonfiles.py`, which pulls jsonschema at module scope — see
the host-runnable boundary test in `tap/tests/test_boot_pointer.py`.

## The detectors, so this can be re-run

Two sweeps found these; the second exists because the first missed a whole class.

1. **Code-clone sweep** — duplicate `def` names across modules; normalized-AST body hashing;
   repeated multi-line idioms. Finds copy-paste. **Blind to module scope** — it missed
   `REPO_ROOT` entirely because a module-level constant is not a function.
2. **Value-level sweep** — the better one. Asks "does this VALUE appear in more than one
   module?", not "is this code cloned?", so it relates a named constant in one file to a bare
   literal in another. Five methods: module-scope assignment RHS collision; env-var read
   inventory grouped by variable; literal inventory grouped by value; **divergent defaults**
   (same key, different fallbacks — highest risk, already-divergent by construction); repeated
   fallback-chain shapes.

**Run any sweep with a positive control.** Seed it with already-fixed findings and require it
to report which ones it rediscovers; a detector that cannot re-find known duplicates proves
nothing when it comes back clean. Also: **agent findings are leads, not verdicts** — one sweep
asserted "no import boundary exists" for the git-askpass pair when the boundary was real and
load-bearing.

**Strongest signal from the value sweep, worth preserving:** of 31 TAP environment variables,
exactly **one** (`TAP_BOOT_PROFILE`) is read in more than one module. The settings.py
projection discipline is genuinely holding.

**What a RID-claim check would add (and miss).** If implementation sites carry
`TAP-IMPLEMENTS(rid)` claims, two claims on one RID flags duplication — and catches
same-job/different-code pairs that value scanning cannot see. It composes with
`TAP-KNOWN-DUPE`: two authoritative claims with no declared group is a defect. But it is
**blind to the shape that caused the worst findings here** — two *different* requirements each
deriving the same underlying fact (the grid-table set, the secrets root, the askpass
mechanism). Those need the value-level scan. It also cannot see duplication of facts no
requirement mentions (`REPO_ROOT`, asset bundles, placement defaults).
