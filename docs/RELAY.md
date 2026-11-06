# The iPhone relay

The relay lets the iPhone app read what is waiting on you and answer from the phone. It works through a folder in iCloud Drive, so it needs no server and no account. The schema and the signing rules are in [APP.md](APP.md).

## Setup

```
teyla relay connect   # the whole setup: relay on, key, first sync, then opens Teyla on the Mac
teyla relay status    # on, paired, last snapshot
```

`connect` opens Teyla for Mac with the pairing key. Click "Use this folder" in its window. Then, on the iPhone, open Teyla on the Mac, choose Connect iPhone and scan the QR code; in the phone app pick the Teyla folder once. `connect` reuses an existing key and never rotates it. If Teyla for Mac is not installed, `connect` prints the pairing string instead: paste it into Teyla on your Mac or iPhone. The full Teyla app on the Mac needs no pairing. It shows the iPhone QR code under Connect iPhone.

The manual path, step by step:

```
teyla relay on        # creates iCloud Drive/Teyla, installs the sync agent
teyla relay pair      # prints the pairing string (the same one again later): paste it into Teyla on your Mac or iPhone
```

`[relay] folder` in `~/.teyla/config.toml` moves the folder.

## What is synced

| File | Written by | Holds |
|---|---|---|
| `state.teyla` | Mac | The signature, then the snapshot: open questions with Teyla's triage, the core products with their progress, questions Teyla closed, running sessions, tasks, finished work, today's spend |
| `outbox/<id>.json` | Phone | One signed action: an answer, a correction to a running session, a new task for a product, closing a question Teyla suggests closing, reopening one that was closed, or logging one activity (+1) |
| `sent/<id>.json` | Mac | The result of one action: `ok`, how it was delivered, a detail |

The Mac runs `teyla relay sync` when `outbox/` changes and every 60 seconds. It delivers an action only when the signature is valid, the action is under 7 days old, and the question has not changed since you read it. Each action is delivered once. If the Mac stops in the middle of one, the phone shows "interrupted; check the session, then send again", and Teyla does not retry it.

Closing and reopening run `teyla asks accept-close <id>` and `teyla asks undo <id>` on the Mac, one question at a time. They send no text to a session.
Logging an activity runs `teyla growth log --kind <kind>` for one of eleven fixed kinds; the entry's text is the fixed `+1`.

An answer never goes to the clipboard. When only the Mac can deliver it, the phone shows "needs the Mac" and the question stays open.

## Privacy

The snapshot holds the text of your questions, Teyla's proposed answers, the titles of your sessions, and for each core product a progress line, the titles of its last merged pull requests, its user counts and its milestone. iCloud Drive encrypts it in transit and at rest, but Apple holds the keys unless you turn on Advanced Data Protection. Turn it on if Apple should not be able to read the snapshot. The signature stops anyone who can write to the folder from sending actions. It does not hide the snapshot.

Safe mode (`teyla config set safe.enabled=true`) makes `sync` do nothing.

## Unpair

```
teyla relay off              # stops the agent, leaves the folder and the key
teyla relay pair --rotate    # replaces the key; the old pairing stops working at once
rm ~/.teyla/relay.key        # removes the key; the relay cannot sync until you pair again
```

Delete the Teyla folder in iCloud Drive to remove the synced files.

## Files on the Mac

| Path | Holds |
|---|---|
| `~/.teyla/relay.key` | The shared key, mode 0600. Never printed except by `pair` |
| `~/.teyla/relay.json` | `{on, folder, synced}` |
| `~/.teyla/relay-journal/<id>.json` | One file per action, kept 8 days, with no text in it |
| `~/Library/LaunchAgents/com.zaitsew.teyla.relay.plist` | The sync agent; the log is `~/Library/Logs/teyla-relay.log` |
