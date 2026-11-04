#!/usr/bin/env bash
# The gate (POLICY §10): what CI used to run, on this laptop. scripts/release.sh runs it;
# run it before pushing.
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { uv venv -q && uv pip install -q -e '.[reel]' pytest; }
# Private data and non-English text must never reach this public repo: see CONTRIBUTING.md.
PYTHONPATH=src .venv/bin/python scripts/leak_check.py
# The web review package (packages/review-web): type check and unit tests. The pytest run below builds
# its fixture with Vite, so the dependencies must be installed; a Mac without node skips both.
if command -v npm >/dev/null 2>&1; then
  [ -d packages/review-web/node_modules ] || (cd packages/review-web && npm ci --silent)
  (cd packages/review-web && npm run --silent check)
fi
# The Android review package (packages/review-android): the JVM unit tests. A Mac with no JDK or no Android SDK
# prints a skip line instead (the pytest run below still checks the two modules' public API from the sources).
# TEYLA_REVIEW_ANDROID_BUILD=1 also builds the fixture app both ways and runs the store check on it.
android_jdk=""
for c in "${JAVA_HOME:-}" "$HOME"/.local/jdk-*/Contents/Home; do
  [ -n "$c" ] && [ -x "$c/bin/javac" ] && { android_jdk="$c"; break; }
done
android_sdk=""
for c in "${ANDROID_HOME:-}" "${ANDROID_SDK_ROOT:-}" "$HOME/Library/Android/sdk" "$HOME/Android/Sdk"; do
  [ -n "$c" ] && [ -d "$c/platforms" ] && { android_sdk="$c"; break; }
done
if [ -n "$android_jdk" ] && [ -n "$android_sdk" ]; then
  (
    export JAVA_HOME="$android_jdk" ANDROID_HOME="$android_sdk"
    cd packages/review-android
    if command -v teyla >/dev/null 2>&1; then teyla load --wait --kind build; fi
    ./gradlew --console=plain -q :teyla-review:testDebugUnitTest
    ./gradlew --stop >/dev/null
  )
else
  echo "skip: packages/review-android (needs a JDK and the Android SDK)"
fi
PYTHONPATH=src .venv/bin/python -m pytest -q
