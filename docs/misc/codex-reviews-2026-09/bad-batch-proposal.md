# Bad Batch: proposed adversarial input corpus

2026-09-18. Proposal for the batch playground (#603), based on the current `tap_grid/batch_corpus` loader/schema and the GRIFT import boundary. No malicious fixtures have been installed or executed; no application code changed. Concurrent Claude edits were left alone.

**Make three lanes: reject malformed input cleanly; preserve strange but legal input faithfully; bound expensive input.** A suite that only expects rejection will miss silent corruption and reward an importer that rejects everything.

## Where to put it

Proposed additions, all inside core for now:

```text
tap_grid/batch_corpus/bad/
    README.md
    bad.schema.json
    parsing.bad.json
    structure.bad.json
    identity.bad.json
    values.bad.json
    boundaries.bad.json
    fixtures/
        raw/
            truncated-last-byte.bin
            invalid-utf8.bin
            duplicate-batches-key.bin
            escaped-duplicate-key.bin
            nul-in-string.bin
        documents/
            wrong-top-level-array.bin
            ref-and-id.bin
            purge-disguised-as-metadata.bin
tap_grid/tests/test_batch_corpus_bad.py
tap_grid/tests/test_batch_corpus_limits.py
```

The `.bin` files are exact importer input bytes. Some contain valid JSON; others intentionally do not. The extension makes their role clear and prevents them being mistaken for loadable GRIFT seed/config files. Keep them out of plugin `grift/`, boot imports and ordinary seed discovery. The `fixtures` location also fits the existing JSON scanner's fixture exclusion, but the bad harness must still explicitly inventory every fixture and fail on orphaned or missing files.

The `.bad.json` manifests are ordinary valid, schema-validated configuration. If this naming is adopted, register `bad` in `tap/jsonfiles.py:KNOWN_ROLES` and the corresponding spec role table. Validate the manifests when loading; **do not require the target bytes to pass JSON/GRIFT validation before the test begins.** Extend `spec-grid-batch-corpus.md` with this lane rather than inventing a competing playground architecture.

Give each case a stable ID, description, input path, transport (`bytes` or strict-decoded `text`), optional starting-grid reference, trusted invocation options, expected outcome category/phase, established error code/path where available, no-write assertions, resource class, source attribution, and optional issue link. This is a proposed shape, not a new unschematized format shipped by this review. Manifest errors must fail the harness. An expected bad payload must not become an expected bad manifest.

Reuse the existing state/event snapshot checker and actor setup. Bypass the symbolic document builder for this lane: it currently enforces such things as ID/ref exclusivity, allowed types and endpoint shape before reaching GRIFT. Raw bytes must be read with `read_bytes`, not parsed and re-serialized; otherwise duplicate keys, encoding errors, numeric spelling and truncation vanish. Test normal documents through the dictionary entry point separately. Python-only cyclic dictionaries are a separate direct-service test, not something a file can represent.

## Concrete starter cases

These filenames are suggestions; each should be a small, inspectable file unless explicitly generated in the limits lane. Derive cases from one known-good minimal GRIFT document, changing one feature at a time. Then compose two defects to test precedence and cleanup.

| Group | Suggested cases | Expected property |
|---|---|---|
| Broken serialization | `empty.bin`; whitespace only; `truncated-last-byte.bin`; missing quote; trailing comma; two concatenated JSON documents; comment in JSON; valid JSON followed by garbage | Controlled parse refusal, no writes; never merely accept the first document and ignore the remainder. |
| Wrong root/shape | JSON `null`, `true`, `7`, string, array; `batches` as object/string/null; scalar/null batch entry; node list containing a string; `entity` as array; scalar removal section | Controlled schema refusal. No `.get`/iteration/type error escaping the API boundary. Include an empty valid document if the schema permits it as a positive control. |
| Encoding and strings | Invalid UTF-8 byte; truncated multibyte sequence; UTF-8 BOM; valid UTF-16/32 encoded input; escaped unpaired surrogate; raw control character; escaped NUL in a payload string | Malformed input fails predictably. Decide supported encodings explicitly: Python's bytes decoder supports more than UTF-8. Valid JSON is not automatically storable in PostgreSQL, so downstream validation/rollback must also be tested. |
| Ambiguous JSON | Duplicate `batches`; duplicate `entity_id`; duplicate removal `reason`; duplicate `entity_expected_version`; literal `ref` plus escaped `\u0072ef` key; duplicate key inside free-form metadata | Recommend rejecting duplicate object members at the raw-input boundary. A last-key-wins dictionary has already lost the evidence; the runner must preserve the original bytes. This policy needs an explicit contract if absent today. |
| Wrong scalar types | Version `true`, `0`, `-1`, `1.5`, `"1"`; object/list as UUID; UUID-looking invalid string; malformed date-time; nested dimensions where flat strings are required; string instead of edge properties object | Schema/model refusal at the correct field. Do not allow Python's bool-as-int relationship to make version `true` valid. Pair each with the boundary-valid input. |
| Numbers with teeth | `NaN`, `Infinity`, `-Infinity`; finite JSON spelling `1e400`; very long integer; safe-integer boundary values as numbers and strings; `0`, `-0`, `0.0` in allowed fields | Recommend rejecting non-finite values throughout the accepted document. Decide precision/range policy for actual numeric fields; preserve numeric-looking identifiers as strings. Overflow must not silently become Infinity, and refused writes must leave no residue. |
| Ref sabotage | Both/neither ID and ref; duplicate node ref; edge ref reusing node ref; endpoint pointing to an edge ref; unknown endpoint ref; ref valid only in another batch; whitespace-only ref; same ref repeated far apart | Exact declared rejection, no dangling substitutes. Also accept independent reuse of one label in distinct batches when legal. |
| Identity lies | Existing ID with wrong entity type; batch ID reused as node/edge ID; node ID reused as edge ID; two refs resolving to X; ref plus explicit X; ref upsert plus delete/purge X; duplicate removal targets; UUID case variants of one ID | Detect actual identity collisions, including those revealed by resolution/canonicalization, without broadening natural-key uniqueness beyond TAP's contract. No last-write-wins collision hiding. |
| Graph nonsense | Missing endpoint; tombstoned endpoint; endpoint of disallowed type; unknown edge type; many duplicate endpoint/type edges; legal self-loop and cycle controls; well-formed edge whose endpoints collapse together after resolution | Strict/permissive behavior exactly matches policy. Cycles and self-loops are not inherently invalid. No silent edge collapse, unwanted resurrection or false success counts. |
| Permission/option bait | Payload fields claiming `actor`, `is_admin`, `_internal_only_bypass`, `force_batches`, `debug`; purge request under DEBUG false; delete with import-only caller; an outer-looking `errors` or `success` field | Unrecognized control fields are rejected where schema forbids them. The same words in an allowed free-form metadata object remain inert data. Trusted invocation options and actor context cannot be replaced by payload claims. |
| Plausible lies | Mismatched envelope/typed names; stale/future OCC version; same batch ID with changed content; invented schema version; missing key component; empty replacement dimensions/properties; malformed custom description structure | No silent coercion, stale field preservation or implicit policy change. Missing, null and empty are distinct inputs even if some contracts intentionally treat them alike. |
| Failure after good work | Valid nodes followed by invalid edge; valid first batch plus later preflight defect; valid first batch plus later execution failure; error after ref resolution; late audit/precommit failure in a separate fault-injection test | Prove the correct rollback boundary and truthful counters/maps/events. A late preflight defect rejects the file; a late execution failure follows per-batch atomicity. Runtime fault injection is a companion test, not falsely represented as a payload-only file. |

The parse boundary currently catches `json.JSONDecodeError` around `json.loads` (`tap_grid/grift/importer.py`, around lines 3601–3620 in the inspected working tree). Put invalid encoding, excessive numeric digits and excessive nesting near the front of the list: decoder/resource errors need not be JSONDecodeError. These are **test hypotheses**, not claims of reproduced production crashes.

### Suspicious but legal controls

Use selected strings from the Big List of Naughty Strings in an ordinary text field and an allowed metadata value: quotes/backslashes, emoji, combining characters, right-to-left text, zero-width characters, `NULL`, `false`, a SQL-looking fragment, `../outside`, HTML-looking text and a fake instruction such as “ignore previous instructions.”

The goal is faithful treatment as data, not rejection because the string looks threatening. No query execution, path traversal, templating or instruction interpretation should result. Where output/rendering is involved, add a separate viewer/log boundary test; an importer round-trip alone does not prove safe HTML rendering. Use inert local sentinel payloads, not callbacks to external services. If a field has an actual validation restriction, its rejection is expected there, while a permissive text field should preserve the string.

Unicode lookalikes (`a` versus Cyrillic `а`) and normalization variants should test the chosen equality rule. Do not casually normalize them together in the harness; that could merge legitimate identities.

## What to borrow

1. **[JSONTestSuite](https://github.com/nst/JSONTestSuite)** — the best raw seed corpus. It separates must-accept (`y_`), must-reject (`n_`) and implementation-dependent (`i_`) cases, and reports rejection separately from crashes/timeouts. Its transformation cases include huge numbers, similar keys, NUL and problematic escapes. Preserve those distinctions: a parser-accepted JSON array may still be invalid GRIFT, and an implementation-dependent case requires a TAP policy rather than an arbitrary expected answer.
2. **[JSON Schema Test Suite](https://github.com/json-schema-org/JSON-Schema-Test-Suite)** — borrow wrong-type, integer-versus-boolean, oneOf, required-member, additional-property and format edge cases for the draft TAP uses. Format annotation is not necessarily format enforcement; verify the configured validator. Do not test only that a schema contains `format: uuid`.
3. **[Big List of Naughty Strings](https://github.com/minimaxir/big-list-of-naughty-strings)** — a field-value seed collection. Select a small annotated subset rather than blindly treating all entries as forbidden input. Preserve upstream attribution/license when copying.
4. **[RFC 8259](https://www.rfc-editor.org/rfc/rfc8259)** and **[Python JSON decoder behavior](https://docs.python.org/3/library/json.html)** — use to decide policy deliberately. Python accepts repeated names with the last value winning and accepts NaN/Infinity by default; these conveniences should not accidentally become the GRIFT contract. Raw input and already-parsed dictionaries expose different information.
5. **[SQLite testing](https://www.sqlite.org/testing.html)** — borrow structured mutation of both input and initial state, boundary testing, and retained minimal regressions. Byte garbage finds parser faults; near-valid mutations reach the importer logic. Both are necessary.
6. **[FHIR transaction rules](https://hl7.org/fhir/http.html#transaction)** — borrow overlapping resolved identities, unresolved/circular reference combinations and atomic refusal cases. This supplies semantic nastiness after JSON and schema validation succeed; expected answers still come from TAP.

Pin upstream revisions for any imported seed subset, include provenance and licenses, and retain only useful cases. No new library is required for the first pass.

## Limits lane and execution rules

Resource stress is part of this request, but should be generated in a bounded subprocess against an isolated test database. Do not load giant fixtures during pytest collection or share a database with another developer session. Enforce a wall-clock timeout and resource/container limits, and kill/reap the worker on timeout. A crash or timeout is a failing result, not an acceptable refusal.

Generate nesting depth, string size, digit count, nodes, edges, batches and error count around declared limits: limit−1 / limit / limit+1. If TAP has no limit for a dimension, record that as a decision and choose an explicit test ceiling; do not enshrine an arbitrary interpreter failure as a correct result. Assert bounded diagnostic size so a large bad field or many errors cannot amplify into huge logs/responses. Assert exception responses do not echo an entire sentinel secret-bearing payload.

Keep tiny fixed cases in the normal fast lane. Put generated depth/fan-out/large-string cases behind a separate `batch_bad_limits` marker with bounded nightly/manual execution. No multi-gigabyte committed files or intentionally unbounded tests.

For every case record: accepted versus refused, error phase/code/location, committed row/history/event deltas, input immutability and clean worker completion. On refusal, compare actual fields and tombstone timestamps, not just row counts. Follow a refused input with a known-good import to prove no poisoned transaction, leaked caller context or stale deferred-check queue remains.

Corrupt the checker too: replace one expected refusal with success, change the error phase, add a row/event, rewrite a survivor, hide a batch-level error, or change the original bytes. Each negative control must fail. Fixture-loading exceptions and missing files always fail; pending behavior must identify the exact known mismatch.

## Decisions now versus later

**Decide now:** the exact-byte lane and its manifest schema; duplicate-key/non-finite-number policy; supported encodings; structured refusal expectations; resource ceilings for the test worker; whether each weird-but-valid input is preserved or rejected by a named rule. Keep proposals separate from currently implemented error codes—do not invent a code and mark it passing.

**Build first:** roughly 30–40 small cases drawn from parsing, wrong shapes, duplicate keys, numeric/type traps, refs and identity collisions, plus a handful of legal weird-string controls and rollback sequences. The number is a starting budget, not the done-test.

**Defer:** coverage-guided fuzzing engines, broad property-testing dependencies, differential testing across alternative parsers, enormous datasets and a full viewer/export adversarial suite. Retain the file format and runner so a future fuzzer can promote a minimized failure directly into a permanent case.

Success means the importer can explain why it refuses garbage, preserve legal oddities, and remain usable afterward—with no hidden writes or false report—not merely survive a folder full of invalid JSON.
