#!/bin/sh
# Starts `teyla mcp` for the plugin's .mcp.json. An app started from the Dock has a short PATH
# without ~/.local/bin, where `uv tool install` puts teyla, so look there too, as the hooks do.
for t in "$(command -v teyla 2>/dev/null)" "$HOME/.local/bin/teyla"; do
  [ -n "$t" ] && [ -x "$t" ] && exec "$t" mcp
done
echo "teyla mcp: the teyla CLI is not installed (see https://github.com/zaitsew/teyla#or-by-hand)" >&2
exit 1
