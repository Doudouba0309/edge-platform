# syntax=docker/dockerfile:1
# Tier 1 base image: one boring Ubuntu 24.04 userland for arm64 and x86_64.
# The base digest is pinned; dependency installation is the only network step.
FROM ubuntu:24.04@sha256:ac3a3d13e90c660a1cb3e89ec695533399f7378dc1ae5fbdc28eb5781d561594

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PATH="/opt/venv/bin:${PATH}"

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates \
        python3 \
        python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv

WORKDIR /build
COPY pyproject.toml README.md constraints.txt ./
COPY src ./src
RUN pip install --no-cache-dir --retries 5 --timeout 60 -c constraints.txt . \
    && rm -rf /build

RUN mkdir -p /home/edge /var/lib/edge-platform /etc/edge-platform \
    && chown -R 10001:10001 /home/edge /var/lib/edge-platform /etc/edge-platform

USER 10001:10001
WORKDIR /home/edge

EXPOSE 8081
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/healthz', timeout=2)"

ENTRYPOINT ["edge-collector", "--config", "/etc/edge-platform/collector.yaml"]
