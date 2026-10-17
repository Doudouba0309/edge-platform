#!/usr/bin/env bash
# Generate a local test CA plus server/client certificates for the smoke test.
# These are throwaway credentials for localhost only. certs/ is git-ignored.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERT_DIR="${ROOT}/certs"
: "${CERT_DIR:?}"
mkdir -p "$CERT_DIR"
rm -f \
  "$CERT_DIR/ca.crt" "$CERT_DIR/ca.key" \
  "$CERT_DIR/server.crt" "$CERT_DIR/server.key" \
  "$CERT_DIR/client.crt" "$CERT_DIR/client.key" \
  "$CERT_DIR/server.csr" "$CERT_DIR/client.csr" \
  "$CERT_DIR/server.ext" "$CERT_DIR/client.ext" \
  "$CERT_DIR/ca.srl"

cd "$CERT_DIR"

openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 3650 \
  -keyout ca.key -out ca.crt \
  -subj "/CN=edge-platform-test-ca" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" >/dev/null 2>&1

openssl req -new -newkey rsa:2048 -nodes -sha256 \
  -keyout server.key -out server.csr \
  -subj "/CN=localhost" >/dev/null 2>&1
cat > server.ext <<'EOF'
subjectAltName=DNS:localhost,IP:127.0.0.1
extendedKeyUsage=serverAuth
EOF
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 3650 -sha256 -extfile server.ext >/dev/null 2>&1

openssl req -new -newkey rsa:2048 -nodes -sha256 \
  -keyout client.key -out client.csr \
  -subj "/CN=dev-gateway-01" >/dev/null 2>&1
cat > client.ext <<'EOF'
extendedKeyUsage=clientAuth
EOF
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out client.crt -days 3650 -sha256 -extfile client.ext >/dev/null 2>&1

rm -f server.csr client.csr server.ext client.ext ca.srl
# The Mosquitto container runs as an unprivileged user; these are localhost-only
# test credentials, so make them readable and keep the whole directory ignored.
chmod 644 ca.crt ca.key server.crt server.key client.crt client.key

echo "test certificates written to ${CERT_DIR}"
