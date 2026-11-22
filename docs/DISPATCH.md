# Dispatch and say

`teyla dispatch` starts new work. `teyla say` corrects a session that is running. The Teyla for Mac
window and the iPhone relay call both ([APP.md](APP.md)).

```
teyla dispatch <product> [--harness codex|claude] [--model M] [--json] [--dry] -- <text>
teyla say <ref> [--json] [--dry] -- <text>
```

Both print `{ok, via, detail, id}`. Free text always follows `--` and is one argv entry. No shell
parses it.

## dispatch

1. Resolve `<product>` to a repo: a name from `teyla products`' repo list, or a path to a checkout.
2. `git fetch origin`. A failed fetch is reported, and the last known `origin/<default>` is used.
3. Find the default branch: `origin/HEAD`, else `origin/main`, else `origin/master`.
4. `git worktree add --no-track -b task/<yyyymmdd-hhmm>-<slug> ~/.worktrees/<repo>/<branch> origin/<default>`.
   The main checkout is never touched. It refuses when the worktree path exists.
5. Start one detached session in the worktree (new process group, stdin closed). Output goes to
   `~/.teyla/dispatch/<id>.log`, mode 0600.
6. Append `{id, product, harness, worktree, branch, started, pid, log}` to `~/.teyla/dispatch.jsonl`
   (mode 0600).

The prompt is a fixed header, then the text verbatim: "Task from the owner via Teyla. Work only in this
worktree and branch. Follow the repo's rules. End with the session-end card."

| Harness | `via` | Command |
|---|---|---|
| `codex` (default) | `codex-exec` | `codex-lane -m gpt-6.1-sol -C <worktree> -s workspace-write --add-dir <repo>/.git -- <prompt>`. `codex-lane` pins the Standard tier and waits for the machine guard. |
| `claude` | `claude-bg` | `teyla load --wait --kind lane && claude --bg --model claude-sonnet-5-5 --permission-mode <mode> --name <name> <prompt>` |

`--add-dir` lets the session commit: a worktree keeps its git data in the main repo's `.git`.
The Claude permission mode is `[dispatch] claude_permission_mode` in `~/.teyla/config.toml`
(default `acceptEdits`). `--model` takes a plain model name; anything that looks like a flag is
refused.

`--dry` fetches nothing, creates nothing and starts nothing. It prints the worktree, the branch and
both commands. `link` is `file://<worktree>`: a headless run has no session link yet.

Safe mode (`TEYLA_SAFE=1` or `[safe] enabled`) refuses dispatch.

## say

`<ref>` is the `id` of a `running[]` row, its session id, or a prefix of either with at least 6
characters. An unknown or ambiguous ref returns `ok: false`.

| Session | `via` | What happens |
|---|---|---|
| Live interactive Codex | `codex-queue` | `codex queue --thread <session> --message=<text>`. Delivered after the current turn. |
| Anything else | `opened` | The text goes to the clipboard and the session's link opens. |

`say` never resumes a live session with `claude --resume` or `codex exec resume`. Two writers on one
transcript corrupt it.

## answer: delivery is confirmed

`teyla answer` starts a Codex resume or `claude --bg --resume`. A running process does not prove
delivery. The item is marked done only when the session's transcript gains a user entry holding the
text: the Codex rollout, or the Claude transcript under `~/.claude/projects/` (a copy that
`--bg --resume` starts for a running session counts). It waits up to 10 s. Without the entry it
returns `ok: true` with "started, not confirmed yet" and leaves the item open.
