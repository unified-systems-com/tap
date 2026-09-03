# WOG — Way of the Grid

## Philosophy

`wog/` holds the Way of the Grid: the philosophy the system is built from. It is not
engineering canon — a spec says how a surface behaves, and WOG says what we believe — but it is
*cited* by engineering canon, and once a document is cited by name it needs the same structural
discipline as any other referenced thing: a stable identifier, one definition per name, and a
citation that resolves.

Much of the corpus is already load-bearing under other names — `WOG-Oneness` is derive-a-fact-once,
`WOG-Mindfulness`'s "know when it knows not" is the FLIP known-unknown hinge, `WOG-Accuracy` is the
coverage-delta honesty surface, and `WOG-Chaotic-Majority` ("continuously define what is right") is the
allowlist, fail-closed posture stated as epistemology. Citing entries makes those derivations traceable
to their root rather than adding a second layer of doctrine.

This spec governs only the corpus's *structure* and *citation mechanics*. It has no opinion on
content: what an entry says, and whether it is right, is the author's business.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Stable Reference | An entry can be cited by name from anywhere and the citation keeps resolving as the corpus evolves. |
| 2. | Status Without Drift | An entry's authority is carried by where it lives, never by a header that can disagree with reality. |
| 3. | Mechanically Checkable | Structure is guard-enforced; content is not touched. |
| 4. | Cheap to Evolve | Promotion and demotion are file moves, not migrations. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-wog-tiers | [Status Is Carried by File](#status-is-carried-by-file) | Implemented | Three tier files; promote/demote is a move |
| req-wog-identity | [Entry Identity](#entry-identity) | Implemented | Name is the identity; unique across all tiers |
| req-wog-entry-shape | [Entry Shape](#entry-shape) | Implemented | Title + matching underline; the parseable unit |
| req-wog-citation | [Citation Form](#citation-form) | Implemented | `WOG-<Name>`, multi-word joined by dashes |
| req-wog-resolution | [Citations Resolve](#citations-resolve) | Implemented | A dangling `WOG-*` citation fails the build |

### Status Is Carried by File
----
RID: `req-wog-tiers`

Status: `Implemented`

The corpus lives in `wog/` and is split by status into three files:

| File | Tier | Weight |
| --- | --- | --- |
| `wog/wog.txt` | settled | Governs. |
| `wog/wog-in-process.txt` | in process | Argues. |
| `wog/wog-apocrypha.txt` | apocrypha | Neither governs nor argues; kept for context. |

Settled entries govern; in-process entries argue. Promote to the main text when one's fully baked,
demote to apocrypha when it's no longer needed.

Promotion and demotion are **file moves**. Status is therefore never stored twice: there is no status
header to drift from the entry's actual location, and git history records when a move happened,
consistent with deriving document versioning from git rather than storing it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-wog-tiers-1 | Three tier files | Implemented | `wog/` contains exactly the settled, in-process, and apocrypha files. | |
| req-wog-tiers-2 | No status header | Implemented | An entry carries no status field; its file is its status. | |

### Entry Identity
----
RID: `req-wog-identity`

Status: `Implemented`

**The name is the identity; the file is the status.** An entry's title is its permanent
identifier. Moving an entry between tiers changes its authority but not its name, so every
existing citation keeps resolving across a promotion or demotion — the same stable-id/mutable-status
split that requirements use, where an RID never encodes its own status.

Entry names are **unique across all tiers**: one entry, one name, wherever it lives. This is
`WOG-Oneness` applied to WOG itself, and it is what lets a resolver answer "which tier is this in?"
with a single answer.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-wog-identity-1 | Names unique across tiers | Implemented | No name appears in more than one tier file, and no file repeats a name. | Guard: `wog-name-uniqueness`. |
| req-wog-identity-2 | Citations survive a move | Implemented | Moving an entry between tiers does not change its citation form. | Follows from the name being the identity. |

### Entry Shape
----
RID: `req-wog-entry-shape`

Status: `Implemented`

An entry is a title line followed by an underline of `-` characters **the same length as the
title**, then free-form body text until the next entry. Each file opens with its own title and a
`=` underline.

The shape is deliberately minimal — it is plain text, and the point is that it stays readable and
writable without tooling. The matching-length rule exists so the parse is unambiguous: it is what
separates a title from a body line that happens to be followed by dashes.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-wog-entry-shape-1 | Underline matches title | Implemented | Every entry's underline is exactly as long as its title. | Guard: `wog-entry-shape`. |
| req-wog-entry-shape-2 | Every entry has a body | Implemented | An entry is not empty. | Guard: `wog-entry-shape`. |

### Citation Form
----
RID: `req-wog-citation`

Status: `Implemented`

Entries are cited by name in the style of a PEP: `WOG-` followed by the entry name, with
multi-word names joined by dashes.

- `Oneness` → `WOG-Oneness`
- `Chaotic Majority` → `WOG-Chaotic-Majority`
- `Benches v Chairs` → `WOG-Benches-v-Chairs`

A citation names an entry; it does not encode the entry's tier. Encoding the tier would break every
citation on promotion, which is the failure this convention exists to avoid.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-wog-citation-1 | Dash-joined names | Implemented | A multi-word entry is cited with its spaces replaced by dashes. | |
| req-wog-citation-2 | Tier not encoded | Implemented | No citation form includes the tier. | |

### Citations Resolve
----
RID: `req-wog-resolution`

Status: `Implemented`

Every `WOG-*` citation anywhere in the repository must resolve to an entry in one of the tier
files. A citation that does not resolve is a defect: it points a reader — human or agent — at
canon that does not exist, and it is the exact failure mode a renamed or deleted entry produces
silently.

The resolver reads all three tier files and reports which tier the entry currently occupies, so a
reader can weigh a settled citation differently from an in-process one without the citation itself
having to say so.

This mirrors the discipline already applied to requirement RIDs, where a guard asserts that every
cited `req-*` resolves to a real requirement.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-wog-resolution-1 | No dangling citations | Implemented | Every `WOG-<Name>` occurrence in tracked text resolves to an entry. | Guard: `wog-citation-resolution`. |
| req-wog-resolution-2 | Tier reported | Implemented | The resolver can name the tier an entry currently sits in. | `tap.guards._wog_scan.entries()`. |

## Future

- **Tier-aware citation weight in review.** A reviewer (or an AI reviewer) could flag doctrine that
  leans on an in-process entry as if it were settled. Named, not built; the trigger is a citation
  actually being used that way.
- **Grid-native corpus.** WOG entries are nodes with edges to the requirements that derive from
  them. This is the same seam as the grid-native roadmap and waits on the same trigger.

## Status Vocabulary

This spec uses the standard TAP spec states: `Proposed`, `Approved for Development`,
`In Development`, `Implemented`, `Verified`, `Refactoring`, `Deprecating`, `Deprecated`, `Backlog`.
