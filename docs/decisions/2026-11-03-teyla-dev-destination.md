# teyla.dev sends people to the install line, then to the apps

Decided 2026-11-03 by the owner, who asked whether to build a full-function web version or send people to the macOS and iOS apps. The answer to the recommendation below, verbatim: "ok, go with recommended option".

## The decision

- The landing page's primary action is the line a person pastes into Claude Code or Codex.
- The Mac and iPhone apps become a destination when they are on sale. Today the seller account is under a submission hold, so the page names no store.
- There is no hosted web version. `teyla web` is the full dashboard in a browser, on 127.0.0.1.
- The landing page is variant A, the paste line first. Variant B, a pack picker first, is removed. It is in the history of [PR #350](https://github.com/zaitsew/teyla/pull/350).

## Why not a hosted version

| Option | Needs | Problem |
|---|---|---|
| Upload sessions to a server | Server, accounts, a local uploader | Breaks "no server, no account"; transcripts can hold other people's data |
| Read files in the browser | File System Access API | Chromium only; cannot install hooks or launchd jobs |
| A page on teyla.dev drives the local CLI | A rework of the `teyla web` security model | More attack surface for a nicer address |

Any of these still needs a local program to read sessions and apply fixes.

## Not measured

No prototype was built, demand was not measured and hosting was not priced.

## When to reopen

People ask for a hosted version, or the owner decides Teyla should earn revenue through accounts. A read-only demo on sample data is the cheaper step, and it keeps the promise. It was offered and is not part of this decision.
