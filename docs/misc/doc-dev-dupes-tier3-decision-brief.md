---
spec: ../../specs/spec-tap-known-dupes.md
audience: [developer, llm]
covers:
  - doc-duplicate-derivation-backlog.md
  - ../../specs/spec-tap-known-dupes.md
  - ../../specs/spec-tap-tree-scanner.md
assumes:
  - Reader has the Tier 3 / Tier 4 tables of doc-duplicate-derivation-backlog.md open.
update-triggers:
  - A ruling below is made — record it in the owning spec, mark the row here Ruled, and strike the matching backlog row
  - Any cited site moves — this brief is evidence-of-record for the 2026-08-20 pass, correct rather than let drift
---

# Tier 3 Decision Brief — 2026-08-20 evidence pass

Read-only verification of the seven Tier 3 findings plus the Tier 4 GRIFT pre-check,
three parallel scouts over current HEAD (`be29b578`). Each section: verdict, the
evidence that changes the picture, the decision, and a recommendation. No edits made.

## F1 — Boot-profile file path (worse than recorded)

**Verdict: holds, and bigger.** Not "five spellings, two raw readers" — **four raw
readers** (`tap/preboot.py:176`, `tap/crypto_bom.py:538` inline, `tap_auth/boot.py:56`,
`tap_boot/profile.py:158`) against exactly **one** schema-validated read
(`tap_boot/profile.py:186`), plus writers, a shell spelling in spawn, and a sixth
`.stem`-footgun spelling in `tap/tests/test_preboot.py:21`.

**Constraint discovered:** the root differs by design — `tap_boot` derives `boot/` from
`settings.BASE_DIR`, everyone else from `__file__`; and `tap_boot/tests/test_profile.py`
monkeypatches `boot_dir`. So the shared helper must take the dir:
`profile_path(boot_dir: Path, profile_id: str)`, leaving root derivation to callers —
which also keeps this separable from the parked "REPO_ROOT seven ways" item.

**Decision — where it lives:** (A) `tap/boot_records.py` (stdlib-only, already exports
`RECORD_SUFFIX`, import edge from boot_pointer exists; cost: muddies its in-package
charter) or (B) new stdlib-only leaf `tap/boot_naming.py` mirroring `tap/secret_naming.py`,
with `RECORD_SUFFIX` moved there and re-exported. **Recommend B** — the repo already
chose this shape for the same problem.

## F2 — Boot-profile `enabled` default (latent, with a real non-shipped path)

**Verdict: holds.** `tap/preboot.py:190,199` default **False**; `tap_boot/profile.py:160`
defaults **True**; `:207,216` strict. Schema requires `enabled` everywhere and all seven
shipped/in-package profiles set it — but **both disagreeing readers bypass the schema**
(preboot by design; `profile_install_slugs` gratuitously). An unvalidated profile via
`spawn --boot-file` missing `enabled` is reported installable while preboot never
installs the plugin — a confusing late failure, not a silent hole.

**Recommend (both halves, cheap):** (a) `profile_install_slugs` passes
`schema=_SCHEMA_PATH` — it has jsonschema in hand and no reason to skip; (b) flip
`:160` to `.get("enabled", False)` so the readers agree fail-closed even when
validation is bypassed. Surviving duplication = one boolean default spelled twice
across the pre-Django boundary → `TAP-KNOWN-DUPE(boot-enabled-default)`.

## F3 — ORM write-shape recognizers (latent blind spot, no live bypass)

**Verdict: holds.** Cred-bind has `update_or_create`, direct-write doesn't; **both**
miss `aupdate_or_create`. Every in-tree `update_or_create` today touches non-managed
models (`EntityType`, `Capability`, `ProtectedGroup`, `ExternalIdentity`) or the
WebAuthn pair the cred-bind scanner covers — which is exactly how the divergence was
born. `tap/authz_coverage.py` is a *function*-name recognizer, not ORM — stays out.

**Recommend:** shared vocabulary + chain-walk in `tap/source_scan.py` (the substrate
both already import; spec-tap-tree-scanner's consolidation worklist gains a row):
`MANAGER_WRITES` / `TERMINAL_WRITES` / `orm_write_target(call, *, is_target)` with the
consumer keeping its own model-resolution (runtime `ManagedModelIndex` vs hardcoded
WebAuthn pair — genuinely different, must not merge). Add `update_or_create` +
`aupdate_or_create` to both. Guardrail: `req-tap-tree-scanner-consolidation-2` set-diff
before/after (expected identical today — assert, don't assume).

## F4 — Out-of-scope predicates + the `tap_secrets` walk (real, inert, worth closing)

**Verdict: holds, wider.** The exclusion set exists in **five** variants (three
identical 9-name sets, `jsonfiles` missing `tap_secrets`, `secret_pattern` a documented
11-name superset, `record_site` a 10-name variant dropping `vendor`+`tap_secrets`).
The `tap_secrets` gap is guarded today by three accidents: the scanner's hardcoded root
list, `rglob(recurse_symlinks=False)`, and the in-container dangling symlink. But spawn
legitimately creates `tap_secrets` as a **real directory** when `~/tap-secrets` is
absent, and the failure mode if the roots ever widen is disclosure-by-error-message of
the live secret store (absolute host path in guard output). Also found: the authz
scanner alone omits `migrations` from its skip.

**Recommend:** (a) one-line `tap_secrets` addition to `tap/jsonfiles.py:209` now —
zero behavior change, removes a load-bearing accident; **scoped to `scan_json_files`
only** (`discover_json_files`/secrets loader walk the secrets root on purpose).
(b) `DEFAULT_EXCLUDE_DIRS` + `default_out_of_scope(path, *, extra, tests, migrations)`
in `tap/source_scan.py`; consumers declare their deltas.
**Sub-decision:** authz's missing `migrations` skip — declare it (`migrations=False`
explicit) or adopt the skip (changes its flagged set → set-diff + baseline re-check).
**Recommend declare-for-now**; adopting is a one-word follow-up after the set-diff.

## F5 — Boot-record digest parsing (the divergence with teeth is duplicate names)

**Verdict: holds; the backlog named the wrong risk.** The `None` vs `""` defaults are
cosmetic — both fail closed identically (traced). The real divergence: **duplicate
record names resolve three ways** — boot_pointer `next()` = first wins, boot_records
dict = last wins, manifest.py = hard error — so the host-side stage-0 gate and the
in-repo guard can verify against *different* declared digests. boot_pointer also lacks
the `isinstance(sha256, str)` check the others carry.

**Recommend:** `declared_record_digests(manifest) -> dict[str, str]` in
`tap/boot_records.py` (stdlib-only, already inside the host-runnable transitive
boundary, already owns `canonical_digest_bytes`), **hard-error on duplicate names**
(the strictest of the three semantics wins on an integrity surface); manifest.py calls
it for extraction and keeps its own error prose. Note: the integrity surface carries no
`TAP-IMPLEMENTS` claim — minting one on the helper is a natural rider.

## F6 — `scope:key` qualification (the backlog named the wrong uuid5 site)

**Verdict: holds; sharper trap.** All four recorded sites are byte-identical
(`f"{scope}:{key}"`), and four more exist (`tap/registry.py:240,270`,
`tap_cares/secrets/loader.py:229` with a lenient isinstance guard, `tap_grid/admin.py:208`).
**The string that feeds the collector uuid5 is produced by `ScopedRegistry.keys()` —
`tap/registry.py:270` — not the backlog's `tap_cares/registry.py:125`**, which is only
a lookup key that must agree with it. What `qualify()` must preserve byte-for-byte:
single `:`, scope-then-key, zero normalization (grammar is case-preserving), str-not-bytes.
Drift doesn't error — it mints a duplicate set of Collector nodes and orphans edges.

**Recommend:** `qualify()` in `tap/registry.py` beside `SCOPED_TOKEN_PATTERN` (already
the declared grammar home; settings-free; runtime_secrets already imports from it).
Sequencing: non-uuid5 sites first; `ScopedRegistry.keys()` as its own commit with a
before/after UUID diff over the registered collector set. `tap_boot/profile.py:82` gets
a `TAP-KNOWN-DUPE(scope-key-qualify)` tag (settings-bound; entangled with F1 otherwise);
loader keeps its lenient guard via an explicit variant or its own tag.

## F7 — `TAP_LOCAL_PASSWORD_ENABLED` — **CLOSED by verification**

Both halves read bare `settings.TAP_LOCAL_PASSWORD_ENABLED` (fail-closed, no default);
the views half never had the wrong-way `getattr` — the 08-13 fix only ever needed to
touch `auth_backends.py`. The one asymmetry (`tap_auth/boot.py:150` `.get(..., True)`)
is the profile-schema layer's documented opt-out default. No action; backlog row struck.

## Tier 4 pre-check — GRIFT serialization: **no exposure difference, downgrade to hygiene**

All three engines import and call the **same six leaf serializers** from
`grift/subgraph.py`; field selection is not duplicated anywhere. Duplicated: the
dispatch wrappers only — executor/orm_compiler pairs still body-byte-identical.
Envelope-level `info`/`warnings` differ (orm_compiler adds them) but that's above the
collapse line. One genuine gap: executor's `_serialize_typed_nodes` (pre-materialized
typed models, one query fewer, missing the `entity_type != "edge"` slug filter) needs
its **own** exported helper — collapse to three exports, not two. Validation: the
Gridkin SQL snapshots live in the evicted `gryphon_playground` repo; in-tree validation
is `test_grift_subgraph.py` + `test_grift_envelope.py` (+ smoke over the eight
downstream consumers listed in the scout record).

## Ruling sheet

| # | Decision | Recommendation | Ruling |
| :---: | --- | --- | --- |
| F1 | Helper home | New stdlib leaf `tap/boot_naming.py` (Option B) | **Ruled: Option B (George, 2026-08-20); landed** |
| F2 | Divergent default | Schema in `profile_install_slugs` + flip `:160` to False + KNOWN-DUPE tag | **Ruled: rec, improved (George, 2026-08-20) — `step_enabled()` in the F1 leaf collapses the default to ONE spelling, no tag needed; landed** |
| F3 | Recognizer collapse | Shared vocab in `tap/source_scan.py`; add `update_or_create`/`aupdate_or_create` both sides; set-diff | — |
| F4a | `tap_secrets` gap | Fix now, one line, scoped to `scan_json_files` | — |
| F4b | Predicate collapse + authz `migrations` | `default_out_of_scope()` in source_scan; authz declares `migrations=False` for now | — |
| F5 | Digest-parse collapse | `declared_record_digests()` in boot_records; duplicate names = hard error | **Ruled: rec (George, 2026-08-20); landed. Claim-minting rider DEFERRED — the claims machinery is mid-rewrite in a concurrent session** |
| F6 | `qualify()` | In `tap/registry.py`; uuid5 site isolated commit + UUID diff; tap_boot site tagged | — |
| F7 | — | Closed by verification | ✓ |
| T4 | GRIFT collapse | Downgraded to hygiene; three exported helpers; in-tree test validation | — |
