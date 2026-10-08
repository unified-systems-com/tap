# Verification record

Core source: `a6581ada042a61da8f3dbb3791b34066991d6c14`. Runtime: existing project container, Python 3.14.7. No database connection was used by either probe.

## Natural-key helper

Executed the pinned module directly, followed by in-memory inputs.

```text
type-overwrite {'type': 'same', 'id': '7'} {'type': 'same', 'id': '7'}
cross-type keys equal True
unbounded integer JSON {"id":9007199254740993}
1e21 JSON {"id":1000000000000000000000}
empty properties key 6a0db25e-cb4a-858c-8011-2721d85f6e23
```

## Backfill command

Executed the pinned Command class with in-memory registry/model/row doubles. This verifies command logic; it is not an integration test.

```text
CASE undeclared + empty keyed type
panel: 0 live row(s), keyed on ('slug',)
  check clean — every stored key matches a recompute
EXIT CLEAN
CASE same key, different dimensions
panel: 2 live row(s), keyed on ('slug',)
  shared key across dimensions (permitted): panel key=computed-key dimension shapes=2
  check clean — every stored key matches a recompute
EXIT CLEAN
CASE stored nonnull, recomputed null
panel: 1 live row(s), keyed on ('slug',)
  no key: panel A — a constituting value is absent
  check clean — every stored key matches a recompute
EXIT CLEAN
```

## Input artifacts

- `identity-phase-2-codex-prompt.md` SHA-256: `3ddf5106af01eb55dc5fc5f39c376f5d20c73a09750a1a1dca762ab0207a76f6`
- `identity-phase-2-audit.html` SHA-256: `8221ad2c21ea90d61bab6897269f6f12d24aff68f0c4a808c32c7f097d148558`
- `identity-phase-2.html` SHA-256: `8c737468f85a2c27a771e2d7d4a5c64b18f1003759a536f7a0d9421a0d17b48c`

## Limits

No live-grid key census, database concurrency test, plugin collector execution, migrations, or installed Gryphon corpus run was performed. Source citations were checked against immutable snapshots, including 120 individually anchored plugin type declarations.
