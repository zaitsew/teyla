"""teyla — command line.

  teyla monitor [--days N] [--json] [--samples] [--share] [--out FILE]   adoption report from local harness logs
  teyla advise  [--days N]                                       just the findings
  teyla sessions [--days N] [--project SUBSTR]                   one line per session
  teyla corrections [--days N] [--project SUBSTR]                correction-shaped human turns, clustered
  teyla policy init [--owner] [--claude-md] [--ops-root-init] [--dry]   POLICY.md, global CLAUDE.md, an ops root
  teyla policy status|sync [--dry]                                the wiring into every harness
  teyla policy sync-repo <path>... [--prefer agents|claude]      AGENTS.md ⇄ CLAUDE.md in repos
  teyla policy ack [--note TEXT]                                  record acceptance of ~/.claude/CLAUDE.md's current hash
  teyla policy refresh [--dry] [--resolved]                       three-way merge of template changes into ~/.agents/POLICY.md
  teyla harvest <path> [--project SLUG]                          tool spine + corrections for sessions touching a path
  teyla models [--days N] [--json] [--refresh]                   model ladder + price drift report
  teyla models --write-policy [--dry] [--drop-absent]             rewrite the ladder table in ~/.agents/POLICY.md
  teyla models --write-prices                                     ~/.teyla/prices.json from models.dev
  teyla wiki init|status|lint|confirm <path> [slug]              the facts store as an LLM-maintained wiki
  teyla feedback [--days N] [--out FILE]                         one redacted file to send to the maintainer
  teyla run <product:routine> [--dry] [--force]                  the run engine: grants, caps, gate A/B/C, receipt
  teyla inbox [list|show|approve|reject]                          the needs-you inbox
  teyla kill [on|off|status]                                       global kill switch
  teyla triggers [list|install|uninstall]                          clock triggers → LaunchAgents
  teyla promote <product:routine> --gate B|C                       earned autonomy on counted evidence
  teyla receipts <product:routine>                                 what ran, under which rules and grants
  teyla doctor [--quiet] [--json] [--refresh]                    what must be true here, and the fix for each thing that is not
  teyla config show | set KEY=VALUE                               ~/.teyla/config.toml, incl. [env] for launchd/hook runs
  teyla update [--check] [--force] [--wire] [--quiet]            newer release → install, then policy sync/refresh, plugin refresh, routines
  teyla platform [init|env-example] [--json] [--no-net]          the shared resources set up once, and the step for each missing one
  teyla productize [path...] [--json] [--owner-steps]            what stands between each product and its second user
  teyla products [path...]                                       real-usage counters from every repo's ./check.sh usage
  teyla routines [path...] [--json]                               routines + manual checks from every repo's teyla.toml
  teyla routine install|status [--if-stale]                       Teyla's own daily (update+doctor) and weekly launchd routines
  teyla connectors [--days N] [--json]                             per-connector round-trips, read/write, empty-or-error rate; advice C1–C4
  teyla plugins [name|path] [--json]                              skill/rule/fact quality pass over a Claude Code plugin
  teyla plugin install <source>                                   install a plugin by hand-editing its registry (no `claude` CLI)
  teyla plugin uninstall <name>                                   reverse it
  teyla plugin refresh [--force]                                  bring the installed plugin copy to this package's version
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

from . import __version__
from .adapters import load_all
from .advise import advise
from .monitor import metrics
from .report import markdown, to_json


def _sessions(args):
    ss = load_all()
    if getattr(args, "project", None):
        ss = [s for s in ss if args.project in s.project or (s.cwd and args.project in s.cwd)]
    if getattr(args, "no_sidechain", True):
        ss = [s for s in ss if not s.sidechain]
    return ss


def cmd_monitor(args):
    from . import policy
    from .monitor import redact
    ss = _sessions(args)
    m = metrics(ss, args.days)
    F = advise(m, policy.status())
    if args.share:
        m = redact(m); args.samples = False
    out = to_json(m, F) if args.json else markdown(m, F, include_samples=args.samples)
    if args.out:
        open(args.out, "w").write(out); print(f"wrote {args.out}")
    else:
        sys.stdout.write(out)


def cmd_advise(args):
    from . import policy
    m = metrics(_sessions(args), args.days)
    for f in advise(m, policy.status()):
        print(f"[{f['severity']}] {f['id']} {f['title']}\n    {f['evidence']}\n    → {f['action']}")


def cmd_sessions(args):
    ss = sorted(_sessions(args), key=lambda s: s.first or "")
    if args.days:
        import datetime as dt
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)).isoformat()
        ss = [s for s in ss if (s.first or "") >= cutoff]
    print(f"{'day':10} {'harness':12} {'sid':8} {'MB':>5} {'h':>5} {'turns':>5} {'corr':>4} {'out':>6} {'agents':>6}  project / title")
    for s in ss:
        t = s.tokens
        print(f"{s.day:10} {s.harness:12} {s.sid[:8]:8} {s.size/1e6:5.1f} {s.hours or 0:5.1f} {s.n_user:5} {s.n_corr:4} {t['output_tokens']/1e3:5.0f}k {len(s.agents):6}  {s.project[:40]} · {(s.title or s.first_prompt)[:60].replace(chr(10),' ')}")


def cmd_corrections(args):
    ss = _sessions(args)
    rows = [(s.day, s.project, s.sid[:8], t.text) for s in ss for t in s.user_turns if t.corr]
    rows.sort()
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
    if args.action == "init":
        print(policy.init(force=args.force, owner=args.owner, dry=args.dry))
        from . import config
        # Roots: an explicit flag, else what an existing policy's Layout section says, else the default.
        layout = policy.layout_roots()
        args.code_root = args.code_root or layout.get("code_root") or "~/repos"
        args.ops_root = args.ops_root or layout.get("ops_root") or "~/ops"
        if layout:
            print(f"layout from policy: code_root={layout.get('code_root', '-')} ops_root={layout.get('ops_root', '-')}")
        if not args.dry:
            print(config.write(code_root=args.code_root, ops_root=args.ops_root, force=args.force))
            if policy.POLICY.exists() and not policy.BASE_PATH.exists():
                policy.BASE_PATH.parent.mkdir(parents=True, exist_ok=True)
                policy.BASE_PATH.write_text(policy.render_template(args.owner))
                print(f"recorded template base at {policy.BASE_PATH}")
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
    elif args.action == "status":
        for k, v in policy.status().items():
            print(f"{k:14} {'ok' if v else ('not installed' if v is None else 'MISSING')}")
    elif args.action == "sync":
        for line in policy.sync(dry=args.dry, owner=args.owner):
            print(line)
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




def cmd_routines(args):
    from .routines import evaluate_all, render_text, render_json, summarize, exit_code
    reports = evaluate_all(args.paths or None)
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
    if args.action == "install":
        for line in routine_install.install(if_stale=getattr(args, "if_stale", False)):
            print(line)
    elif args.action == "status":
        for line in routine_install.status():
            print(line)


def cmd_scaffold(args):
    from .scaffold import scaffold
    for line in scaffold(args.path, name=args.name, kind=args.kind, license=args.license):
        print(line)


def main(argv=None):
    # ~/.teyla/config.toml [env] first: under launchd or the desktop app's session hook this is
    # the only place SSL_CERT_FILE or a proxy can come from, and it must be set before any socket.
    from . import config as _config
    _config.apply_env()
    p = argparse.ArgumentParser(prog="teyla", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=__version__)
    sp = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("monitor", cmd_monitor), ("advise", cmd_advise), ("sessions", cmd_sessions), ("corrections", cmd_corrections)):
        q = sp.add_parser(name); q.set_defaults(fn=fn)
        q.add_argument("--days", type=int); q.add_argument("--project")
        if name == "monitor":
            q.add_argument("--json", action="store_true"); q.add_argument("--samples", action="store_true"); q.add_argument("--out")
            q.add_argument("--share", action="store_true", help="redact: pseudonymous projects, no session ids, no correction text")
        if name == "corrections":
            q.add_argument("--cluster", action="store_true")
    q = sp.add_parser("policy"); q.set_defaults(fn=cmd_policy)
    q.add_argument("action", choices=["init", "status", "sync", "sync-repo", "ack", "refresh"]); q.add_argument("paths", nargs="*")
    q.add_argument("--resolved", action="store_true", help="refresh: the merge conflict is resolved in POLICY.md; move the base forward")
    q.add_argument("--dry", action="store_true"); q.add_argument("--force", action="store_true")
    q.add_argument("--owner", help="your name, written into POLICY.md (default: login name)")
    q.add_argument("--claude-md", action="store_true", help="init: also write ~/.claude/CLAUDE.md from the global template if absent")
    q.add_argument("--merge-rule", help='init --claude-md: the merging sentence (default: "open the PR/MR, then stop")')
    q.add_argument("--code-root", help="init: where repos live (default: the Layout section of an existing POLICY.md/CLAUDE.md, else ~/repos)")
    q.add_argument("--ops-root", help="init: the ops root (default: from the Layout section, else ~/ops)")
    q.add_argument("--ops-root-init", action="store_true", help="init: also create the ops root (CLAUDE.md, .claude/, wiki-ready, runs/ ignored)")
    q.add_argument("--prefer", choices=["agents", "claude"], help="sync-repo: when AGENTS.md and CLAUDE.md both exist and differ, keep this one and symlink the other to it")
    q.add_argument("--note", help="ack: free-text note recorded alongside the acknowledgement")
    q = sp.add_parser("harvest"); q.set_defaults(fn=cmd_harvest); q.add_argument("path"); q.add_argument("--project")
    from . import wiki, feedback, models, plugins, plugin_install, connectors, control, doctor, update
    from . import platform as platform_mod, productize as productize_mod
    doctor.register(sp); update.register(sp); _config.register(sp)
    platform_mod.register(sp); productize_mod.register(sp)
    wiki.register(sp); feedback.register(sp); models.register(sp)
    plugins.register(sp); plugin_install.register(sp); connectors.register(sp); control.register(sp)
    q = sp.add_parser("products"); q.set_defaults(fn=cmd_products); q.add_argument("paths", nargs="*")
    q = sp.add_parser("routines"); q.set_defaults(fn=cmd_routines)
    q.add_argument("paths", nargs="*"); q.add_argument("--json", action="store_true")
    q.add_argument("--issues", action="store_true", help="open one GitHub issue per BROKEN check (needs gh)")
    q = sp.add_parser("routine"); q.set_defaults(fn=cmd_routine)
    q.add_argument("action", choices=["install", "status"])
    q.add_argument("--if-stale", action="store_true", help="install: only rewrite when a wrapper names a binary that moved or a plist is missing")
    q = sp.add_parser("scaffold"); q.set_defaults(fn=cmd_scaffold)
    q.add_argument("path")
    q.add_argument("--name", required=True)
    q.add_argument("--kind", choices=["cli", "app", "service", "ios"], default="cli")
    q.add_argument("--license", choices=["apache", "mit", "none"], default="apache")
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    main()
