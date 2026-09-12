#!/usr/bin/env bash
# add-product.sh <name> <port> — give one product a home on the shared server.
#
#     bash add-product.sh notes 8080
#
# Run it on the server as the deploy user. It creates /srv/<name>/ from the fragments the
# product repo ships in deploy/droplet/ — docker-compose.fragment.yml, Caddyfile.fragment
# and .env.example — pulls the images, starts the stack and reloads the proxy. Everything
# it writes is inside /srv/<name>/, so removing a product is `docker compose down` plus
# deleting one directory.
#
# Fragments are looked for in --from <dir> (default: ./deploy/droplet). Placeholders
# {{name}}, {{port}} and {{domain}} are substituted; anything else is copied as-is.
set -euo pipefail

COMPOSE_ROOT="${COMPOSE_ROOT:-/srv}"
FROM="./deploy/droplet"
DOMAIN="${DOMAIN:-example.com}"

usage() {
  echo "usage: add-product.sh <name> <port> [--from <dir>] [--domain <domain>]" >&2
  exit 64
}

NAME=""
PORT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --from)   FROM="${2:-}"; shift 2 ;;
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    -*) echo "unknown flag: $1" >&2; usage ;;
    *)
      if [ -z "$NAME" ]; then NAME="$1"; elif [ -z "$PORT" ]; then PORT="$1"; else usage; fi
      shift ;;
  esac
done
[ -n "$NAME" ] && [ -n "$PORT" ] || usage
case "$NAME" in
  *[!a-z0-9-]*) echo "name must be lowercase letters, digits and dashes: $NAME" >&2; exit 64 ;;
esac

DEST="${COMPOSE_ROOT}/${NAME}"
ROOT_COMPOSE="${COMPOSE_ROOT}/docker-compose.yml"
render() {  # render <src> <dest> — never overwrites; a hand-edited file survives a re-run
  local src="$1" dst="$2"
  [ -f "$src" ] || { echo "  missing fragment: $src" >&2; return 1; }
  if [ -f "$dst" ]; then echo "  keeping existing $dst"; return 0; fi
  sed -e "s/{{name}}/${NAME}/g" -e "s/{{port}}/${PORT}/g" -e "s/{{domain}}/${DOMAIN}/g" "$src" > "$dst"
  echo "  wrote $dst"
}

# add_include <compose-file> — make sure the root stack's `include:` list names this
# product's compose file, exactly once. The first product on a fresh box has no
# `include:` section at all (setup-server.sh deliberately leaves it out, so Caddy can
# start with zero products); later products append to whatever is already there.
add_include() {
  local line="  - path: ${DEST}/docker-compose.yml"
  [ -f "$ROOT_COMPOSE" ] || { echo "  missing root compose: $ROOT_COMPOSE" >&2; return 1; }
  if grep -qF "$line" "$ROOT_COMPOSE"; then
    echo "  already in ${ROOT_COMPOSE}'s include list"
    return 0
  fi
  if grep -q '^include:' "$ROOT_COMPOSE"; then
    awk -v line="$line" '{ print } /^include:/ && !a { print line; a=1 }' "$ROOT_COMPOSE" > "${ROOT_COMPOSE}.tmp"
  else
    awk -v line="$line" '/^services:/ && !a { print "include:"; print line; print ""; a=1 } { print }' "$ROOT_COMPOSE" > "${ROOT_COMPOSE}.tmp"
  fi
  mv "${ROOT_COMPOSE}.tmp" "$ROOT_COMPOSE"
  echo "  added ${DEST}/docker-compose.yml to ${ROOT_COMPOSE}'s include list"
}

echo "== ${NAME} → ${DEST} (port ${PORT}, ${NAME}.${DOMAIN})"
mkdir -p "$DEST"
render "${FROM}/docker-compose.fragment.yml" "${DEST}/docker-compose.yml"
render "${FROM}/Caddyfile.fragment"          "${DEST}/Caddyfile"
add_include

if [ ! -f "${DEST}/.env" ]; then
  if [ -f "${FROM}/.env.example" ]; then
    render "${FROM}/.env.example" "${DEST}/.env"
    chmod 600 "${DEST}/.env"
    echo "  fill in ${DEST}/.env before the app will start"
  else
    : > "${DEST}/.env"
    chmod 600 "${DEST}/.env"
  fi
fi

echo "== pulling and starting"
( cd "$COMPOSE_ROOT" && docker compose pull "${NAME}" 2>/dev/null || true )
( cd "$COMPOSE_ROOT" && docker compose up -d )

echo "== reloading the proxy"
docker exec caddy caddy reload --config /etc/caddy/Caddyfile 2>/dev/null \
  || ( cd "$COMPOSE_ROOT" && docker compose restart caddy )

echo
echo "done: https://${NAME}.${DOMAIN}"
echo "  logs:   cd ${COMPOSE_ROOT} && docker compose logs -f ${NAME}"
echo "  remove: cd ${COMPOSE_ROOT} && docker compose rm -sf ${NAME} && rm -rf ${DEST}"
