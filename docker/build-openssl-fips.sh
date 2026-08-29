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
# THE ONLY AUTHORING SITE for what OpenSSL source we build. Prose mentions of "3.0.9"
# elsewhere (Dockerfile comments, the SBOM supplemental, the assessment record) are
# commentary or downstream declarations, not inputs to this build.
#
# 3.0.9 is FROZEN ON PURPOSE, not stale. It is the version CMVP validated as module #4282;
# a newer OpenSSL is a DIFFERENT module and would leave the validated boundary. The frozen
# provider runs against the base image's modern libcrypto, which OpenSSL supports by design
# (a certified fips.so is forward-compatible with any later libcrypto — decision D4 in
# docs/misc/doc-fips-assessment-record.md). So this pin does not age out the way a normal
# dependency pin does, and Renovate must not treat it as one. What CAN change is whether
# #4282 is still an ACTIVE certificate and whether 3.0.9's provider code has an unfixed
# advisory — a certificate question, not a version question. See tap#231.
#
# THE EXIT RAMP IS REAL, AND IT IS NOT "NEVER". A critical vulnerability in the provider is a
# sanctioned reason to move off the validated version: federal guidance treats patching a
# serious flaw as the higher duty, and CMVP has documented paths for security-relevant changes
# (confirm the CURRENT path before relying on it — the specific scenario numbering moves).
# "We could not patch, we were validated" is not a defensible position. So what this pin
# protects against is a CASUAL bump, never a bump. Moving for a critical CVE is a named,
# recorded decision, and the machinery below exists to make that decision cheap to execute
# once it is made — not to make it hard to reach.
#
# WHAT THIS MEANS FOR DETECTION: because a real CVE must be actionable, we need to SEE one.
# Nothing does today. Renovate cannot (no manager parses this file, and no advisory feed keys
# on a tarball we compile ourselves), and Trivy cannot (fips.so is not in any package database
# — this is the "invisible to every scanner" line in docker/sbom-supplemental.json, meant as a
# reason to DECLARE it and not yet cashed in). tap#231 carries the fix: a CPE on the SBOM
# component, so the artifact is legible to the vocabulary vulnerability scanners actually
# speak. Freezing the version and not watching for its CVEs is the combination to avoid.
#
# Bumping (a deliberate re-validation decision, never a routine version bump):
#   1. Confirm the target version has its OWN CMVP certificate — OR record that this is a
#      security-driven move under the exit ramp above, naming the CVE and who decided.
#   2. Set OSSL_VERSION + OSSL_SHA256 from the release page.
#   3. Re-read doc/fingerprints.txt AT THE NEW TAG. If a different team member signed it,
#      replace docker/openssl-release-keys.asc and OSSL_SIGNING_PRIMARY. The key list
#      published on openssl-library.org names only CURRENTLY-ACTIVE signers and will not
#      vouch for an older release — the tag's own file is the authority.
#   4. Update the version + purl in docker/sbom-supplemental.json (both images).
#
# OSSL_SHA256 and OSSL_SIGNING_PRIMARY are deliberately NOT derived from anything: a digest
# computed from the file it checks verifies nothing. They are independent assertions,
# transcribed by a human from upstream and reviewed in the diff.
OSSL_VERSION=3.0.9
OSSL_SHA256=eb1ab04781474360f77c318ab89d8c5a03abc38e63d65a603cabbf1b00a1dc90
OSSL_SIGNING_PRIMARY=A21FAB74B0088AA361152586B8EF1A6BA9DA2D5C

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
# THE ASSERTION. VALIDSIG's first field is the signing SUBKEY (527466A21CA79E6D for 3.0.9)
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

say "OpenSSL ${OSSL_VERSION} FIPS provider installed (CMVP #4282)"
say "  source:  ${BASE_URL}/${TARBALL}"
say "  sha256:  ${OSSL_SHA256}"
say "  signer:  ${OSSL_SIGNING_PRIMARY}"
