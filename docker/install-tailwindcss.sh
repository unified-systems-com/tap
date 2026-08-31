#!/usr/bin/env bash
# Install the pinned tailwindcss standalone binary into a cache volume,
# verifying its SHA-256 against the manifest-pinned checksum BEFORE installing.
#
# Implements:
#   req-grid-thirdparty-manifest.sec-9  (build-time component recorded in manifest)
#   req-grid-thirdparty-manifest.sec-10 (build-time integrity verification)
# See: tap_grid/specs/spec-grid-security.md
#      tap_web/specs/spec-web-tailwind-pipeline.md
#
# Runs INSIDE the web container — invoked by the `/tailwind-rebuild` skill on
# demand, not at image build time. The binary is installed into /opt/tailwind/
# which is backed by a named Docker volume (`tailwind_bin`, see
# docker-compose.yml), so the first invocation downloads + verifies and
# subsequent invocations short-circuit. The binary lives in Docker's internal
# volume storage; nothing executes on the host.
#
# The manifest at tap_web/third_party_manifest.toml is the single source of
# truth for the expected hashes. This script grep-extracts the relevant
# per-arch line — no TOML parser shipped in the slim base image, so the
# extraction is intentionally simple (one-key-per-line layout in the
# manifest is the readable shape and also the grep-friendly shape).
#
# Required env:
#   TAILWIND_VERSION  — must match the manifest entry's `version`
# Detected at runtime:
#   ARCH from `dpkg --print-architecture` (amd64 → linux-x64, arm64 → linux-arm64)
# Output:
#   /opt/tailwind/tailwindcss (mode 0755)

set -euo pipefail

VERSION="${TAILWIND_VERSION:-3.4.17}"
MANIFEST=/app/tap_web/third_party_manifest.toml
INSTALL_PATH=/opt/tailwind/tailwindcss

if [ ! -f "${MANIFEST}" ]; then
    echo "install-tailwindcss: manifest not found at ${MANIFEST}" >&2
    exit 1
fi

ARCH=$(dpkg --print-architecture)
case "${ARCH}" in
    amd64) PLATFORM_DASHED="linux-x64";  KEY="checksum_sha256_linux_x64"  ;;
    arm64) PLATFORM_DASHED="linux-arm64"; KEY="checksum_sha256_linux_arm64" ;;
    *) echo "install-tailwindcss: unsupported arch '${ARCH}'" >&2; exit 1 ;;
esac

# Pull the expected hash out of the manifest. We scope the match by also
# requiring the surrounding `[[component]]` block to mention tailwindcss —
# otherwise a future entry could accidentally collide on the same key name.
EXPECTED=$(awk -v key="${KEY}" '
    /^\[\[component\]\]/ { in_block=0; is_tw=0 }
    /^name *= *"tailwindcss"/ { is_tw=1 }
    is_tw && $0 ~ "^"key" *=" {
        match($0, /"[0-9a-fA-F]+"/);
        if (RSTART > 0) print substr($0, RSTART+1, RLENGTH-2);
        exit
    }
' "${MANIFEST}")

if [ -z "${EXPECTED}" ]; then
    echo "install-tailwindcss: no ${KEY} found for tailwindcss in ${MANIFEST}" >&2
    exit 1
fi

# Idempotency short-circuit: if the binary is already present at the install
# path AND its SHA-256 matches the manifest, skip the download. This is what
# makes repeat skill invocations cheap (no network, no curl, no sha256sum on
# 40MB) while still re-verifying integrity each time. A cache-poisoned binary
# would fail the checksum check and trigger a fresh download below.
if [ -x "${INSTALL_PATH}" ]; then
    CACHED=$(sha256sum "${INSTALL_PATH}" | cut -d' ' -f1)
    if [ "${CACHED}" = "${EXPECTED}" ]; then
        echo "install-tailwindcss: cached binary at ${INSTALL_PATH} verified (sha256=${CACHED}), skipping download"
        exit 0
    fi
    echo "install-tailwindcss: cached binary checksum mismatch — re-downloading"
    echo "  cached:           ${CACHED}"
    echo "  manifest expects: ${EXPECTED}"
fi

URL="https://github.com/tailwindlabs/tailwindcss/releases/download/v${VERSION}/tailwindcss-${PLATFORM_DASHED}"
TMP=$(mktemp)
trap "rm -f '${TMP}'" EXIT

echo "install-tailwindcss: downloading ${URL}"
# --proto '=https' --tlsv1.2: -L follows redirects, and without --proto a 302 to
# http:// is followed in the clear (SonarCloud shell:S6506). The SHA-256 check below
# already defeats a swapped payload; this closes the transport itself.
curl -fsSL --proto '=https' --tlsv1.2 -o "${TMP}" "${URL}"

ACTUAL=$(sha256sum "${TMP}" | cut -d' ' -f1)

if [ "${ACTUAL}" != "${EXPECTED}" ]; then
    echo "install-tailwindcss: SHA-256 mismatch for tailwindcss-${PLATFORM_DASHED}" >&2
    echo "  manifest expects: ${EXPECTED}" >&2
    echo "  downloaded:       ${ACTUAL}" >&2
    echo "  manifest path:    ${MANIFEST}" >&2
    echo "  url:              ${URL}" >&2
    exit 1
fi

mkdir -p "$(dirname "${INSTALL_PATH}")"
install -m 0755 "${TMP}" "${INSTALL_PATH}"
echo "install-tailwindcss: tailwindcss v${VERSION} (${PLATFORM_DASHED}) installed at ${INSTALL_PATH}, sha256=${ACTUAL}"
"${INSTALL_PATH}" --help > /dev/null
