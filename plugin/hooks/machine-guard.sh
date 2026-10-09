#!/bin/sh
# PreToolUse (Bash): refuse a heavy shell command while the machine is already drowning.
#
# On 2026-10-09 a 24 GB Mac kernel-panicked while many agent sessions each booted simulators
# and ran xcodebuilds in parallel (swap 11+ GB, load average 500+). Each agent saw only its own
# task. This hook is the admission control: a command that starts heavy work (a build, a booted
# simulator, a headless agent lane) is first put to `teyla load --admit KIND`, which looks at
# the whole machine. Refused -> exit 2 and the refusal on stderr, which the harness shows to the
# model; the model is told what to do instead (reuse a booted simulator, `teyla load --wait`).
#
# THIS HOOK FAILS OPEN, unlike pre-tool-use.sh. The kill switch must never become "the hook
# broke, so the tool ran", because that hook is a safety control. This one is a courtesy to the
# machine: a guard that blocks real work because of its own bug (teyla missing, an older CLI
# without --admit, a python crash, a slow `ps`) gets uninstalled, and then nothing guards the
# machine at all. So every outcome except an explicit "teyla guard: ... refused" is exit 0.
# The only fail-closed control is ~/.teyla/KILL, in pre-tool-use.sh.
#
# Cost. It runs before EVERY Bash call, so the ordinary path is pure sh: TEYLA_GUARD=0 and a
# coarse `case` over the raw JSON, no process started except the one that reads stdin. Only a
# payload that mentions a heavy tool pays for one awk (to extract and classify the command),
# and only a command that really is heavy pays for the config read and `teyla`.
#
# What is heavy. The command is split at ; & | ( ` { $( and newlines, each segment loses its
# wrappers (VAR=1, env, time, sudo, nice, xcrun, `bash -c "`, if/then/do) and the first word
# decides, so `cd x && xcodebuild -scheme A test` is a build, `git commit -m "xcodebuild"` and
# `grep xcodebuild log` are not.
#   build  xcodebuild (not -list -showsdks -version -showBuildSettings -showdestinations -help),
#          swift build|test, gradle/gradlew with a task, cargo build|test, bazel build|test
#   sim    simctl boot|create|clone, and `simctl bootstatus ... -b` (which boots)
#   lane   codex exec, codex-lane, codex-review, claude-review, claude -p|--print, grok -p|--prompt
# Not gated: simctl list|io|launch|install|spawn|shutdown|terminate|erase|delete (they free
# resources or use an already-booted device).
#
# Skipped (exit 0): TEYLA_GUARD=0; `[guard] enabled = false` in ~/.teyla/config.toml; a command
# that already contains `teyla load --wait` (the agent is waiting for a slot, which is the
# point). The idiom for an agent:  teyla load --wait --kind build && xcodebuild ...
#
# Timeout. `teyla load --admit` is one sysctl and one ps (well under 150 ms), but the hook is
# registered with a 15 s timeout in every harness. A timed-out hook is a non-blocking error in
# Claude Code (the call proceeds) and fail-open in Codex and Grok, so there is no need for a
# watchdog process here; sh has no portable timeout and a hand-rolled one is how orphans start.
#
#   (none)    Claude Code and Codex: refusal text on stderr, exit 2.
#   --grok    Grok shows only the first stderr line of an exit 2, so the whole refusal also goes
#             to stdout as {"decision":"deny","reason":...} (Grok honours it on any exit code).
#
# TEYLA_HOME overrides ~/.teyla (tests, second profiles).

mode="${1:-}"

[ "${TEYLA_GUARD:-}" = 0 ] && exit 0

payload=$(cat 2>/dev/null)

# Coarse screen, no process spawned: only these substrings can start heavy work. False
# positives (a path with "gradle" in it) just go on to the exact classifier.
case "$payload" in
    *xcodebuild*|*swift\ *|*gradle*|*cargo\ *|*bazel*|*simctl*|*codex\ *|*codex-*|*claude\ *|*claude-review*|*grok\ *) ;;
    *) exit 0 ;;
esac

kinds=$(printf '%s' "$payload" | awk '
  function strip(s) { gsub(/^["\047(]+/, "", s); gsub(/["\047)]+$/, "", s); return s }
  function base(s) { sub(/^.*\//, "", s); return s }
  function unesc(s) {
    gsub(/\\\\/, "\001", s); gsub(/\\n/, ";", s); gsub(/\\[tr]/, " ", s)
    gsub(/\\"/, "\"", s); gsub(/\\\//, "/", s); gsub(/\\u0026/, "\\&", s)
    gsub(/\\u003[cC]/, "<", s); gsub(/\\u003[eE]/, ">", s)
    gsub(/\001/, "\\", s)
    return s
  }
  function wrapper(b) {
    return b ~ /^(env|time|sudo|nice|nohup|exec|command|caffeinate|arch|builtin|setsid|stdbuf|timeout|xcrun|if|then|do|else|elif|while|until|!)$/
  }
  function isshell(b) { return b ~ /^(sh|bash|zsh|dash)$/ }
  # The kind of one segment ("" when it is not heavy).
  function classify(seg,    nt, raw, tok, m, k, p, t, b, c, a, na, i, a1, ro, tasks) {
    nt = split(seg, raw, /[ \t]+/); m = 0
    for (k = 1; k <= nt; k++) if (raw[k] != "") tok[++m] = raw[k]
    p = 1
    while (p <= m) {
      t = strip(tok[p]); b = base(t)
      if (t ~ /^[A-Za-z_][A-Za-z0-9_]*=/) { p++; continue }
      if (wrapper(b)) {
        p++
        while (p <= m && (tok[p] ~ /^-/ || tok[p] ~ /^[0-9.]+[smhd]?$/ || tok[p] ~ /^[A-Za-z_][A-Za-z0-9_]*=/)) {
          if (tok[p] ~ /^-?-(sdk|toolchain|u|g|n)$/) p++
          p++
        }
        continue
      }
      if (isshell(b) && p < m && strip(tok[p + 1]) ~ /^-[A-Za-z]*c$/) { p += 2; continue }
      if (isshell(b) && p < m && strip(tok[p + 1]) !~ /^-/) { p++; t = strip(tok[p]); b = base(t) }
      break
    }
    if (p > m) return ""
    c = base(strip(tok[p])); na = 0
    for (i = p + 1; i <= m; i++) a[++na] = strip(tok[i])
    a1 = ""
    for (i = 1; i <= na; i++) {
      if (a[i] == "--set" || a[i] == "--sdk" || a[i] == "-sdk") { i++; continue }
      if (a[i] ~ /^-/ || a[i] ~ /^\+/) continue
      a1 = a[i]; break
    }
    if (c == "xcodebuild") {
      for (i = 1; i <= na; i++)
        if (a[i] ~ /^-(list|showsdks|version|showBuildSettings|showBuildSettingsForIndex|showdestinations|help|usage|h|checkFirstLaunchStatus|runFirstLaunch|license)$/) return ""
      return "build"
    }
    if (c == "swift") return (a1 == "build" || a1 == "test") ? "build" : ""
    if (c == "cargo") return (a1 == "build" || a1 == "test") ? "build" : ""
    if (c == "bazel" || c == "bazelisk") return (a1 == "build" || a1 == "test") ? "build" : ""
    if (c == "gradle" || c == "gradlew") {
      tasks = 0
      for (i = 1; i <= na; i++) {
        if (a[i] ~ /^(--stop|--status|--version|-v|-version|--help|-h|-\?)$/) return ""
        if (a[i] !~ /^-/) tasks++
      }
      return tasks ? "build" : ""
    }
    if (c == "simctl") {
      if (a1 == "boot" || a1 == "create" || a1 == "clone") return "sim"
      if (a1 == "bootstatus") for (i = 1; i <= na; i++) if (a[i] == "-b") return "sim"
      return ""
    }
    if (c == "codex-lane" || c == "codex-review" || c == "claude-review") return "lane"
    if (c == "codex") { for (i = 1; i <= na; i++) if (a[i] == "exec") return "lane"; return "" }
    if (c == "claude") { for (i = 1; i <= na; i++) if (a[i] == "-p" || a[i] == "--print") return "lane"; return "" }
    if (c == "grok") { for (i = 1; i <= na; i++) if (a[i] == "-p" || a[i] == "--prompt") return "lane"; return "" }
    return ""
  }
  { all = all $0 "\n" }
  END {
    i = index(all, "\"command\"")
    if (!i) exit
    rest = substr(all, i + 9)
    sub(/^[ \t\n]*:[ \t\n]*/, "", rest)
    if (substr(rest, 1, 1) != "\"") exit
    rest = substr(rest, 2)
    out = ""; n = length(rest); if (n > 20000) n = 20000
    for (j = 1; j <= n; j++) {
      ch = substr(rest, j, 1)
      if (ch == "\\") { out = out ch substr(rest, j + 1, 1); j++ }
      else if (ch == "\"") break
      else out = out ch
    }
    cmd = unesc(out)
    if (cmd ~ /teyla[ \t]+load[ \t]+.*--wait/) exit
    ns = split(cmd, seg, /[;&|(`{]|\$\(/)
    for (s = 1; s <= ns; s++) {
      k = classify(seg[s])
      if (k != "" && !(k in seen)) { seen[k] = 1; print k }
    }
  }' 2>/dev/null)

[ -n "$kinds" ] || exit 0

# `[guard] enabled = false` (false/0/no/off), TOML-ish like the other hooks: comments and
# quotes ignored, last wins. No file, no switch.
cfg="${TEYLA_HOME:-$HOME/.teyla}/config.toml"
if [ -f "$cfg" ]; then
    awk '
      /^[ \t]*\[/ { t = $0; sub(/#.*/, "", t); gsub(/[ \t\r]/, "", t); inside = (t == "[guard]"); next }
      inside {
        line = $0; sub(/#.*/, "", line); n = index(line, "="); if (!n) next
        k = substr(line, 1, n - 1); v = substr(line, n + 1)
        gsub(/[ \t"\047]/, "", k); gsub(/[ \t"\047\r]/, "", v)
        if (k == "enabled") { v = tolower(v); off = (v == "false" || v == "0" || v == "no" || v == "off") }
      }
      END { exit off ? 0 : 1 }' "$cfg" 2>/dev/null && exit 0
fi

# The plugin ships inside the teyla repo, so its sources sit one level up. Used only as a
# fallback, when teyla is not installed on this machine (same as pre-tool-use.sh).
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
    src="${CLAUDE_PLUGIN_ROOT}/../src"
else
    src="${0%/*}/../../src"
fi

teyla=$(command -v teyla 2>/dev/null)
[ -n "$teyla" ] && [ -x "$teyla" ] || teyla=""
[ -n "$teyla" ] || { [ -x "$HOME/.local/bin/teyla" ] && teyla="$HOME/.local/bin/teyla"; }
py=""
if [ -z "$teyla" ] && [ -d "$src/teyla" ]; then
    py=$(command -v python3 2>/dev/null)
    # /usr/bin/python3 on a Mac without the developer tools pops an install dialog instead of running.
    if [ "$py" = /usr/bin/python3 ] && [ "$(uname -s 2>/dev/null)" = Darwin ]; then
        xcode-select -p >/dev/null 2>&1 || py=""
    fi
fi
[ -n "$teyla" ] || [ -n "$py" ] || exit 0

for kind in $kinds; do
    if [ -n "$teyla" ]; then
        out=$("$teyla" load --admit "$kind" 2>/dev/null)
    else
        out=$(PYTHONPATH="$src${PYTHONPATH:+:$PYTHONPATH}" "$py" -m teyla load --admit "$kind" 2>/dev/null)
    fi
    status=$?
    # Exit 2 is also what argparse says to an older teyla that has no --admit; only the
    # guard's own refusal, which starts with this prefix, blocks.
    [ "$status" -eq 2 ] || continue
    case "$out" in
        "teyla guard:"*) ;;
        *) continue ;;
    esac
    printf '%s\n' "$out" >&2
    if [ "$mode" = "--grok" ]; then
        reason=$(printf '%s\n' "$out" | awk 'BEGIN { ORS = "\\n" } { gsub(/\\/, "\\\\"); gsub(/"/, "\\\""); gsub(/[\001-\037]/, " "); print }')
        printf '{"decision": "deny", "reason": "%s"}\n' "$reason"
    fi
    exit 2
done
exit 0
