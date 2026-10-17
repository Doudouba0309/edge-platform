#!/usr/bin/env bash
# Fail if a tracked path or staged content looks like a credential.
# Deliberately checks the git index, so it works both locally and in CI.
set -euo pipefail

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "secret guard: not inside a git work tree" >&2
  exit 1
fi

status=0

while IFS= read -r -d '' file; do
  case "$file" in
    certs/*|secrets/*|*.pem|*.key|*.p12|*.pfx|*.jks|id_rsa|*/id_rsa|id_ed25519|*/id_ed25519|id_ecdsa|*/id_ecdsa|id_dsa|*/id_dsa)
      echo "secret guard: tracked secret-like path: ${file}" >&2
      status=1
      ;;
    .env|*/.env|.env.*|*/.env.*)
      case "$file" in
        .env.example|*/.env.example|.env.sample|*/.env.sample|.env.template|*/.env.template) ;;
        *)
          echo "secret guard: tracked environment file: ${file}" >&2
          status=1
          ;;
      esac
      ;;
  esac
done < <(git ls-files -z)

# Assemble the marker so this script does not match its own pattern.
marker="PRIVATE"" KEY"
pattern="-----BEGIN (RSA |EC |OPENSSH |DSA )?${marker}-----"
content_hits="$(git grep --cached -I -l -E -e "$pattern" -- . 2>/dev/null || true)"
if [ -n "$content_hits" ]; then
  while IFS= read -r hit; do
    echo "secret guard: private-key material in tracked file: ${hit}" >&2
  done <<< "$content_hits"
  status=1
fi

if [ "$status" -ne 0 ]; then
  echo "secret guard: refusing to continue with credential-like files" >&2
  exit 1
fi

count="$(git ls-files | wc -l | tr -d ' ')"
echo "secret guard: clean (${count} tracked files)"
