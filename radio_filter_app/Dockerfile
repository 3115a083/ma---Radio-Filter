# Isolated Music Assistant image; no scripts or packages downloaded from this repo at build time.
# Update this upstream release tag only after review and CI validation.
FROM ghcr.io/music-assistant/server:2.10.6

ARG BUILD_VERSION=0.1.0
ARG BUILD_ARCH=amd64
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}" \
      org.opencontainers.image.source="https://github.com/3115a083/ma---Radio-Filter"

COPY radio_filter/ /tmp/radio_filter/
RUN set -eu; \
    SITE_PACKAGES="$(/app/venv/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"; \
    PROVIDER_PATH="${SITE_PACKAGES}/music_assistant/providers/radio_filter"; \
    mkdir -p "${PROVIDER_PATH}"; \
    cp -R /tmp/radio_filter/. "${PROVIDER_PATH}/"; \
    /app/venv/bin/python -m compileall -q "${PROVIDER_PATH}"; \
    rm -rf /tmp/radio_filter
