# TAP Intentional Duplication (Known-Dupes) Specification

## Philosophy

The derive-the-same-fact-twice audit (2026-08) established the standing guard: when a fact is
needed in two places, call one function — never copy the logic or re-derive from a different
source. But some duplication is **intentional and structural**: an import boundary makes one
function impossible (settings-free code cannot read Django settings; stage-0 host tools cannot
import venv-only modules; pre-Django code cannot use the Django-side parser). These pairs are
not defects — yet an *undocumented* intentional duplicate is indistinguishable from
drift-in-waiting: the next editor changes one side, nothing points at the partner, and the
divergence class the audit exists to kill is reborn with a clean conscience.

The remedy is the same discipline TAP applies everywhere else (log-site tokens, RID-linked
guards, declare-vs-decide): when we intentionally duplicate, we **flag it, document it, and
track it** — in the code at every site, in the owning spec, and with a guard that makes a
stale or orphaned flag loud. Editing one member of a known-dupe group means putting eyes on
its partners; the tag is how you find them in one grep.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Findable | Every intentional duplicate names a greppable group id; one search finds every partner |
| 2. | Explained | Every site says WHY the duplication is structural (the boundary that forbids one function) |
| 3. | Tracked | The owning spec documents the group; a guard fails on orphaned or undocumented groups |
| 4. | Honest | Anything NOT tagged is claiming to be a single source — the audit treats it as a defect |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-known-dupes | [Known-Dupe Tagging](#known-dupe-tagging) | Implemented | `TAP-KNOWN-DUPE(<id>)` comment at every intentional-duplicate site; ≥2 sites per id and a spec mention, guard-enforced |

---

### Known-Dupe Tagging
----
RID: `req-tap-known-dupes`
Status: `Implemented`

Every **intentional** duplicate derivation — the same fact computed in two or more places
because a structural boundary (import direction, stage-0 constraints, settings-free contexts)
forbids sharing one function — is marked at **every** participating site with a tag comment:

```python
# TAP-KNOWN-DUPE(<group-id>): <why this cannot share one function; where the partner lives>
```

- **`<group-id>`** is a short kebab-case name shared by every site in the group. The id is
  the link: `grep -rn "TAP-KNOWN-DUPE(<group-id>)"` finds every partner. Ids are stable —
  renaming one is an edit to every site plus the owning spec.
- **The comment carries the why and the partner** in human-readable form, so a reader of one
  site learns the boundary and the counterpart without leaving the file. (The guard checks
  structure — group size and spec mention — not comment prose; the prose quality is a review
  responsibility.)
- **The owning spec documents the group**: the spec section that owns the duplicated fact
  names the tag (the literal `TAP-KNOWN-DUPE(<group-id>)` string appears in exactly the
  spec(s) that own it), so the duplication is part of the requirement's reviewed contract,
  not a code-only aside.
- **The guard (`known-dupes`) enforces the structure**: every group id found in code has
  **≥ 2 code sites** (a singleton means the partner was deleted or never tagged — either way
  the tag is lying, fail) and **≥ 1 spec mention** (an undocumented group is untracked).
  Collapsing a group to one true source means deleting every tag and its spec mention in the
  same change — the guard makes forgetting that loud.
- **Untagged duplication stays a defect.** This spec legitimizes nothing by default: the
  derive-same-fact-twice audit treats any untagged re-derivation as a finding. The tag is a
  narrow, reviewed acknowledgment that ONE specific group is structural — the KNOWN_DUPE
  analog of `# noqa: TAP-LOG-ID`, visible in review and greppable forever.

Current groups (authoritative list is the code — `grep -rn "TAP-KNOWN-DUPE("`):

- `TAP-KNOWN-DUPE(secrets-root)` — the two canonical `TAP_SECRETS_ROOT` lookups
  (`tap/settings.py` inside Django, `tap/secrets_root.py` outside), owned by
  `req-tap-cares-secrets-root-resolution` in `tap_cares/specs/spec-tap-cares-secrets.md`.
- `TAP-KNOWN-DUPE(admin-role)` — the two spellings of the `tap_admin` role name
  (`tap_auth/roles.py` `ADMIN_ROLE` in Django, `tap_auth/boot.py` `_ADMIN_ROLE` at
  settings time, where the role registry cannot be imported), owned by
  `req-tap-auth-boot` in `tap_auth/specs/spec-tap-auth-v0.md`.
- `TAP-KNOWN-DUPE(write-scope-caps)` — the write-class capability names, spelled in the
  `*_CAPABILITY` constants of `tap_auth/capabilities.py` and restated in the
  `tap_grid/write_guard.py` module-scope frozenset (importing the constants there would
  close the cycle through `tap_auth.enforcement`, which imports `write_guard` at module
  scope), owned by `req-tap-auth-capabilities` in `tap_auth/specs/spec-tap-auth-v0.md`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-known-dupes-1 | Tag At Every Site | Implemented | Every intentional-duplicate site carries `TAP-KNOWN-DUPE(<id>)` with the shared group id; the comment states why sharing is impossible and where the partner lives. | Prose quality is review-owned. |
| req-tap-known-dupes-2 | No Orphan Groups | Implemented | Every group id present in code has ≥ 2 code sites. A singleton fails the guard — the partner was deleted or never tagged. | The stale-tag detector. |
| req-tap-known-dupes-3 | Spec-Documented Groups | Implemented | Every group id is named (as the literal tag string) in at least one spec file, tying the duplication to a reviewed requirement. | |
| req-tap-known-dupes-4 | Untagged Duplication Stays A Defect | Implemented | The tag legitimizes only its own group; the audit discipline (one function, never re-derive) governs everything untagged. | Doctrine, enforced by audit practice. |

#### Future
- Seed the remaining deliberate shadows from the 2026-08 audit as they are worked: the
  pre-Django `tap-plugin.toml` parsers (audit #6, `tap/plugin_deps.py` + `tap/preboot.py`
  shadowing `tap_plugins/manifest.py`) and the boot-record digest parsing pair (audit #5) if
  its collapse determines the parse must stay duplicated.
- If group counts grow past a handful, consider `manage.py dupes` listing groups with sites —
  derived from the tags, never a second registry.

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed |  |
| Approved for Development | Requirement is accepted and ready to be implemented |
| In Development |  |
| Implemented |  |
| Verified |  |
| Refactoring |  |
| Deprecating |  |
| Deprecated | Not part of the current architecture and should not be implemented |

## RID Format

`req-<application>-<specification>-<feature>-<sub-feature>`

## Requirements Format

Requirements use RID sections with Status, prose contract, and Acceptance Criteria tables as
in the other TAP specifications.
