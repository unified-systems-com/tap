#!/bin/sh
# Build the FIPS-validated OpenSSL provider (fips.so) from verified upstream source.
#
# This is the provenance root of TAP's FIPS posture (req-cicd-supply-chain-provenance,
# tap#221). The tarball this script fetches BECOMES /usr/lib/ossl-modules/fips.so in both
# shipped images. `openssl fipsinstall` later pins the bytes we BUILT; nothing downstream
# can tell us the SOURCE was authentic — so every source gate lives here, and nowhere else.
#
# It runs in the `ossl-builder` stage of BOTH shipped Dockerfiles (the root one and
# docker/postgres/Dockerfile). One script, one set of pins: a bump cannot half-apply to one
# image and not the other (derive-a-fact-once). Before this script existed the web image
# verified its source and the DB image fetched the same tarball over bare curl with no
# integrity check at all — same fips.so, same compliance claim, two different trust stories.
#
# Why a script and not an inline RUN: this is the most security-significant operation in the
# build, and an `&&`-chained shell one-liner is the worst available place to read it, review
# it, or test it. Here each gate is a named step with its own failure message.
#
# Usage (both Dockerfiles):
#   COPY docker/openssl-release-keys.asc docker/build-openssl-fips.sh /opt/ossl/
#   RUN /opt/ossl/build-openssl-fips.sh
#
# Requires in the stage: build-base perl linux-headers curl gpg gpg-agent
# Produces: /usr/local/lib/ossl-modules/fips.so  (via `make install_fips`)
set -eu

# ---------------------------------------------------------------------------- the pins
#
# THE ONLY AUTHORING SITE for what OpenSSL source we build. Prose mentions of the version
# elsewhere (Dockerfile comments, the SBOM supplemental, the assessment record) are
# commentary or downstream declarations, not inputs to this build — and the claims that
# MATTER (whether the shipped provider is CMVP-validated, and under which certificate) are
# DERIVED from this file by tap/fips_pins.py, never restated: the crypto-BOM gate, the SBOM
# component's fips-validation property, the README's status clause and the fips-claims guard
# all read OSSL_VERSION against OSSL_CMVP_VALIDATED below. A hand-written "CMVP #NNNN" that
# disagrees with what this file says fails the guard (presence is not correctness).
#
# THE POLICY THAT MOVES THIS PIN (decision D17, docs/misc/doc-fips-assessment-record.md,
# 2026-09-02): a secure OpenSSL matters more than a validated one, read LITERALLY. A CMVP
# certificate freezes the module at the validated build; patch currency is the property this
# project will not give up; and the boundary design (D4: a frozen fips.so beside the base
# image's modern libcrypto) keeps the trade cheap, because the module is algorithms-only and
# most OpenSSL CVEs live in the libcrypto/libssl code that is already current. So the pin
# tracks the FIPS code line's patched releases, and when the pinned version carries no
# certificate the artifact is honestly declared "FIPS mode on, approved-algorithms-only, NOT
# CMVP-validated as shipped" — a distinct state, never passed off as validated. Re-pin to a
# validated version (the table below) for a build an audit needs the certificate for.
#
# What this pin therefore protects against is a CASUAL bump, never a bump: every move is a
# per-CVE triage against the shipped module (the bump-openssl-fips skill, req-fips-pin-
# currency-7 — the 2026-09 triage in docs/misc/doc-fips-provider-cve-triage-2026-09.md is
# the standing pattern) and a recorded decision. Renovate must not treat this as a normal
# dependency pin; the grype-declared-nightly lane is what watches it (tap#231, tap#294).
#
# Bumping (the bump-openssl-fips skill carries the full procedure):
#   1. Triage the advisory against the shipped fips.so (ask the binary, not the description).
#   2. Set OSSL_VERSION + OSSL_SHA256 from the release page (scripts/verify-openssl-release
#      <version> prints them — transcribe, never type).
#   3. Re-read doc/fingerprints.txt AT THE NEW TAG. If a different team member signed it,
#      replace docker/openssl-release-keys.asc and OSSL_SIGNING_PRIMARY. The key list
#      published on openssl-library.org names only CURRENTLY-ACTIVE signers and will not
#      vouch for an older release — the tag's own file is the authority.
#   4. Update the version + purl + cpe in docker/sbom-supplemental.json (both images).
#   5. If the new version has its own CMVP certificate, add it to OSSL_CMVP_VALIDATED (with
#      the certificate page as the source); otherwise the derived posture flips to the
#      unvalidated-build state and the fips-claims guard will refuse any prose still
#      claiming a certificate — fix the prose, do not silence the guard.
#
# OSSL_SHA256 and OSSL_SIGNING_PRIMARY are deliberately NOT derived from anything: a digest
# computed from the file it checks verifies nothing. They are independent assertions,
# transcribed by a human from upstream and reviewed in the diff.
OSSL_VERSION=3.0.22
OSSL_SHA256=67ebca7e50d17383028045486653492195b83db95f8558709701bb47b5c1ef81
OSSL_SIGNING_PRIMARY=B146647E45A7B33947AB226B2A2C87D161692D40

# ---------------------------------------------------------------------------- CMVP validations
#
# THE ONLY AUTHORING SITE for which OpenSSL FIPS provider versions carry a CMVP certificate.
# Each entry is <version>=<certificate>/<FIPS standard>/<sunset date>, transcribed from the
# certificate's own CMVP page (never from a vendor announcement), and is what makes the
# derived "validated as shipped?" answer TRUE rather than merely present:
#   #4282 — OpenSSL FIPS Provider 3.0.8 / 3.0.9, FIPS 140-2, Active, sunset 2026-09-21
#           https://csrc.nist.gov/projects/cryptographic-module-validation-program/certificate/4282
#   #4985 — OpenSSL FIPS Provider 3.1.2, FIPS 140-3 level 1, Active, sunset 2030-03-10
#           https://csrc.nist.gov/projects/cryptographic-module-validation-program/certificate/4985
#           (OpenSSL's own certificate; #5102 is Chainguard's rebrand of the same module)
# Observed 2026-09-02. A sunset date that has passed does NOT delete the entry: the version
# was validated; the derived posture reports the certificate as sunset.
OSSL_CMVP_VALIDATED="3.0.8=4282/140-2/2026-09-21 3.0.9=4282/140-2/2026-09-21 3.1.2=4985/140-3/2030-03-10"

# ---------------------------------------------------------------------------- layout
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
KEYFILE="${OSSL_KEYFILE:-${HERE}/openssl-release-keys.asc}"
BUILD_DIR="${OSSL_BUILD_DIR:-/build}"
TARBALL="openssl-${OSSL_VERSION}.tar.gz"
BASE_URL="https://github.com/openssl/openssl/releases/download/openssl-${OSSL_VERSION}"

# The unprivileged identity that touches the network and the signature. See step 4.
SANDBOX_USER=osslverify
SANDBOX_DIR=/ossl-sandbox        # scratch; writable ONLY by ${SANDBOX_USER}
INPUT_DIR=/ossl-input            # root-owned 0555, contents 0444 — read-only to the sandbox
RUNNER_DIR=/ossl-runner          # root-owned 0555; holds the bodies the sandbox executes

say()   { printf 'build-openssl-fips: %s\n' "$*"; }
fatal() { printf 'build-openssl-fips: FATAL: %s\n' "$*" >&2; exit 1; }

[ -r "${KEYFILE}" ] || fatal "release key not readable at ${KEYFILE}"

# ---------------------------------------------------------------------------- 1. the sandbox
#
# Everything that parses bytes we did not write — the TLS session, the HTTP response, the
# OpenPGP signature packet — runs as this user, never as root. `adduser -S -D -H` makes a
# system account with no password and no home directory of its own.
addgroup -S "${SANDBOX_USER}" 2>/dev/null || true
adduser -S -D -H -G "${SANDBOX_USER}" "${SANDBOX_USER}" 2>/dev/null || true
id -u "${SANDBOX_USER}" >/dev/null 2>&1 || fatal "could not create sandbox user ${SANDBOX_USER}"

rm -rf "${SANDBOX_DIR}" "${INPUT_DIR}" "${RUNNER_DIR}"
install -d -m 0700 -o "${SANDBOX_USER}" -g "${SANDBOX_USER}" "${SANDBOX_DIR}"
install -d -m 0555 "${RUNNER_DIR}"

# Run a body script as ${SANDBOX_USER} with --no-new-privs, which makes the kernel ignore
# setuid bits and file capabilities for the whole subtree — so even a setuid binary reachable
# in this stage cannot be used to climb back to root.
#
# The body is a FILE, not an interpolated string. Nesting a command inside `su -c "... sh -c
# '...'"` means three levels of quoting, and a single quote in the payload silently rewrites
# the command instead of failing — an unreadable construct in the one script that most needs
# to be readable. Bodies are written by root into a 0555 directory as 0444 files, so the
# sandbox user can execute them and cannot edit them.
sandboxed() {
    su -s /bin/sh "${SANDBOX_USER}" -c "setpriv --no-new-privs /bin/sh ${RUNNER_DIR}/$1"
}
write_body() {
    _b="${RUNNER_DIR}/$1"
    cat > "${_b}"
    chmod 0444 "${_b}"
}

# A one-line self-test of the mechanism itself. If `su` or `setpriv` were ever to stop
# dropping privilege — a busybox change, a missing applet, a base-image swap — every step
# below would silently run as root and still SUCCEED, so nothing downstream would notice.
# This is the only thing standing between "confined" and "believed to be confined".
write_body selftest.sh <<'SELFTEST'
id -u
SELFTEST
_sandbox_uid=$(sandboxed selftest.sh) || fatal "sandbox self-test could not run"
[ "${_sandbox_uid}" != "0" ] \
    || fatal "sandbox self-test ran as uid 0 — privilege drop is NOT in effect. Refusing to
    fetch or verify anything unconfined."
say "sandbox active: ${SANDBOX_USER} (uid ${_sandbox_uid}), --no-new-privs"

# ---------------------------------------------------------------------------- 2. fetch
#
# --proto '=https' --tlsv1.2 refuse a plaintext or downgraded redirect; -f makes an HTTP
# error a non-zero exit rather than a saved error page. Neither is integrity — that is
# steps 3 and 4 — they only keep the fetch from being trivially redirected.
say "fetching ${BASE_URL}/${TARBALL} (+ .asc) as ${SANDBOX_USER}"
write_body fetch.sh <<EOF
set -eu
cd ${SANDBOX_DIR}
curl -fsSL --proto '=https' --tlsv1.2 -o ${TARBALL}     ${BASE_URL}/${TARBALL}
curl -fsSL --proto '=https' --tlsv1.2 -o ${TARBALL}.asc ${BASE_URL}/${TARBALL}.asc
EOF
sandboxed fetch.sh || fatal "download failed"

# ---------------------------------------------------------------------------- 3. gate one: digest
#
# Checked FIRST and by coreutils, not by gpg: from here on the bytes are pinned, so a
# compromised signature verifier in step 4 cannot swap the tarball for another one.
say "verifying sha256 against the pin"
( cd "${SANDBOX_DIR}" && printf '%s  %s\n' "${OSSL_SHA256}" "${TARBALL}" | sha256sum -c - ) \
    || fatal "sha256 mismatch for ${TARBALL} — expected ${OSSL_SHA256}. The bytes served are
    not the bytes we pinned. Do NOT bump the pin to match: confirm upstream first."

# ---------------------------------------------------------------------------- 4. gate two: signature
#
# Independent of the digest: the digest proves we got the bytes we expected, the signature
# proves those bytes are the ones OpenSSL published. A pin transcribed from a compromised
# release page would pass step 3 and fail here.
#
# CONFINEMENT. This is the step where an attacker-supplied file is parsed by a large C
# program with a long CVE history, so it gets the tightest box the stage can build:
#
#   * unprivileged uid + --no-new-privs (step 1), proven by the self-test, not assumed;
#   * inputs are root-owned 0444 inside a root-owned 0555 directory — gpg can READ the
#     tarball, signature and key and can modify NONE of them, so it cannot tamper with the
#     source tree that step 5 compiles;
#   * a throwaway GNUPGHOME holding only the committed key, with TMPDIR pointed inside it —
#     the only path gpg can write is one deleted before the compiler runs;
#   * --no-options ignores every gpg.conf on the system; --no-autostart and
#     --no-auto-key-retrieve keep dirmngr from launching, so an honest gpg makes no network
#     request and cannot be steered into fetching a key an attacker chose.
#
# What this does NOT defend against, stated plainly: a genuinely backdoored gpg binary can
# print a VALIDSIG line it did not earn. Confinement bounds what a compromised verifier can
# DO to the image; it cannot make a liar's verdict true. The defence against that is step 3's
# digest, which gpg never touches.
#
# THE ASSERTION. VALIDSIG's first field is the signing SUBKEY (64ED7B1DCCE71CB2 for 3.0.22; 527466A21CA79E6D signed 3.0.9)
# and its LAST field is the PRIMARY. doc/fingerprints.txt lists PRIMARIES, so the primary is
# what we assert — comparing the subkey against that list makes an authorized key look
# unlisted. Asserting the fingerprint (rather than trusting keyring membership, which is all
# `gpgv` does) pins the identity OpenSSL publishes as authoritative; it is also the only form
# available here, since Wolfi's `gpg` package ships no `gpgv` binary.
say "verifying the detached PGP signature (primary ${OSSL_SIGNING_PRIMARY})"
install -d -m 0555 "${INPUT_DIR}"
install -m 0444 "${SANDBOX_DIR}/${TARBALL}"     "${INPUT_DIR}/${TARBALL}"
install -m 0444 "${SANDBOX_DIR}/${TARBALL}.asc" "${INPUT_DIR}/${TARBALL}.asc"
install -m 0444 "${KEYFILE}"                    "${INPUT_DIR}/release-keys.asc"

_gpghome="${SANDBOX_DIR}/gnupg"
write_body verify.sh <<EOF
set -eu
umask 077
mkdir -p ${_gpghome}
export TMPDIR=${_gpghome}
_gpg="gpg --no-options --homedir ${_gpghome} --batch --no-autostart --no-auto-key-retrieve"
\${_gpg} --quiet --import ${INPUT_DIR}/release-keys.asc
\${_gpg} --status-fd 1 --verify ${INPUT_DIR}/${TARBALL}.asc ${INPUT_DIR}/${TARBALL} 2>/dev/null
EOF
status=$(sandboxed verify.sh) || fatal "gpg exited non-zero verifying ${TARBALL}.asc"

printf '%s\n' "${status}" \
    | grep -qE "^\[GNUPG:\] VALIDSIG [0-9A-F]{40} .* ${OSSL_SIGNING_PRIMARY}\$" \
    || fatal "no VALIDSIG line naming authorized primary ${OSSL_SIGNING_PRIMARY}.
    gpg said:
${status}"

# The box is torn down before a compiler is ever invoked: nothing gpg could have written
# survives into the build.
rm -rf "${_gpghome}" "${INPUT_DIR}" "${RUNNER_DIR}"

# ---------------------------------------------------------------------------- 5. build
#
# Both gates have passed; from here the bytes are trusted and the work is an ordinary build.
# enable-fips builds the FIPS provider; install_fips installs fips.so (and nothing else).
say "both gates passed — building the FIPS provider"
mkdir -p "${BUILD_DIR}"
tar -xf "${SANDBOX_DIR}/${TARBALL}" -C "${BUILD_DIR}"
rm -rf "${SANDBOX_DIR}"

cd "${BUILD_DIR}/openssl-${OSSL_VERSION}"
./Configure enable-fips
make -j"$(nproc)"
make install_fips

# Derived, not restated: what this build IS, read from the table above.
cmvp_entry=""
for entry in ${OSSL_CMVP_VALIDATED}; do
    case "${entry}" in
        "${OSSL_VERSION}="*) cmvp_entry="${entry#*=}" ;;
        *) ;;  # another validated version — not the one pinned
    esac
done
if [ -n "${cmvp_entry}" ]; then
    cmvp_rest="${cmvp_entry#*/}"
    say "OpenSSL ${OSSL_VERSION} FIPS provider installed — CMVP #${cmvp_entry%%/*} (FIPS ${cmvp_rest%%/*}, sunset ${cmvp_rest#*/})"
else
    say "OpenSSL ${OSSL_VERSION} FIPS provider installed — NOT CMVP-validated as shipped (security-driven build of the FIPS code line; decision D17)"
fi
say "  source:  ${BASE_URL}/${TARBALL}"
say "  sha256:  ${OSSL_SHA256}"
say "  signer:  ${OSSL_SIGNING_PRIMARY}"
