# tap-cares Evidence Specification

**What we say we received from the source, kept exactly.** A collector that talks to an external system retains the exact bytes each call returned, content-addressed by digest, with the facts of the request beside them, so that every node and edge on the grid traces back through its batch and its collection job to the evidence it was derived from — and so that processing can be replayed against that evidence without touching the source again.

## Philosophy

The grid holds what TAP *derived*: nodes and edges shaped from what a source answered. Today nothing holds what the source *said*. When a shaper is wrong, when a source truncates a response, when an auditor asks how a control status was established, the answer is a traceback or a memory of a run. George, 2026-09-14: "collectors retain the exact bytes returned by their respective APIs / GraphQL endpoints so that we have a full auditability record … provenance traceable back to what we say we received from the source … a repeatable, standardized process … an important capability for FedRAMP compliance and others."

This is a **tap-cares** capability, not a collector's. A collector already runs in three layers — it *gathers*, *confirms* the gather is reliable, then hands it to the *processing* layers above (the first implementer's reliability spec, `spec-github-core-reliability.md`, requirement *Gather, Confirm, Process*). The gather is already the evidence: bytes, digest, completeness, request facts. This spec is the store those gathers land in and the contract every collector that opts in follows, so the second implementer writes no storage code and an auditor reads one shape across every source.

**Prior art** (surveyed 2026-09-14; *documented*):

- **in-toto attestations / SLSA provenance.** A statement names immutable *subjects* by digest and a *predicate* about them; SLSA's provenance predicate lists the *materials* a build consumed, each by digest. Borrow the shape exactly: the GRIFT batch and its nodes are the subject, the shaping is the predicate, the evidence records are the materials. Reject building the full attestation envelope in v0 — the grid's own edges carry the relation, and a signed envelope is a Backlog export.
- **Content-addressed storage** (git objects, OCI blobs). Key bytes by their sha256; identical content is stored once; immutability and deduplication come free; a digest mismatch is detectable by construction. Borrow whole.
- **NIST SP 800-53 audit controls.** AU-3 (content of audit records: what, when, where, source, outcome, subject), AU-9 (protection of audit information), AU-11 (retention), SI-7 (software, firmware and information integrity). FedRAMP evidence collection today is largely exports and screenshots; machine evidence with a digest chain is the stronger form, and the record shape below is written to answer AU-3's six questions directly.
- **WORM / object lock** (S3 Object Lock: governance mode, which privileged users can override, and compliance mode, which nobody can until the retention date). Borrow the distinction as a Backlog requirement; v0 stores on a filesystem where the guarantee is procedural, and says so.
- **Transparency logs** (Sigstore / Rekor). Signing evidence digests into an append-only log makes tampering with the store detectable by a third party. Backlog: the digest chain is the prerequisite and lands now.
- **Request identity from the source.** A source that returns a request id (the first implementer returns `X-GitHub-Request-Id`) and an `ETag` gives the record two identifiers an auditor can take back to the vendor. Record them when present; never depend on them.

What the survey changed: the chain of custody became an *edge on the grid* rather than a field on the job — the in-toto shape is subject → materials, and the grid already expresses that as `Batch → evidence_record`. And retention became a declared policy with three states for a missing blob, because AU-11 is a policy question, and a blob that is missing when policy says it should exist is an integrity finding, not a shrug.

Three doctrines bear directly. **Derive a fact once:** the bytes are the fact; digest, size and every derived field come from them, never typed twice. **Presence is not correctness:** a record is verified against its bytes on every read, never trusted because a row exists. **Three states, never two:** a blob is *present*, *expired by policy*, or *missing unexpectedly*, and a reader can tell which.

**Provenance markers.** Claims marked *observed* were measured on the first implementer (github_core) on 2026-09-14; prior art is *documented*; everything else is *designed*.

## Goals

| # | Name | Description |
| --- | --- | --- |
| 1 | Exact Bytes | What the source returned is kept unaltered and content-addressed; nothing is rewritten, summarized or reformatted on the way in. |
| 2 | Chain Of Custody | Any node or edge on the grid resolves, by edges, to the evidence records it was derived from, and each to its digest and request facts. |
| 3 | One Shape, Every Source | The record, the store and the access path are tap-cares'; a collector opts in through one hook and writes no storage code. |
| 4 | Replayable | Processing layers can be fed stored evidence and produce the same batch, so regression corpora, offline re-derivation and diagnosis need no source access. |
| 5 | Honest Retention | Retention is a declared per-instance policy; a missing blob says whether policy or failure removed it. |
| 6 | Legible To Player 3 | Evidence metadata is on the grid, Gryphon-queryable, with structured codes; bytes are readable under a named capability. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-cares-evidence-record | [The Evidence Record](#the-evidence-record) | Proposed | Bytes + sha256 + request facts; AU-3's six questions answered by field |
| req-tap-cares-evidence-store | [Blob Store And Grid Node](#blob-store-and-grid-node) | Proposed | Bytes in a content-addressed store under a TAP data root; metadata as an `evidence_record` node |
| req-tap-cares-evidence-custody | [Chain Of Custody](#chain-of-custody) | Proposed | `CollectionJob → evidence_record` and `Batch → evidence_record` edges; node → batch → evidence resolves in Gryphon |
| req-tap-cares-evidence-redaction | [Exact Bytes, Flagged Sensitivity](#exact-bytes-flagged-sensitivity) | Proposed | Bodies are never rewritten; request facts follow the redaction rule; sensitive content is flagged, not removed |
| req-tap-cares-evidence-retention | [Retention Policy](#retention-policy) | Proposed | Declared per instance, never a default; present / expired / missing-unexpectedly |
| req-tap-cares-evidence-integrity | [Integrity](#integrity) | Proposed | Digest verified on every read; a mismatch is a finding on the grid, never served silently |
| req-tap-cares-evidence-access | [Access](#access) | Proposed | Metadata under `grid.read`; bytes under `cares.read_evidence`; service layer only |
| req-tap-cares-evidence-optin | [Opt-In Through One Hook](#opt-in-through-one-hook) | Proposed | `CollectorBase.record_evidence(gather)`; a collector declares its posture in its spec |
| req-tap-cares-evidence-replay | [Replay](#replay) | Proposed | Processing fed from stored evidence; the first implementer's byte-identical-batch proof is the first consumer |
| req-tap-cares-evidence-sizing | [Sizing And Write Path](#sizing-and-write-path) | Proposed | Bytes written synchronously as received; metadata batched per layer; numbers with provenance |
| req-tap-cares-evidence-worm | [Object Lock](#object-lock) | Backlog | Compliance-mode immutability on an object store |
| req-tap-cares-evidence-signing | [Signing And Transparency](#signing-and-transparency) | Backlog | Sign digests into an append-only log |
| req-tap-cares-evidence-export | [Auditor Export](#auditor-export) | Backlog | A bundle: manifest of digests, records, bytes, and the chain, for a named scope |
| req-tap-cares-evidence-nongoals | [v0 Non-Goals](#v0-non-goals) | Proposed | What this spec deliberately does not do |

### The Evidence Record
----
RID: `req-tap-cares-evidence-record`

Status: `Proposed`

One record per response a collector received through its seam. The record has two parts: the **bytes**, stored exactly as received (before any decompression the transport hides is fine to undo; after it, nothing changes), and the **facts**, which answer AU-3's six questions by field.

| AU-3 question | Field | Rule |
| --- | --- | --- |
| What | `endpoint` (template, e.g. `/repos/{owner}/{repo}/actions/runs`, `graphql:config_layer`), `method`, `variables` | Template, never a URL with a query string; variables restricted to a per-collector allow-list (identifiers and cursors), never a token or a signature |
| When | `observed_at` (source/world time of the response, `req-grid-history-time-2`), `recorded_at` (system time of the write) | Both; they differ under retry |
| Where | `source` (the collector's source identity: host or account), `collector_key`, `collection_job` | The job is an edge (`req-tap-cares-evidence-custody`), copied here as an id for queries that start from the record |
| Source | `credential_kind` (e.g. `app`, `pat`, `none`) | Kind, never the value or a fingerprint of it |
| Outcome | `status` (HTTP or transport class), `complete` (the gather's completeness), `degraded_paths` (pruned GraphQL paths), `failure_class` when the call failed | Copied from the gather; a failed call with a body is still evidence |
| Subject | `digest` (`sha256:<hex>` of the bytes), `size_bytes`, `content_type`, `source_request_id`, `etag` | Digest and size derived from the bytes at write; request id and etag copied from typed headers when the source supplies them |

Plus: `flags` (`contains_signed_urls`, `contains_credentials_suspected`, `non_json`) set by the seam's inspection (`req-tap-cares-evidence-redaction`), `compression` (how the bytes are stored at rest), and `retention_class` (which policy row applies, `req-tap-cares-evidence-retention`).

No response header is ever stored as a header dump; the typed subset above (request id, etag, date, rate-limit values where the collector's seam records them) is copied into named fields and nothing else survives.

**Columns for the questions, an open blob for the shape — the grid's relief valve, applied (George, 2026-09-14).** One `evidence_record` type serves every source; there is no `github_evidence` subclass. Every field in the table above is a **typed column** on the model, and every one a query filters on — `source`, `collector_key`, `collection_job`, `endpoint`, `digest`, `observed_at`, `status`, `complete`, `blob_state`, `retention_class` — carries a database index: a B-tree on a real column is what the store is fast at, and Gryphon treats it as strictly typed. Beside the columns sit the two open fields every TAP model carries:

| Field | Holds | Rule |
| --- | --- | --- |
| `configuration` | What varies by source and is never filtered on: GitHub's rate-limit snapshot, GraphQL `cost` and the page size used; a cloud provider's request id, region and API version; a scanner's binary version and persona | Keyed by `source`; **each collector that opts in declares the sub-schema of its contribution in its own spec** (the un-schema'd-blob tolerance of 2026-06-30 is not extended to the one type whose job is auditability); the record's schema requires the `source` key inside it to equal the column |
| `tags` | Facts the seam knows at fetch time that have no node to link yet: the layer name, a repository full name before it resolves, a cursor position | Free; the honest home for a fact until it has a node |

**The payload is never in the row.** zizmor's finding model keeps the scanner's verbatim output in a `raw` JSON field, and that precedent stops here: tens of megabytes per run, sensitive content, JSONB rows. The bytes live in the store (`req-tap-cares-evidence-store`); the row holds the digest.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-record-1 | Bytes Exact | Proposed | The stored bytes, decompressed from at-rest form, equal the bytes the seam received, byte for byte; the digest equals their sha256. | |
| req-tap-cares-evidence-record-2 | Six Questions Answered | Proposed | Every record carries `endpoint`, `method`, `observed_at`, `recorded_at`, `source`, `collector_key`, `credential_kind`, `status`, `complete`, `digest`, `size_bytes`. | AU-3 mapping. |
| req-tap-cares-evidence-record-3 | No Secret Shape | Proposed | No field contains a URL query string, an `Authorization` value, a credential value or a header dump; the record schema rejects unknown keys. | |
| req-tap-cares-evidence-record-4 | Queried Facts Are Indexed Columns | Proposed | `source`, `collector_key`, `collection_job`, `endpoint`, `digest`, `observed_at`, `status`, `complete`, `blob_state`, `retention_class` are model columns with a database index; none lives only inside `configuration`. | A class-def test reads the model's fields and indexes. |
| req-tap-cares-evidence-record-5 | Open Fields, Declared Per Source | Proposed | `configuration` and `tags` exist on the model; `configuration.source` must equal the `source` column; every opted-in collector's spec declares the sub-schema of its `configuration` contribution, and the record validator applies it by `source`. | First implementer: github_core's seam. |
| req-tap-cares-evidence-record-6 | Payload Never In The Row | Proposed | No field of `evidence_record` holds the response bytes or a parsed copy of them; a guard fails a model that adds one. | The `raw`-in-row precedent is named and rejected. |

### Blob Store And Grid Node
----
RID: `req-tap-cares-evidence-store`

Status: `Proposed`

Bytes are not rows. They live in a **content-addressed blob store** under a TAP data root; the facts live on the grid as a first-class node so they are queryable, dimensioned, FLIP-tracked and access-controlled like everything else.

#### Implementation

- **Blob store.** `TAP_EVIDENCE_ROOT` (default `/var/lib/tap/evidence`, a named volume in compose, an object-store prefix later) holding `sha256/<aa>/<bb>/<hex>` with the bytes compressed at rest (`zstd`, level chosen for read speed; `compression` on the record). Writes are `write-temp → fsync → rename`, so a blob is either whole or absent. Identical content across runs is one blob; the record still exists per observation, because *that we observed it then* is the fact.
- **Grid node.** `tap_cares.models.EvidenceRecord`, `ENTITY_TYPE = "evidence_record"`, `DEFAULT_DIMENSIONS = {"tap_cares": "evidence_record"}`, INTERNAL_ONLY like `CollectionJob` (`req-tap-cares-collector-job-model`): the fields of `req-tap-cares-evidence-record`, with `digest` indexed. The node is the metadata; the blob is reached only through the service (`req-tap-cares-evidence-access`).
- **Store interface.** One class, `EvidenceStore`, with `put(bytes) -> digest`, `open(digest) -> stream`, `exists(digest)`, `stat(digest)`; the filesystem implementation is v0; an S3-compatible implementation is the Backlog seam (`req-tap-cares-evidence-worm`). No other module touches the root.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-store-1 | Content Addressed | Proposed | Two records with identical bytes share one blob path; `put` of existing content is a no-op returning the digest. | |
| req-tap-cares-evidence-store-2 | Atomic Blobs | Proposed | A write interrupted before rename leaves no blob at the digest path; `exists` is false. | |
| req-tap-cares-evidence-store-3 | Node Per Observation | Proposed | Each response produces one `evidence_record` node even when its bytes deduplicate. | |
| req-tap-cares-evidence-store-4 | One Root, One Class | Proposed | Only `EvidenceStore` reads or writes under `TAP_EVIDENCE_ROOT`; a guard test walks tap_cares and every installed collector for other references. | |

### Chain Of Custody
----
RID: `req-tap-cares-evidence-custody`

Status: `Proposed`

The in-toto shape on the grid: the batch and its nodes are the subject; the evidence records are the materials.

| Edge | From → To | Created by | Meaning |
| --- | --- | --- | --- |
| `PRODUCED_EVIDENCE` | `collection_job → evidence_record` | The task body at each layer boundary and at terminal state, from the collector's accumulator (the `PRODUCED_BATCH` pattern, `req-tap-cares-collector-grift-import-6`) | This run received this |
| `DERIVED_FROM_EVIDENCE` | `batch → evidence_record` | `submit_grift(document, evidence=[...])`: the collector names the gathers a batch was processed from | This batch's facts came from these bytes |

With FLIP already pointing every field at the batch that set it (`req-grid-flip-batch-1`), any node resolves: field → batch → `DERIVED_FROM_EVIDENCE` → evidence → digest and request facts. The canonical question is one Gryphon traversal from the batch; a panel or Player 3 needs no tap_cares code to answer "says who?".

A FAILED run's evidence is still linked (the failure path already links produced batches, `req-tap-cares-collector-failure-mode`): what the source said before the run died is exactly the evidence a diagnosis wants.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-custody-1 | Job Links Its Evidence | Proposed | After a run, `MATCH (j:collection_job)-[:PRODUCED_EVIDENCE]->(e:evidence_record) RETURN e` for the job returns one node per response received, including on a FAILED run. | |
| req-tap-cares-evidence-custody-2 | Batch Names Its Materials | Proposed | A batch submitted with `evidence=` carries a `DERIVED_FROM_EVIDENCE` edge to each named record; a batch submitted without it carries none and the job records `EVIDENCE_UNLINKED` once. | Three states: linked / opted-out / forgot. |
| req-tap-cares-evidence-custody-3 | Node To Bytes | Proposed | From any node in the first implementer's batch, batch id → `DERIVED_FROM_EVIDENCE` → record → `open(digest)` yields bytes whose digest matches. | |

### Exact Bytes, Flagged Sensitivity
----
RID: `req-tap-cares-evidence-redaction`

Status: `Proposed`

Two rules pull against each other and this spec states the tension rather than hiding it. Evidence must be **exact** — a rewritten body is not evidence. Sources return **sensitive material** in bodies: signed download URLs that grant access for minutes, secret names, emails, private configuration text.

Resolution:

1. **Bodies are never rewritten.** The bytes are the bytes.
2. **Facts follow the redaction rule** the first implementer's seam already applies to run records (its reliability spec, requirement *Observability*): templates not URLs, allow-listed variables, typed header fields, never a credential.
3. **Sensitivity is flagged, not removed.** The seam inspects the body cheaply at write (a signed-URL pattern; a credential-shaped token pattern) and sets `flags`; the record's `retention_class` may be tightened by policy for flagged records (`req-tap-cares-evidence-retention`).
4. **Access is the protection** (`req-tap-cares-evidence-access`): bytes are readable only under a capability that is not granted by default, through the service layer, with the read itself recorded.
5. **Named accepted risk** (`req-sec-honest-risk-1`): an operator with `cares.read_evidence` can read a signed URL for as long as the source honours it. The store does not shorten that window; the source's expiry does.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-redaction-1 | Bytes Untouched | Proposed | A body containing a signed URL is stored byte-identical and the record carries `contains_signed_urls: true`. | |
| req-tap-cares-evidence-redaction-2 | Facts Redacted | Proposed | A request with a query-string token yields a record whose `endpoint` is the template and whose `variables` omit the token. | |

### Retention Policy
----
RID: `req-tap-cares-evidence-retention`

Status: `Proposed`

Retention is a **declared policy per instance**, in the boot profile (`evidence_retention`), never a code default. The policy names retention classes and their durations (e.g. `default: 400d`, `flagged: 30d`, `failed_run: 90d`) and which class a record takes (by collector, by flag, by run outcome). No policy declared → nothing is retained and every opted-in collector records `EVIDENCE_DISABLED` once per run: absent policy is a visible state, not a silent default of forever or of nothing.

Expiry removes the **blob**, never the **record**: the node keeps its digest and facts forever (they are small and are the chain), and gains `blob_state = expired` with the policy row that removed it. A reader therefore sees three states:

| `blob_state` | Meaning |
| --- | --- |
| `present` | Bytes available, digest verified on read |
| `expired` | Removed by the named retention policy on the recorded date — an expected absence |
| `missing` | Should be present by policy and is not — an integrity finding (`req-tap-cares-evidence-integrity`) |

Retention runs as a scheduled tap-cares task under its own capability (`cares.expire_evidence`), records what it removed, and never removes a blob still referenced by a record whose class has not expired (dedup means one blob may serve many records).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-retention-1 | Policy Declared Or Disabled | Proposed | With no `evidence_retention` in the profile, no blob is written and each opted-in run records `EVIDENCE_DISABLED`. | |
| req-tap-cares-evidence-retention-2 | Expiry Keeps The Record | Proposed | After expiry the node exists with `blob_state = expired` and the policy row; `open(digest)` refuses with a typed error naming the state. | |
| req-tap-cares-evidence-retention-3 | Shared Blob Survives | Proposed | A blob referenced by one expired and one live record is kept. | |

### Integrity
----
RID: `req-tap-cares-evidence-integrity`

Status: `Proposed`

Every read verifies: `open(digest)` streams the bytes through sha256 and refuses to complete if the digest differs, raising a typed error and recording an `EVIDENCE_INTEGRITY` finding on the grid (a `security`-domain `CONCERN`, `req-sec-concern-gaps-4`) naming the record, the expected and observed digests, and the reader. A blob that should be present by policy and is not (`blob_state = missing`) is the same finding class. A scheduled verification pass may walk the store; v0 requires the on-read check only.

sha256 through the platform's validated provider is the only cryptography this spec uses (`spec-fips.md`); nothing new is introduced.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-integrity-1 | Mismatch Refused And Recorded | Proposed | A blob altered on disk is refused on read and an `EVIDENCE_INTEGRITY` finding exists naming the record. | |
| req-tap-cares-evidence-integrity-2 | Missing Is A Finding | Proposed | A record whose blob is absent while policy says present reads `blob_state = missing` and the same finding is recorded on first access. | |

### Access
----
RID: `req-tap-cares-evidence-access`

Status: `Proposed`

| Surface | Capability | Notes |
| --- | --- | --- |
| `evidence_record` nodes (metadata) | `grid.read` | Queryable like any node; this is what Player 3 reads to reason about provenance |
| Bytes (`open`) | `cares.read_evidence` (new; `risk: high`; not on any default role) | Through the tap-cares service only; every byte read is itself recorded (`EVIDENCE_READ`: record, reader, time) — audit information is protected by auditing its access (AU-9) |
| Expiry | `cares.expire_evidence` (new) | The scheduled task's actor |
| Write | The `tap_cares.collector` program actor during a run | No other path writes evidence |

Declared in `tap_auth/tap_auth.capabilities.json` beside the existing `cares.*` capabilities; the direct-write and authz backstops apply as to any TAP-managed type.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-access-1 | Metadata Readable, Bytes Gated | Proposed | An actor with `grid.read` alone can query `evidence_record` nodes and receives a capability error from `open`. | |
| req-tap-cares-evidence-access-2 | Reads Recorded | Proposed | Each successful `open` produces an `EVIDENCE_READ` record naming the reader. | |

### Opt-In Through One Hook
----
RID: `req-tap-cares-evidence-optin`

Status: `Proposed`

`CollectorBase` (`tap_cares/collectors/base.py`) gains `record_evidence(gather) -> digest | None`: the collector's seam calls it once per response with the gather object (bytes plus the facts in `req-tap-cares-evidence-record`). The base writes the blob, accumulates the record on the instance (the `_produced_batches` pattern, `req-tap-cares-collector-grift-import-5`), and the task body lands the records and edges. `submit_grift` gains `evidence=` for `DERIVED_FROM_EVIDENCE`.

Opt-in is **declared, not inferred**: a collector's plugin spec carries an **Evidence** section stating one of three postures — *records evidence* (which surfaces), *does not* (why: e.g. the source is local files already on disk; the source forbids retention), or *not yet*. A collector that never calls the hook and declares nothing is an omission the plugin-validation report lists, not a decision.

The first implementer is github_core through its reliability spec's *Gather, Confirm, Process* requirement; the gather it already defines is this hook's argument without translation.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-optin-1 | One Call Per Response | Proposed | A collector calling `record_evidence` once per response ends its run with exactly that many `evidence_record` nodes linked to the job. | |
| req-tap-cares-evidence-optin-2 | Posture Declared | Proposed | The plugin report shows each collector's evidence posture (records / does not / undeclared); undeclared is listed as a gap. | Three states. |

### Replay
----
RID: `req-tap-cares-evidence-replay`

Status: `Proposed`

Because processing layers consume gathers and never the network (the first implementer's *Processing Is Network-Blind* criterion), a stored record rebuilds a gather: bytes from the store, facts from the node. `tap_cares.evidence.replay(job) -> Iterable[Gather]` yields a job's evidence in the order received; a collector's processing layer fed those gathers must produce a byte-identical GRIFT batch to the live run — the first implementer's *Replayable* criterion (its reliability spec) is this requirement's first consumer and its proof.

The operator surface — a management command that re-runs processing for a job and lands or diffs the result — is deferred (`Future` below) until a second consumer needs it; the library function ships first because the test suite is the first user and the command is a thin wrapper that would otherwise be designed without a use.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-replay-1 | Gathers Rebuilt | Proposed | `replay(job)` yields gathers whose bytes and facts equal those recorded, in received order. | |
| req-tap-cares-evidence-replay-2 | Byte-Identical Batch | Proposed | The first implementer's processing over `replay(job)` equals the live batch. | Proven by the first implementer's *Replayable* criterion. |

#### Future

`manage.py replay_collection <job> [--diff|--land]` once a second consumer (an operator re-deriving after a shaper fix; a corpus refresh) exists.

### Sizing And Write Path
----
RID: `req-tap-cares-evidence-sizing`

Status: `Proposed`

| Figure | Value | Provenance |
| --- | --- | --- |
| One GraphQL pull-request page | 248 KB | *observed* 2026-09-14 (the truncated read: 219,264 of 248,285 bytes) |
| One GraphQL config-layer page | a few MB (100 repositories with inlined workflow trees) | *estimated* from the query shape |
| REST pages | 20–100 KB each, hundreds per run | *estimated* |
| Raw JSON per run | 20–60 MB | *estimated* |
| Compressed at rest | ~10× smaller (JSON with repeated keys) | *documented* for zstd on JSON |
| Per organization per year, one run per day | 1–2 GB compressed | *estimated* |
| Records per run | hundreds (one per response) — against the *observed* 7,693 nodes the first implementer lands per run | *observed* / *estimated* |

**Write path.** Bytes are written **synchronously as received** (`put` before the gather is returned to the collector): a crash later in the run loses nothing already received, and the cost is one fsync of a compressed page, milliseconds against network calls of seconds. Records accumulate in memory and land as `evidence_record` nodes plus edges **at each layer boundary** and at terminal state, so a run with hundreds of responses does not write hundreds of node transactions inline and a FAILED run still lands what it gathered. Blob writes never go through the request thread's grid connection.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-sizing-1 | Synchronous Bytes | Proposed | Killing a collector after the tenth response leaves ten blobs present. | |
| req-tap-cares-evidence-sizing-2 | Batched Metadata | Proposed | A run of N responses produces at most (layers + 1) node-writing transactions for evidence, not N. | |
| req-tap-cares-evidence-sizing-3 | Measured, Not Estimated | Proposed | After the first implementer's first retained run, this table's *estimated* rows are replaced by *observed* values in a spec update. | The spec says what it does not know. |

### Object Lock
----
RID: `req-tap-cares-evidence-worm`

Status: `Backlog`

An `EvidenceStore` implementation over an S3-compatible object store with Object Lock in **compliance mode** (no principal can shorten retention until the date) for instances whose assessment requires WORM; governance mode is the operator-testing form. The filesystem store's immutability is procedural (no writer but `EvidenceStore`; no delete but expiry) and this spec says so. Enter a sprint when an assessment names the control.

### Signing And Transparency
----
RID: `req-tap-cares-evidence-signing`

Status: `Backlog`

Sign each job's evidence manifest (the ordered digests) and record it in an append-only transparency log (Sigstore/Rekor or a self-hosted equivalent), so tampering with the store is detectable by a party who does not trust the operator. The digest chain landed by this spec is the prerequisite; the signing key's custody is the open question.

### Auditor Export
----
RID: `req-tap-cares-evidence-export`

Status: `Backlog`

`manage.py export_evidence --scope <job|collector|date-range>` producing a bundle: a manifest of digests, the records as JSON, the bytes, and the custody edges as an in-toto-shaped statement per batch, for handing to an assessor. Needs the export format decided with a real assessor first.

### v0 Non-Goals
----
RID: `req-tap-cares-evidence-nongoals`

Status: `Proposed`

- **Rewriting or redacting bodies.** Never; sensitivity is flagged and access-gated (`req-tap-cares-evidence-redaction`).
- **Evidence for sources that are already artifacts** (local files, git objects, a scanner's own output already on disk). Their bytes are their own evidence; a collector declares *does not* with that reason.
- **A search or panel over evidence.** `evidence_record` nodes are Gryphon-queryable; a page is built when someone needs one.
- **Cross-instance or federated evidence.** One instance, one store.
- **Retention by default.** No policy, no retention, said out loud.

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
| Deprecated |  |
| Backlog | Shaped, deliberately deferred; enters a sprint on a named trigger |

## RID Format

`req-tap-cares-evidence-<feature>[-<n>]`
