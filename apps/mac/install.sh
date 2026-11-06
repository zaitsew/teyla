#!/usr/bin/env bash
# Build Teyla.app in Release and install it to ~/Applications.
# The first command waits for a free build slot; exit status 3 means the machine is too loaded.
teyla load --wait --kind build
status=$?
if [ "$status" -eq 3 ]; then
  echo "The machine is too busy to build right now (teyla load exited 3). Try again in a few minutes." >&2
  exit 3
elif [ "$status" -ne 0 ]; then
  echo "teyla load failed with status $status. Is the teyla CLI installed?" >&2
  exit "$status"
fi

set -euo pipefail
cd "$(dirname "$0")"

command -v xcodegen >/dev/null || { echo "xcodegen is required: brew install xcodegen" >&2; exit 1; }

xcodegen generate --quiet
xcodebuild \
  -project Teyla.xcodeproj \
  -scheme Teyla \
  -configuration Release \
  -destination 'platform=macOS' \
  -derivedDataPath build \
  build | tail -n 20

app="build/Build/Products/Release/Teyla.app"
[ -d "$app" ] || { echo "Build finished but $app is missing." >&2; exit 1; }

dest="$HOME/Applications/Teyla Admin.app"
mkdir -p "$HOME/Applications"
# Builds before 0.41 were installed as Teyla.app. Remove that copy only when it is this full build,
# never a store build someone put there.
old="$HOME/Applications/Teyla.app"
if [ -d "$old" ] && [ "$(defaults read "$old/Contents/Info" CFBundleIdentifier 2>/dev/null)" = "com.zaitsew.teyla.local" ]; then
  rm -rf "$old"
fi
rm -rf "$dest"
ditto "$app" "$dest"
echo "Installed: $dest"
