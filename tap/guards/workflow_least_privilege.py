"""Workflow least-privilege guard — `spec-cicd-hardening.md` (`req-cicd-runner-least-privilege`).

TAP-IMPLEMENTS: req-cicd-runner-least-privilege@449f6a767407/319cd4839b9a (enforcement) — the
    guard that fails any workflow job without an explicit least-privilege permissions block.

The job is the token boundary: every GitHub Actions job gets its own `GITHUB_TOKEN`,
scoped by `permissions:` blocks. This guard pins the three structural invariants over
`.github/workflows/*.yml`:

1. **Explicit permissions** (`-2`): every workflow declares a top-level `permissions:`
   block; top-level grants are read-only; write scopes appear only at job level.
2. **Write-job co-tenancy** (`-3`): in a job whose effective token carries any write
   scope, every third-party `uses:` step requires a review-visible
   `# guard-allow: req-cicd-runner-least-privilege — <reason>` annotation inside that
   job's block (one annotation covers the job — the annotated steps ARE the job's
   write, e.g. the `docker/*` publish steps). First-party (`actions/*`, `github/*`),
   local (`./…`) and same-org refs are exempt. Additionally, every `actions/checkout`
   in a write-scoped job must set `persist-credentials: false` — the practical token
   leak is the credential checkout persists into `.git` config, where any later step
   can read it.
3. **SHA-pinned externals** (`-4`): every external `uses:` ref (not local, not
   same-org) is a 40-hex commit SHA, with a `# v<version>` comment on the line for
   human legibility. Same-org refs stay tag-based by design (`-5` — the compensating
   control is the `v*` tag ruleset, tracked there); mutable third-party tags are the
   2026-03-19 trivy-action compromise vector.

Parsing is PyYAML `safe_load` (dev-group dependency; parses only our own committed
files) for structure, plus the raw text for what YAML cannot see: comments (the
`guard-allow` annotations, the `# v` pin comments) and job line ranges.

Scope limits (named in the spec): `GITHUB_TOKEN` grants only — App-token power is
out of band; static declarations, not runtime data flow; core repo workflows only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tap.guards.base import REPO_ROOT, Guard

WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

RID = "req-cicd-runner-least-privilege"
ANNOTATION = f"guard-allow: {RID}"

#: Prefixes whose actions are exempt from the co-tenancy annotation requirement
#: (GitHub-owned namespaces). They are NOT exempt from SHA-pinning.
_FIRST_PARTY_PREFIXES = ("actions/", "github/")
#: Our own org — reusable-workflow refs stay tag-based (`-5`); exempt from both.
_SAME_ORG_PREFIX = "unified-systems-com/"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _is_local(ref: str) -> bool:
    return ref.startswith("./")


def _is_same_org(ref: str) -> bool:
    return ref.startswith(_SAME_ORG_PREFIX)


def _is_first_party(ref: str) -> bool:
    return ref.startswith(_FIRST_PARTY_PREFIXES)


def _grants_write(permissions: Any) -> bool:
    """True if a `permissions:` value grants any write scope."""
    if permissions is None:
        return False
    if isinstance(permissions, str):
        return permissions.strip() == "write-all"
    if isinstance(permissions, dict):
        return any(str(level).strip() == "write" for level in permissions.values())
    return False


def _job_line_ranges(raw_lines: list[str]) -> dict[str, tuple[int, int]]:
    """Map job name -> (start, end) line indexes, from the raw text.

    Jobs are two-space-indented keys under a top-level `jobs:` key. Comments and
    blank lines between jobs are attributed to the following job (harmless here).
    """
    ranges: dict[str, tuple[int, int]] = {}
    in_jobs = False
    current: str | None = None
    start = 0
    for i, line in enumerate(raw_lines):
        if re.match(r"^jobs:\s*(#.*)?$", line):
            in_jobs = True
            continue
        if in_jobs and re.match(r"^[A-Za-z_#-]", line):  # next top-level key ends jobs
            if not line.lstrip().startswith("#"):
                if current is not None:
                    ranges[current] = (start, i)
                    current = None
                in_jobs = False
            continue
        if in_jobs:
            m = re.match(r"^  ([A-Za-z0-9_-]+):\s*(#.*)?$", line)
            if m:
                if current is not None:
                    ranges[current] = (start, i)
                current = m.group(1)
                start = i
    if current is not None:
        ranges[current] = (start, len(raw_lines))
    return ranges


def scan_workflow(path: Path, raw: str, data: dict[str, Any]) -> list[str]:
    """Return violation messages for one parsed workflow file."""
    violations: list[str] = []
    rel = path.name
    raw_lines = raw.splitlines()

    # -2: explicit, read-only top level ---------------------------------------
    if "permissions" not in data:
        violations.append(
            f"{rel}: no top-level `permissions:` block — every workflow must declare its "
            f"token grants explicitly ({RID}-2); inherited defaults are not a posture."
        )
    elif _grants_write(data.get("permissions")):
        violations.append(
            f"{rel}: top-level `permissions:` grants a write scope — write scopes belong at "
            f"job level, in a job that contains nothing else ({RID}-2)."
        )

    jobs: dict[str, Any] = data.get("jobs") or {}
    job_ranges = _job_line_ranges(raw_lines)

    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        effective_perms = job.get("permissions", data.get("permissions"))
        write_job = _grants_write(effective_perms)
        j_start, j_end = job_ranges.get(job_name, (0, len(raw_lines)))
        job_block = "\n".join(raw_lines[j_start:j_end])
        job_annotated = ANNOTATION in job_block

        refs: list[tuple[str, Any]] = []
        if isinstance(job.get("uses"), str):  # reusable-workflow call
            refs.append((job["uses"], None))
        for step in job.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("uses"), str):
                refs.append((step["uses"], step))

        for ref, step in refs:
            if _is_local(ref) or _is_same_org(ref):
                continue

            # -4: SHA pin + legibility comment --------------------------------
            pinned = ref.rsplit("@", 1)
            if len(pinned) != 2 or not _SHA_RE.match(pinned[1]):
                violations.append(
                    f"{rel} job `{job_name}`: `uses: {ref}` is not pinned to a 40-hex commit "
                    f"SHA ({RID}-4). Mutable tags are the trivy-action-compromise vector; "
                    f"Renovate maintains the pins — do not hand-write tags."
                )
            else:
                uses_lines = [ln for ln in raw_lines[j_start:j_end] if ref in ln]
                if uses_lines and not any("# v" in ln for ln in uses_lines):
                    violations.append(
                        f"{rel} job `{job_name}`: `uses: …@{pinned[1][:12]}…` has no `# v<version>` "
                        f"comment — a bare SHA is illegible to reviewers ({RID}-4)."
                    )

            # -3: co-tenancy in write jobs ------------------------------------
            if write_job and not _is_first_party(ref):
                if not job_annotated:
                    violations.append(
                        f"{rel} job `{job_name}`: third-party `uses: {ref}` shares a job whose "
                        f"token carries a write scope, with no `# {ANNOTATION}` annotation in the "
                        f"job ({RID}-3). Either move the step to a read-only job, or annotate the "
                        f"justified co-tenancy with its reason."
                    )

            # -3: checkout must not persist the token in write jobs -----------
            if write_job and ref.startswith("actions/checkout@") and step is not None:
                with_block = step.get("with") or {}
                if with_block.get("persist-credentials") is not False:
                    violations.append(
                        f"{rel} job `{job_name}`: `actions/checkout` in a write-scoped job must set "
                        f"`persist-credentials: false` — otherwise the job token is readable from "
                        f"`.git` config by every later step ({RID}-3)."
                    )
    return violations


def scan_workflows(workflows_dir: Path = WORKFLOWS_DIR) -> list[str]:
    """Scan every workflow file; returns all violations (empty = clean)."""
    import yaml

    violations: list[str] = []
    for path in sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml")):
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            violations.append(f"{path.name}: does not parse to a mapping — not a workflow?")
            continue
        violations.extend(scan_workflow(path, raw, data))
    return violations


class WorkflowLeastPrivilegeGuard(Guard):
    slug = "workflow-least-privilege"
    map_row = "Workflow least privilege (token boundary)"
    rid = RID
    description = (
        "A workflow job's GITHUB_TOKEN is the write-capable credential a compromised third-party "
        "action would steal. This enforces the token boundary: explicit read-only defaults, write "
        "scopes isolated in annotated single-purpose jobs, checkout credentials never persisted "
        "where write tokens live, and every external action frozen to a reviewed commit SHA "
        "(mutable tags are the 2026-03-19 trivy-action compromise vector)."
    )

    def check(self) -> None:
        violations = scan_workflows()
        assert not violations, (
            "Workflow least-privilege violations (spec-cicd-hardening.md " + RID + "):\n  " + "\n  ".join(violations)
        )
