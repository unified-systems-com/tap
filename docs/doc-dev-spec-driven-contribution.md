---
title: Spec-Driven Contribution — Getting a Change Past the Gate
spec: specs/spec-tap-requirement-traceability.md
audience:
  - developer
  - llm
covers:
  - req-tap-traceability-claim
  - req-tap-traceability-roles
  - req-tap-traceability-staleness
  - req-tap-traceability-code-staleness
  - req-tap-traceability-minting
  - req-tap-traceability-scope
  - req-tap-traceability-disposition
  - req-tap-traceability-accounting
  - req-tap-traceability-status
update-triggers:
  - The `Trace:` disposition vocabulary gains or loses a category
  - The claim role vocabulary changes (derivation / enforcement / surface)
  - The accounting buckets change, or the Unaccounted ratchet changes its fail-closed conditions
  - `scripts/implements-tag` changes its flags or output
  - The status vocabulary in `specs/spec-req-template.md` changes
assumes:
  - You have a running development session (`scripts/spawn-session.sh`)
---

# Spec-Driven Contribution

TAP's behaviour is defined by specifications, not by the code that happens to implement
them. A requirement is the unit: it has an identifier, a status, and — once it claims to
be built — evidence that it is.

This is enforced, not aspirational. If you add a requirement and do nothing else, or flip
one to `Implemented` without evidence, the gate fails your push. This page is how to not
have that happen.

Canonical source is `specs/spec-tap-requirement-traceability.md`. Where this page and that
spec disagree, the spec wins.

## The short version

If you are adding a feature:

1. Write the requirement in the owning spec with `Status: Proposed`.
2. Build it. Mark the tests that prove it with `@pytest.mark.spec("<rid>")`.
3. Flip the status to `Implemented` **in the same change that lands the evidence**.

That is the whole happy path. Steps 1 and 3 are usually the same pull request; they only
separate when the design is agreed before the work starts.

## Why a push fails

Every requirement in the corpus lands in exactly one bucket. Most buckets need nothing
from you:

| Bucket | How a requirement gets there |
| --- | --- |
| Unbuilt | `Status:` is `Proposed`, `Backlog`, `In Development`, `Approved for Development`, or `Refactoring` |
| Retired | `Status:` is `Deprecated`, `Deprecating`, or `Retired` |
| Doctrine | `Status: In Force` — a standing rule rather than a built thing |
| Disputed | `Status: Disputed` — spec and implementation disagree; needs a review-ledger row |
| Mapped | Evidence exists: a test citation, an implementation claim, or both |
| Excluded | A `Trace:` line says why no code maps to it |

Anything else is **Unaccounted**, and Unaccounted is a ratcheting count that fails closed
in two situations: **a new requirement**, and **a status flip to `Implemented`**. Those
are the two moments where the gate will stop you, and both are moments where you know
something the tree does not.

The corollary is the useful part: a requirement sitting at `Proposed` costs you nothing.
Write the spec first and the gate stays out of your way until you claim to have built it.

## Evidence, in increasing order of effort

### A test citation — the usual answer

Mark the test that proves an acceptance criterion:

```python
@pytest.mark.spec("req-example-dimension-core-1")
def test_dimension_is_rejected_when_unknown() -> None:
    ...
```

The marker must name a requirement or acceptance criterion that exists; a typo fails
rather than passing silently. For most contributions this is the only thing you need to
do, and it is not extra work — you were writing the test anyway.

### An implementation claim — when one function owns the fact

A claim asserts something stronger: **this function is where this requirement's fact is
derived, and no other function may derive it.** It is deliberately scarce. Claims are for
requirements where a canonical derivation matters — a security decision, a boundary, a
rule that would be dangerous to reimplement elsewhere. A requirement with no claim is not
a defect.

Never hand-write one. Mint it:

```bash
scripts/implements-tag req-example-thing derivation
```

That prints a complete line with the spec end already fingerprinted and a placeholder for
the code end. Paste it into the docstring of the owning function, then stamp the code end:

```bash
scripts/implements-tag --resync path/to/module.py
```

An unstamped claim fails the guard, so the second step cannot be quietly skipped. Roles
are `derivation`, `enforcement`, or `surface` — a requirement is often realised at several
layers, and each layer may carry one claim.

### A disposition — when no code maps to it

Some requirements legitimately have no Python implementation. Mark them with a `Trace:`
line after `Status:`, separated by one blank line (every metadata line is — Markdown would
otherwise join them into one rendered line; `scripts/spec-two-line-metadata` applies the form):

```
Status: `Implemented`

Trace: `non-python` — docker/entrypoint.sh
```

The vocabulary is closed, and an unknown category or a missing payload is a parse failure:

| Category | For | Payload |
| --- | --- | --- |
| `process` | Governance or process conformed to by humans and workflow | Optional reason |
| `narrative` | An umbrella statement whose substance lives in its children | Optional reason |
| `non-python` | Shell, workflows, Dockerfiles, templates, seed data | **Required** — the file path |
| `external` | Another repo, an evicted plugin, org configuration | **Required** — the repo or system |

An excluded requirement cannot also carry evidence. If you find yourself wanting both, one
of the two is wrong.

## Claims go stale on purpose

A claim fingerprints both ends of the link. Two things will therefore break it, and both
are supposed to:

- **You edited the requirement.** The spec hash moves, every claim on it reports
  `Outdated`, and someone has to re-read the implementation against the new wording.
- **You edited the claimed function.** The code hash moves, the claim reports `Drifted`,
  and it has to be re-verified against the requirement.

Neither is a bug in the tooling. A link that merely exists is not a link that is true. In
both cases the fix is to check that the implementation still satisfies the requirement,
and then re-stamp:

```bash
scripts/implements-tag --resync path/to/module.py
```

Re-stamping without re-reading is the one way to make this system worthless. It is also
invisible in a diff, which is why it is worth saying out loud.

## Before you push

```bash
scripts/implements-tag --check
```

Lists malformed, unresolvable, stale, and drifted claims. Clean output looks like:

```
89 claim(s), all well-formed, resolving and current.
```

The full battery is `scripts/test`, which includes the accounting and evidence guards. If
the gate rejects your push with an Unaccounted count, the cause is almost always one of
the two fail-closed moments above: a requirement you added, or a status you flipped.

## Two things that catch people out

**`Verified` is not yours to declare.** It requires two independent classes of evidence — a
claim *and* a test citation. One class earns `Implemented`. Setting `Verified` without both
fails.

**Status is not decorative.** ``Status: `Proposed (Deferred)` `` does not parse as `Proposed`;
it parses as nothing, and the requirement falls into Unaccounted. Keep the status value
canonical and put the nuance in the prose. The vocabulary lives in
`specs/spec-req-template.md`.
