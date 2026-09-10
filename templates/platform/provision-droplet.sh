#!/usr/bin/env bash
# provision-droplet.sh — create the one shared server, from the values in platform.toml.
#
#     bash provision-droplet.sh            # says exactly what it would do, creates nothing
#     bash provision-droplet.sh --yes      # creates it
#
# It reads ~/.teyla/platform.toml for the provider, the droplet name and the token's env
# var name, reads that token from the secrets file named in [secrets], and creates one
# s-1vcpu-2gb Ubuntu 24.04 droplet with every ssh key on the account. Then it waits for an
# IP and prints the two things you must do next: the DNS record, and setup-server.sh.
#
# Exits 2 — before touching anything — when doctl is absent or the token is unset, saying
# which one it was and how to fix it. That is the only failure mode worth scripting around.
set -euo pipefail

MANIFEST="${TEYLA_PLATFORM:-$HOME/.teyla/platform.toml}"
REGION="${REGION:-fra1}"
SIZE="${SIZE:-s-1vcpu-2gb}"
IMAGE="${IMAGE:-ubuntu-24-04-x64}"
YES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --yes)      YES=1; shift ;;
    --manifest) MANIFEST="${2:-}"; shift 2 ;;
    --region)   REGION="${2:-}"; shift 2 ;;
    --size)     SIZE="${2:-}"; shift 2 ;;
    -h|--help)  sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 64 ;;
  esac
done

# tomlish <section> <key> — the value of key inside [section]. Enough TOML for a flat
# manifest of strings and booleans; anything richer belongs in Python, not here.
tomlish() {
  [ -f "$MANIFEST" ] || return 0
  awk -v section="[$1]" -v key="$2" '
    /^\[/ { in_section = ($0 == section); next }
    in_section {
      line = $0
      sub(/#.*$/, "", line)
      split(line, kv, "=")
      k = kv[1]; gsub(/[ \t]/, "", k)
      if (k == key) {
        v = substr(line, index(line, "=") + 1)
        gsub(/^[ \t]+|[ \t]+$/, "", v)
        gsub(/^"|"$/, "", v)
        print v
        exit
      }
    }' "$MANIFEST"
}

NAME="$(tomlish server name)";        NAME="${NAME:-apps-1}"
TOKEN_ENV="$(tomlish server token_env)"; TOKEN_ENV="${TOKEN_ENV:-DIGITALOCEAN_ACCESS_TOKEN}"
SSH_USER="$(tomlish server ssh_user)"; SSH_USER="${SSH_USER:-deploy}"
DOMAIN="$(tomlish domain name)"
SECRETS="$(tomlish secrets file)";     SECRETS="${SECRETS:-$HOME/.config/teyla/platform.env}"
SECRETS="${SECRETS/#\~/$HOME}"

missing=0
if ! command -v doctl >/dev/null 2>&1; then
  echo "MISSING: doctl — install it: brew install doctl" >&2
  missing=1
fi
TOKEN="$(printenv "$TOKEN_ENV" || true)"
if [ -z "$TOKEN" ] && [ -f "$SECRETS" ]; then
  TOKEN="$(sed -n "s/^[[:space:]]*\(export[[:space:]]\+\)\?${TOKEN_ENV}=//p" "$SECRETS" | head -n1 | tr -d '"'"'"'')"
fi
if [ -z "$TOKEN" ]; then
  echo "MISSING: ${TOKEN_ENV} — create a token at https://cloud.digitalocean.com/account/api/tokens" >&2
  echo "         then add it as ${TOKEN_ENV}= in ${SECRETS} (mode 600)" >&2
  missing=1
fi
[ "$missing" -eq 0 ] || exit 2
export DIGITALOCEAN_ACCESS_TOKEN="$TOKEN"

KEY_IDS="$(doctl compute ssh-key list --format ID --no-header | paste -sd, -)"
if [ -z "$KEY_IDS" ]; then
  echo "MISSING: no ssh key on the DigitalOcean account — add yours at" >&2
  echo "         https://cloud.digitalocean.com/account/security (or: doctl compute ssh-key import)" >&2
  exit 2
fi

echo "would create: ${NAME}  ${SIZE}  ${IMAGE}  ${REGION}  ssh keys: ${KEY_IDS}"
if [ "$YES" -ne 1 ]; then
  echo
  echo "nothing created. Re-run with --yes to create it."
  exit 0
fi

if doctl compute droplet get "$NAME" >/dev/null 2>&1; then
  echo "already exists: ${NAME}"
else
  doctl compute droplet create "$NAME" \
    --size "$SIZE" --image "$IMAGE" --region "$REGION" \
    --ssh-keys "$KEY_IDS" --enable-monitoring --wait >/dev/null
fi

IP="$(doctl compute droplet get "$NAME" --format PublicIPv4 --no-header)"
echo
echo "created ${NAME} at ${IP}"
echo
echo "next, in order:"
echo "  1. DNS: an A record  ${DOMAIN:+*.$DOMAIN}${DOMAIN:-<product>.<your domain>}  ->  ${IP}"
echo "  2. scp setup-server.sh Caddyfile root@${IP}:/root/ && ssh root@${IP} 'bash /root/setup-server.sh'"
echo "  3. put the IP in your platform manifest:  host = \"${IP}\"  in ${MANIFEST}"
echo "  4. ssh ${SSH_USER}@${IP} and add the first product with add-product.sh"
