#!/usr/bin/env bash
# Publishes site/public to teyla.dev with the wrangler login on this machine.
# `npx wrangler login` once if it says you are not signed in.
set -euo pipefail
cd "$(dirname "$0")"
npx --yes wrangler@4 deploy
