# tap-cares Evidence Specification

**What we say we received from the source, kept exactly.** A collector that talks to an external system retains the exact bytes each call returned, content-addressed by digest, with the facts of the request beside them, so that every node and edge on the grid traces back through its batch and its collection job to the evidence it was derived from — and so that processing can be replayed against that evidence without touching the source again.

## Philosophy

The grid holds what TAP *derived*: nodes and edges shaped from what a source answered. Today nothing holds what the source *said*. When a shaper is wrong, when a source truncates a response, when an auditor asks how a control status was established, the answer is a traceback or a memory of a run. George, 2026-09-14: "collectors retain the exact bytes returned by their respective APIs / GraphQL endpoints so that we have a full auditability record … provenance traceable back to what we say we received from the source … a repeatable, standardized process … an important capability for FedRAMP compliance and others."

This is a **tap-cares** capability, not a collector's. A collector runs in three layers — it *gathers*, *confirms* the gather is reliable, then hands it to the *processing* layers above (the first implementer's reliability spec, `spec-github-core-reliability.md`, requirement *Gather, Confirm, Process*). The gather is already the evidence: bytes, digest, completeness, request facts. This spec owns the **Gather contract** every collector's seam produces, the store those gathers land in, and the rules every opted-in collector follows, so the second implementer writes no storage code and an auditor reads one shape across every source.

**Prior art** (surveyed 2026-09-14; *documented*):

- **in-toto attestations / SLSA provenance.** A statement names immutable *subjects* by digest and a *predicate* about them; SLSA's provenance predicate lists the *materials* a build consumed, each by digest. Borrow the shape exactly: the GRIFT batch and its nodes are the subject, the shaping is the predicate, the evidence records are the materials. Reject building the full attestation envelope in v0 — the grid's own edges carry the relation, and a signed envelope is a Backlog export.
- **Content-addressed storage** (git objects, OCI blobs). Key bytes by their sha256; identical content is stored once; immutability and deduplication come free; a digest mismatch is detectable by construction. Borrow whole — for the *bytes*. The *observation* (that we received this, then, from there) is not content-addressed: two observations can share bytes and remain two facts.
- **NIST SP 800-53 audit controls.** AU-3 (content of audit records: what, when, where, source, outcome, subject), AU-9 (protection of audit information), AU-11 (retention), SI-7 (software, firmware and information integrity). FedRAMP evidence collection today is largely exports and screenshots; machine evidence with a digest chain is the stronger form, and the record shape below is written to answer AU-3's six questions directly.
- **WORM / object lock** (S3 Object Lock: governance mode, which privileged users can override, and compliance mode, which nobody can until the retention date). Borrow the distinction as a Backlog requirement; v0 stores on a filesystem where the guarantee is procedural, and says so.
- **Transparency logs** (Sigstore / Rekor). Signing evidence digests into an append-only log makes tampering with the store detectable by a third party. Backlog: the digest chain is the prerequisite and lands now.
- **Request identity from the source.** A source that returns a request id and an `ETag` gives the record two identifiers an auditor can take back to the vendor. Record them when present; never depend on them.

What the survey changed: the chain of custody became *edges on the grid* rather than fields on the job — the in-toto shape is subject → materials, and the grid already expresses that as `Batch → evidence_record`. And retention became a question this spec refuses to answer prematurely: v0 keeps everything, and the policy questions are written down where the Backlog requirement will settle them.

Three doctrines bear directly. **Derive a fact once:** the bytes are the fact; digest, size and every derived field come from them, never typed twice, and where a fact must be duplicated for a query the duplicate is derived by one function and checked. **Presence is not correctness:** a record is verified against its bytes on every read, never trusted because a row exists; a column nobody writes is a trap and is not declared. **Three states, never two:** a collector's evidence posture is *required*, *best effort* or *off*; a blob is *present* or *missing*, and missing is always a finding until retention exists to make a third state honest.

**Provenance markers.** Claims marked *observed* were measured on the first implementer (github_core) on 2026-09-14; prior art is *documented*; everything else is *designed*. Nothing in this spec is implemented.

## Goals

| # | Name | Description |
| --- | --- | --- |
| 1 | Exact Bytes | What the source returned is kept unaltered and content-addressed; nothing is rewritten, summarized or reformatted on the way in. |
| 2 | Chain Of Custody | Any node or edge on the grid resolves, by edges, to the evidence records it was derived from, and each to its digest and request facts. |
| 3 | One Shape, Every Source | The Gather contract, the record, the store and the access path are tap-cares'; a collector opts in through one hook and writes no storage code. |
| 4 | Replayable | Processing layers can be fed stored evidence and produce the same batch, modulo a listed set of non-deterministic fields, so regression corpora, offline re-derivation and diagnosis need no source access. |
| 5 | Kept Until Retention Lands | v0 expires nothing; a blob that is not where its record says it is, is always an integrity finding. Retention is a Backlog requirement with its questions written down. |
| 6 | Legible To Player 3 | Evidence metadata is on the grid, Gryphon-queryable, with structured codes; bytes are readable under a named capability. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-cares-evidence-record | [The Evidence Record](#the-evidence-record) | Proposed | Columns for the questions, an open blob for the shape; sequence and schema version; the payload never in the row |
| req-tap-cares-evidence-store | [Blob Store, Envelope And Grid Node](#blob-store-envelope-and-grid-node) | Proposed | Content-addressed bytes plus a durable observation envelope, written before the call returns; recovery sweep; the `evidence_record` node |
| req-tap-cares-evidence-custody | [Chain Of Custody](#chain-of-custody) | Proposed | `CollectionJob → evidence_record` and `Batch → evidence_record` edges naming record ids; node → batch → evidence resolves in Gryphon |
| req-tap-cares-evidence-redaction | [Exact Bytes, Flagged Sensitivity](#exact-bytes-flagged-sensitivity) | Proposed | Bodies never rewritten; one validator over every metadata field; sensitive content flagged, not removed |
| req-tap-cares-evidence-retention | [Retention Policy](#retention-policy) | Backlog | Not soon (George, 2026-09-14). v0 keeps everything; the questions retention must settle are listed here |
| req-tap-cares-evidence-integrity | [Integrity](#integrity) | Proposed | Verify before releasing bytes; decompression failure and digest mismatch share one error contract; a finding on the grid |
| req-tap-cares-evidence-access | [Access](#access) | Proposed | Metadata under `grid.read`; bytes by record id under `cares.read_evidence`; reads recorded |
| req-tap-cares-evidence-optin | [The Gather Contract, Opt-In And Failure Semantics](#the-gather-contract-opt-in-and-failure-semantics) | Proposed | tap-cares owns `Gather`; `record_evidence(gather) -> id`; posture `required / best_effort / off` decides what a preservation failure does |
| req-tap-cares-evidence-replay | [Replay](#replay) | Proposed | Records in `sequence` order, at the recorded processing identity, against an empty grid; identical modulo a listed field set |
| req-tap-cares-evidence-sizing | [Sizing And Write Path](#sizing-and-write-path) | Proposed | Bytes and envelope written synchronously; nodes and edges batched per layer; numbers with provenance |
| req-tap-cares-evidence-worm | [Object Lock](#object-lock) | Backlog | Compliance-mode immutability on an object store |
| req-tap-cares-evidence-signing | [Signing And Transparency](#signing-and-transparency) | Backlog | Sign digests into an append-only log |
| req-tap-cares-evidence-export | [Auditor Export](#auditor-export) | Backlog | A bundle: manifest of digests, records, bytes, and the chain, for a named scope |
| req-tap-cares-evidence-skill | [Wired Into Collector Creation](#wired-into-collector-creation) | Proposed | The build-collector skill asks for the evidence posture and emits the hook; the undeclared default is decided before the skill edit lands |
| req-tap-cares-evidence-nongoals | [v0 Non-Goals](#v0-non-goals) | Proposed | What this spec deliberately does not do |

### The Evidence Record
----
RID: `req-tap-cares-evidence-record`

Status: `Proposed`

One record per response a collector received through its seam. The record has two parts: the **bytes**, stored exactly as received (undoing transport compression is fine; after that, nothing changes), and the **facts**, which answer AU-3's six questions by field.

| AU-3 question | Field | Rule |
| --- | --- | --- |
| What | `endpoint` (template, e.g. `/repos/{owner}/{repo}/actions/runs`, `graphql:config_layer`), `method`, `variables` | Template, never a URL with a query string; variables restricted to a per-collector allow-list (identifiers and cursors) — cursors live here and nowhere else |
| When | `observed_at` (source/world time of the response, `req-grid-history-time-2`), `recorded_at` (system time of the write), `sequence` (durable, per job, monotonic, assigned when the envelope is written), `call_group` (one logical call across its pages and retries), `attempt` | `sequence` is the replay order; `call_group` + `attempt` distinguish a retry from a new page |
| Where | `source` (the **observed system's identity only**: host or account — never a schema or collector name), `collector_key`, `collection_job` | `collection_job` is derived at write from the `PRODUCED_EVIDENCE` edge by one function and checked for consistency (`req-tap-cares-evidence-custody`); it is a query convenience, not a second truth |
| Source | `credential_kind` (e.g. `app`, `pat`, `none`) | Kind, never the value or a fingerprint of it |
| Outcome | `status` (HTTP or transport class), `complete` (the gather's completeness), `degraded_paths` (pruned partial-response paths), `failure_class` when the call failed | Copied from the gather; a failed call with a body is still evidence |
| Subject | `digest` (`sha256:<hex>` of the bytes), `size_bytes`, `content_type`, `source_request_id`, `etag` | Digest and size derived from the bytes at write; request id and etag copied from the gather's typed headers when the source supplies them — these are columns and are never repeated inside `configuration` |

Plus: `flags` (`contains_signed_urls`, `contains_credentials_suspected`, `non_json`) set by the seam's inspection (`req-tap-cares-evidence-redaction`), `compression` (how the bytes are stored at rest), `blob_state` (`present | missing`; `expired` arrives with `req-tap-cares-evidence-retention`), and `schema_version` (small integer; which version of the collector's `configuration` sub-schema this record was written under).

No response header is ever stored as a header dump; the Gather contract's typed subset (`req-tap-cares-evidence-optin`) is copied into named fields and nothing else survives.

**Columns for the questions, an open blob for the shape — the grid's relief valve, applied (George, 2026-09-14).** One `evidence_record` type serves every source; there is no `github_evidence` subclass. Every field above is a **typed column** on the model, strictly typed to Gryphon. Beside the columns sit the two open fields every TAP model carries:

| Field | Holds | Rule |
| --- | --- | --- |
| `configuration` | What varies by source and is never filtered on — a source's rate-limit snapshot, a query's cost, a provider's region and API version, a scanner's binary version and persona | Sub-schema selected by **`collector_key` + `schema_version`**, never by `source` (a source is an identity, not a shape); **each opted-in collector's spec declares every sub-schema version it has ever written**, so a historical record validates against the version it names and stays readable when the shape moves; the un-schema'd-blob tolerance of 2026-06-30 is not extended to the one type whose job is auditability |
| `tags` | Facts the seam knows at fetch time that have no node to link yet: the layer name, a repository full name before it resolves | Free in shape, not in content: the same validator as every other field; a cursor is not a tag |

**One authoritative home per fact.** The record validator rejects a `configuration` or `tags` key that duplicates a column (`source_request_id`, `etag`, `digest`, `observed_at`, `status`, `endpoint`, …) and a `tags` key that duplicates `variables`. The only permitted duplicate is `collection_job` against the edge, derived by one function and consistency-checked (`req-tap-cares-evidence-custody-1`).

**The payload is never in the row.** A finding model elsewhere keeps a scanner's verbatim output in a `raw` JSON field, and that precedent stops here: tens of megabytes per run, sensitive content, JSONB rows. The bytes live in the store (`req-tap-cares-evidence-store`); the row holds the digest.

**Indexes are justified by principal queries**, not sprayed over every filterable column:

| Principal query | Index |
| --- | --- |
| (a) All records of a job, in order — replay, diagnosis | `(collection_job, sequence)` |
| (b) Records by content — dedup, "who else received these bytes" | `(digest)` |
| (c) A collector's records over time | `(collector_key, observed_at)` |
| (d) A source's records for one endpoint over time — "what did the vendor say about X, when" | `(source, endpoint, observed_at)` |
| (e) The integrity sweep — everything not present | partial index on `(blob_state) WHERE blob_state <> 'present'` |
| (f) Schema selection for validation | `(collector_key, schema_version)` |

No standalone index on a boolean (`complete`, flags): they filter within (a)–(d), never lead a query.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-record-1 | Bytes Exact | Proposed | The stored bytes, decompressed from at-rest form, equal the bytes the seam received, byte for byte; the digest equals their sha256. | |
| req-tap-cares-evidence-record-2 | Six Questions Answered | Proposed | Every record carries `endpoint`, `method`, `observed_at`, `recorded_at`, `sequence`, `call_group`, `attempt`, `source`, `collector_key`, `credential_kind`, `status`, `complete`, `digest`, `size_bytes`, `schema_version`. | AU-3 mapping plus replay order. |
| req-tap-cares-evidence-record-3 | No Secret Shape | Proposed | No field — columns, `configuration` or `tags` — contains a URL query string, an `Authorization` value, a credential value or a header dump; the record schema rejects unknown top-level keys. | One validator (`req-tap-cares-evidence-redaction`). |
| req-tap-cares-evidence-record-4 | Indexes Serve Named Queries | Proposed | The model declares exactly the indexes (a)–(f) above; a class-def test asserts each exists and names the principal query it serves; no index exists on a boolean alone. | |
| req-tap-cares-evidence-record-5 | Open Fields, Declared Per Collector And Version | Proposed | `configuration` validates against the sub-schema the opted-in collector's spec declares for the record's `collector_key` + `schema_version`; a record written under an older version still validates against that version; a `configuration`/`tags` key duplicating a column or `variables` is rejected. | First implementer: github_core's seam. |
| req-tap-cares-evidence-record-6 | Payload Never In The Row | Proposed | No field of `evidence_record` holds the response bytes or a parsed copy of them; a guard fails a model that adds one. | The `raw`-in-row precedent is named and rejected. |

### Blob Store, Envelope And Grid Node
----
RID: `req-tap-cares-evidence-store`

Status: `Proposed`

Bytes are not rows. They live in a **content-addressed blob store** under a TAP data root. The **observation** — the facts and custody ids of one response — is written durably beside them as an **envelope** before the call returns, so that what the collector received survives a crash whether or not the grid was ever told. The grid node is created from the envelope, by the run or by recovery.

#### Implementation

- **Capture is on iff `TAP_EVIDENCE_ROOT` is configured.** Unset → the hook records `EVIDENCE_DISABLED` once per run and stores nothing (three states: capturing / disabled / not opted in). No retention policy exists in v0; nothing expires (`req-tap-cares-evidence-retention`).
- **Blob store.** `TAP_EVIDENCE_ROOT/blobs/sha256/<aa>/<bb>/<hex>`, bytes compressed at rest (`zstd`; `compression` on the record). Writes are `write-temp → fsync → rename`: a blob is whole or absent. Identical content across observations is one blob.
- **Envelope.** `TAP_EVIDENCE_ROOT/observations/<job-id>/<sequence>.json`: the record's facts (every column of `req-tap-cares-evidence-record`, including the intended `evidence_record` entity id, minted at write), written `write-temp → fsync → rename` **after** the blob and **before** `record_evidence` returns. The envelope, not the node, is the durability boundary.
- **Recovery sweep.** At worker start and at the start of each run of the same collector, `recover_evidence()` walks `observations/` for envelopes with no matching `evidence_record` node and creates the node and its custody edges from the envelope (idempotent by entity id). An envelope whose blob is absent creates the node with `blob_state = missing` and an integrity finding (`req-tap-cares-evidence-integrity`).
- **The guarantee, stated exactly:** after a crash following N successful `record_evidence` calls, recovery yields N records, every custody edge, and one blob per distinct digest — no more is promised. Facts the run had not yet gathered are not evidence; a `submit_grift` that never ran produces no batch and no `DERIVED_FROM_EVIDENCE` edges.
- **Grid node.** `tap_cares.models.EvidenceRecord`, `ENTITY_TYPE = "evidence_record"`, `DEFAULT_DIMENSIONS = {"tap_cares": "evidence_record"}`, INTERNAL_ONLY like `CollectionJob` (`req-tap-cares-collector-job-model`), with the columns and indexes of `req-tap-cares-evidence-record`.
- **Store interface.** One class, `EvidenceStore`: `put(bytes) -> digest`, `write_envelope(envelope)`, `read_verified(digest) -> bytes` (`req-tap-cares-evidence-integrity`), `exists(digest)`, `stat(digest)`, `iter_envelopes()`. Digest-keyed access is **internal** to this class; every public read is by record id (`req-tap-cares-evidence-access`). The filesystem implementation is v0; an object-store implementation is the Backlog seam (`req-tap-cares-evidence-worm`). No other module touches the root.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-store-1 | Content Addressed | Proposed | Two records with identical bytes share one blob path; `put` of existing content is a no-op returning the digest. | |
| req-tap-cares-evidence-store-2 | Atomic Blobs And Envelopes | Proposed | A write interrupted before rename leaves no blob and no envelope at its path. | |
| req-tap-cares-evidence-store-3 | Crash Recovery, Exactly | Proposed | A collector killed after its tenth `record_evidence` call — two of the ten bodies identical — recovers to exactly 10 `evidence_record` nodes, 9 blobs, and every `PRODUCED_EVIDENCE` edge; no `DERIVED_FROM_EVIDENCE` edge exists because no batch was submitted. | The guarantee, tested as stated. |
| req-tap-cares-evidence-store-4 | Node Per Observation | Proposed | Each response produces one `evidence_record` node even when its bytes deduplicate. | |
| req-tap-cares-evidence-store-5 | One Root, One Class | Proposed | Only `EvidenceStore` reads or writes under `TAP_EVIDENCE_ROOT`; a guard test walks tap_cares and every installed collector for other references. | |
| req-tap-cares-evidence-store-6 | Off When Unconfigured | Proposed | With `TAP_EVIDENCE_ROOT` unset, an opted-in run stores nothing and records `EVIDENCE_DISABLED` once. | |

### Chain Of Custody
----
RID: `req-tap-cares-evidence-custody`

Status: `Proposed`

The in-toto shape on the grid: the batch and its nodes are the subject; the evidence records are the materials. Edges name **record ids** — observations — never digests, because two observations may share bytes and the chain must say which one this batch used.

| Edge | From → To | Created by | Meaning |
| --- | --- | --- | --- |
| `PRODUCED_EVIDENCE` | `collection_job → evidence_record` | The task body at each layer boundary and at terminal state, from the collector's accumulator (the `PRODUCED_BATCH` pattern, `req-tap-cares-collector-grift-import-6`), or by recovery from the envelope | This run received this |
| `DERIVED_FROM_EVIDENCE` | `batch → evidence_record` | `submit_grift(document, evidence=[record_id, …])`: the collector names the records a batch was processed from | This batch's facts came from these observations |

With FLIP already pointing every field at the batch that set it (`req-grid-flip-batch-1`), any node resolves: field → batch → `DERIVED_FROM_EVIDENCE` → record → digest and request facts. The canonical question is one Gryphon traversal from the batch; a panel or Player 3 needs no tap_cares code to answer "says who?".

The record's `collection_job` column is **derived from the `PRODUCED_EVIDENCE` edge** by one function at write (`TAP-KNOWN-DUPE(evidence-job-column)`, documented in `specs/spec-tap-known-dupes.md` when built); a consistency check in the integrity sweep reports any record whose column and edge disagree.

A FAILED run's evidence is still linked (the failure path already links produced batches, `req-tap-cares-collector-failure-mode`): what the source said before the run died is exactly the evidence a diagnosis wants.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-custody-1 | Job Links Its Evidence, Column Agrees | Proposed | After a run, `MATCH (j:collection_job)-[:PRODUCED_EVIDENCE]->(e:evidence_record) RETURN e` for the job returns one node per response received, including on a FAILED run; every returned record's `collection_job` column equals the job's id, and the sweep reports zero disagreements. | |
| req-tap-cares-evidence-custody-2 | Batch Names Its Materials By Id | Proposed | A batch submitted with `evidence=[ids]` carries a `DERIVED_FROM_EVIDENCE` edge to each named record; two records sharing a digest are distinguishable by which one the edge names. | |
| req-tap-cares-evidence-custody-3 | Node To Bytes | Proposed | From any node in the first implementer's batch, batch id → `DERIVED_FROM_EVIDENCE` → record → `read_evidence(record_id)` yields bytes whose digest matches the record. | |

### Exact Bytes, Flagged Sensitivity
----
RID: `req-tap-cares-evidence-redaction`

Status: `Proposed`

Two rules pull against each other and this spec states the tension rather than hiding it. Evidence must be **exact** — a rewritten body is not evidence. Sources return **sensitive material** in bodies: signed download URLs that grant access for minutes, secret names, emails, private configuration text.

Resolution:

1. **Bodies are never rewritten.** The bytes are the bytes.
2. **One validator over every metadata field.** The no-credential / no-query-string / no-header-dump rule the first implementer's seam applies to run records (its reliability spec, requirement *Observability*) runs over the record's columns **and over `configuration` and `tags`**, because all of it is readable under `grid.read`. A record that fails validation is not written; under posture `required` that fails the run (`req-tap-cares-evidence-optin`).
3. **Sensitivity is flagged, not removed.** The seam inspects the body cheaply at write (a signed-URL pattern; a credential-shaped token pattern) and sets `flags`.
4. **Access is the protection** (`req-tap-cares-evidence-access`): bytes are readable only under a capability that is not granted by default, through the service layer, with the read itself recorded.
5. **Named accepted risk** (`req-sec-honest-risk-1`): an actor with `cares.read_evidence` can read a signed URL for as long as the source honours it. The store does not shorten that window; the source's expiry does.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-redaction-1 | Bytes Untouched | Proposed | A body containing a signed URL is stored byte-identical and the record carries `contains_signed_urls: true`. | |
| req-tap-cares-evidence-redaction-2 | Metadata Validated Everywhere | Proposed | A query-string token in `variables`, an `Authorization` value in `configuration`, and a header dump in `tags` are each rejected by the same validator; the record is not written. | |

### Retention Policy
----
RID: `req-tap-cares-evidence-retention`

Status: `Backlog`

Not soon (George, 2026-09-14: "we're not going to build that anytime soon"). **v0 keeps everything:** capture is on iff `TAP_EVIDENCE_ROOT` is configured (`req-tap-cares-evidence-store`), nothing expires, `blob_state` is `present | missing`, and a missing blob is always an integrity finding. There is no retention class on the record and no expiry capability, because a column nobody writes and a capability nobody holds are presence traps.

When this requirement is built it must settle, at minimum:

- **The policy surface.** Where an instance declares retention (boot profile), the classes (by collector, by flag, by run outcome), and what "no policy declared" means once expiry exists.
- **Expiry versus physical availability of a shared blob.** Dedup means one blob serves many records; a blob is removable only when *every* record referencing it has expired, so "expired" on a record and "absent" on disk are different facts and the record must carry both.
- **Policy change.** Shortening retention must not retroactively remove blobs still referenced by a record under the old class without an explicit, recorded decision; lengthening cannot resurrect a removed blob and must say so.
- **Expiry versus concurrent collection.** A sweep running during a collection must never remove a blob a `record_evidence` call has just deduplicated onto; the ordering (envelope before blob release, or a reference count under the store's lock) is the design question.
- **The third state.** `blob_state = expired` (removed by a named policy row on a recorded date) joins `present | missing`, and only then does "missing" narrow to "should be present and is not".
- **Capability and actor.** `cares.expire_evidence` and the scheduled task that holds it.

### Integrity
----
RID: `req-tap-cares-evidence-integrity`

Status: `Proposed`

**Verify before releasing bytes.** `EvidenceStore.read_verified(digest)` decompresses into a bounded buffer (or a temp file above a size threshold), hashes the result, compares, and only then hands the bytes to the caller. It never streams to the caller and rejects at the end; a caller either receives verified bytes or an error. Decompression failure and digest mismatch share **one error contract**: `EvidenceIntegrityError` (typed: record id, expected digest, observed digest or `undecodable`, reader) and an `EVIDENCE_INTEGRITY` finding on the grid — a `security`-domain `CONCERN` (`req-sec-concern-gaps-4`) — naming the same facts. A record whose blob is absent (`blob_state = missing`) raises the same error class and records the same finding on first access.

A scheduled verification pass (`req-tap-cares-evidence-sizing` names its index) walks records not `present` and any sample of present ones; v0 requires the on-read check.

sha256 through the platform's validated provider is the only cryptography this spec uses (`spec-fips.md`); nothing new is introduced.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-integrity-1 | Verified Before Release | Proposed | A blob altered on disk yields `EvidenceIntegrityError` and no bytes reach the caller; the `EVIDENCE_INTEGRITY` finding names the record and both digests. | |
| req-tap-cares-evidence-integrity-2 | Undecodable Is The Same Error | Proposed | A blob truncated on disk (decompression fails) yields the same error class and finding, with `observed = undecodable`. | |
| req-tap-cares-evidence-integrity-3 | Missing Is A Finding | Proposed | A record whose blob is absent reads `blob_state = missing`, raises the same error on read, and the finding is recorded once. | |

### Access
----
RID: `req-tap-cares-evidence-access`

Status: `Proposed`

Every public surface is keyed by **record id** — the observation — never by digest.

| Surface | Capability | Notes |
| --- | --- | --- |
| `evidence_record` nodes (metadata) | `grid.read` | Queryable like any node; what Player 3 reads to reason about provenance; `configuration` and `tags` included, hence the validator |
| `read_evidence(record_id) -> bytes` | `cares.read_evidence` (new; `risk: high`; on no default role) | The tap-cares service resolves the record, calls `read_verified(digest)`, and records `EVIDENCE_READ` (record id, reader, time) — audit information protected by auditing its access (AU-9) |
| Write | The `tap_cares.collector` program actor during a run, and the recovery sweep at worker start | No other path writes evidence |

Declared in `tap_auth/tap_auth.capabilities.json` beside the existing `cares.*` capabilities; the direct-write and authz backstops apply as to any TAP-managed type.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-access-1 | Metadata Readable, Bytes Gated | Proposed | An actor with `grid.read` alone can query `evidence_record` nodes and receives a capability error from `read_evidence`. | |
| req-tap-cares-evidence-access-2 | Reads Recorded By Id | Proposed | Each successful `read_evidence` produces an `EVIDENCE_READ` record naming the record id and the reader. | |
| req-tap-cares-evidence-access-3 | No Public Digest Path | Proposed | No service or view accepts a digest as a read key; `read_verified` is not importable outside `EvidenceStore`'s module (guard test). | |

### The Gather Contract, Opt-In And Failure Semantics
----
RID: `req-tap-cares-evidence-optin`

Status: `Proposed`

**tap-cares owns the `Gather` contract.** `tap_cares.collectors.gather.Gather` is a protocol (and reference dataclass) with the named fields the record needs: `bytes`, `surface`, `scope`, `endpoint` (template), `method`, `variables`, `complete`, `degraded_paths`, `failure_class`, `status`, `observed_at`, `credential_kind`, `headers` (the typed subset: request id, etag, date, and whatever else the collector's spec names), `call_group`, `attempt`, and `configuration` (the collector's declared sub-schema contribution, with its `schema_version`). A collector's seam produces objects conforming to it; the first implementer's `gather.py` conforms. **Adoption instructions live in the plugin's spec**, not here.

**One hook.** `CollectorBase` (`tap_cares/collectors/base.py`) gains `record_evidence(gather) -> evidence_record_id | None`: the seam calls it once per response. The base puts the blob, assigns `sequence`, mints the record's entity id, writes the envelope, accumulates the record on the instance (the `_produced_batches` pattern, `req-tap-cares-collector-grift-import-5`), and returns the id the collector will later pass to `submit_grift(document, evidence=[…])`. The task body lands nodes and edges at layer boundaries and terminal state.

**Posture, declared per collector** in its spec and on a manifest surface to be named when built: `evidence: required | best_effort | off`.

| Posture | On a preservation failure (root unwritable, disk full, envelope write failed, node or edge write refused, validator rejection) | On `submit_grift(evidence=…)` with a record that was not preserved |
| --- | --- | --- |
| `required` | `record_error` + raise — the run **FAILS loudly** under the standard failure protocol (`req-tap-cares-collector-failure-mode-1`, `-2`); evidence is part of the collector's correctness | Refuses to commit the batch: `GRIFT_BATCH_REJECTED`-shaped error naming the missing record ids (`req-tap-cares-collector-grift-import-11`) |
| `best_effort` | `EVIDENCE_LOST` warn record (what, why, sequence); the run continues | Commits the batch without that link and records `EVIDENCE_UNLINKED` naming the batch and the missing ids |
| `off` | Nothing; the hook is a no-op returning `None` | No edges; nothing recorded |

A collector that declares nothing is `undeclared` — listed as a gap by the plugin-validation report, never treated as `off`. `EVIDENCE_DISABLED` (root unconfigured, `req-tap-cares-evidence-store`) is a fourth, instance-level state and overrides posture for the run.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-optin-1 | Contract Conformance | Proposed | A gather missing any named field is rejected by `record_evidence` with a typed error before anything is written. | |
| req-tap-cares-evidence-optin-2 | One Call, One Record, One Id | Proposed | A collector calling `record_evidence` once per response ends its run with exactly that many `evidence_record` nodes linked to the job, and the ids it received are the ids on the nodes. | |
| req-tap-cares-evidence-optin-3 | Required Fails Loudly | Proposed | Under `required`, an unwritable root fails the run with one error record; `submit_grift(evidence=[unknown_id])` refuses the batch. | |
| req-tap-cares-evidence-optin-4 | Best Effort Says So | Proposed | Under `best_effort`, the same failures yield `EVIDENCE_LOST` / `EVIDENCE_UNLINKED` warn records, a SUCCESSFUL run and a committed batch. | |
| req-tap-cares-evidence-optin-5 | Posture Declared | Proposed | The plugin report shows each collector's posture (`required` / `best_effort` / `off` / `undeclared`); `undeclared` is listed as a gap. | Three states plus the omission. |

### Replay
----
RID: `req-tap-cares-evidence-replay`

Status: `Proposed`

Because processing layers consume gathers and never the network (the first implementer's *Processing Is Network-Blind* criterion), a stored record rebuilds a gather: bytes via `read_verified`, facts from the node. Determinism is made concrete, not assumed:

- **Order.** `tap_cares.evidence.replay(job) -> Iterable[Gather]` yields the job's records in `sequence` order; `call_group` and `attempt` let a consumer collapse retries exactly as the live run did.
- **Processing identity.** At run time the job records, in `CollectionJob.results` under `processing_identity`: the plugin distribution and version, the collector's manifest digest, and the seam's constants that affect shaping (page sizes, caps). Replay is defined **at that recorded identity**; a replay at another version is a migration test, not a replay.
- **Ground.** Replay runs against an **empty grid** or a named snapshot; identity-derived ids (uuid5 through the plugin's identity functions) make node and edge ids deterministic without the live grid.
- **The contract.** Processing at the recorded identity, fed `replay(job)`, produces a batch **identical modulo the listed fields**: `batch_entity.entity_id` and `batch_node.name`; every `recorded_at`; `CollectionJob`-scoped ids in edges to the job; and any field the collector's spec lists as non-deterministic (it must list them; an unlisted difference is a defect). Everything else — node ids, node data, edge ids, edge properties, dimensions — is byte-identical after canonical JSON serialization.

The operator surface (a management command that re-runs processing for a job and lands or diffs the result) is deferred to Future until a second consumer exists; the library function ships first because the first implementer's *Replayable* criterion is its first user and proof.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-replay-1 | Ordered, Verified Gathers | Proposed | `replay(job)` yields gathers in `sequence` order whose bytes pass `read_verified` and whose facts equal the records. | |
| req-tap-cares-evidence-replay-2 | Identity Recorded | Proposed | Every job of an opted-in collector carries `processing_identity` with dist, version, manifest digest and seam constants. | |
| req-tap-cares-evidence-replay-3 | Identical Modulo The List | Proposed | The first implementer's processing over `replay(job)` against an empty grid equals the live batch after canonical serialization, except exactly the listed fields; the test names any other difference. | The first implementer's *Replayable* criterion proves this. |

#### Future

`manage.py replay_collection <job> [--diff|--land]` once a second consumer (an operator re-deriving after a shaper fix; a corpus refresh) exists.

### Sizing And Write Path
----
RID: `req-tap-cares-evidence-sizing`

Status: `Proposed`

| Figure | Value | Provenance |
| --- | --- | --- |
| One large paged response | 248 KB | *observed* on the first implementer, 2026-09-14 (a truncated read: 219,264 of 248,285 bytes) |
| One heavy aggregate response | a few MB | *estimated* from the first implementer's query shape |
| Ordinary paged responses | 20–100 KB each, hundreds per run | *estimated* |
| Raw JSON per run | 20–60 MB | *estimated* |
| Compressed at rest | ~10× smaller (JSON with repeated keys) | *documented* for zstd on JSON |
| Per source per year, one run per day | 1–2 GB compressed | *estimated* |
| Records per run | hundreds (one per response) — against the *observed* 7,693 nodes the first implementer lands per run | *observed* / *estimated* |

**Write path.** Blob and envelope are written **synchronously, before `record_evidence` returns** (`req-tap-cares-evidence-store`): two fsyncs of small files, milliseconds against network calls of seconds. Nodes and edges accumulate and land **at each layer boundary** and at terminal state, so a run of hundreds of responses does not write hundreds of node transactions inline, and recovery covers the gap between envelope and node. Blob writes never go through the request thread's grid connection.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-sizing-1 | Synchronous Preservation | Proposed | Killing a collector after the tenth response leaves ten envelopes and every distinct blob present. | Pairs with `store-3`. |
| req-tap-cares-evidence-sizing-2 | Batched Metadata | Proposed | A run of N responses produces at most (layers + 1) node-writing transactions for evidence, not N. | |
| req-tap-cares-evidence-sizing-3 | Measured, Not Estimated | Proposed | After the first implementer's first retained run, this table's *estimated* rows are replaced by *observed* values in a spec update. | The spec says what it does not know. |

### Object Lock
----
RID: `req-tap-cares-evidence-worm`

Status: `Backlog`

An `EvidenceStore` implementation over an S3-compatible object store with Object Lock in **compliance mode** (no principal can shorten retention until the date) for instances whose assessment requires WORM; governance mode is the operator-testing form. The filesystem store's immutability is procedural (no writer but `EvidenceStore`; no deletion path exists in v0) and this spec says so. Enter a sprint when an assessment names the control; depends on `req-tap-cares-evidence-retention`.

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

### Wired Into Collector Creation
----
RID: `req-tap-cares-evidence-skill`

Status: `Proposed`

George, 2026-09-14: "put a req at the bottom to update the collector creation skill (if we have one) so that this gets wired in and to decide how we want other collectors to fail." There is one: `tap_grid/skills/build-collector/SKILL.md`. Two things follow, in order.

**1. Decide the undeclared default first.** `req-tap-cares-evidence-optin` lists a collector that declares nothing as an `undeclared` gap — visible, tolerated. The alternative is to fail closed: undeclared means `required`, and a collector that never wrote the line cannot run until it does. Each has a cost. Tolerating keeps every existing collector running the day this ships and makes the gap a report line; failing closed makes auditability the default and turns the first boot after upgrade into a stop for every collector that has not chosen. This is George's decision, not the skill author's; it is recorded here (with the date and the reason) before the skill edit lands, and `req-tap-cares-evidence-optin` is amended to match. Until it is made, the spec's answer is `undeclared`.

**2. Then wire the skill.** The build-collector skill gains, in the same PR that flips this requirement:

| Where in the skill | What it gains |
| --- | --- |
| Step 1 (agreed shape) | An **evidence posture** item: `required` / `best_effort` / `off`, with one line on why, decided with the author like every other shape question; the default from (1) named so an author who skips it knows what they chose |
| Step 1.5 / Step 3 | When the collector's client goes through a seam, the seam produces `Gather`s (`tap_cares.collectors.gather.Gather`) and calls `record_evidence` — named as part of the client decision, so a hand-rolled client knows it owes the hook |
| Step 7 (collector class) | The `record_evidence(gather)` call site pattern and the `configuration` sub-schema the collector declares (`req-tap-cares-evidence-record-5`), with its `schema_version` |
| Step 8 (spec section) | The plugin spec's evidence table: posture, sub-schema per version, which surfaces are captured, which are `off` and why |
| Gotchas | The `raw`-in-row precedent, named as the thing not to do |

`new-plugin` and `create-plugin-spec` need one sentence each pointing at the posture question; they do not carry the mechanics.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-evidence-skill-1 | Default Decided And Recorded | Proposed | This section names the undeclared-posture decision (`undeclared` gap vs fail-closed `required`), who made it and when; `req-tap-cares-evidence-optin` says the same thing. | George's call. |
| req-tap-cares-evidence-skill-2 | Skill Asks And Emits | Proposed | `build-collector` Step 1 asks the posture; Step 7 shows the `record_evidence` call and the sub-schema declaration; Step 8's spec template carries the evidence table; the gotcha names `raw`-in-row. | One PR to tap, skills tier, after (1). |
| req-tap-cares-evidence-skill-3 | Sibling Skills Point | Proposed | `new-plugin` and `create-plugin-spec` each carry one sentence pointing at the posture question and this spec. | |

### v0 Non-Goals
----
RID: `req-tap-cares-evidence-nongoals`

Status: `Proposed`

- **Rewriting or redacting bodies.** Never; sensitivity is flagged and access-gated (`req-tap-cares-evidence-redaction`).
- **Retention, expiry, WORM, signing, export.** Backlog, each with its trigger named.
- **Evidence for sources that are already artifacts** (local files, git objects, a scanner's own output already on disk). Their bytes are their own evidence; a collector declares `off` with that reason.
- **A search or panel over evidence.** `evidence_record` nodes are Gryphon-queryable; a page is built when someone needs one.
- **Cross-instance or federated evidence.** One instance, one store.
- **Consumer-specific shapes in this spec.** What a particular source puts in `configuration`, and how its seam adopts the contract, lives in that plugin's spec.

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
