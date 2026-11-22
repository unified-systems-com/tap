# A product image: tap-web plus one boot record's whole environment (req-tap-bake-product-image).
#
# Nothing in this file names a product (req-tap-bake-lifecycle-2). The build context holds one
# file, `record.boot.json`; the rest comes from the base image, including the builder itself.
#
#   docker build -f docker/product-image.Dockerfile \
#     --build-arg TAP_WEB=ghcr.io/unified-systems-com/tap-web@sha256:<digest> \
#     --build-arg PROFILE=<profile id> <directory holding record.boot.json>
#
# TAP_WEB must name the base by digest; the builder refuses a tag (req-tap-bake-product-image-1).
ARG TAP_WEB

# --- bake: build the environment as the image's unprivileged user --------------------------
FROM ${TAP_WEB} AS bake
ARG TAP_WEB
ARG PROFILE
USER root
COPY record.boot.json /app/boot/${PROFILE}.boot.json
RUN chmod 0444 /app/boot/${PROFILE}.boot.json \
 && mkdir -p /app/tap-product && chown nonroot:0 /app/tap-product
USER nonroot
RUN bash /app/docker/bake-product-image.sh "${PROFILE}" "${TAP_WEB}"

# --- final: the base plus the baked environment, owned by root ------------------------------
# Copied rather than chowned in place: a `chown -R` layer would store the whole venv a second
# time. Root ownership means the serving user cannot change what the manifest describes
# (req-tap-bake-immutable-env).
FROM ${TAP_WEB}
ARG PROFILE
COPY --from=bake --chown=root:0 /app/boot/${PROFILE}.boot.json /app/boot/${PROFILE}.boot.json
COPY --from=bake --chown=root:0 /app/.venv /app/.venv
COPY --from=bake --chown=root:0 /app/tap-product /app/tap-product
ENV TAP_BOOT_PROFILE=${PROFILE}
USER nonroot
