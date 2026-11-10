#!/bin/sh
# Run the iPhone post drafter on the Mac, with the same rules and the same on-device model family.
# Input: a JSON list of {"id", "text"} on stdin. Output: JSON drafts on stdout.
# Usage: teyla notes --json | jq '[.[] | {id, text}]' | scripts/post-drafter-eval/run.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
out="${TMPDIR:-/tmp}/teyla-post-drafter-eval"
swiftc -O -parse-as-library "$here/../../apps/ios/Teyla/Core/PostDrafter.swift" "$here/Eval.swift" -o "$out"
exec "$out"
