# Codex reviews, September 2026 (archive)

Point-in-time reviews written by Codex on 2026-09-17 and 2026-09-18 for the grid reconciliation and batch-corpus work. They are saved here from the untracked `review/` directory of the `double-tap-git-serious` session, which held the only copy. The identity phase 2 reviews are the reasoning record for tap#458 and tap#140, both still open when this was archived on 2026-10-08.

Each file is as it was written. Line anchors and "current state" claims are true only as of the commits the file names, and are not kept up to date. Absolute local paths inside come from the original session. The probe scripts carry a `.txt` suffix so the repository's lint and type checks, which walk every `.py` file, do not treat them as first-party code.

| File | Date | What it is | Tracked in (as of 2026-10-08) |
| --- | --- | --- | --- |
| `identity-phase-2/review.md` | 2026-09-17 | Independent review of the identity phase 2 plan: ten findings, and the six rulings argued individually. Marked superseded by the revised review below. | tap#458, tap#140 (open) |
| `identity-phase-2/cascade-first-review.md` | 2026-09-17 | The revised review that replaced it: the "Cascade First" decision and what to decide now versus defer. | tap#458, tap#140 (open) |
| `identity-phase-2/verification.md`, `cascade-verification.md` | 2026-09-17 | What each review's probes did and did not show. | |
| `identity-phase-2/*-probe.py.txt` | 2026-09-17 | The probe scripts behind those records. | |
| `identity-phase-2/source-inventory.md` | 2026-09-17 | Pinned snapshot of the plugin sources the review read. Stale by design. | |
| `cascade-corpus-review.md` | 2026-09-18 | Review of the cascade confirmation corpus. | tap#578 and PR#582, tap#586 and tap#587 (closed 2026-09-18) |
| `bad-batch-proposal.md` | 2026-09-18 | Codex's proposed adversarial input corpus for GRIFT. | |
| `bad-batch-assessment.md` | 2026-09-18 | Assessment of that proposal: adopt the question, not the shape. | tap#603, tap#613 (closed); PR#639 (merged) |
| `batch-playground-recommendations.md`, `batch-playground-probes.py.txt` | 2026-09-18 | Review of the batch playground, with the probes behind its code findings. | tap#605 and tap#606 (closed); tap#607 and tap#608 (open) |
