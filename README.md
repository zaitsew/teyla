# Teyla

Teyla is the operating layer for one person who runs many products through AI coding agents on one Mac. It keeps you in charge: what waits on you, your own words, how agents write, what it costs, whether the machine survives, and whether a build reached a person. It runs locally.

Setting this up with an AI agent? It reads [AGENTS.md](AGENTS.md). Every call that leaves your machine is listed in [docs/PRIVACY.md](docs/PRIVACY.md).

## Quick start

```bash
uv tool install --python 3.12 git+https://github.com/zaitsew/teyla   # or: pipx install ...; Python 3.11+. uv may download Python 3.12 (about 25 MB) if you have none
teyla start                            # what your agents cost, and seven fixes you can accept one by one and undo; a yes to O6 also installs the Claude Code plugin
teyla policy init --owner "Your Name" && teyla policy sync   # one POLICY.md for every harness (offer O5 does this too)
teyla routine install                  # daily and weekly checks under launchd
teyla doctor                           # what must be true here, and the fix for each gap
teyla asks                             # every question an AI session left waiting on you
teyla product init                     # which repo is which product (proposal; --write saves it)
teyla spend --days 7                   # what the week cost, and which part bought nothing
```

Teyla works with Claude Code, Codex, Grok, Cursor and Hermes. It reads the session files already on your disk.

## What it does

### What waits on you

A session ends on a question, the desktop app archives it, and nobody reads it again. In 14 days, 40 Claude Code sessions ended that way and 1 got an answer.

```bash
teyla asks                      # open questions by product, oldest first, with a link that reopens the session
teyla asks --html --open        # the same as one page for your phone
teyla asks done <id>            # close one; snooze <id> <days> hides it
```

You get the question word for word, its age and the options the agent offered. Details: [docs/ASKS.md](docs/ASKS.md).

The same list lives in one window: **Teyla for Mac** opens with a one-sentence brief, orders the questions by what each unblocks, shows the sessions running now, and sends your answer into the session that asked. It updates live and reads everything through the CLI.

```bash
cd apps/mac && ./install.sh     # builds Teyla.app into ~/Applications (macOS 15, Xcode, xcodegen)
teyla state                     # what the window shows, in the terminal
teyla answer <id> -- "<text>"   # send an answer without opening the session
```

Details: [apps/mac/README.md](apps/mac/README.md), [docs/APP.md](docs/APP.md).

### Your own words

You write a long prompt, an agent turns it into a plan, and a later session works from the plan. The detail is gone. Teyla keeps the source.

```bash
teyla intent backfill --days 30   # keep the long prompts already in your transcripts
teyla intent [product]            # list them; `teyla intent path <product>` prints the file
```

Prompts of 400 characters or more go to `~/.teyla/intent/<product>.md`, outside the repo, with secrets scrubbed. No model summarises them. Session start points at the file, and the policy says a plan quotes the sentences it serves. Details: [docs/INTENT.md](docs/INTENT.md).

### How agents write

Replies run long and open with filler. The policy sets one contract: the answer first, short sentences, a ban list, and a session-end card of at most 12 lines.

```bash
teyla prose --days 7   # reply length, long sentences, ban-list hits and preambles, per harness and project
```

You get numbers per project, and the weekly digest names a median over 150 words. Details: [docs/WRITING.md](docs/WRITING.md).

### What it costs

Usage dashboards do not name the habits that burn tokens: subagents that inherit the top model, build lanes that drift up to Opus, sessions that re-read 300k tokens each turn.

```bash
teyla spend --days 7     # cost at API list price; the part that bought nothing, with a fix for each
teyla lanes --days 7     # per subagent type and model: turns, peak context, dollars, review P1s
teyla monitor --days 30  # tokens by model and project, cache-read ratio, giant sessions, advice
```

`teyla spend --alert` runs daily and puts a budget breach in the next session's first line.

### Whether the machine survives

Ten agents that each start "just one" build or simulator fill swap together, and the kernel panics. Teyla is the scheduler they lack.

```bash
teyla load                                         # OK, BUSY or CRITICAL, with the numbers
teyla load --wait --kind build && xcodebuild ...   # wait for a free slot instead of piling on
teyla crash                                        # after a panic: the machine's load before it
```

The plugin's machine guard refuses a build, simulator or headless lane while the Mac is overloaded. It fails open. `teyla storage` lists what holds disk and RAM.

### One policy for every harness

Your rules live in one harness. Switch to another and the model has never heard of them.

```bash
teyla policy sync            # ~/.agents/POLICY.md and your own rules into Claude Code, Codex, Grok, Hermes, Cursor
teyla harness sync           # the same skills and hooks in the others
teyla harness verify --live  # can each harness do work now, and did the policy arrive
```

An edit made inside a generated copy is filed in `teyla policy inbox`, never overwritten silently. What each harness can and cannot do: [docs/HARNESSES.md](docs/HARNESSES.md).

### Whether a build reached a person

An app for one person becomes an app for four only with accounts, per-user data, a backend off your laptop and a build on other people's phones.

```bash
teyla productize --owner-steps   # every product against R1 to R10, then one list of what only you can do
teyla platform                   # the shared resources you buy once: server, domain, mail, Apple, Google Play
teyla testflight                 # did the newest uploaded build reach your tester (iOS)
teyla play                       # the same for the Android internal track
```

Each product names one primary platform; any other needs a dated trigger. Details: [docs/PRODUCTIZE.md](docs/PRODUCTIZE.md).

### Whether the automated half ran

Launchd jobs, cron lines, desktop tasks and scheduled workflows fail silently.

```bash
teyla routines     # every routine and manual check in each repo's teyla.toml: ok, NOT LOADED, STALE
teyla schedules    # every scheduled task on this machine, its last run, and what vanished
teyla reviews      # merged PRs that never got a review
```

`teyla run product:routine` runs a routine under capability grants and stops at a gate for your approval in `teyla inbox`. Details: [docs/CONTROL-PLANE.md](docs/CONTROL-PLANE.md).

## Privacy and safe mode

Teyla reads the transcripts already on your disk, and no data leaves your machine. Every outbound call is listed in the network table of [`prompts/onboard.md`](prompts/onboard.md).

On a managed work laptop, switch on safe mode: `teyla policy init --work`. Nothing then reaches the network unless you pass `--allow-network` to the command you typed. Safe mode also stops self-update and runs repo commands only in the repos you list. `teyla uninstall --dry` lists every file Teyla wrote. See [docs/WORK.md](docs/WORK.md).

## Docs

- [START](docs/START.md): `teyla start`: the diagnosis, the seven offers, how a saving is counted, how to undo
- [COMMANDS](docs/COMMANDS.md): every command with its flags (`teyla --help` prints the same list)
- [GUIDE](docs/GUIDE.md): install and update, the plugin, the policy, routines, cloud sessions
- [MANUAL](docs/MANUAL.md): the whole method and the numbers behind each threshold
- [HARNESSES](docs/HARNESSES.md): what each harness reads and what differs
- [PRODUCTIZE](docs/PRODUCTIZE.md): from an app you use to an app four people use
- [CONTROL-PLANE](docs/CONTROL-PLANE.md): runs, gates, receipts and the kill switch
- [WIKI](docs/WIKI.md): the facts store
- [WORK](docs/WORK.md): safe mode for a work laptop
- [ASKS](docs/ASKS.md), [INTENT](docs/INTENT.md), [WRITING](docs/WRITING.md), [PRODUCTS](docs/PRODUCTS.md): the newest commands
- [ROADMAP](docs/ROADMAP.md): what is next

## License

Apache-2.0.
