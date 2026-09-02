"""FIPS validation claims derive from the pin — `spec-fips.md` (`req-fips-pin-currency-8`).

The day the OpenSSL FIPS provider pin moves to a version without a CMVP certificate (decision
D17), every prose claim of "CMVP #4282" or "FIPS-validated" in the public surfaces becomes false
while remaining present — and a present-but-false compliance claim is worse than a missing one,
because nobody goes looking for the thing the record says is handled.

So the surfaces that make the claim are checked against `tap.fips_pins` (the one derivation
from `docker/build-openssl-fips.sh`): a certificate number that disagrees with the pinned
version's, or any certificate / "FIPS-validated" claim when the pinned version is unvalidated,
fails. The README must additionally carry the derived status clause verbatim, so the public
sentence can never drift from what ships.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard

#: The surfaces that speak about the provider's validation to someone who is not reading the pin.
CLAIM_SURFACES = (
    "README.md",
    "Dockerfile",
    "docker/postgres/Dockerfile",
    "docker/sbom-supplemental.json",
    "docker/postgres/sbom-supplemental.json",
)


class FipsClaimsGuard(Guard):
    slug = "fips-validation-claims"
    map_row = "FIPS validation claims derive from the pin"
    rid = "req-fips-pin-currency-8"
    description = (
        "A hand-written certificate claim that disagrees with the pinned provider version is a false "
        "compliance statement that passes every presence check; the public surfaces are verified "
        "against the derivation and fail closed."
    )

    def check(self) -> None:
        from tap.fips_pins import check_claims, read_pins

        pins = read_pins()  # PinsUnreadable propagates: NOT OBSERVABLE is a failure, not a pass
        problems = check_claims(pins, [REPO_ROOT / rel for rel in CLAIM_SURFACES])
        try:
            readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        except OSError as exc:
            readme = ""
            problems.append(f"README.md: not readable ({exc})")
        if pins.status_clause() not in readme:
            problems.append(f"README.md does not carry the derived status clause verbatim: {pins.status_clause()!r}")
        if problems:
            raise AssertionError(
                "FIPS validation claims disagree with the pin (docker/build-openssl-fips.sh):\n  "
                + "\n  ".join(problems)
            )
