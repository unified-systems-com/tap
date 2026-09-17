"""Workflow runner-interpreter guard — `spec-dev-local-execution.md` (`req-dev-localexec-runner-interpreter`).

A GitHub Actions runner ships its own `python3`, and it is not the interpreter the codebase
is written for (`requires-python` in `pyproject.toml`; the container is 3.14). A module using
newer grammar dies at PARSE time there. `publish-images` ran `python3 scripts/sbom/generate.py`
on the runner's 3.12; `generate.py` loads `tap/fips_pins.py`, whose PEP 758 `except A, B:`
only parses on 3.14 — and every publish from 2026-09-02 to 2026-09-17 shipped images with no
SBOM attestations (tap#518). The host syntax floor (`tap/host_syntax_floor.py`) could not see
it: the break was a module loaded by path at runtime, one hop past what it derives (tap#523).

So CI does not depend on the floor at all. In every workflow job, a step that runs repo
Python must be preceded — IN THE SAME JOB — by `actions/setup-python` whose
`python-version-file` names a `pyproject.toml`. The interpreter is then derived from
`requires-python`, never authored twice; a `python-version:` literal is itself a violation.

What counts as "runs repo Python" (a `run:` step, or a step with `shell: python…`):

- `python`/`python3[.N]` followed by a path (`scripts/x.py`, `tap/x.py`, `"$VAR"`) — any
  path, including a variable: a path this scan cannot resolve fails CLOSED.
- `-m <module>` where the module is repo code (`tap…`, `tap_…`, `scripts…`) or an
  interpreter-bound installer/builder (`pip`, `build`). Other `-m` modules (`json.tool`) are
  the stdlib and pass.
- Inline code — `-c '…'`, `-` / no argument (stdin, heredoc, pipe), or `shell: python` —
  when the step's script imports repo code (`import tap…`, `from tap_x import …`, `sys.path`,
  `spec_from_file_location`, `runpy`). Stdlib-only inline code passes: it cannot reach a
  repo module's grammar.

Not counted: `uv run …` / `uvx …` (uv resolves `requires-python` itself); commands inside a
container (`docker run|exec`, `docker compose … exec|run`, `scripts/dc`) and jobs with a
job-level `container:`; version probes (`python3 -V`, `--version`). Interpreter names that
are not a command word (inside `echo` prose, a path like `/usr/bin/python3.14-config`) may
still match — the review-visible escape hatch is a job-level
`# guard-allow: req-dev-localexec-runner-interpreter — <reason>` annotation, as for the
least-privilege guard. Exemptions scope to the one simple command holding the interpreter
(split at unquoted `;` `&&` `||` `|`), never to the whole line; absolute interpreter paths
(`/usr/bin/python3`) count. A setup-python step protects only later steps that run under the
same `if:` (or runs unconditionally), and never with `continue-on-error`.

Scope limits (named): the scan reads workflow YAML only. A script a step calls
(`scripts/change-tier`, whose own `python3` runs `tap/bom_inputs.py`) is policed by the host
syntax floor, not here. Static text, not runtime data flow.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

from tap.guards.base import REPO_ROOT, Guard
from tap.guards.workflow_least_privilege import _job_line_ranges

WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

RID = "req-dev-localexec-runner-interpreter"
ANNOTATION = f"guard-allow: {RID}"

_SETUP_PYTHON = "actions/setup-python@"

# `python`, `python3`, `python3.14` as a whole shell word, bare or as an absolute path
# (`/usr/bin/python3` IS the runner's system interpreter). The lookbehind rejects identifier
# and relative-path neighbours (`mypython3`, `$python3`, `.venv/bin/python`); the lookahead
# requires a word boundary the shell would honour (`python3.14-config` is not an interpreter).
_INTERPRETER = re.compile(r"(?<![\w.$/-])(?:/[\w.+-]+)*/?python(?:3(?:\.\d+)?)?(?=$|[\s;|&)`'\"])")
_UV_PREFIX = re.compile(r"\buv\s+run\b|\buvx\b|\buv\s+tool\s+run\b")
_CONTAINER_LINE = re.compile(r"\bdocker\s+(?:run|exec)\b|\bdocker\s+compose\b|(?:^|\s)(?:\./)?scripts/dc\b")
_REPO_IMPORT = re.compile(
    r"(?:^|[\s;'\"])(?:from|import)\s+(?:tap|tap_\w+|scripts)\b|\bsys\.path\b|\bspec_from_file_location\b|\brunpy\b",
    re.MULTILINE,
)
_REPO_MODULE = re.compile(r"^(?:tap|tap_\w+|scripts)(?:\.|$)")
_INTERPRETER_BOUND_MODULES = frozenset({"pip", "build"})
# Interpreter options that consume the following word.
_OPTS_WITH_ARG = frozenset({"-W", "-X", "--check-hash-based-pycs"})
_VERSION_PROBES = frozenset({"-V", "-VV", "--version", "-h", "--help"})
_SHELL_STOP = re.compile(r"^(?:[;|&)`]|&&|\|\||[0-9]?>|<)")


def _logical_lines(script: str) -> list[str]:
    """Join backslash continuations; drop shell comment lines."""
    joined = re.sub(r"\\\n\s*", " ", script)
    return [ln for ln in joined.splitlines() if not ln.lstrip().startswith("#")]


def _commands(line: str) -> list[str]:
    """Split one logical line into simple commands at unquoted `;` `&&` `||` `|` `(` and backtick.

    Exemptions (`uv run`, container commands) apply to the command that holds the interpreter,
    never to its neighbours: `python3 scripts/x.py; docker run img true` must still flag.
    Quoted text stays whole, so `docker compose exec web sh -c 'cd /app && python3 x.py'` is
    one command: the container's.
    """
    commands: list[str] = []
    current: list[str] = []
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            quote = "" if ch == quote else quote
            current.append(ch)
        elif ch in "'\"":
            quote = ch
            current.append(ch)
        elif line.startswith(("&&", "||"), i):
            commands.append("".join(current))
            current = []
            i += 1
        elif ch in ";|(`":
            commands.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    commands.append("".join(current))
    return [c for c in commands if c.strip()]


def _words_after(text: str) -> list[str]:
    """The shell words after an interpreter match, up to the first command separator."""
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()<>")
        lexer.whitespace_split = True
        words = []
        for word in lexer:
            if _SHELL_STOP.match(word):
                break
            words.append(word)
        return words
    except ValueError:  # unbalanced quote: an inline -c '… spanning lines
        return text.split()


def _classify_invocation(args: list[str], script: str) -> str | None:
    """Why this interpreter call runs repo Python, or None when it does not."""
    i = 0
    while i < len(args):
        word = args[i]
        if word in _VERSION_PROBES:
            return None
        if word in _OPTS_WITH_ARG:
            i += 2
            continue
        if word == "-m":
            module = args[i + 1] if i + 1 < len(args) else ""
            if _REPO_MODULE.match(module):
                return f"`-m {module}` is repo code"
            if module in _INTERPRETER_BOUND_MODULES:
                return f"`-m {module}` installs/builds for this interpreter"
            return None
        if word in ("-c", "-"):
            return "inline code imports repo modules" if _REPO_IMPORT.search(script) else None
        if word.startswith("-") and word != "-":
            i += 1
            continue
        return f"runs `{word}`"
    # No script argument: code arrives on stdin (pipe or heredoc).
    return "stdin code imports repo modules" if _REPO_IMPORT.search(script) else None


def repo_python_calls(script: str) -> list[str]:
    """Reasons each interpreter call in a `run:` script runs repo Python (empty = none)."""
    reasons: list[str] = []
    for line in _logical_lines(script):
        for command in _commands(line):
            if _CONTAINER_LINE.search(command):
                continue
            for m in _INTERPRETER.finditer(command):
                if _UV_PREFIX.search(command[: m.start()]):
                    continue
                reason = _classify_invocation(_words_after(command[m.end() :]), script)
                if reason:
                    reasons.append(reason)
    return reasons


def _setup_python_problem(step: dict[str, Any]) -> str | None:
    """None when a setup-python step derives the version from a pyproject, else why not."""
    with_block = step.get("with") or {}
    if "python-version" in with_block:
        return "sets a `python-version:` literal — derive it with `python-version-file: pyproject.toml`"
    version_file = str(with_block.get("python-version-file", ""))
    if not version_file.endswith("pyproject.toml"):
        return "has no `python-version-file` naming a `pyproject.toml` — the version must be derived"
    return None


def _condition(step: dict[str, Any]) -> str | None:
    """A step's `if:`, normalised for comparison (`${{ }}` and whitespace stripped), or None."""
    raw = step.get("if")
    if raw is None:
        return None
    text = str(raw).strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2]
    return " ".join(text.split())


def _step_label(step: dict[str, Any], index: int) -> str:
    return f"step {index + 1}" + (f" `{step['name']}`" if step.get("name") else "")


def scan_workflow(path: Path, raw: str, data: dict[str, Any]) -> list[str]:
    """Return violation messages for one parsed workflow file.

    TAP-IMPLEMENTS: req-dev-localexec-runner-interpreter@0b2738139e7e/751803df980b (enforcement) — the one
        predicate deciding whether a workflow job runs repo Python on an interpreter derived from
        requires-python.
    """
    violations: list[str] = []
    rel = path.name
    raw_lines = raw.splitlines()
    job_ranges = _job_line_ranges(raw_lines)

    for job_name, job in (data.get("jobs") or {}).items():
        if not isinstance(job, dict) or job.get("container"):
            continue
        j_start, j_end = job_ranges.get(job_name, (0, len(raw_lines)))
        if ANNOTATION in "\n".join(raw_lines[j_start:j_end]):
            continue

        # The `if:` conditions under which a derived interpreter is installed (None = always). A
        # setup step only protects a later step running under the same condition, and never when
        # `continue-on-error: true` lets the job go on without it.
        derived_when: set[str | None] = set()
        for index, step in enumerate(job.get("steps") or []):
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if isinstance(uses, str) and uses.startswith(_SETUP_PYTHON):
                problem = _setup_python_problem(step)
                if problem:
                    violations.append(
                        f"{rel} job `{job_name}` {_step_label(step, index)}: setup-python {problem} ({RID})."
                    )
                elif step.get("continue-on-error") not in (None, False):
                    violations.append(
                        f"{rel} job `{job_name}` {_step_label(step, index)}: setup-python has `continue-on-error`, so "
                        f"a failed install leaves later steps on the runner's interpreter ({RID})."
                    )
                else:
                    derived_when.add(_condition(step))
                continue
            script = step.get("run")
            if not isinstance(script, str):
                continue
            shell = str(step.get("shell", ""))
            reasons = (
                ["`shell: python` step imports repo modules"]
                if shell.startswith("python") and _REPO_IMPORT.search(script)
                else repo_python_calls(script)
            )
            if reasons and not (None in derived_when or _condition(step) in derived_when):
                violations.append(
                    f"{rel} job `{job_name}` {_step_label(step, index)}: {'; '.join(sorted(set(reasons)))} on the "
                    f"runner's system interpreter. Add `actions/setup-python` with `python-version-file: "
                    f"pyproject.toml` earlier in this job, run it via `uv run`, or annotate `# {ANNOTATION} — "
                    f"<reason>` in the job ({RID})."
                )
    return violations


def scan_workflows(workflows_dir: Path = WORKFLOWS_DIR) -> list[str]:
    """Scan every workflow file; returns all violations (empty = clean)."""
    import yaml

    violations: list[str] = []
    for path in sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml")):
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        if isinstance(data, dict):
            violations.extend(scan_workflow(path, raw, data))
    return violations


class WorkflowRunnerPythonGuard(Guard):
    slug = "workflow-runner-python"
    map_row = "Workflow jobs run repo Python on the repo's interpreter"
    rid = RID
    description = (
        "A runner's system python3 is not the interpreter the code is written for; a module using "
        "newer grammar dies at parse time there, and publish-images shipped no SBOM attestations for "
        "15 days that way (tap#518). Every workflow job that runs repo Python must first install the "
        "interpreter derived from pyproject.toml's requires-python via actions/setup-python (or use uv run)."
    )

    def check(self) -> None:
        violations = scan_workflows()
        # An explicit raise, not `assert`: `python -O` strips asserts, and a guard must not
        # fail open under an optimisation flag (Bandit B101; precedent: direct_write.py).
        if violations:
            raise AssertionError(
                "Workflow runner-interpreter violations (spec-dev-local-execution.md "
                + RID
                + "):\n  "
                + "\n  ".join(violations)
            )
