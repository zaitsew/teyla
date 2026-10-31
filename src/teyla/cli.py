"""teyla — command line.

  teyla                                                          the welcome: your numbers and the next three commands (never an error)
  teyla today [--json] [--fresh]                                 the daily screen: waiting questions by product, the Inbox, the week's spend, one next step
  teyla help [--all | COMMAND]                                   the commands in six groups; --all lists every one
  teyla monitor [--days N] [--json] [--samples] [--share] [--out FILE]   adoption report from local harness logs
  teyla advise  [--days N]                                       just the findings
  teyla sessions [--days N] [--project SUBSTR]                   one line per session
  teyla corrections [--days N] [--project SUBSTR] [--recorded]   correction-shaped human turns, clustered; --recorded: the stored ones
  teyla intent [product] [--days N] [--grep TEXT] [--json]       the owner's long prompts, verbatim, per product (~/.teyla/intent/); none: one line per product
  teyla intent path <product> | backfill [--days 30] [--dry]     the file to read before planning; fill it from Claude Code and Codex transcripts
  teyla intent cover <plan.md> [--product P] [--since DATE] [--last N] [--model] [--json]   which of his sentences the plan neither serves nor sets aside; exit 1 if any
  teyla start [--days N] [--agent|--json] [--yes]                 diagnose your agent spend, then offer one-keystroke fixes (--agent: JSON for an AI to relay, writes nothing)
  teyla web [--no-open] [--port N]                                 the dashboard in your browser: diagnosis, today, products, notes, spend (127.0.0.1 only)
  teyla apply OFFER... [--yes] [--dry] [--owner NAME] | undo CHANGE_OR_OFFER... [--force] | changes [--json]   make, revert and list the changes `start` offers
  teyla policy init [--owner] [--work] [--claude-md] [--ops-root-init] [--dry]   POLICY.md, global CLAUDE.md, an ops root
  teyla policy status|sync [--dry] [--quiet]                      the wiring into every harness (hand edits to a generated copy are filed first)
  teyla policy inbox [--done FILE|--all]                          hand edits found in generated policy files, waiting for review
  teyla policy sync-repo <path>... [--prefer agents|claude]      AGENTS.md ⇄ CLAUDE.md in repos
  teyla policy ack [--note TEXT]                                  record acceptance of ~/.claude/CLAUDE.md's current hash
  teyla policy refresh [--dry] [--resolved]                       three-way merge of template changes into ~/.agents/POLICY.md
  teyla harvest <path> [--project SLUG]                          tool spine + corrections for sessions touching a path
  teyla asks [--days N] [--product P] [--all] [--json] [--html [-o FILE] [--open]]   every question an AI session left waiting on you
  teyla asks done <id-prefix>... [--note TEXT] | undo <id-prefix>... | snooze <id-prefix> <days>   close one, reopen one, or hide one
  teyla product [list] [--json] | show <id> [--json] [--quick] | init [--write] | add <id> [--repo P] | set <id> k=v... | park|wake <id>   the product registry (~/.teyla/products.toml)
  teyla product assign <ask-id-prefix|session-id> <id> [--ask-only]   file a session's asks under another product
  teyla note "text" [--product P] [--json] | link <id> <product> | drop|undrop <id>   keep a text idea, linked to a product (~/.teyla/notes/)
  teyla note --suggest "text" --json [--cwd DIR]                   the product a note would get, plus the picker list; writes nothing
  teyla notes [--product P | --inbox] [--all] [--json]             your notes, newest first
  teyla state [--json]                                             ranked questions, products and running sessions in one snapshot
  teyla portfolio [--json] [--refresh] [--product ID]              where every product stands: health, platforms, PRs, spend
  teyla answer <id-prefix> <text...> [--json] [--dry]              answer a question inside the session that asked it
  teyla relay on|off|status [--json]                               the iPhone relay: switch it on or off, say where it stands
  teyla relay pair [--json] [--rotate]                             create the shared key, print the pairing string
  teyla relay sync [--quiet]                                       one pass: write the snapshot, deliver the signed outbox
  teyla say <ref> [--json] [--dry] -- <text>                       correct a running session (Codex: queued; else copy and open)
  teyla dispatch <product> [--harness codex|claude] [--model M] [--json] [--dry] -- <text>   start new work in a fresh worktree
  teyla spend [--days N] [--by-day] [--alert] [--json]           what the AI work cost, which part bought nothing; --by-day: subagent cost by model family
  teyla lanes [--days N] [--project SUBSTR] [--json]             subagent lanes by type and model: cost, turns, peak context, review P1s
  teyla prose [--days N] [--project SUBSTR] [--json]             final reply length, long sentences, ban-list hits and preambles
  teyla voice check <file|-> --chart <dir|file> [--lang L] [--format F] [--model] [--json]   a draft against a voice chart
  teyla voice chart <repo> [--lang L] [--out DIR] [--force] [--json]   scaffold a product's voice chart (en, es, ru); a chart is complete at 10 accepted and 5 rejected lines
  teyla copy brief|write|judge|apply ...                         UI copy from a brief: one call per language, a judge, then the catalogs (xcstrings, strings.xml, i18n)
  teyla models [--days N] [--json] [--refresh]                   model ladder + price drift report
  teyla models watch [--refresh] [--json] [--ack [ID...]] [--seed FILE]  new models, what they replace, repos naming superseded ids
  teyla tidy [paths...] [--json] [--apply] [--quiet]              duplicates, dead references and whitespace junk in the rule and memory files; --apply: mechanical fixes only, backup first
  teyla models --write-policy [--dry] [--drop-absent]             rewrite the ladder table in ~/.agents/POLICY.md
  teyla models --write-prices                                     ~/.teyla/prices.json from models.dev
  teyla lang [repo...] [--json] [--quiet] [--commits N]          tracked files and commit messages holding non-English (non-Latin script) text
  teyla wiki init|status|lint|confirm <path> [slug]              the facts store as an LLM-maintained wiki
  teyla feedback [--days N] [--out FILE]                         one redacted file to send to the maintainer
  teyla run <product:routine> [--dry] [--force]                  the run engine: grants, caps, gate A/B/C, receipt
  teyla inbox [list|show|approve|reject]                          the needs-you inbox
  teyla kill [on|off|status]                                       global kill switch
  teyla triggers [list|install|uninstall]                          clock triggers → LaunchAgents
  teyla promote <product:routine> --gate B|C                       earned autonomy on counted evidence
  teyla receipts <product:routine>                                 what ran, under which rules and grants
  teyla doctor [--quiet] [--json] [--refresh]                    what must be true here, and the fix for each thing that is not
  teyla remind add "<what>" <YYYY-MM-DD> [--how "..."]            file a dated to-do; doctor WARNs within 30d, FIXes once overdue
  teyla remind list | done <n>                                    everything pending; clear the n-th
  teyla load [--json] [--record] [--quiet] [--admit KIND] [--wait --kind KIND] [--timeout S] [--cwd DIR]   machine load: snapshot, verdict (exit 0 OK, 1 BUSY, 2 CRITICAL), admission, wait for a slot
  teyla guard tick [--quiet] [--dry] | status                    the guard by itself: record, alert file, stop idle Gradle/Kotlin daemons (the load agent runs tick every minute)
  teyla crash [--days N] [--json] [--ack]                         after a crash: the panic, the machine's load before it, what to change
  teyla storage [--json] [--no-sizes]                             disk and RAM held by agent work: worktrees, build output, caches
  teyla storage clean [--apply] [--auto]                          remove finished worktrees and idle build output (dry run by default)
  teyla storage sims [--reap] [--dry] [--json]                    booted simulators: in use or idle; --reap shuts down the idle ones
  teyla storage sweep [--temp] [--dry] [--json]                   temp build output, old DerivedData, caches and logs agents leave behind
  teyla config show | set KEY=VALUE                               ~/.teyla/config.toml, incl. [env] for launchd/hook runs
  teyla config set safe.enabled=true                              work mode: no network (--allow-network per command), no self-update
  teyla update [--check] [--force] [--wire] [--quiet]            newer release → install, then policy sync/refresh, plugin refresh, routines
  teyla platform [init|env-example] [--json] [--no-net]          the shared resources set up once, and the step for each missing one
  teyla productize [path...] [--json] [--owner-steps]            what stands between each product and its second user
  teyla testflight [path...] [--json] [--quiet] [--china] [--allow-network]    did the build reach a person: newest upload vs newest build your tester can install; --china: is any app still available in China mainland
  teyla play [path...] [--json] [--quiet] [--allow-network]          did the Android build reach a person: internal track status, closed-test age on Google Play
  teyla schedules [--json] [--quiet] [--all] [--allow-network]    every scheduled task (Claude desktop, launchd, cloud routines, GitHub, teyla.toml): did it run, what vanished
  teyla schedules forget KEY [KEY...]                              acknowledge VANISHED tasks removed on purpose (clears the banner)
  teyla reviews [--days N] [--json] [--quiet] [repo...]            review debt: merged PRs never reviewed, merged with an open P1, skipped
  teyla review [list|pull|triage ID|open IDS...]                   the inbox of review captures: pull from the relay and TestFlight, triage to fix|rule|reject, lane brief
  teyla taste [list|confirm ID|render [repo]]                      the taste ledger: rule proposals, the owner's confirm, DESIGN.md rendered from the files
  teyla products [path...]                                       real-usage counters from every repo's ./check.sh usage
  teyla routines [path...] [--json]                               routines + manual checks from every repo's teyla.toml
  teyla check <product> <check> ok|broken [--note TEXT]            confirm a manual check: status + today's date in its teyla.toml
  teyla digest [--write] [--no-notify]                            the weekly digest: the top three actions, each with its command
  teyla routine install|status|catch-up [--if-stale] [--dry]     Teyla's own daily (update+doctor) and weekly launchd routines; catch-up runs what launchd skipped
  teyla grok-cost [--last|--session ID] [--cwd PATH] [--days N] [--by project|session] [--json]   Grok CLI cost at list price
  teyla mcp [--list-tools]                                       Teyla as an MCP server on stdio: asks, answer, intent, load, routines, monitor
  teyla connectors [--days N] [--json]                             per-connector round-trips, read/write, empty-or-error rate; advice C1–C4
  teyla plugins [name|path] [--json]                              skill/rule/fact quality pass over a Claude Code plugin
  teyla plugin install <source>                                   install a plugin by hand-editing its registry (no `claude` CLI)
  teyla plugin uninstall <name>                                   reverse it
  teyla plugin refresh [--force]                                  bring the installed plugin copy to this package's version
  teyla harness status|sync [--dry]                               the same skills, hooks and policy in Cursor, Codex, Grok, Hermes
  teyla harness verify [--live] [--timeout S] [--json]           can each harness do work now; --live sends one line through each
  teyla rule "<sentence>" [--scope <glob>]                        a rule into .claude/rules/, mirrored into AGENTS.md
  teyla correct "<what was wrong>"                                a correction into ~/.teyla/corrections/<repo>.jsonl, secrets scrubbed
  teyla rules propose [--days 7] [--min 2] [--write]              proposed rule diff from human corrections only; hits on existing rules
  teyla rules stale                                               expired and never-hit rules, as removal candidates (never deleted)
  teyla prompt [name]                                             the prompts shipped with this version (onboard, …); none: list them
  teyla uninstall [--dry] [--keep-data]                           undo every write Teyla made here; --dry lists every file it wrote
  teyla cloud check [repo...] [--json]                            what a cloud session would lack in each repo; exit 1 on a blocker
  teyla cloud inbox [--days N]                                    cloud branches with no PR + open PRs labelled needs-mac
  teyla cloud prep <repo> [--dry] [--allow-public] [--fix-gitignore]   AGENTS.md shipping section, hooks, rules, setup doc for cloud sessions
  teyla reel list [--since 24h] [--repo NAME] [--all]             sessions (Claude Code and Codex) with repo, span, commits, PRs
  teyla reel story|check <session-id|story.json> [--ask TEXT] [--seconds N] [-o FILE]   the redacted Story as JSON; every string a reel would show
  teyla reel product [repo] [--input MOVIE] [--copy FILE] [--lang L,..] [--formats vertical,square] [--voice [--yes]] [--dry]   a product demo from a screen recording, with captions from the copy table
  teyla kit init|check [repo] [--force|--json]                   the brand kit: scaffold brand/kit.toml; fail a kit with a missing piece, an asset without provenance, or two characters
  teyla kit shots [repo] [--lang L,..] [--look light|dark|large] [--sizes S,..] [--dry]   store screenshots from the matrix captures and docs/store/captions.json (needs teyla[reel])
  teyla kit image <repo> "<scene>" [--model M] [--yes] [--dry]    one image of the mascot from the reference images; prints the price, refuses without --yes
  teyla kit compare <repo> "<scene>" [--models a,b] [--poses 10] [--yes]   ten poses, two models, a contact sheet; plan and price only without --yes
  teyla post draft [repo] --channel x|instagram|tiktok|threads|youtube [--event TEXT] [--text TEXT]   a post checked against the voice chart, into brand/posts/queue/
  teyla post pack [repo] [--event TEXT] [--week YYYY-Www]        the weekly flagship pack (one reel, one screenshot set, three posts) as a checklist
  teyla docs check [repo...] [--all] [--json] [--strict]         README opening, quick start, length, dead commands, decision history in docs
  teyla ux check [repo...] [--all] [--json] [--strict]           literals instead of tokens, crowded screens, copy rules, DESIGN.md
  teyla ux shots <repo> [--check-manifest] [--dry] [--runs N] [--budget-min N] [--keep-temp] [--strict]   capture matrix: light/dark/large text x languages, 3 runs, a11y + layout checks
  teyla ux diff <repo>                                            design/shots against design/shots/baseline: changed, new, missing, unstable; exit 1 on any
  teyla ux accept <repo> --yes [--allow-unstable]                 make the run the baseline, record who and when
  teyla ux judge A.png B.png [--repo R] [--both-orders] [--dry]  which of two screens is better on the five rubric items; --calibrate REPO against your decided pairs
  teyla scout design [--week W] [--dry] [--no-model]            the weekly design scout: what changed, at most two rule proposals
  teyla hosts [repo...] [--all] [--write] [--json] [--quiet]    every host a repo's code can reach, by file and line, against docs/PRIVACY.md; exit 1 on an undocumented host
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

from . import __version__
from .adapters import load_all, since_epoch
from .advise import advise
from .monitor import metrics
from .report import markdown, to_json


def _sessions(args):
    ss = load_all(since=since_epoch(getattr(args, "days", None)))
    if getattr(args, "project", None):
        ss = [s for s in ss if args.project in s.project or (s.cwd and args.project in s.cwd)]
    if getattr(args, "no_sidechain", True):
        ss = [s for s in ss if not s.sidechain]
    return ss


def _grok_week(rows=None):
    """This week's Grok cost, for A13/A14. Not part of metrics(): it reads updates.jsonl of the
    week's sessions, and the report window (--days) is not the week."""
    from . import grokcost
    try:
        return grokcost.week(rows=rows)
    except Exception:  # noqa: BLE001 — advisory only
        return None


def _cloud_sessions(days):
    """Cloud sessions from `Claude-Session:` commit trailers, for A19 and the report section.
    Not part of metrics(): it reads git, not transcripts, and may ask gh for PR state."""
    from . import cloud
    try:
        return cloud.scan_sessions(days=days)
    except Exception:  # noqa: BLE001 — advisory only
        return []


def _grok_rows(days):
    """Grok list-price cost rows for the headless section's window (≤ 29 days), or None."""
    from .adapters import grok
    try:
        return grok.session_costs(since=since_epoch(min(days or 29, 29)))
    except Exception:  # noqa: BLE001 — advisory only
        return None


def _harness_errors(days):
    """Quota/balance/auth errors each installed harness recorded in the window (A18)."""
    from . import health
    try:
        return health.window_errors(days or 29)
    except Exception:  # noqa: BLE001 — advisory only
        return []


def _extras(m, sessions, days):
    """What monitor and advise add to metrics(): Grok's cost in the headless rows and this week's
    Grok cost (one read of Grok's usage serves both), and the harness errors."""
    from .monitor import headless
    rows = _grok_rows(days)
    if rows is not None:
        m["headless"] = headless(sessions, days, grok_rows=rows)
    m["grok_week"] = _grok_week(rows if (days or 29) >= 7 else None)
    m["harness_errors"] = _harness_errors(days)


def _deliver(text: str) -> bool:
    """Write `text` to stdout and flush it. True only when it reached the pipe: stdout is
    buffered, so `sys.stdout.write` returning says nothing about a closed `| head` or a full
    disk, and a finding marked seen on that say-so is never shown (caught in review, P2)."""
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
        return True
    except (OSError, ValueError):
        try:  # keep the interpreter's exit flush from raising a second time
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return False


def cmd_monitor(args):
    from . import policy
    from .monitor import redact, scrub_home
    from .detect import enrich
    ss = _sessions(args)
    m = enrich(metrics(ss, args.days))
    _extras(m, ss, args.days)
    m["cloud_sessions"] = _cloud_sessions(args.days)
    if args.share:
        # Redact before advising: findings quote projects, sessions and connectors in their
        # evidence, and computed from the raw metrics they would carry the real names out
        # (caught in review, P1: A17 named the project that drives the volume).
        m = redact(m); args.samples = False
    F = advise(m, policy.status())
    out = to_json(m, F) if args.json else markdown(m, F, include_samples=args.samples)
    if args.share:
        out = scrub_home(out)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(out)
        delivered = _deliver(f"wrote {args.out}\n")
    else:
        delivered = _deliver(out)
    # Only after the report was delivered: an unwritable --out, or a closed pipe, must not
    # silence the never-acknowledged A10 on the next run (caught in review, P2).
    if not delivered:
        return 1
    if getattr(args, "no_mark_seen", False):   # tests build a bare Namespace
        return
    from .advise import mark_seen
    mark_seen(F)


def cmd_advise(args):
    from . import policy
    from .detect import enrich
    ss = _sessions(args)
    m = enrich(metrics(ss, args.days))
    _extras(m, ss, args.days)
    m["cloud_sessions"] = _cloud_sessions(args.days)
    F = advise(m, policy.status())
    text = "".join(f"[{f['severity']}] {f['id']} {f['title']}\n    {f['evidence']}\n    → {f['action']}\n" for f in F)
    if not _deliver(text):
        return 1
    from .advise import mark_seen
    mark_seen(F)


def cmd_sessions(args):
    ss = sorted(_sessions(args), key=lambda s: s.first or "")
    if args.days:
        import datetime as dt
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)).isoformat()
        ss = [s for s in ss if (s.first or "") >= cutoff]
    print(f"{'day':10} {'harness':12} {'sid':8} {'MB':>5} {'h':>5} {'turns':>5} {'corr':>4} {'out':>6} {'agents':>6}  project / title")
    for s in ss:
        t = s.tokens
        # A batch session (`claude -p`, `codex exec`, `grok -p`) has no human turns to count.
        turns, corr = ("batch", "-") if s.batch else (s.n_user, s.n_corr)
        print(f"{s.day:10} {s.harness:12} {s.sid[:8]:8} {s.size/1e6:5.1f} {s.hours or 0:5.1f} {turns:>5} {corr:>4} {t['output_tokens']/1e3:5.0f}k {len(s.agents):6}  {s.project[:40]} · {(s.title or s.first_prompt)[:60].replace(chr(10),' ')}")


def correction_rows(sessions):
    """(day, project, sid, text) for every correction-shaped human turn. Batch sessions — a
    pipeline calling `grok -p` a thousand times with the same brief — have no human turns to
    cluster, and their prompt would otherwise top every list."""
    rows = [(s.day, s.project, s.sid[:8], t.text) for s in sessions if not s.batch for t in s.user_turns if t.corr]
    rows.sort()
    return rows


def cmd_corrections(args):
    if args.recorded:
        # What `teyla correct`, the capture hook and inbox rejections stored — ~/.teyla/corrections/
        # plus any pre-0.12 <repo>/.teyla/corrections.jsonl under code_root — not the transcripts.
        from . import corrections
        import datetime as dt
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)).isoformat() if args.days else ""
        for key, rec in corrections.all_records():
            if str(rec.get("ts") or "") < cutoff or (args.project and args.project not in key + str(rec.get("cwd") or "")):
                continue
            print(f"{str(rec.get('ts') or '')[:10]} {key[:30]:30} {str(rec.get('text') or '')[:200].replace(chr(10), ' ')}")
        return
    rows = correction_rows(_sessions(args))
    if args.cluster:
        c = Counter(r[3].lower().strip()[:60] for r in rows)
        for k, n in c.most_common(40):
            if n >= 2:
                print(f"{n:3}  {k}")
        return
    for day, proj, sid, txt in rows:
        print(f"{day} {proj[:30]:30} {sid}  {txt[:200].replace(chr(10),' ')}")


def cmd_policy(args):
    from . import policy
    failed: list[str] = []
    if args.action == "init":
        msg = policy.init(force=args.force, owner=args.owner, dry=args.dry, work=args.work)
        print(msg)
        from . import config
        # Roots: an explicit flag, else what an existing policy's Layout section says, else the default.
        layout = policy.layout_roots()
        args.code_root = args.code_root or layout.get("code_root") or "~/repos"
        args.ops_root = args.ops_root or layout.get("ops_root") or "~/ops"
        if layout:
            print(f"layout from policy: code_root={layout.get('code_root', '-')} ops_root={layout.get('ops_root', '-')}")
        if not args.dry:
            print(config.write(code_root=args.code_root, ops_root=args.ops_root, force=args.force))
            if policy.POLICY.exists() and not policy.is_own() and (not policy.BASE_PATH.exists() or msg.startswith("wrote")):
                # A freshly written policy is the template itself; its base must be that same
                # template, or the first refresh after `--work --force` merges the home one back in.
                policy.BASE_PATH.parent.mkdir(parents=True, exist_ok=True)
                policy.BASE_PATH.write_text(policy.render_template(args.owner or policy._owner_from(policy.POLICY.read_text())))
                print(f"recorded template base at {policy.BASE_PATH}")
            if args.work:
                # Safe mode goes on even when the policy step was refused: it only ever makes this
                # machine do less. But the command succeeds only when both halves hold — a work
                # laptop left on the home policy must not read "done" (Codex review).
                try:
                    set_msg = config.set_value("safe.enabled", "true")
                except OSError as e:
                    set_msg = f"could not write {config.CONFIG_PATH}: {e}"
                print(set_msg)
                if not (set_msg.startswith("set ") and config.safe_mode()):
                    failed.append(f"safe mode: {set_msg}")
                else:
                    print("safe mode on: no network without --allow-network, no self-update, no repo commands "
                          "outside [products] repos, no hand-edited plugin registry — `teyla doctor` shows it")
                if not policy.is_work():
                    failed.append(f"work policy: {policy.POLICY} is still the home template ({msg}) — "
                                  "rerun with --force to replace it (a dated backup is kept)")
        if args.claude_md:
            msg = policy.init_claude_md(owner=args.owner, merge_rule=args.merge_rule, code_root=args.code_root,
                                        ops_root=args.ops_root, force=args.force, dry=args.dry)
            print(msg)
            if msg.startswith("wrote"):
                # Teyla wrote it, so Teyla acknowledges it: otherwise A10 fires for weeks on an
                # edit Teyla itself made, and the fix depends on the owner remembering that.
                print(policy.ack(note="written by `teyla policy init --claude-md`"))
        if args.ops_root_init:
            for line in policy.init_ops_root(args.ops_root, owner=args.owner, code_root=args.code_root, dry=args.dry):
                print(line)
        if failed:
            for f in failed:
                print(f"teyla policy init --work: FAILED — {f}", file=sys.stderr)
            return 1
        return 0
    elif args.action == "status":
        for k, v in policy.status().items():
            print(f"{k:14} {'ok' if v else ('not installed' if v is None else 'MISSING')}")
    elif args.action == "sync":
        # --quiet: unattended (the daily routine, and session-start.sh in the background when
        # CLAUDE.md or POLICY.md is newer than a generated copy): nothing printed when nothing
        # changed, one line per file written otherwise; POLICY.md and CLAUDE.md are never created or edited.
        for line in policy.sync(dry=args.dry, owner=args.owner, unattended=args.quiet):
            if not (args.quiet and line == "already in sync"):
                print(line)
    elif args.action == "inbox":
        if args.done or args.all:
            for line in policy.inbox_done(args.done, everything=args.all):
                print(line)
        else:
            print(policy.inbox_summary())
    elif args.action == "sync-repo":
        for p in args.paths:
            print(policy.sync_repo(p, dry=args.dry, prefer=args.prefer))
    elif args.action == "ack":
        print(policy.ack(note=args.note))
    elif args.action == "refresh":
        if args.resolved:
            print(policy.resolved())
        else:
            for line in policy.refresh(dry=args.dry):
                print(line)


def cmd_harvest(args):
    from .harvest import harvest
    print(harvest(args.path, project=args.project))


def cmd_products(args):
    from .products import table
    print(table(args.paths or None))


def cmd_probe_sql(args):
    from .products import probe_sql
    code, lines = probe_sql(args.ref, args.sql, args.prefix)
    print("\n".join(lines))
    return code




def cmd_routines(args):
    from .routines import evaluate_all, render_text, render_json, summarize, exit_code, write_lines
    if getattr(args, "issues", False):
        from . import net
        if not net.gate("`teyla routines --issues` (it calls GitHub through gh)"):
            return 1
    reports = evaluate_all(args.paths or None)
    write_lines(reports)  # the one-liners the session-start hook shows; only the CLI writes them
    from . import digest
    digest.write_banner_items()  # routines not running and broken checks reach the banner
    if getattr(args, "issues", False):
        from .routines import open_issues
        for line in open_issues(reports):
            print(line)
    if args.json:
        print(json.dumps(render_json(reports), indent=2))
    else:
        print(render_text(reports))
    n, m, k = summarize(reports)
    return exit_code(n, m, k)


def cmd_routine(args):
    from . import routine_install
    if args.action == "catch-up":
        lines = routine_install.catch_up(dry=args.dry, heal=True)
        if not args.quiet or any("MISSED" in l or "REPAIR" in l for l in lines):
            for line in lines:
                print(line)
        return 0
    if args.action == "install":
        for line in routine_install.install(if_stale=getattr(args, "if_stale", False), dry=args.dry):
            print(line)
    elif args.action == "status":
        for line in routine_install.status():
            print(line)


def cmd_prompt(args):
    """Print a prompt shipped with this installed version; without a name, list them."""
    from . import prompts_dir
    d = prompts_dir()
    names = sorted(p.stem for p in d.glob("*.md"))
    if not args.name:
        print("\n".join(names))
        return 0
    if args.name not in names:
        print(f"no prompt {args.name!r}; one of: {', '.join(names)}", file=sys.stderr)
        return 1
    sys.stdout.write((d / f"{args.name}.md").read_text())
    return 0


def cmd_help(args):
    from .helpgroups import cmd_help as grouped
    return grouped(list(args.words or []))


def cmd_scaffold(args):
    from .scaffold import scaffold
    for line in scaffold(args.path, name=args.name, kind=args.kind, license=args.license, owner=args.owner):
        print(line)


class _Parser(argparse.ArgumentParser):
    """The top-level parser prints the grouped help (`teyla --help`) and a one-line error. A
    subcommand's parser is the plain argparse one: its own options are what `teyla X --help` shows."""
    _top = False

    def format_help(self) -> str:
        if self._top:
            from . import helpgroups
            from .ui import Style
            return helpgroups.render(False, Style(sys.stdout)) + "\n"
        return super().format_help()

    def error(self, message: str):
        if self._top:
            print(f"teyla: {message}. Run `teyla help` for the commands.", file=sys.stderr)
            raise SystemExit(2)
        super().error(message)


def build_parser() -> argparse.ArgumentParser:
    """The whole parser, built in-process (`teyla docs check` reads its subcommands from here)."""
    from . import config as _config
    p = _Parser(prog="teyla", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p._top = True
    p.add_argument("--version", action="version", version=__version__)
    sp = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("monitor", cmd_monitor), ("advise", cmd_advise), ("sessions", cmd_sessions), ("corrections", cmd_corrections)):
        q = sp.add_parser(name); q.set_defaults(fn=fn)
        q.add_argument("--days", type=int); q.add_argument("--project")
        if name == "monitor":
            q.add_argument("--json", action="store_true"); q.add_argument("--samples", action="store_true"); q.add_argument("--out")
            q.add_argument("--share", action="store_true", help="redact: pseudonymous projects, connectors and skills; no session ids, paths or correction text")
            # teyla mcp: an agent's call is not the owner reading the report, so it must not use up A10.
            q.add_argument("--no-mark-seen", action="store_true", help=argparse.SUPPRESS)
        if name == "corrections":
            q.add_argument("--cluster", action="store_true")
            q.add_argument("--recorded", action="store_true", help="the stored corrections (teyla correct, capture hook), not transcript turns")
    q = sp.add_parser("policy"); q.set_defaults(fn=cmd_policy)
    q.add_argument("action", choices=["init", "status", "sync", "sync-repo", "ack", "refresh", "inbox"]); q.add_argument("paths", nargs="*")
    q.add_argument("--resolved", action="store_true", help="refresh: the merge conflict is resolved in POLICY.md; move the base forward")
    q.add_argument("--dry", action="store_true"); q.add_argument("--force", action="store_true")
    q.add_argument("--owner", help="your name, written into POLICY.md (default: login name)")
    q.add_argument("--work", action="store_true", help="init: the work-laptop policy (approved providers only, same-provider reviews) and safe mode on")
    q.add_argument("--claude-md", action="store_true", help="init: also write ~/.claude/CLAUDE.md from the global template if absent")
    q.add_argument("--merge-rule", help='init --claude-md: the merging sentence (default: "open the PR/MR, then stop")')
    q.add_argument("--code-root", help="init: where repos live (default: the Layout section of an existing POLICY.md/CLAUDE.md, else ~/repos)")
    q.add_argument("--ops-root", help="init: the ops root (default: from the Layout section, else ~/ops)")
    q.add_argument("--ops-root-init", action="store_true", help="init: also create the ops root (CLAUDE.md, .claude/, wiki-ready, runs/ ignored)")
    q.add_argument("--prefer", choices=["agents", "claude"], help="sync-repo: when AGENTS.md and CLAUDE.md both exist and differ, keep this one and symlink the other to it")
    q.add_argument("--note", help="ack: free-text note recorded alongside the acknowledgement")
    q.add_argument("--quiet", action="store_true", help="sync: unattended (the daily routine runs it): silent when nothing changed, one line per file written; never creates POLICY.md or edits CLAUDE.md")
    q.add_argument("--done", metavar="FILE", help="inbox: mark one pending hand edit done (its file is deleted)")
    q.add_argument("--all", action="store_true", help="inbox: mark every pending hand edit done")
    q = sp.add_parser("harvest"); q.set_defaults(fn=cmd_harvest); q.add_argument("path"); q.add_argument("--project")
    from . import grokcost, wiki, feedback, models, plugins, plugin_install, connectors, control, doctor, update, remind, rules, harness, storage, cloud, lang
    from . import platform as platform_mod, productize as productize_mod
    doctor.register(sp); update.register(sp); _config.register(sp)
    platform_mod.register(sp); productize_mod.register(sp)
    from . import testflight as testflight_mod
    testflight_mod.register(sp)
    from . import play as play_mod
    play_mod.register(sp)
    wiki.register(sp); feedback.register(sp); models.register(sp)
    plugins.register(sp); plugin_install.register(sp); connectors.register(sp); control.register(sp)
    remind.register(sp); rules.register(sp); harness.register(sp); storage.register(sp)
    from . import uninstall as uninstall_mod
    uninstall_mod.register(sp); grokcost.register(sp)
    from . import digest as digest_mod, routines as routines_mod
    digest_mod.register(sp); routines_mod.register_check(sp)
    cloud.register(sp); lang.register(sp)
    from . import reviews as reviews_mod
    reviews_mod.register(sp)
    from . import intent as intent_mod
    intent_mod.register(sp)
    from . import schedules as schedules_mod
    schedules_mod.register(sp)
    from . import spend as spend_mod
    spend_mod.register(sp)
    from . import lanes as lanes_mod
    lanes_mod.register(sp)
    from . import prose as prose_mod
    prose_mod.register(sp)
    from . import voice as voice_mod
    voice_mod.register(sp)
    from . import tidy as tidy_mod
    tidy_mod.register(sp)
    from . import load as load_mod
    load_mod.register(sp)
    from . import guard as guard_mod
    guard_mod.register(sp)
    from . import crash as crash_mod
    crash_mod.register(sp)
    from .reel import cli as reel_cli
    reel_cli.register(sp)
    from . import asks as asks_mod
    asks_mod.register(sp)
    from . import mcp as mcp_mod
    mcp_mod.register(sp)
    from . import today as today_mod
    today_mod.register(sp)
    q = sp.add_parser("help", help="the commands in six groups; --all lists every one; help COMMAND shows its options")
    q.set_defaults(fn=cmd_help); q.add_argument("words", nargs="*", metavar="[--all | COMMAND]")
    from . import registry as registry_mod
    registry_mod.register(sp)
    from . import notes as notes_mod
    notes_mod.register(sp)
    from . import state as state_mod
    state_mod.register(sp)
    from . import portfolio as portfolio_mod
    portfolio_mod.register(sp)
    from . import answer as answer_mod
    answer_mod.register(sp)
    from . import relay as relay_mod
    relay_mod.register(sp)
    from . import review as review_mod
    review_mod.register(sp)
    from . import taste as taste_mod
    taste_mod.register(sp)
    from . import dispatch as dispatch_mod
    dispatch_mod.register(sp)
    from . import docs_check as docs_check_mod
    docs_check_mod.register(sp)
    from . import ux_check as ux_check_mod
    ux_check_mod.register(sp)
    from . import scout_design as scout_design_mod
    scout_design_mod.register(sp)
    from . import hosts as hosts_mod
    hosts_mod.register(sp)
    from . import leak as leak_mod
    leak_mod.register(sp)
    from . import leak_install as leak_install_mod
    leak_install_mod.register(sp)
    from . import kit as kit_mod, post as post_mod
    kit_mod.register(sp)
    post_mod.register(sp)
    from . import copy_lane as copy_lane_mod
    copy_lane_mod.register(sp)
    from . import start as start_mod
    start_mod.register(sp)
    from . import web as web_mod
    web_mod.register(sp)
    q = sp.add_parser("products"); q.set_defaults(fn=cmd_products); q.add_argument("paths", nargs="*")
    q = sp.add_parser("probe-sql", help="one read-only Supabase query for ./check.sh usage; prints key=value")
    q.set_defaults(fn=cmd_probe_sql); q.add_argument("ref", help="Supabase project ref")
    q.add_argument("sql", help="a query returning one row; column aliases become the keys")
    q.add_argument("--prefix", default="", help="prepended to every key, e.g. hub_")
    q = sp.add_parser("routines"); q.set_defaults(fn=cmd_routines)
    q.add_argument("paths", nargs="*"); q.add_argument("--json", action="store_true")
    q.add_argument("--issues", action="store_true", help="open one GitHub issue per BROKEN check (needs gh)")
    q.add_argument("--allow-network", action="store_true", help="safe mode: allow gh for this one run")
    q = sp.add_parser("routine"); q.set_defaults(fn=cmd_routine)
    q.add_argument("action", choices=["install", "status", "catch-up"])
    q.add_argument("--if-stale", action="store_true", help="install: only rewrite when a wrapper names a binary that moved or a plist is missing")
    q.add_argument("--dry", action="store_true", help="install: list what it would write and load; catch-up: say which runs launchd skipped, run nothing")
    q.add_argument("--quiet", action="store_true", help="catch-up: print only when something was missed")
    q = sp.add_parser("prompt", help="print a paste-able prompt shipped with this version (onboard, work-account-kickoff, ...)")
    q.set_defaults(fn=cmd_prompt); q.add_argument("name", nargs="?")
    q = sp.add_parser("scaffold"); q.set_defaults(fn=cmd_scaffold)
    q.add_argument("path")
    q.add_argument("--name", required=True)
    q.add_argument("--kind", choices=["cli", "app", "service", "ios"], default="cli")
    q.add_argument("--license", choices=["apache", "mit", "none"], default="apache")
    q.add_argument("--owner", help="copyright holder written into the LICENSE (default: git config user.name)")
    return p


def _commands(parser: argparse.ArgumentParser) -> list[str]:
    for act in parser._actions:
        if isinstance(act, argparse._SubParsersAction):
            return list(act.choices)
    return []


def _friendly(e: Exception, cmd: str) -> str:
    """One line for a failure a new user can hit: what is missing and how to fix it."""
    from .control import state as control
    if isinstance(e, ModuleNotFoundError) and e.name and not e.name.startswith("teyla"):
        pkg = {"PIL": "pillow"}.get(e.name.split(".")[0], e.name.split(".")[0])
        return (f"teyla: `teyla {cmd}` needs the Python package '{pkg}', which is not installed. "
                f"Fix: uv tool install --force --python 3.12 --with {pkg} git+https://github.com/zaitsew/teyla")
    if isinstance(e, OSError) and getattr(e, "filename", None):
        where = str(e.filename)
        if where.startswith(str(control.home())):
            return (f"teyla: cannot read {where} ({e.strerror or type(e).__name__}). "
                    "`teyla doctor` shows what is missing or has the wrong permissions.")
    return f"teyla: `teyla {cmd}` failed: {type(e).__name__}: {e}. Set TEYLA_DEBUG=1 for the traceback."


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    from . import leak_install as _leak_install
    argv = _leak_install.alias(argv)      # `teyla leak install|terms` -> leak-install|leak-terms
    # ~/.teyla/config.toml [env] first: under launchd or the desktop app's session hook this is
    # the only place SSL_CERT_FILE or a proxy can come from, and it must be set before any socket.
    from . import config as _config
    _config.apply_env()
    # The first screen, and the help, need no parser: they must stay fast and never fail.
    if not argv:
        from . import welcome
        return welcome.run()
    if argv[0] in ("-h", "--help", "help"):
        from . import helpgroups
        return helpgroups.cmd_help(argv[1:])
    parser = build_parser()
    if not argv[0].startswith("-") and argv[0] not in _commands(parser):
        from . import helpgroups
        return helpgroups.unknown(argv[0], _commands(parser))
    args, extra = parser.parse_known_args(argv)
    # argparse stops filling a positional list at the first option, so `teyla asks done --note x
    # id1 id2` would reject id1 id2. Bare words left over go back into that command's list.
    # After "--" everything is a word, even "-x": `teyla answer <id> --json -- <text>`.
    before, after = (extra[:extra.index("--")], extra[extra.index("--") + 1:]) if "--" in extra else (extra, [])
    if extra and isinstance(getattr(args, "words", None), list) and not any(e.startswith("-") for e in before):
        args.words += before + after
    elif extra:
        parser.error("unrecognized arguments: " + " ".join(extra))
    from . import net, invisible
    net.allow_for_this_command(getattr(args, "allow_network", False))
    try:
        return args.fn(args)
    except invisible.InvisibleText as e:
        # Any rule or policy write that met a hidden character: nothing was written; say where.
        print(f"teyla: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001 — a person typing a command gets one line, not a traceback
        if os.environ.get("TEYLA_DEBUG"):
            raise
        print(_friendly(e, getattr(args, "cmd", "") or argv[0]), file=sys.stderr)
        return 1


if __name__ == "__main__":
    main()
