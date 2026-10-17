# syntax=docker/dockerfile:1
# Offline Greengrass V2 nucleus image for Tier 1 verification.
#
# This is deliberately separate from the collector image: the nucleus needs a
# JRE and runs as root, while the collector runs as an unprivileged process.
# The production base image will compose them once the collector is packaged as
# a Greengrass component.
FROM ubuntu:24.04@sha256:ac3a3d13e90c660a1cb3e89ec695533399f7378dc1ae5fbdc28eb5781d561594

ARG NUCLEUS_VERSION=2.18.4
ARG NUCLEUS_SHA256=9d7b620633d09180f81a6b7d31e9dd6bb53dab3c038f32d788ade6469e583d6e

ENV DEBIAN_FRONTEND=noninteractive \
    NUCLEUS_VERSION=${NUCLEUS_VERSION}

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        openjdk-17-jre-headless \
        openssl \
        procps \
        python3 \
        python3-venv \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/gg-install \
    && curl -fsSL "https://d2s8p88vqu9w66.cloudfront.net/releases/greengrass-${NUCLEUS_VERSION}.zip" \
        -o /tmp/nucleus.zip \
    && echo "${NUCLEUS_SHA256}  /tmp/nucleus.zip" | sha256sum -c - \
    && unzip -q /tmp/nucleus.zip -d /opt/gg-install \
    && rm -f /tmp/nucleus.zip \
    && test -f /opt/gg-install/lib/Greengrass.jar \
    && java -jar /opt/gg-install/lib/Greengrass.jar --version | grep -q "${NUCLEUS_VERSION}"

COPY nucleus/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# The nucleus' own local MQTT broker uses 8883 by default.
EXPOSE 8883

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD pgrep -f 'Greengrass.jar|greengrass' >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
