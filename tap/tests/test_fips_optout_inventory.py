"""Every explicit FIPS opt-out is accounted for (req-fips-optout-inventory, decision D21).

Both images load OpenSSL's `default` provider beside `fips` and `base`, under
`default_properties = fips=yes`. An ordinary request still reaches only the FIPS module; only a
request that opts out (`usedforsecurity=False`, a `-fips` / `fips=no` / `provider=default` property
query) reaches `default`, and from there it can reach ANY algorithm. So the posture holds only if no
opt-out serves a security function, and that is checked, not assumed: the crypto-BOM inventories
every opt-out in TAP, plugin and installed dependency source, and each needs a reviewed reason.

The runtime probes run in a fresh subprocess, for the reason tap/tests/test_fips_pedantic.py gives:
a refused fetch poisons the process's default library context (L18).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tap import crypto_bom
from tap.crypto_providers import FIPS_OPT_OUT, FIPS_OPT_OUTS, Boundary, Disposition

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVATION_SCRIPT = REPO_ROOT / "docker" / "activate-fips-system-wide.sh"
DOCKERFILES = (REPO_ROOT / "Dockerfile", REPO_ROOT / "docker" / "postgres" / "Dockerfile")


def _pyfile(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


@pytest.mark.spec("req-fips-optout-inventory-1")
@pytest.mark.parametrize(
    ("body", "flagged"),
    [
        ("import hashlib\nhashlib.md5(b'x', usedforsecurity=False)\n", True),
        ("import hashlib\nhashlib.new('sha3_256', usedforsecurity=False)\n", True),
        ("Q = '-fips'\n", True),
        ("Q = 'provider=default'\n", True),
        ("Q = 'provider=default,fips=no'\n", True),
        ("Q = 'fips = no'\n", True),
        ("import hashlib\nhashlib.md5(b'x', usedforsecurity=0)\n", True),
        ("import hashlib\nhashlib.md5(b'x', usedforsecurity=bool(0))\n", True),
        ("import hashlib\nflag = False\nhashlib.md5(b'x', usedforsecurity=flag)\n", True),
        ("import hashlib\nhashlib.md5(b'x', **{'usedforsecurity': False})\n", True),
        ("import hashlib\nhashlib.md5(b'x', usedforsecurity=True)\n", False),
        ("Q = 'fips=yes'\n", False),
        ("DOC = 'runs in FIPS mode; see the fips provider'\n", False),
        ("import hashlib\nhashlib.sha256(b'x')\n", False),
    ],
)
def test_every_opt_out_is_a_finding(tmp_path, body: str, flagged: bool) -> None:
    _pyfile(tmp_path, "m.py", body)
    findings = [f for f in crypto_bom._optout_findings([tmp_path]) if f.provider == FIPS_OPT_OUT]
    assert bool(findings) is flagged
    for f in findings:
        assert f.artifact.startswith(str(tmp_path / "m.py") + ":")


@pytest.mark.spec("req-fips-optout-inventory-1")
def test_test_code_and_the_self_check_are_not_inventoried(tmp_path) -> None:
    (tmp_path / "tests").mkdir()
    _pyfile(tmp_path / "tests", "test_x.py", "import hashlib\nhashlib.md5(b'x', usedforsecurity=False)\n")
    (tmp_path / "tap").mkdir()
    _pyfile(tmp_path / "tap", "fips.py", "import _hashlib\n_hashlib.new('md5', b'x', usedforsecurity=False)\n")
    assert crypto_bom._optout_findings([tmp_path]) == []


@pytest.mark.spec("req-fips-optout-inventory-2")
def test_an_undispositioned_opt_out_fails_the_gate(tmp_path) -> None:
    _pyfile(tmp_path, "new_dep.py", "import hashlib\nhashlib.md5(b'x', usedforsecurity=False)\n")
    [finding] = crypto_bom._optout_findings([tmp_path])
    assert finding.boundary is None and finding.is_failure
    assert "FIPS_OPT_OUTS" in finding.detail


@pytest.mark.spec("req-fips-optout-inventory-2")
def test_a_reviewed_opt_out_is_recorded_not_failed(tmp_path, monkeypatch) -> None:
    _pyfile(tmp_path, "cachekey.py", "import hashlib\nhashlib.md5(b'x', usedforsecurity=False)\n")
    reviewed = Disposition("*/cachekey.py::", FIPS_OPT_OUT, Boundary.NON_SECURITY_USE, "cache key", "rid")
    monkeypatch.setattr(crypto_bom, "FIPS_OPT_OUTS", (reviewed,))
    [finding] = crypto_bom._optout_findings([tmp_path])
    assert finding.boundary is Boundary.NON_SECURITY_USE and not finding.is_failure
    assert finding.detail == "cache key"


@pytest.mark.spec("req-fips-optout-inventory-2")
def test_a_review_covers_one_function_not_the_whole_file(tmp_path, monkeypatch) -> None:
    (tmp_path / "django" / "utils").mkdir(parents=True)
    _pyfile(
        tmp_path / "django" / "utils",
        "cache.py",
        "from hashlib import md5\n"
        "def set_response_etag(r):\n    return md5(r, usedforsecurity=False)\n"
        "def sign_session(r):\n    return md5(r, usedforsecurity=False)\n",
    )
    reviewed = Disposition(
        "django/utils/cache.py::set_response_etag", FIPS_OPT_OUT, Boundary.NON_SECURITY_USE, "etag", "rid"
    )
    monkeypatch.setattr(crypto_bom, "FIPS_OPT_OUTS", (reviewed,))
    by_line = {f.artifact.rsplit(":", 1)[1]: f for f in crypto_bom._optout_findings([tmp_path])}
    assert not by_line["3"].is_failure, "the reviewed function stays reviewed"
    assert by_line["5"].is_failure and "sign_session" in by_line["5"].detail, "a new function is a new finding"


@pytest.mark.spec("req-fips-optout-inventory-2")
def test_every_reviewed_opt_out_carries_a_reason() -> None:
    assert FIPS_OPT_OUTS, "the inventory is empty — the scan or the table is broken"
    for d in FIPS_OPT_OUTS:
        assert d.provider == FIPS_OPT_OUT and d.boundary in (Boundary.NON_SECURITY_USE, Boundary.UNREACHED), d
        path, sep, scope = d.artifact.partition("::")
        assert sep and scope and ":" not in path, f"name a file and its function, never a line: {d.artifact}"
        assert len(d.rationale.split()) >= 8, f"{d.artifact}: a reason, not a label"


@pytest.mark.spec("req-fips-optout-inventory-2")
@pytest.mark.parametrize(
    "body",
    [
        "from requests.auth import HTTPDigestAuth\n",
        "import requests\nrequests.get('u', auth=requests.auth.HTTPDigestAuth('a', 'b'))\n",
    ],
)
def test_reaching_a_security_opt_out_is_must_fix(tmp_path, body: str) -> None:
    _pyfile(tmp_path, "plugin.py", body)
    reached = [f for f in crypto_bom._source_findings([tmp_path]) if f.provider == f"{FIPS_OPT_OUT}-reached"]
    assert reached and all(f.boundary is Boundary.MUST_FIX and f.is_failure for f in reached)


@pytest.mark.spec("req-fips-optout-inventory-2")
@pytest.mark.skipif(not Path("/app/.venv").is_dir(), reason="needs the image's installed environment")
def test_the_installed_environment_has_no_unreviewed_opt_out() -> None:
    unreviewed = [f for f in crypto_bom.core_report().findings if f.provider == FIPS_OPT_OUT and f.is_failure]
    assert not unreviewed, "\n".join(f"{f.artifact}: {f.detail}" for f in unreviewed)


@pytest.mark.spec("req-fips-optout-inventory-3")
def test_activation_keeps_default_behind_fips_yes() -> None:
    text = ACTIVATION_SCRIPT.read_text(encoding="utf-8")
    assert "require 'default = default_sect'" in text
    assert "require 'default_properties = fips=yes'" in text
    assert "openssl dgst -md5 >/dev/null" in text, "the build must prove a plain MD5 request is refused"
    assert "openssl enc -chacha20" in text, "the build must prove a plain non-approved cipher is refused"
    assert "-propquery '-fips'" in text, "the build must prove the explicit non-security path works"
    assert "require_absent 'legacy = legacy_sect'" in text, "Chainguard's legacy provider must stay off"


@pytest.mark.spec("req-fips-optout-inventory-3")
@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_the_rollback_activation_also_loads_default(dockerfile: Path) -> None:
    text = dockerfile.read_text(encoding="utf-8")
    assert "'default = default_sect'" in text and "'default_properties = fips=yes'" in text, dockerfile


# Exit codes: 0 = as required, 1 = an ordinary request reached a non-approved algorithm,
# 2 = the explicit non-security path failed.
PROBE = """
import hashlib, sys
try:
    hashlib.md5(b"x")
    print("plain md5 ALLOWED"); sys.exit(1)
except ValueError:
    pass
try:
    hashlib.md5(b"x", usedforsecurity=False)
except ValueError as exc:
    print(f"non-security md5 failed: {exc!r}"); sys.exit(2)
"""


@pytest.mark.spec("req-fips-optout-inventory-3")
@pytest.mark.skipif(os.environ.get("TAP_FIPS_MODE") != "1", reason="the image declares FIPS off")
def test_only_an_explicit_opt_out_reaches_md5() -> None:
    result = subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — a fresh interpreter IS the test (L18); argv list, no shell, a literal probe  # nosec B603  # noqa: S603
        [sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, f"{result.stdout}{result.stderr}"
