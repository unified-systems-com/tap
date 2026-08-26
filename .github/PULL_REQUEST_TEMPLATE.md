<!--
  TITLE: describe the change, not the mechanism that produced it.
  "promote: session-x -> main" and "AI session updates" tell a reviewer nothing.
  BODY: declare everything in the diff. A contract change, a new spec section, or a
  security-relevant edit that the body does not mention is worse than no body at all.
  See CONTRIBUTING.md - Pull Requests.
-->

## What this changes

<!-- Replace this with what a reviewer is actually approving. -->

# Pull Request Checklist

## Contribution terms

- [ ] I have read and agree to `CONTRIBUTING.md`, including licensing my contribution under Apache License 2.0 and, effective upon adoption, under any later permissive OSI-approved license the project adopts, to all recipients of the work.
- [ ] I have certified every commit under the Developer Certificate of Origin, Version 1.1, with a `Signed-off-by` line.
- [ ] If my employer or another organization may own or control rights in this contribution, I am authorized to submit it under the project's contribution terms.
- [ ] If this contribution was prepared with significant AI assistance, I have personally reviewed it and have no reason to believe it contains third-party material that cannot lawfully be included under the project's contribution terms.

## Engineering

- [ ] Tests cover the new or changed behavior, and the suite (`scripts/test`) passes.
- [ ] `black`, `ruff`, and `mypy` come back clean; any suppression carries a justification on the line.
- [ ] Any requirement I added, or flipped to `Implemented`, carries evidence (a test citing it with `@pytest.mark.spec`, an implementation claim, or both) or a documented `Trace:` exclusion. See `docs/doc-dev-spec-driven-contribution.md`.
- [ ] I have read the automated review feedback on this PR, including suppressed findings, and acted on it or dismissed it consciously (`scripts/pr-review-triage <pr>`).
