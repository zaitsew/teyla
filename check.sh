#!/usr/bin/env bash
# The gate (POLICY §10): what CI used to run, on this laptop. scripts/release.sh runs it;
# run it before pushing. `./check.sh docs` runs only the tests that read a tracked document.
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { uv venv -q && uv pip install -q -e '.[reel]' pytest; }
# Private data and non-English text must never reach this public repo: see CONTRIBUTING.md.
PYTHONPATH=src .venv/bin/python scripts/leak_check.py
# `./check.sh docs` stops here with a part of the suite: the test modules that read a tracked document
# (README.md, AGENTS.md, docs/). tests/conftest.py marks them `docs`. The pre-push hook runs this for a push
# that changes documents and nothing else, so a README edit costs seconds and still cannot break what they pin.
if [ "${1:-}" = docs ]; then
  PYTHONPATH=src exec .venv/bin/python -m pytest -q -m docs
fi
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
    # No `./gradlew --stop`: it stops every daemon on the Mac, so two check.sh runs (two pushes) killed
    # each other's tests (2026-11-15). The guard tick stops a Gradle daemon idle 30 min.
    ./gradlew --console=plain -q :teyla-review:testDebugUnitTest
  )
else
  echo "skip: packages/review-android (needs a JDK and the Android SDK)"
fi
PYTHONPATH=src .venv/bin/python -m pytest -q
