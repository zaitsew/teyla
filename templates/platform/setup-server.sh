#!/usr/bin/env bash
# setup-server.sh — turn a fresh Ubuntu 24.04 box into the one shared app server.
#
# Run as root, once, over ssh:
#
#     scp setup-server.sh Caddyfile root@<host>:/root/
#     ssh root@<host> 'bash /root/setup-server.sh'
#
# Idempotent: every step checks before it acts, so a second run is a no-op and a
# half-finished first run can simply be re-run. It creates a `deploy` user carrying the
# ssh key you connected with, installs docker plus the compose plugin, closes everything
# but 22/80/443, turns on unattended security upgrades, and starts one reverse proxy that
# picks up each product's own compose file and site block from /srv/<product>/.
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
COMPOSE_ROOT="${COMPOSE_ROOT:-/srv}"
ACME_EMAIL="${ACME_EMAIL:-admin@example.com}"

log() { printf '\n== %s\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "run this as root on the server, not on your laptop" >&2
  exit 1
fi

log "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg ufw unattended-upgrades

log "docker"
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else
  echo "docker already installed: $(docker --version)"
fi
systemctl enable --now docker

log "user ${DEPLOY_USER}"
if ! id -u "${DEPLOY_USER}" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "${DEPLOY_USER}"
fi
usermod -aG docker "${DEPLOY_USER}"
install -d -m 0700 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "/home/${DEPLOY_USER}/.ssh"
if [ -f /root/.ssh/authorized_keys ]; then
  # The key you are connected with right now — so you never lock yourself out by
  # copying the wrong one.
  install -m 0600 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" \
    /root/.ssh/authorized_keys "/home/${DEPLOY_USER}/.ssh/authorized_keys"
else
  echo "WARNING: /root/.ssh/authorized_keys is absent — add a key for ${DEPLOY_USER} by hand" >&2
fi

log "firewall"
ufw allow 22/tcp  >/dev/null
ufw allow 80/tcp  >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
ufw status | sed 's/^/  /'

log "unattended upgrades"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

log "layout under ${COMPOSE_ROOT}"
install -d -m 0755 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "${COMPOSE_ROOT}"
install -d -m 0755 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "${COMPOSE_ROOT}/caddy_data" "${COMPOSE_ROOT}/caddy_config"

if [ ! -f "${COMPOSE_ROOT}/Caddyfile" ]; then
  if [ -f "$(dirname "$0")/Caddyfile" ]; then
    install -m 0644 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "$(dirname "$0")/Caddyfile" "${COMPOSE_ROOT}/Caddyfile"
  else
    cat > "${COMPOSE_ROOT}/Caddyfile" <<'EOF'
{
	email {$ACME_EMAIL}
}
import /srv/*/Caddyfile
EOF
    chown "${DEPLOY_USER}:${DEPLOY_USER}" "${COMPOSE_ROOT}/Caddyfile"
  fi
fi

# The root stack: the proxy, plus every product's own compose file. A fresh server has no
# products yet, so this starts with no `include:` at all — a glob include with nothing to
# match fails with "no such file", and that would mean Caddy never starts on a new box.
# `add-product.sh` appends one explicit `include:` entry per product, idempotently.
if [ ! -f "${COMPOSE_ROOT}/docker-compose.yml" ]; then
  cat > "${COMPOSE_ROOT}/docker-compose.yml" <<EOF
# The shared stack. One proxy; add-product.sh appends one include: entry per product
# below, each pointing at its own docker-compose.yml and Caddyfile. Never by hand.
services:
  caddy:
    image: caddy:2-alpine
    container_name: caddy
    restart: unless-stopped
    environment:
      ACME_EMAIL: \${ACME_EMAIL:-${ACME_EMAIL}}
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ${COMPOSE_ROOT}/Caddyfile:/etc/caddy/Caddyfile:ro
      - ${COMPOSE_ROOT}:/srv:ro
      - ${COMPOSE_ROOT}/caddy_data:/data
      - ${COMPOSE_ROOT}/caddy_config:/config
    networks:
      - apps

networks:
  apps:
    name: apps
    driver: bridge
EOF
  chown "${DEPLOY_USER}:${DEPLOY_USER}" "${COMPOSE_ROOT}/docker-compose.yml"
fi

log "starting the proxy"
docker network inspect apps >/dev/null 2>&1 || docker network create apps >/dev/null
( cd "${COMPOSE_ROOT}" && docker compose up -d )

log "done"
cat <<EOF
  ssh ${DEPLOY_USER}@<host>            # from now on, not root
  ${COMPOSE_ROOT}/                     # one directory per product
  bash add-product.sh <name> <port>    # add one

Point DNS at this box before the first product: an A record for
<product>.<your domain> → this host's IP. Caddy gets the certificate itself.
EOF
