# Teyla adoption review — portable prompt

Upload this file to any Claude Code session (or paste it) and say: **"Run the Teyla adoption review."**
It needs nothing installed. It reads local session logs and your Claude Code setup, computes
**aggregates only**, and writes two files you can share back without leaking work content.

Everything it produces stays on this machine until you decide to share `teyla-report.md`.

## What Claude should do

1. **Create the output directory** `./teyla-review/<today>/` in the current working directory.
2. **Run the miner below** with `python3` (stdlib only). It writes `teyla-report.json` and prints a summary.
   If `~/.claude/projects` is absent, say so and continue with steps 3–5 on whatever exists.
3. **Inventory the setup** (write `setup.md`): every plugin under `~/.claude/plugins/` (name, version,
   skills, commands, hooks, MCP servers it declares), every `.claude/skills/*/SKILL.md` and
   `.claude/rules/*.md` in the workspace, `CLAUDE.md` / `AGENTS.md` word counts, `settings.json` hooks,
   and `claude mcp list` output (names and status only — no URLs with tokens, no headers).
4. **Cross-reference usage vs inventory**: which skills/commands/MCP tools were invoked (counts from the
   report's `skills` and `tools`), which never were, which corrections repeat.
5. **Write `teyla-report.md`** using the template at the end. Aggregates only. **Never include**: message
   text, file paths under the workspace, ticket keys, document titles, people's names, customer names,
   URLs, or anything from tool results. Counts, rates, model names, tool *names*, skill *names* are fine. Project identifiers are not: number them p01, p02.
6. **Advise**: the top three changes, each with the evidence line from the report and one concrete edit
   (a `model:` override, a rule sentence for `.claude/rules/`, a session-splitting habit, a skill to
   write, a hook to add). Apply the ones that are pure file edits in the workspace; list the rest.
7. **Feedback to Teyla** (last section): what this prompt could not measure, which advice looked wrong,
   what metric would have helped. This is how the tool improves.

## The miner

Save as `teyla-review/<today>/mine.py` and run `python3 mine.py ~/.claude/projects teyla-report.json`.
Optional second store: if a claude.ai data export (`conversations.json`) is present, pass it as a third
argument; it is counted separately.

```python
#!/usr/bin/env python3
"""Teyla portable miner — aggregates only. stdlib. Schema teyla.report.v1-portable."""
import json, sys, os, re, glob, collections, datetime, hashlib
root, out = sys.argv[1], sys.argv[2]
export = sys.argv[3] if len(sys.argv) > 3 else None
CORR = re.compile(r"\b(no[,.!]|not like that|don'?t|do not|wrong|again|stop|undo|revert|actually|instead|i said|i told|why did|you should have|never|always|shouldn'?t)\b", re.I)
KEYS = ("input_tokens","cache_creation_input_tokens","cache_read_input_tokens","output_tokens")
def text_of(c):
    if isinstance(c,str): return c
    return "\n".join(b.get("text","") for b in c or [] if isinstance(b,dict) and b.get("type")=="text")
S=[]
for f in sorted(glob.glob(os.path.join(os.path.expanduser(root),"*","*.jsonl"))):
    s=dict(project=os.path.basename(os.path.dirname(f)), sid=os.path.basename(f)[:8], size=os.path.getsize(f),
           first=None,last=None,models=collections.Counter(),usage=collections.defaultdict(collections.Counter),
           tools=collections.Counter(),skills=collections.Counter(),agents=collections.Counter(),
           user=0,corr=0,corr_norm=[],compactions=0,gov_edits=0,sidechain=False)
    for line in open(f,errors="replace"):
        try: o=json.loads(line)
        except: continue
        t=o.get("type"); ts=o.get("timestamp")
        if ts: s["first"]=s["first"] or ts; s["last"]=ts
        if o.get("isSidechain"): s["sidechain"]=True
        if t=="system" and "compact" in line.lower(): s["compactions"]+=1
        if t=="assistant":
            m=o.get("message",{}); model=m.get("model","?"); s["models"][model]+=1
            u=m.get("usage") or {}
            for k in KEYS: s["usage"][model][k]+=u.get(k,0) or 0
            for b in m.get("content") or []:
                if isinstance(b,dict) and b.get("type")=="tool_use":
                    n=b.get("name"); s["tools"][n]+=1; inp=b.get("input",{}) or {}
                    if n in ("Agent","Task"): s["agents"][inp.get("model") or "inherit"]+=1
                    elif n=="Skill": s["skills"][inp.get("skill")]+=1
                    if (n in ("Edit","Write","MultiEdit") and str(inp.get("file_path","")).endswith(".claude/CLAUDE.md")) or (n=="Bash" and ".claude/CLAUDE.md" in str(inp.get("command","")) and re.search(r"(>|sed -i|write_text|tee )",str(inp.get("command","")))): s["gov_edits"]+=1
        elif t=="user":
            c=o.get("message",{}).get("content")
            if isinstance(c,list) and any(isinstance(b,dict) and b.get("type")=="tool_result" for b in c): continue
            txt=text_of(c).strip()
            if not txt or o.get("isMeta") or txt.startswith("<"): continue
            s["user"]+=1
            if len(txt)<800 and CORR.search(txt):
                s["corr"]+=1; s["corr_norm"].append(hashlib.sha1(re.sub(r"\W+"," ",txt.lower()).strip().encode()).hexdigest()[:10])
    if s["first"]: S.append(s)
def hours(s):
    try:
        a=datetime.datetime.fromisoformat(s["first"].replace("Z","+00:00")); b=datetime.datetime.fromisoformat(s["last"].replace("Z","+00:00"))
        return round((b-a).total_seconds()/3600,1)
    except: return None
main=[s for s in S if not s["sidechain"]]
tok=collections.Counter(); by_model=collections.defaultdict(collections.Counter); agents=collections.Counter()
tools=collections.Counter(); skills=collections.Counter(); corr_norm=collections.Counter(); by_project=collections.Counter(); by_week=collections.Counter()
giant=[]; gov=[]
for s in main:
    for m,u in s["usage"].items(): by_model[m].update(u); tok.update(u)
    agents.update(s["agents"]); tools.update(s["tools"]); skills.update(s["skills"]); corr_norm.update(s["corr_norm"])
    by_project[s["project"]]+=sum(u["output_tokens"] for u in s["usage"].values())
    by_week[s["first"][:7]]+=1
    h=hours(s)
    if s["size"]>8e6 or (h or 0)>12 or s["compactions"]>=3: giant.append(dict(sid=s["sid"],day=s["first"][:10],mb=round(s["size"]/1e6,1),hours=h,compactions=s["compactions"],turns=s["user"]))
    if s["gov_edits"]: gov.append(dict(sid=s["sid"],day=s["first"][:10],edits=s["gov_edits"]))
user=sum(s["user"] for s in main); corr=sum(s["corr"] for s in main)
rep=dict(schema="teyla.report.v1-portable", generated=datetime.date.today().isoformat(), harness="claude-code",
    n_sessions=len(main), n_subagent_transcripts=len(S)-len(main), tokens=dict(tok), by_model={m:dict(u) for m,u in by_model.items()},
    subagents=dict(agents), subagent_inherit_rate=round(agents["inherit"]/sum(agents.values()),2) if agents else None,
    user_turns=user, corrections=corr, correction_rate=round(corr/user,3) if user else None,
    repeated_corrections=[dict(count=n,fingerprint=k) for k,n in corr_norm.most_common(15) if n>=2],  # irreversible hashes, no text
    cache_read_ratio=round(tok["cache_read_input_tokens"]/max(1,tok["output_tokens"]),1),
    giant_sessions=sorted(giant,key=lambda g:-g["mb"])[:20], governance_file_edits=gov,
    tools=dict(tools.most_common(40)), skills=dict(skills), sessions_by_month=dict(sorted(by_week.items())),
    projects=len(by_project))
if export and os.path.exists(export):
    try:
        conv=json.load(open(export)); msgs=0; tool_names=collections.Counter(); n=0
        for c in conv:
            n+=1
            for m in c.get("chat_messages",[]):
                msgs+=1
                for b in m.get("content",[]) or []:
                    if isinstance(b,dict) and b.get("type")=="tool_use": tool_names[b.get("name")]+=1
        rep["claude_ai_export"]=dict(conversations=n,messages=msgs,tool_uses=dict(tool_names.most_common(40)))
    except Exception as e: rep["claude_ai_export"]=dict(error=str(e)[:100])
json.dump(rep,open(out,"w"),indent=1)
print(json.dumps({k:v for k,v in rep.items() if k not in ("tools","by_model")},indent=1)[:4000])
```

## Report template (`teyla-report.md`)

```
# Teyla adoption report — <org or "personal"> — <date>
window: all local history · sessions: N · subagent transcripts: N · projects: N

## Headline
| output tokens | cache read | cache write | fresh input |
| orchestrate-tier share (name the models) | subagent calls / inherited | human turns / corrections (rate) | cache-read per output | giant sessions | governance-file edits |

## Setup inventory (from setup.md, names only)
plugins · skills · commands · hooks · MCP servers (name, status)

## Used vs never used
| skill/command/tool | invocations | verdict (keep / fix / retire) |

## Repeated corrections (fingerprints only — look the text up locally with the miner, write the rule, never paste the text here)
| count | fingerprint | proposed rule (your words, no content from the turn) |

## Advice (top 3, each with evidence line + the exact edit)

## Applied in this session
## Left for the human

## Feedback to Teyla
- could not measure: …
- advice that looked wrong: …
- metric that would have helped: …
```
