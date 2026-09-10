# How I want work shipped — global instructions for {{owner}}

Applies in every repo. Keep it short: the measured median CLAUDE.md is ~485 words and
grows ~57 a day without pruning. Anything added here should displace something.

@~/.agents/POLICY.md

## Shipping

- **Merging.** {{merge_rule}}
- **One PR/MR per logical unit** — what I would review in one sitting. Two unrelated
  fixes are two PRs, even if written in the same hour.
- **Do not leave finished work only on a local branch.** Push it and open the PR/MR.
  Merging is a separate question, answered by the rule above.
- **Merge, don't squash.** I want the individual commits in history.
- **Never force-push.** Not to main, not to a shared branch, not "just this once".
- **Never push a diverged main.** If local main is both ahead and behind, push it as a
  named branch and tell me what you found.

## Before anything destructive in git

Check the fact, don't infer it. A branch with no upstream is not a branch whose commits
are missing from the remote.

```
git branch -r --contains <branch>     # is it actually on the remote?
git -C <path> status --porcelain      # is there uncommitted work?
```

Clean and contained → safe. Anything else → stop and tell me. Never `mv` or `rm -rf`
a git worktree; use `git worktree remove`.

## Layout

- `{{code_root}}/<repo>` — flat, one level, one directory per git repo
- `{{ops_root}}` — everything that is not a code repo: notes, plans, runs, the wiki
- `~/.worktrees/<repo>/<branch>` — parallel agent work, out of the project tree
- A path never contains the name of a harness (Claude, Codex, Hermes). The path
  describes the work. Launch every session from the repo root, never from a parent.

## Secrets

Never commit `.env`, keys or tokens; never print a key into a reply or a transcript;
read them from the environment or the keychain. A key that appears in a chat is rotated.

## Reporting

- If you could not verify something, say so in the same sentence as the claim.
- If a subagent or tool reports a fact a command could check, check it.
- Corrections to your own earlier claims go in plainly and once. No apology.
