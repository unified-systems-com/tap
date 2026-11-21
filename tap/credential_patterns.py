"""Credential-shape detection for source control — `req-tap-cares-secrets-credential-patterns`.

The sibling of the envelope scanner in :mod:`tap.runtime_secrets`. That one is
*structural*: it knows TAP's secret envelope and catches a `*.secret.json` committed
with `git add -f`, or a real secret renamed to dodge the suffix. It is excellent at
what it covers and blind to everything else — it reads only `*.json`, so a token
pasted into a `.py`, `.md`, `.sh`, `.yml` or `.env`, or a private key in a `.pem`, is
invisible to it.

This module closes that gap for the credential shapes that can be recognized with
near-zero false positives, and is deliberately narrow about which those are.

**Why issuer-prefixed shapes and not entropy.** A full-history `gitleaks` run over
this repository (1,198 commits, 2026-07-22) produced 13 findings, all from its
entropy-based `generic-api-key` rule and all false positives: log-site-id constants,
an AWS `OriginAccessControlId` in a test fixture, `s3cret-pw-xyz` in a superuser test,
and `authz denied:` lines in committed log samples. Entropy cannot separate "high
Shannon score" from "credential" in a codebase whose test fixtures are full of opaque
identifiers. The patterns below key on the *issuer's own prefix and length* instead,
which is self-identifying: `github_pat_`, `AKIA`, a PEM armor header. The same run
found zero matches for these across 874 text files, which is what makes the guard a
hard zero rather than a ratcheting baseline — there is no accepted-debt list, because
an accepted list of leaked credentials is not a thing that should exist.

**What this deliberately does NOT catch** (honest-risk, `req-sec-honest-risk`):
AWS *secret* access keys, database passwords, bare high-entropy strings, and any
credential with no distinguishing prefix. Those are entropy problems, and entropy
belongs in the per-push `gitleaks` CI step where a human triages findings — not in a
hard-zero guard that must never cry wolf. This module is the fast, exact layer; it is
not, and does not claim to be, a general-purpose secret scanner.

Import-safe and settings-free by design: the pre-commit hook
(`.githooks/pre-commit`) imports it directly with no Django configured, and so does
the guard that walks the whole tree.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# Narrow, review-visible escape hatch — same shape as the `TAP-LOG-ID` marker used by
# the logging convention. A line carrying it is skipped, so documentation that must
# show a real-looking token (an onboarding doc, a test vector) can do so deliberately
# and legibly in review, rather than by weakening a pattern for everyone.
ALLOW_MARKER = "TAP-CREDENTIAL-OK"


@dataclass(frozen=True)
class CredentialPattern:
    """One recognizable credential shape."""

    name: str
    regex: re.Pattern[str]
    description: str


@dataclass(frozen=True)
class CredentialMatch:
    """One credential-shaped string found in the tree."""

    path: str
    line: int
    pattern: str
    #: The matched text, truncated and tail-masked — enough to locate, never enough to use.
    excerpt: str


def _mask(matched: str) -> str:
    """Return a locating excerpt: issuer prefix kept, secret body masked.

    A guard failure is printed in CI logs, which are themselves a disclosure surface.
    Showing the whole token to prove a token was found would leak it a second time.
    """
    head = matched[:10]
    return f"{head}…<{len(matched) - len(head)} chars masked>"


# Ordered most-specific first. Every pattern keys on an issuer-assigned prefix plus a
# length floor, so prose that merely *names* a credential kind (`github_pat`, the
# `GITHUB_PAT_KIND` constant, "an AKIA-style key") cannot match — only the real shape does.
CREDENTIAL_PATTERNS: tuple[CredentialPattern, ...] = (
    CredentialPattern(
        name="github-fine-grained-pat",
        regex=re.compile(r"github_pat_[A-Za-z0-9_]{36,}"),
        description="GitHub fine-grained personal access token (the plugin-pull and core-read credential kind).",
    ),
    CredentialPattern(
        name="github-token",
        regex=re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"),
        description="GitHub classic PAT / OAuth / user / server / refresh token (ghp_, gho_, ghu_, ghs_, ghr_).",
    ),
    CredentialPattern(
        name="aws-access-key-id",
        regex=re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        description="AWS access key id (long-lived AKIA or temporary ASIA).",
    ),
    CredentialPattern(
        name="private-key-block",
        regex=re.compile(r"-----BEGIN (?:[A-Z][A-Z ]* )?PRIVATE KEY-----"),
        description="PEM private-key armor — RSA/EC/OPENSSH/PKCS#8, incl. a GitHub App signing key.",
    ),
    CredentialPattern(
        name="slack-token",
        regex=re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
        description="Slack bot/app/user/refresh token.",
    ),
    CredentialPattern(
        name="google-api-key",
        regex=re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
        description="Google API key.",
    ),
    CredentialPattern(
        name="openai-api-key",
        regex=re.compile(r"\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{40,}"),
        description=(
            "OpenAI project-scoped API key (sk-proj-/sk-svcacct-/sk-admin- — the Codex "
            "reviewer-seat credential kind; legacy bare sk- keys have no reliable floor "
            "and are left to the entropy layer)."
        ),
    ),
    CredentialPattern(
        name="xai-api-key",
        regex=re.compile(r"\bxai-[A-Za-z0-9]{40,}"),
        description=(
            "xAI API key (xai- prefix + long alphanumeric body — the Grok reviewer-seat "
            "credential kind). The 40-char floor and hyphen-free body keep prose like "
            "'xai-code-review' from matching."
        ),
    ),
)


def scan_text(text: str, *, path: str = "<text>") -> list[CredentialMatch]:
    """Return every credential-shaped match in ``text``.

    Lines carrying :data:`ALLOW_MARKER` are skipped whole — the deliberate, reviewable
    exemption for documentation and test vectors.

    Args:
        text: File contents to scan.
        path: Repo-relative path recorded on each match (for reporting only).
    """
    matches: list[CredentialMatch] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for pattern in CREDENTIAL_PATTERNS:
            for found in pattern.regex.finditer(line):
                matches.append(
                    CredentialMatch(
                        path=path,
                        line=lineno,
                        pattern=pattern.name,
                        excerpt=_mask(found.group()),
                    )
                )
    return matches


def scan_paths(repo_root: Path, rel_paths: Iterable[str]) -> list[CredentialMatch]:
    """Scan ``rel_paths`` (repo-relative) for credential shapes.

    Pure over the supplied path list so it is unit-testable and reusable by both the
    whole-tree guard and the staged-files pre-commit hook. Unreadable and non-UTF-8
    (binary) files are skipped: a credential that only exists inside a binary is out of
    scope for this layer, and decoding every blob would make the hook too slow to keep.

    Args:
        repo_root: Directory the relative paths resolve against.
        rel_paths: Repo-relative file paths to read and scan.
    """
    matches: list[CredentialMatch] = []
    for rel in rel_paths:
        try:
            text = (repo_root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        matches.extend(scan_text(text, path=str(rel)))
    return matches


def format_matches(matches: list[CredentialMatch]) -> str:
    """Render matches as an operator-facing block: what, where, and what to do next."""
    lines = [f"  {m.path}:{m.line} — {m.pattern} ({m.excerpt})" for m in matches]
    return "\n".join(lines)


__all__ = [
    "ALLOW_MARKER",
    "CREDENTIAL_PATTERNS",
    "CredentialMatch",
    "CredentialPattern",
    "format_matches",
    "scan_paths",
    "scan_text",
]
