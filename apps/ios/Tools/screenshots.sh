#!/usr/bin/env bash
# App Store screenshots of the iPhone app, from sample mode, on a booted simulator.
#
#   apps/ios/Tools/screenshots.sh <output-dir> [<simulator-udid>]
#
# Use a 6.9-inch simulator (iPhone 16 Pro Max or 17 Pro Max): its PNGs are 1320 by 2868 px, the size the
# App Store takes for the largest iPhones. With no UDID the script uses the one booted simulator, and
# refuses to guess when several are booted. Booting a simulator is the caller's job (`teyla load --wait
# --kind sim` first on this machine); so is shutting it down afterwards.
#
# Set CONTENT_SIZE (for example extra-extra-extra-large) to check the layout at a Dynamic Type size; the
# size goes back to "large" when the script ends. The images are not committed.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
out="${1:?usage: screenshots.sh <output-dir> [<simulator-udid>]}"
udid="${2:-}"
bundle="com.zaitsew.teyla"

if [ -z "$udid" ]; then
  booted="$(xcrun simctl list devices booted | grep -Eo '[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}' || true)"
  [ -n "$booted" ] || { echo "No booted simulator. Boot one, or pass its UDID." >&2; exit 1; }
  [ "$(echo "$booted" | wc -l)" -eq 1 ] || { echo "More than one simulator is booted; pass the UDID of the one to use." >&2; exit 1; }
  udid="$booted"
fi
mkdir -p "$out"

cd "$here"
xcodegen generate >/dev/null
derived="$here/build/DerivedData"
if [ -z "${SKIP_BUILD:-}" ]; then
  teyla load --wait --kind build
  xcodebuild -project Teyla.xcodeproj -scheme Teyla -destination "id=$udid" -derivedDataPath "$derived" \
    CODE_SIGNING_ALLOWED=NO -quiet build
fi
app="$derived/Build/Products/Debug-iphonesimulator/Teyla.app"
[ -d "$app" ] || { echo "Missing $app" >&2; exit 1; }

xcrun simctl install "$udid" "$app"
xcrun simctl status_bar "$udid" override --time 9:41 --batteryState charged --batteryLevel 100 \
  --cellularMode active --cellularBars 4 --wifiBars 3 >/dev/null 2>&1 || true
if [ -n "${CONTENT_SIZE:-}" ]; then xcrun simctl ui "$udid" content_size "$CONTENT_SIZE"; fi
trap 'xcrun simctl status_bar "$udid" clear >/dev/null 2>&1 || true; [ -z "${CONTENT_SIZE:-}" ] || xcrun simctl ui "$udid" content_size large' EXIT

# shot <file> <launch arguments...>: a fresh launch, a pause for the first read, one PNG.
shot() {
  local name="$1"; shift
  xcrun simctl terminate "$udid" "$bundle" >/dev/null 2>&1 || true
  xcrun simctl launch "$udid" "$bundle" "$@" >/dev/null
  sleep 3
  xcrun simctl io "$udid" screenshot --type=png "$out/$name.png" >/dev/null
  echo "$out/$name.png"
}

shot 01-today        -TEYLA_SAMPLE YES -TEYLA_TAB today
shot 02-portfolio    -TEYLA_SAMPLE YES -TEYLA_TAB portfolio
shot 03-product      -TEYLA_SAMPLE YES -TEYLA_TAB portfolio -TEYLA_OPEN sample-app
shot 04-older        -TEYLA_SAMPLE YES -TEYLA_TAB today -TEYLA_OLDER open
shot 05-products     -TEYLA_SAMPLE YES -TEYLA_TAB products
shot 06-welcome      -TEYLA_ONBOARDING_STEP 0
xcrun simctl terminate "$udid" "$bundle" >/dev/null 2>&1 || true
