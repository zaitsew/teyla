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
# The ssh key list is re-read right before the droplet is created, not once at the top —
# a key imported seconds earlier must be on the droplet, not missing from it because this
# script cached an older list. It also refuses to create the droplet when this machine's
# own key (~/.ssh/id_ed25519.pub or id_rsa.pub) is not among the account's keys, so you are
# never locked out of a box you just paid for; pass --no-local-key to skip that check.
#
# Exits 2 — before touching anything — when doctl is absent or the token is unset, saying
# which one it was and how to fix it. That is the only failure mode worth scripting around.
set -euo pipefail

MANIFEST="${TEYLA_PLATFORM:-$HOME/.teyla/platform.toml}"
REGION="${REGION:-fra1}"
SIZE="${SIZE:-s-1vcpu-2gb}"
IMAGE="${IMAGE:-ubuntu-24-04-x64}"
YES=0
NO_LOCAL_KEY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --yes)          YES=1; shift ;;
    --no-local-key) NO_LOCAL_KEY=1; shift ;;
    --manifest)     MANIFEST="${2:-}"; shift 2 ;;
    --region)       REGION="${2:-}"; shift 2 ;;
    --size)         SIZE="${2:-}"; shift 2 ;;
    -h|--help)      sed -n '2,18p' "$0"; exit 0 ;;
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

# list_ssh_keys — "ID NAME FINGERPRINT" per line, one doctl call, always freshly read.
list_ssh_keys() {
  doctl compute ssh-key list --format ID,Name,FingerPrint --no-header
}

# local_key_path — the first public key this machine has, or nothing.
local_key_path() {
  local pub
  for pub in "$HOME/.ssh/id_ed25519.pub" "$HOME/.ssh/id_rsa.pub"; do
    if [ -f "$pub" ]; then echo "$pub"; return 0; fi
  done
  return 1
}

# local_key_fingerprint — this machine's key, in the same MD5 colon-hex form doctl reports.
local_key_fingerprint() {
  local pub
  pub="$(local_key_path)" || return 1
  ssh-keygen -E md5 -lf "$pub" 2>/dev/null | awk '{print $2}' | sed 's/^MD5://'
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

PREVIEW_KEYS="$(list_ssh_keys)"
if [ -z "$PREVIEW_KEYS" ]; then
  echo "MISSING: no ssh key on the DigitalOcean account — add yours at" >&2
  echo "         https://cloud.digitalocean.com/account/security (or: doctl compute ssh-key import)" >&2
  exit 2
fi
PREVIEW_NAMES="$(printf '%s\n' "$PREVIEW_KEYS" | awk '{print $2}' | paste -sd, -)"

echo "would create: ${NAME}  ${SIZE}  ${IMAGE}  ${REGION}  ssh keys: ${PREVIEW_NAMES}"
if [ "$YES" -ne 1 ]; then
  echo
  echo "nothing created. Re-run with --yes to create it."
  exit 0
fi

# Re-read the key list right here, immediately before create — not the list read above,
# which can be seconds stale if a key was just imported. Same for the local-key check: it
# has to run against the list that is about to be installed, not an earlier one.
KEYS="$(list_ssh_keys)"
if [ -z "$KEYS" ]; then
  echo "MISSING: no ssh key on the DigitalOcean account — add yours at" >&2
  echo "         https://cloud.digitalocean.com/account/security (or: doctl compute ssh-key import)" >&2
  exit 2
fi
KEY_IDS="$(printf '%s\n' "$KEYS" | awk '{print $1}' | paste -sd, -)"
KEY_NAMES="$(printf '%s\n' "$KEYS" | awk '{print $2}' | paste -sd, -)"
echo "installing ssh key(s): ${KEY_NAMES}"

if [ "$NO_LOCAL_KEY" -ne 1 ]; then
  LOCAL_PUB="$(local_key_path || true)"
  if [ -z "$LOCAL_PUB" ]; then
    echo "MISSING: no local ssh key (~/.ssh/id_ed25519.pub or id_rsa.pub) — generate one with" >&2
    echo "         ssh-keygen -t ed25519, import it, then re-run (or pass --no-local-key to skip this)" >&2
    exit 2
  fi
  LOCAL_FP="$(local_key_fingerprint || true)"
  if [ -z "$LOCAL_FP" ] || ! printf '%s\n' "$KEYS" | awk '{print $3}' | grep -qxF "$LOCAL_FP"; then
    echo "MISSING: this machine's key (${LOCAL_PUB}, fingerprint ${LOCAL_FP:-unknown}) is not on the" >&2
    echo "         DigitalOcean account — import it: doctl compute ssh-key import $(whoami) --public-key-file ${LOCAL_PUB}" >&2
    echo "         then re-run, or pass --no-local-key to create the droplet without it (you will" >&2
    echo "         need another key or the DO web console to get in)" >&2
    exit 2
  fi
fi

EXISTING_ID="$(doctl compute droplet list --format ID,Name --no-header | awk -v n="$NAME" '$2==n{print $1; exit}')"
if [ -n "$EXISTING_ID" ]; then
  echo "already exists: ${NAME} (id ${EXISTING_ID})"
  DROPLET_ID="$EXISTING_ID"
  IP=""
else
  read -r DROPLET_ID IP < <(doctl compute droplet create "$NAME" \
    --size "$SIZE" --image "$IMAGE" --region "$REGION" \
    --ssh-keys "$KEY_IDS" --enable-monitoring --wait \
    --format ID,PublicIPv4 --no-header)
fi

# Look the droplet up by ID from here on, never by name — the name index can 404 for
# ~20s right after creation even though the droplet itself already exists.
if [ -z "$IP" ]; then
  for _ in 1 2 3 4 5; do
    IP="$(doctl compute droplet get "$DROPLET_ID" --format PublicIPv4 --no-header 2>/dev/null || true)"
    [ -n "$IP" ] && break
    sleep 4
  done
fi
if [ -z "$IP" ]; then
  echo "created ${NAME} (id ${DROPLET_ID}) but no IP yet — check: doctl compute droplet get ${DROPLET_ID}" >&2
  exit 1
fi

echo
echo "created ${NAME} at ${IP}"
echo
echo "next, in order:"
if [ -n "$DOMAIN" ]; then
  echo "  1. DNS: add an A record for each product, e.g.  <product>.${DOMAIN}  ->  ${IP}"
  echo "     (a wildcard  *.${DOMAIN} -> ${IP}  covers every product with one record — a"
  echo "     convenience, not a requirement, and it also means every subdomain resolves,"
  echo "     whether you meant it to or not)"
else
  echo "  1. DNS: add an A record for each product, e.g.  <product>.<your domain>  ->  ${IP}"
  echo "     (a wildcard *.<your domain> -> ${IP} covers every product with one record, at"
  echo "     the cost of resolving every subdomain whether you meant it to or not)"
fi
echo "  2. scp setup-server.sh Caddyfile root@${IP}:/root/ && ssh root@${IP} 'bash /root/setup-server.sh'"
echo "  3. put the IP in your platform manifest:  host = \"${IP}\"  in ${MANIFEST}"
echo "  4. ssh ${SSH_USER}@${IP} and add the first product with add-product.sh"
