# Assessment: Codex's "Bad Batch" adversarial input corpus proposal

2026-09-18. Assessment only; nothing edited, no PR. Read against **origin/main @ 89b7f173** (the
`/Users/george/tap-sessions/main` checkout sits at 3d06470d, *before* the batch corpus landed, so
every file below was read from `origin/main` via `git archive`). Line anchors are origin/main's.
Method is named per claim: **read** (code/spec), **ran** (a throwaway stdlib probe on host Python
3.14.6 — the container is 3.14 too, same `json` module; the importer itself was NOT run),
**fetched** (upstream page), or **inferred** (not observed).

Proposal: `review/bad-batch-proposal.md`. Neighbours: Issue# 613 - tap (second pass, branch
`feat/batch-corpus-2` — at origin/main's tip, no commits yet as of this read), Issue# 617 - tap
(Backlog), Issue# 605/606 - tap (fixed), #607/#608/#610 (open), #609/#611 (PR# 624 - tap, open).

## Recommendation: ADAPT, narrowly

Adopt the *question* the proposal asks — "does the importer refuse garbage cleanly, preserve
legal oddities, and report truthfully?" — but not its *shape*. Reject the separate `bad/`
sub-package, the `.bin` fixture tree, the new `bad` JSON role and manifest schema, the second
runner, and the limits lane. Most of the proposal's semantic rows (ref sabotage, identity lies,
graph nonsense, plausible lies, failure-after-good-work) are Issue# 613 - tap's families in
different words or are already pinned by `test_grift*.py` and the playground; and the lexical
rows (broken serialization, encoding, ambiguous JSON, numbers) test a boundary — raw
`str`/`bytes` into `grift_import` — that no production caller crosses today (the seed loader
decodes files itself; collectors pass in-process dicts; there is no HTTP import endpoint). What
the proposal DOES surface, and what I verified by reading, are three small correctness gaps at
the existing boundary that the corpus format cannot express and that Issue# 613 does not list:
(1) the parse boundary catches only `json.JSONDecodeError`, so invalid UTF-8, an over-long
integer, and deep nesting **escape `grift_import` as exceptions** instead of a structured
refusal; (2) the file-level duplicate-id check compares **raw strings**, so one UUID spelled two
ways (case, braces, `urn:uuid:`) passes `duplicate_entity_id` and the upsert∧removal collision
check while resolving to one row at execution; (3) `grift_version` is checked for non-empty,
never against `"0"`. These close in ONE small PR of plain pytest cases in the importer's existing
test home, plus two `derive-once` fixes — filed as one issue, parented to tap#140. Everything else
is either #613's, already covered, or waits for an actual untrusted-input surface (the trigger
`spec-tap-json-files.md` already names for `req-tap-json-size-guard`).

---

## 1. Is "bad batch" a distinct thing?

**Where the existing playground ends.** `tap_grid/batch_corpus/` is a *semantic* known-answer
corpus: a scenario is symbolic (names → ids the runner mints, `batch.schema.json`), the document
is *built* by `runner._document` (`runner.py:96`-`:172`) and always well-formed, and the oracle
(`model_oracle.py`) must agree at load. Its spec says so: "Not a fuzzer and not a performance
corpus" (`spec-grid-batch-corpus.md:124`). Refusals it pins are the importer's *semantic* codes
— XOR/schema via the builder's own checks, duplicate ids, unknown/duplicate refs, dangling, OCC,
removal policy. It cannot represent a malformed byte, a duplicate JSON key, a NaN, or a UUID
spelled two ways — the proposal is right about that (line 41), and that is exactly why a
"bad" lane does not belong *inside* the corpus format (§2).

**What the fuzz lanes cover (read).** `api-fuzz.yml` runs schemathesis over the Ninja OpenAPI
schema (no-5xx + schema conformance). There is **no GRIFT import router** in `tap_api`
(`git grep grift origin/main -- tap_api` hits only `subgraph` imports in `routers/gryphon.py`
and `routers/searches.py`), so api-fuzz never reaches the importer. `scripts/gryphon-fuzz-campaign`
and `boot/soak.boot.json` are the Gryphon *query* differential fuzzer — unrelated to import.
**Net: no fuzz lane touches GRIFT import; overlap with fuzzing is zero.** But the reason is
telling: GRIFT has no untrusted-input surface to fuzz.

**Who actually calls `grift_import` (read).** `tap_cares/collectors/base.py:271` `submit_grift(document: dict | str | bytes)`
(in-process, the collector's own dict); `tap_plugins/seeding.py:111` (`json.load(fh)` on a
plugin's shipped bundle, read errors → `read_error` outcome, `:118`/`:131`); `tap_plugins/validate/service.py:1627`
(dry-run); the `import_plugin_grift` command (`:230`, `:377`, `json.load`). Nothing passes raw
bytes except `test_grift.py:136 test_bytes_input_parsed`. The `str | bytes` arm of the public
signature (`importer.py:3448`, `:3600`) is therefore a contract with no production consumer —
which is precisely where a *cheap edge* belongs (security posture) and where an *expensive lane*
does not.

**What the proposal adds that nothing covers** (verified by reading; details in §3):
- Exception leak at the parse boundary (`importer.py:3600`-`:3603` catches only
  `json.JSONDecodeError`; stdlib raises `UnicodeDecodeError`, `ValueError` (int-digit limit),
  `RecursionError` — ran).
- Non-canonical UUID spellings defeating the file-level duplicate check
  (`_check_uuid` `importer.py:367`-`:382` returns the raw string; `all_entity_ids: set[str]`
  `:1281`; execution normalises with `uuid.UUID(...)` `:2401`, `:2494`).
- `grift_version` accepted as any non-empty string (`importer.py:1256`; `GRIFT_VERSION = "0"`
  at `:43` is never compared on import).
- Policy questions with no contract today: duplicate JSON names, non-finite numbers, accepted
  encodings (§6).

**What it duplicates:** the five semantic rows map onto Issue# 613 - tap's "Ref syntax/scope",
"Collision after resolution", "Reference rewriting", "Replace/provenance", "Atomic refusal",
"Dangling/edge identity", "OCC", "Replay/force" families almost bullet for bullet (§3 names
each). #613 also rules, in its "Explicitly deferred" block, against "copying every ordinary
validation test into JSON" — which is the proposal's manifest lane in one sentence.

## 2. Placement

The proposal wants `tap_grid/batch_corpus/bad/` + `bad.schema.json` + `*.bad.json` manifests +
`fixtures/raw/*.bin` + two new test files + a `batch_bad_limits` marker, and a `bad` entry in
`tap/jsonfiles.py:191 KNOWN_ROLES`. Against the house rules:

- **Two corpora, one shape.** Both corpora are scenario-is-data + human answer + independent
  oracle at load + one shared checker (`batch_corpus/runner.py` imports `snapshot`/`event_delta`
  from `cascade_corpus/runner.py` — "one home, not a copy"). A byte blob has no oracle and no
  symbolic answer; the proposal admits it must "bypass the symbolic document builder" (line 41).
  That is a second runner and a second manifest format under the corpus directory — the
  Sonar 3% duplication gate and the corpus spec's goals 2-3 (eyeballable, oracle-bearing) both
  push back. It is not a playground; it is importer unit tests.
- **JSON-role rules.** A `bad` role is legal in form (`spec-tap-json-files.md:59`-`:65` table),
  but the payloads would be `.bin`, which the scanner never sees (`scan_json_files` walks
  `rglob("*.json")` only) and which no text guard reads. If exact bytes are ever needed, carry
  them **inside** the JSON case as base64 or an escaped string — all-text, diffable, still
  `read_bytes`-exact; BLNS itself ships `blns.base64.json` for this reason (fetched). No `.bin`.
- **Validation Map.** Every validation surface needs a Map row (`spec-dev-validation.md:124` is
  the batch corpus's). A new marker/lane means a new row, `scripts/test` wiring, change-tier
  wiring. Plain pytest cases in `tap_grid/tests/test_grift.py` ride the existing "core walk"
  row and need none of that.
- **George's ruling.** Playgrounds stay in tap for now and may spin out with declared types
  later (`spec-grid-batch-corpus.md:124`). A bytes lane has no plugin future — it never leaves
  the importer — so the spin-out question does not apply; keep it beside the importer's tests.

**Verdict:** no new package, role, schema, fixture tree or marker. The adopted cases live in
`tap_grid/tests/test_grift.py` (`TestGriftDocumentSchema`, the existing home of `invalid_json`,
missing/unknown keys, bytes input) and `tap_grid/tests/test_grift_identity.py`, as parametrised
cases with a "nothing written" assertion (the pattern `test_grift_refs.py` already uses,
`_nothing_written`).

## 3. Starter cases and controls, one by one

Legend: **COVERED** (name the test/scenario) · **ADD** (exact expected outcome + requirement
pinned) · **#613** (already in that issue's scope — do not duplicate) · **WRONG** (contradicts
TAP's contract) · **RULING** (needs a decision first — an L).

### Broken serialization
| Case | Verdict |
|---|---|
| empty; whitespace only; missing quote; trailing comma; two concatenated documents; JSON then garbage; comment | **COVERED in code, thin in tests**: all raise `JSONDecodeError` (ran) → `invalid_json` at phase `parse`, path `$` (`importer.py:3600`-`:3615`); only `test_invalid_json_string` (`test_grift.py:105`) pins it. **ADD** as one parametrised case list (cheap): expected `success=False`, one error `("invalid_json", "$")`, nothing written. Pins `req-grid-import-grift-results` (structured reporting) and the stdlib fact that "extra data" is a refusal, never "first document wins". |
| truncated last byte | Same row; a truncated document is `JSONDecodeError` (ran: "Expecting value"). |

### Wrong root/shape
`_run_preflight` runs the JSON-Schema pass FIRST (`importer.py:1192`) and the schema is
`type: object`, `additionalProperties: false` at every level (`tap_grid/schemas/grift-document.schema.json:7`
onward). So `null`/`true`/`7`/string/array roots, `batches` as object/string/null, a scalar
batch entry, a string in the node list, `entity` as an array, a scalar removal section — all
land as `schema_validation_failed` before any `.get` (read; `test_missing_metadata_key`,
`test_missing_batches_key`, `test_unknown_top_level_key`, `test_grift.py:111`-`:129`). **ADD**
three or four root-shape cases to the same parametrised list (a `null` root via `"null"` text
input; an array root; `batches: {}`) — expected `("schema_validation_failed", "$")` or the
schema's json path, nothing written. The empty valid document as positive control already
exists: `test_empty_doc_succeeds` (`:100`). **WRONG** nowhere.

### Encoding and strings
| Case | Verdict |
|---|---|
| invalid UTF-8 byte; truncated multibyte | **ADD — a defect, not a test hypothesis.** `json.loads(bytes)` raises `UnicodeDecodeError` (ran), which is not `JSONDecodeError`; `importer.py:3603` does not catch it, so `grift_import(b'...')` **raises** instead of returning a result. Expected after fix: `("invalid_json", "$")`, nothing written. Pins `req-grid-import-grift-results`. |
| UTF-8 BOM | Bytes: accepted (ran — `json.detect_encoding` strips it); str: `JSONDecodeError` "Unexpected UTF-8 BOM" (ran). **RULING** whether to document "bytes may carry a BOM, text may not" or normalise; low stakes. |
| valid UTF-16/32 bytes | Accepted by stdlib (ran); `spec-grift-v0.md:959` "UTF-8 encoded JSON" is under the **Backlog** export-formatting section, not the input contract. **RULING** (§6): UTF-8 only, or "what `json.loads` accepts". No code either way today. |
| escaped unpaired surrogate `\ud800` | Accepted by stdlib (ran). Lands in a text column → PostgreSQL rejects the surrogate on encode → `execution_failed` **(inferred, not run)**. Worth one case to pin the *phase*: today it would be an execution-phase batch failure, not preflight. |
| raw control character | `JSONDecodeError` (ran) → `invalid_json`. Same parametrised list. |
| escaped NUL ` ` in a payload string | Accepted by stdlib (ran). PostgreSQL `text`/`jsonb` reject NUL → `execution_failed` **(inferred)**. **ADD** one case pinning phase/code; if George prefers a preflight refusal, that is a ruling. |

### Ambiguous JSON (duplicate names)
Python: last value wins, incl. `"ref"` vs `"ref"` (ran: `{'ref': 2}`). RFC 8259 §4: names
"SHOULD be unique" (fetched). No TAP contract. Reachable only through the `str | bytes` arm.
**RULING** (§6, recommend refuse via `object_pairs_hook`). Not a test until ruled. **WRONG**
nowhere.

### Wrong scalar types
| Case | Verdict |
|---|---|
| version `true` / `1.5` / `0` / `-1` / `"1"` | **COVERED**: schema `type: integer, minimum: 1` (`grift-document.schema.json:80`, `:223`); jsonschema's `integer` excludes `bool` by its documented semantics (not run here); `test_zero_expected_version_rejected`, `test_string_expected_version_rejected` (`test_grift.py:1717`, `:1740`); the hand check at `:1033`-`:1046` uses `isinstance(int)` (bool would pass there) but the schema pass runs first. A one-line `true` case in the list is cheap insurance. |
| object/list as UUID; UUID-looking invalid string | **COVERED**: `_check_uuid` `:367`-`:382` + `test_invalid_uuid_in_envelope` (`:192`). Note: the schema's `format: uuid` (`:39`, `:114`, `:123`) is **annotation only** — `jsonschema.validate` enforces no formats without a `format_checker` (fetched) — so `_check_uuid` is the only checker. The proposal's warning is correct and already handled by hand code. |
| malformed date-time | **COVERED** by `_check_datetime` (`:396`); `timestamp_*` codes. |
| nested dimensions | **COVERED**: `test_dimensions_non_string_value_rejected` (`:215`). |
| string instead of edge properties object | **COVERED** by the schema (edge payload `properties` typed). |

### Numbers with teeth
| Case | Verdict |
|---|---|
| `NaN`, `Infinity`, `1e400` | Accepted by stdlib as float/inf (ran; RFC forbids, fetched). Then: schema `number` passes; JSONField → `json.dumps` emits `NaN`/`Infinity` → PostgreSQL jsonb rejects → `execution_failed` **(inferred)**. **RULING**: refuse at parse (`parse_constant`) — RFC-conformant, cheap. With dict input a `float('nan')` from a collector still reaches execution; the test after the ruling pins both entry points. |
| very long integer (≥4300 digits) | **ADD — a defect.** stdlib raises `ValueError` "Exceeds the limit (4300 digits)" (ran, 3.11+ int-str limit, fetched) — not `JSONDecodeError`; escapes `:3603`. Same fix as UTF-8. |
| safe-integer boundaries (2^53) | **WRONG for TAP**: Python/PostgreSQL are arbitrary precision; a JS-viewer concern belongs to `tap_web`/`tap_viz`, not the importer. |
| `0`, `-0`, `0.0` in allowed fields | `-0` → `0` (ran). Per-field model validation; nothing to pin generically. |

### Ref sabotage — all COVERED or #613
both/neither id+ref → `test_grift_refs.py:152`, `:163` · duplicate node ref → `:206` · edge ref
reusing a node ref → one `refs` dict across nodes and edges in `refs.py:117`-`:131` (code; **#613**
"node/edge ref-name collision") · endpoint pointing to an edge ref → `refs.py:135`-`:147`
`node_refs` only → `unknown_ref` (code; **#613** "endpoint targeting an edge ref") · unknown
endpoint ref → `:174` · ref valid only in another batch → `:213` · whitespace-only ref →
`_take_ref` `refs.py:175` + `test_a_blank_ref_is_invalid` `:226` (sends `"   "`) · same ref far
apart → `duplicate_ref` · independent reuse across batches → `:213` / **#613** "same label reused
independently in two batches".

### Identity lies
| Case | Verdict |
|---|---|
| existing id, wrong type | **COVERED** `test_existing_entity_wrong_type_fails_preflight` (`:557`). |
| batch id reused as node/edge id; node id as edge id | **COVERED** in code: batch ids enter `all_entity_ids` (`:1363`-`:1375`) → `duplicate_entity_id`; `test_duplicate_entity_id_across_batches_fails` (`:230`), `test_grift_identity.py:134`-`:248`. |
| two refs → X; ref + explicit X; ref upsert + delete/purge X | **COVERED/fixed**: bd2ff339 (Issue# 602), df8aa90a (Issue# 606: "or names as a removal target"); **#613** "Collision after resolution" lists every remaining shape. |
| duplicate removal targets | **COVERED** `test_duplicate_target_within_sub_array_rejected` (`:1253`). |
| **UUID case variants of one id** | **ADD — a defect.** `_check_uuid` accepts anything `uuid.UUID()` parses — upper-case, `{…}`, `urn:uuid:…` — and returns the *raw* string (`:381`-`:382`); `all_entity_ids` is `set[str]` (`:1281`); the upsert∧removal collision is `seen_removal_ids.keys() & all_entity_ids` (`:1901`), also raw. Execution normalises (`uuid.UUID(node_entity_id)`, `:2401`). So a file with `abc…` and `ABC…` passes `req-grift-validation`'s "Duplicate `entity_id` values anywhere in the file are invalid" (`spec-grift-v0.md:922`) and lands as create-then-replace of one row inside one batch **(inferred)**; a removal target spelled `{abc…}` for a node upserted as `abc…` bypasses `entity_id_in_upsert_and_removal`. Fix once: canonicalise in `_check_uuid` (`return str(uuid.UUID(value))`) — every consumer then sees one spelling. Expected after fix: `("duplicate_entity_id", "$.batches[0].nodes[1].entity.entity_id")` / `entity_id_in_upsert_and_removal`, nothing written. Not in **#613**. |

### Graph nonsense — COVERED or #613
missing endpoint → dangling family (7 scenarios) · tombstoned endpoint → Issue# 609 ruled, PR# 624
· disallowed edge type / unknown edge type → no importer-level test found by name; the refusal
is the service layer's (`OUTBOUND_EDGES`) and would surface as `execution_failed` — **NOT
OBSERVED** here; a candidate for #613's "Dangling/edge identity" family rather than a new lane ·
many duplicate endpoint/type edges → **#613** (#547) · self-loop, cycle, endpoints collapsing after
resolution → **#613** "Reference rewriting".

### Permission/option bait — COVERED
`_DOC_ALLOWED`/`_METADATA_ALLOWED`/`_BATCH_ALLOWED`/`_ENVELOPE_ALLOWED` (`importer.py:235`-`:264`)
+ schema `additionalProperties: false` refuse `actor`, `is_admin`, `_internal_only_bypass`,
`force_batches`, `debug`, `errors`, `success` anywhere but a free-form value:
`test_unknown_top_level_key` (`:124`), `test_unknown_key_in_envelope_rejected` (`:200`),
`test_unknown_metadata_key` (`:148`). `force_batches`/`purge` are kwargs of `grift_import`, not
payload. Purge under DEBUG=False → `grift_purge_refused_production`, pinned in
`removals.batch.json` (1 scenario). "Same words in `batch_node.metadata` remain inert" — nothing
reads that map for control (read); one parametrised "preserved verbatim" case is cheap but
optional.

### Plausible lies
mismatched envelope/typed names → `envelope_payload_name_mismatch`, `test_grift.py:1005`-`:1018`
· stale/future OCC → occ family (10) + **#613** · same batch id, changed content → identity family
"skip-if-exists is the batch's…" + **#613** "Replay/force" · **invented schema version** → **ADD/RULING**:
`importer.py:1256` checks non-empty string only; `GRIFT_VERSION = "0"` (`:43`) is never compared,
so `"grift_version": "banana"` imports (read). Cheap edge: refuse ≠ `"0"` with
`schema_validation_failed` at `$.metadata.grift_version`. A ruling because it changes accepted
input · missing key component → `identity_undeclared` / **#613** "incomplete key" · empty
replacement dimensions → Issue# 608 · missing vs null vs empty → `test_null_on_*` (`:1802`-`:1821`)
+ **#613** "omitted vs explicit null/empty".

### Failure after good work — COVERED or #613
multibatch family ("an execution failure in the middle batch lands the batches around it"),
`test_grift_batch_failure.py` (Issue# 605), Issue# 607 (counters, open), **#613** "Atomic
refusal" (first/middle/last op, schema vs model vs precommit). Runtime fault injection → #613.

### Suspicious-but-legal controls
No BLNS-style test exists (grep for emoji/zero-width/RTL/Cyrillic in `test_grift*.py`: none).
Value is modest: the importer does not template, execute or render strings; rendering safety is
Django autoescape in `tap_web` — the proposal itself concedes an importer round-trip proves
nothing about rendering. Two things are worth one parametrised case each: **NUL** (rejected by
PostgreSQL → pins the phase, see above) and **a Cyrillic-`а` vs Latin-`a` slug pair** proving the
declared search is exact-equality, never normalised (pins the identity contract; today's
behaviour is ORM `=`, read from the gate's design — not run). A handful of preserved-verbatim
values (emoji, RTL mark, zero-width joiner, a SQL-looking fragment, `../outside`, the
"ignore previous instructions" string) can ride the same list with expected = stored verbatim.
"Do not normalise lookalikes in the harness" — agreed, and moot: the harness would not.

## 4. What to borrow (all fetched 2026-09-18)

| Source | Exists / says what is claimed | Licence | Borrow the input shape | Borrow the expected outcome |
|---|---|---|---|---|
| JSONTestSuite (nst) | Yes: `y_`/`n_`/`i_` prefixes; exit codes separate crash (>1) and timeout from rejection (1); `test_transform/` has huge numbers, duplicate keys, NUL, bad escapes | MIT | Yes — a dozen `n_`/`i_` bytes as *inline* strings/base64 in the parametrised list, with the upstream filename in the case id | **No** for `i_` (implementation-dependent → TAP must rule; §6); `n_` outcome is "refuse", which maps to `invalid_json` |
| JSON Schema Test Suite | Yes: drafts 2020-12 … 03; `optional/format` explicitly opt-in | MIT | Marginal: TAP validates with `jsonschema` 4.26.0 (uv.lock) and the schema is small; the useful lesson is the format-checker point, already true of TAP | No — TAP's schema is TAP's |
| Big List of Naughty Strings | Yes: `blns.txt`/`.json` + base64 variants; README warns some strings "may be a crime" against third-party software and excludes NUL/EICAR/255+ | MIT | A hand-picked ≤10 with attribution comment | Yes for "preserved verbatim" in a free-text field; No for any field with its own validation |
| RFC 8259 + Python `json` docs | Yes: RFC forbids NaN/Infinity, names SHOULD be unique, UTF-8 for networked JSON; Python: last-wins, NaN accepted by default, bytes auto-detected UTF-8/16/32, 3.11+ int-digit limit | IETF Trust / PSF | Policy source only | These decide §6's rulings |
| SQLite testing.html | Yes: fuzzing (AFL, OSS-Fuzz, dbsqlfuzz mutating SQL *and* the database file), boundary-value (§4.3), mutation (§7.6), regression (§5) | Public-domain doc | The *idea* "mutate input and initial state together" — the batch corpus already does this (grid + documents) | n/a |
| FHIR `http.html#transaction` | Yes: circular references allowed; `urn:uuid` temp ids rewritten; conditional reference with 0 or >1 matches fails the transaction; all-or-nothing | HL7 FHIR (open; check the footer before copying examples) | Already #613's FIRST item; nothing new for a bad-input lane | Already ruled: TAP is per-batch atomic (Issue# 617) |

Pinning upstream revisions and keeping attribution is right; none of the six requires a new
dependency.

## 5. Limits lane and execution rules

**Not justified now.** Facts (read): the `core_ci` line job took ~8 min on the latest gate run
(35412580447, 01:25:10→01:33:09; the batch and cascade corpora are inside it — their own share
was not isolated here, the "~5 min" figure is the caller's); TAP declares **no** size, depth,
digit, node or batch limits for GRIFT (`spec-grift-v0.md`, `spec-grid-import-grift.md`: none),
and the one size ceiling on the books, `req-tap-json-size-guard`, is Backlog with its trigger
spelled out — "until a surface actually ingests operator-supplied or third-party JSON at a trust
boundary" (`spec-tap-json-files.md:281`). No such surface exists (§1).

What a limits lane would cost: a subprocess harness with wall-clock and memory caps, reaping,
an isolated DB, a `batch_bad_limits` marker, a nightly workflow, a Validation Map row, and —
before any of it — the ceilings themselves, which are rulings. What it would catch that nothing
else can: (a) the `RecursionError`/int-digit `ValueError` escapes — but three plain unit tests
catch those for free once the parse boundary catches `ValueError`/`RecursionError`; (b) OOM on a
multi-GB input — real, but the answer is the pre-read `max_bytes` guard already designed at the
loader, not a corpus. Bounded-diagnostic-size and "no secret echoed in an exception" are good
asks and belong to the API/webhook surface when it exists.

The execution rules worth keeping regardless of lane: "corrupt the checker too" (already the
corpus discipline, `test_batch_corpus_checker.py`, 11 negatives); "a known-good import after a
refused one" (the test DB gives this per test; one explicit sequence case is cheap and could ride
the PR).

## 6. Decisions now vs later

**Rulings for George (each an L; none blocks the PR below except where marked):**
1. Duplicate JSON object names at the `str | bytes` boundary: refuse (`object_pairs_hook`; RFC
   "SHOULD be unique"; recommended) or keep Python's last-wins. Only matters for text input.
2. Non-finite numbers (`NaN`, `Infinity`, `1e400`): refuse at parse (`parse_constant`; RFC
   grammar; recommended) — and, for dict input, whether a `float('nan')` in a payload is a
   preflight refusal or stays an execution-phase batch failure.
3. Accepted encodings for bytes: UTF-8 only (spec's stated intent) or "what `json.loads`
   auto-detects" (UTF-8/16/32, BOM tolerated on bytes). Recommend documenting the latter and
   writing no code.
4. `grift_version`: pin to `"0"` (refuse others) or keep "any non-empty string". Recommend pin —
   a future v1 importer needs the refusal to exist already.
5. NUL / unpaired surrogate in a string: leave as `execution_failed` (PostgreSQL's answer) or
   refuse at preflight. Recommend leaving it and pinning the phase.

**Engineering, no ruling needed (the PR):** parse boundary returns a result for every decoder
failure; canonical UUID spelling in `_check_uuid`; parametrised root-shape / serialization
cases; the two identity-spelling cases; optional verbatim-string and NUL cases.

**Premature:** the exact-byte manifest schema and `bad` role; `.bin` fixtures; the limits lane
and "resource ceilings for the test worker"; "structured refusal expectations" as a new
decision (it is already `req-grid-import-grift-results`); "whether each weird-but-valid input is
preserved or rejected by a named rule" as a blanket decision (it is per field, decided when a
field is added); differential parsers, property-testing deps, a viewer/export adversarial suite
(the proposal itself defers these — agreed).

## If adopted: one issue, one PR

**Filed:** Issue# 630 - tap  https://github.com/unified-systems-com/tap/issues/630 (parent tap#140).

**Title:** GRIFT importer: every decoder failure is a structured refusal, and one UUID has one
spelling — the parse-boundary and id-canonicalisation cases from the "bad batch" review.

**Scope (closes alone):**
1. `importer.py:3600`-`:3603`: catch `ValueError` (covers `JSONDecodeError` and
   `UnicodeDecodeError` and the int-digit limit) and `RecursionError` → `invalid_json`, phase
   `parse`, path `$`, message naming the exception class. If rulings 1-2 land first, add
   `object_pairs_hook`/`parse_constant` in the same place; if not, leave them out and say so.
2. `importer.py:367`-`:382` `_check_uuid`: return `str(uuid.UUID(value))` — one canonical
   spelling for `all_entity_ids` (`:1281`), the removal collision (`:1901`), `resolved_refs`,
   result lists and the execution lookups. Check that any test asserting `entity_id` echo
   compares canonical form.
3. Tests in `tap_grid/tests/test_grift.py::TestGriftDocumentSchema` (parametrised): ~12
   serialization/root-shape/encoding bytes (inline strings/base64, JSONTestSuite names as ids,
   MIT attribution) each → one error, expected code+path, `Entity.objects.count()` unchanged;
   plus `NaN`/`1e400`/NUL cases pinned to whatever phase holds after the rulings.
4. Tests in `tap_grid/tests/test_grift_identity.py`: (a) two nodes, one UUID in two spellings →
   `duplicate_entity_id`, nothing written; (b) upsert canonical + delete-target braced →
   `entity_id_in_upsert_and_removal`, nothing written; (c) a removal target in upper-case for an
   existing row still resolves (positive control).
5. Spec: note on `req-grift-validation` (id equality is UUID equality, not string equality) and
   on `req-grid-import-grift-results` (the `str | bytes` arm never raises). No new RID, no
   Validation Map change (rides the core walk).

**Done-test:** `scripts/test --fast tap_grid` green; `grift_import(b'{"a":"\xff"}')`,
`grift_import("[" + "9"*5000 + "]")`, `grift_import("[" * 20000)` each return a
`GriftImportResult` with one `invalid_json`; the two-spelling file is refused with
`duplicate_entity_id`; every existing corpus scenario unchanged (no `pending` added or removed).

**Traps:** container only; `tap_grid/tests/test_grift.py` is ~1800 lines — add a class, do not
scatter; `sys.setrecursionlimit` differs under xdist workers, so assert the class of outcome not
the depth; a `RecursionError` inside `jsonschema` (deep valid nesting in `props`) is a separate
path — one probe, file it if it escapes; do not touch `refs.py` (Issue# 613's branch will).

**Explicitly not this issue:** anything in #613's family list; #617; #607/#608/#610; the limits
lane; the `bad` role; BLNS beyond ≤10 strings.

## Open questions for George

1. Rulings 1-5 above (duplicate names, non-finite numbers, encodings, `grift_version` pin,
   NUL/surrogate phase). The PR can land without 1-3 and 5; 4 is a one-line change if ruled.
2. Should the "unknown/disallowed edge type through GRIFT" case (not observed anywhere at the
   importer level) go to #613's "Dangling/edge identity" family, or is the service-layer test
   enough?
3. Does an untrusted GRIFT ingestion surface (webhook, upload, API) sit anywhere on the fence?
   If yes, `req-tap-json-size-guard` and a bounded-diagnostics rule should be scoped with it,
   and that — not now — is when a limits lane earns its Map row.
4. Confirm the placement verdict: parse/identity-spelling cases as plain pytest beside the
   importer, not a third corpus.
