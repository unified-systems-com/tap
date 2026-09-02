"""The FIPS provider pins, derived once — `spec-fips.md` (`req-fips-pin-currency`).

`docker/build-openssl-fips.sh` is the only authoring site for WHAT OpenSSL we build (`OSSL_VERSION`)
and WHICH provider versions carry a CMVP certificate (`OSSL_CMVP_VALIDATED`). Everything that
needs to say whether the shipped provider is validated reads it from here:

- the crypto Bill-of-Materials (`tap.crypto_providers` / `tap.crypto_bom`), which classifies
  OpenSSL-routed providers as VALIDATED or as the distinct FIPS_MODE_UNVALIDATED_BUILD state;
- the SBOM generator (`scripts/sbom/generate.py`), which stamps the provider component with a
  `tap:fips-validation` property;
- the fips-claims guard (`tap.guards.fips_claims`), which refuses a hand-written "CMVP #NNNN" or
  "FIPS-validated" claim in the public surfaces that disagrees with the pin.

Why a module and not a grep: the day the pin moves off a validated version (decision D17), every
prose claim of a certificate becomes false while remaining PRESENT. Deriving the fact removes the
second copy that could be wrong; where a copy must exist (the README's status clause), it is
verified against this derivation and fails closed.

Settings-free and stdlib-only: this runs in the boot gate before Django, on a bare CI runner, and
on the host. The script is shipped in the image (`/app/docker/build-openssl-fips.sh`), so the
same reader works at boot and in a checkout.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
#: The one authoring site (req-fips-pin-currency-2: read, never restate).
PIN_SCRIPT = REPO_ROOT / "docker" / "build-openssl-fips.sh"
#: Where the built provider lives in both images.
PROVIDER_PATH = "/usr/lib/ossl-modules/fips.so"

_ASSIGN_RE = re.compile(
    r'^(OSSL_VERSION|OSSL_SHA256|OSSL_SIGNING_PRIMARY|OSSL_CMVP_VALIDATED)=("?)([^"\n]*)\2\s*$', re.M
)
_ENTRY_RE = re.compile(
    r"^(?P<version>\d+\.\d+\.\d+)=(?P<cert>\d+)/(?P<standard>140-[23])/(?P<sunset>\d{4}-\d{2}-\d{2})$"
)
#: A hand-written certificate claim, wherever prose makes one.
CLAIM_RE = re.compile(r"CMVP\s*#\s*(\d{3,5})")
#: The phrase that asserts validation without a number.
VALIDATED_PHRASE_RE = re.compile(r"FIPS-validated", re.I)


class PinsUnreadable(ValueError):
    """The pin script is absent or its format changed — the facts are NOT OBSERVABLE, never assumed."""


class Posture(StrEnum):
    """What the shipped provider IS, derived from the pin (three states, never two)."""

    #: The pinned version carries a CMVP certificate.
    VALIDATED = "fips-validated"
    #: FIPS mode on, approved-algorithms-only, built from OpenSSL's FIPS code line at a version with
    #: no certificate of its own — a recorded security-driven build (D17), never passed off as validated.
    UNVALIDATED_BUILD = "fips-mode-unvalidated-build"


@dataclass(frozen=True)
class Validation:
    """One CMVP certificate as transcribed from its own CMVP page."""

    certificate: str
    standard: str
    sunset: str  # ISO date; a past date means the certificate has sunset, not that it never existed

    def describe(self) -> str:
        return f"CMVP #{self.certificate} (FIPS {self.standard}, sunset {self.sunset})"


@dataclass(frozen=True)
class Pins:
    version: str
    sha256: str
    signing_primary: str
    validated: dict[str, Validation]

    @property
    def validation(self) -> Validation | None:
        """The certificate covering the PINNED version, or None (an unvalidated build)."""
        return self.validated.get(self.version)

    @property
    def posture(self) -> Posture:
        return Posture.VALIDATED if self.validation else Posture.UNVALIDATED_BUILD

    def status_clause(self) -> str:
        """The derived status, for the SBOM property and the README's status clause — verbatim."""
        if self.validation:
            return f"OpenSSL {self.version} FIPS provider, {self.validation.describe()}"
        nearest = ", ".join(f"{v}/#{c.certificate}" for v, c in sorted(self.validated.items()))
        return (
            f"OpenSSL {self.version} FIPS provider, not CMVP-validated as shipped "
            f"(security-driven build of the FIPS code line, decision D17; validated versions: {nearest})"
        )


def read_pins(script: Path = PIN_SCRIPT) -> Pins:
    """Parse the pins from the build script. Raises PinsUnreadable rather than guessing."""
    try:
        text = script.read_text(encoding="utf-8")
    except OSError as exc:
        raise PinsUnreadable(f"cannot read {script}: {exc}") from exc
    found = {m.group(1): m.group(3).strip() for m in _ASSIGN_RE.finditer(text)}
    missing = [
        k for k in ("OSSL_VERSION", "OSSL_SHA256", "OSSL_SIGNING_PRIMARY", "OSSL_CMVP_VALIDATED") if k not in found
    ]
    if missing:
        raise PinsUnreadable(f"{script}: could not read {', '.join(missing)} — has its format changed?")
    validated: dict[str, Validation] = {}
    for raw in found["OSSL_CMVP_VALIDATED"].split():
        m = _ENTRY_RE.match(raw)
        if m is None:
            raise PinsUnreadable(
                f"{script}: OSSL_CMVP_VALIDATED entry {raw!r} is not <version>=<cert>/<140-x>/<YYYY-MM-DD>"
            )
        validated[m["version"]] = Validation(m["cert"], m["standard"], m["sunset"])
    return Pins(found["OSSL_VERSION"], found["OSSL_SHA256"], found["OSSL_SIGNING_PRIMARY"], validated)


def check_claims(pins: Pins, paths: list[Path]) -> list[str]:
    """Every hand-written certificate claim in `paths` must agree with the derivation.

    - a `CMVP #NNNN` naming a certificate other than the pinned version's is a false claim;
    - when the pinned version is unvalidated, any `CMVP #` or "FIPS-validated" is a false claim;
    - a missing file is reported (absence is not a passing claim).
    Returns problems; empty means every claim present is true.
    """
    problems: list[str] = []
    cert = pins.validation.certificate if pins.validation else None
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append(f"{path}: not readable ({exc})")
            continue
        for n, line in enumerate(text.splitlines(), start=1):
            for claimed in CLAIM_RE.findall(line):
                if cert is None:
                    problems.append(
                        f"{path}:{n}: claims CMVP #{claimed} but OpenSSL {pins.version} is not a validated build"
                    )
                elif claimed != cert:
                    problems.append(
                        f"{path}:{n}: claims CMVP #{claimed} but OpenSSL {pins.version} is certificate #{cert}"
                    )
            if cert is None and VALIDATED_PHRASE_RE.search(line):
                problems.append(
                    f"{path}:{n}: says 'FIPS-validated' but OpenSSL {pins.version} is not a validated build"
                )
    return problems


def running_version(pins: Pins) -> tuple[str, str]:
    """The provider version to classify AGAINST at runtime, and where it came from.

    The pin says what the build was told to compile; the active provider says what is running.
    They differ whenever code is newer than the image it runs on (a dev worktree mounted into a
    published image, the lean-boot gate exercising a branch against `:latest`) — so runtime
    classification follows the ACTIVE provider (`"active"`), and falls back to the pin
    (`"pinned"`) only when no provider is observable. The mismatch itself is recorded, not hidden.
    """
    observed = observed_provider_version()
    if observed is not None:
        return observed, "active"
    return pins.version, "pinned"


_PROVIDER_BLOCK_RE = re.compile(r"^  fips\n(?:    .*\n)*?    version: (\S+)", re.M)


def observed_provider_version(run: Callable[..., subprocess.CompletedProcess[str]] | None = None) -> str | None:
    """The version the ACTIVE fips provider reports (`openssl list -providers -verbose`), or None
    when not observable (no CLI, no fips provider loaded). The pin says what we meant to ship;
    this says what shipped — tap#225 is why both are asked."""
    runner = run or subprocess.run
    try:
        proc = runner(["openssl", "list", "-providers", "-verbose"], capture_output=True, text=True, timeout=30)
    except OSError, subprocess.SubprocessError:
        return None
    if proc.returncode != 0:
        return None
    m = _PROVIDER_BLOCK_RE.search(proc.stdout)
    return m.group(1) if m else None
