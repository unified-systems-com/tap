#!/bin/bash
# Bake one boot record's whole environment into a product image (req-tap-bake-product-image).
#
# Runs once, as the image's unprivileged user, inside docker/product-image.Dockerfile — never at
# container start. It does at build time what docker/entrypoint.sh otherwise does at every start:
# seed the uv cache from the image's verified wheel-cache seed, build the core venv from uv.lock,
# then install the record's plugins (tap.product_image) and prove pre-boot accepts the result.
# What it leaves behind is a venv and an install manifest; the caches it used are removed.
#
# usage: bake-product-image.sh <profile id> <tap-web image, by digest>
set -euo pipefail

profile="${1:?profile id}"
base_image="${2:?tap-web image reference, by digest}"
cd /app

export UV_CACHE_DIR
UV_CACHE_DIR="$(mktemp -d /tmp/tap-bake-uv.XXXXXX)"
trap 'rm -rf "${UV_CACHE_DIR}"' EXIT

echo "==> Verifying the wheel-cache seed against its build-time manifest..."
python3 /usr/local/lib/tap/seed_manifest.py verify /opt/uv-cache-seed /opt/uv-cache-seed.manifest.json
cp -r /opt/uv-cache-seed/. "${UV_CACHE_DIR}/"

echo "==> Building the core environment from uv.lock (uv sync --frozen --all-packages)..."
# Not --no-build: psycopg-c ships only as source and is built against the image's own libpq and
# FIPS OpenSSL, which is why the image's deps-warm stage builds it; --no-build refuses it outright
# (tried 2026-11-22). Every sdist is hash-checked against uv.lock, and its built wheel comes from
# the seed verified above, so nothing unpinned builds here. The entrypoint has run this same sync.
uv sync --frozen --all-packages  # NOSONAR (S8541) — see above

echo "==> Installing the record's plugins and writing the install manifest..."
/app/.venv/bin/python -m tap.product_image build --profile "${profile}" --base-image "${base_image}"

# Pre-boot in product-image mode, exactly as a start runs it, so a record the image cannot
# satisfy fails the build rather than the first launch. There is no database at build time.
echo "==> Checking pre-boot accepts the image..."
TAP_BOOT_INSTALL__SNAPSHOT_BEFORE_MIGRATE=false /app/.venv/bin/python -m tap.preboot --profile "${profile}" >/dev/null

# Compile once here, so no start pays for it and the read-only venv needs no __pycache__ writes.
/app/.venv/bin/python -m compileall -q -j 0 /app/.venv/lib >/dev/null
echo "==> Product image environment baked for profile '${profile}'."
