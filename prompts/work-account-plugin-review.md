# Teyla review for a work account — an internal plugin, Claude activity, connectors

Upload this one file to Claude Code on the work machine (it is self-contained) and say **"Run the Teyla work review."**
Output stays on the work machine; you decide what to share back. The share-back file is designed
to contain **no** employer content: no ticket keys, doc titles, customer or colleague names,
message text, URLs, or code. Read it before sharing anyway.

## Scope for Claude

Three subjects, one report:

**A. The internal plugin** (the plugin you built; find it under `~/.claude/plugins/`, a repo
in the workspace, or wherever `claude plugin list` points).
1. Inventory: plugin.json, every skill (name + one-line description + word count + last modified),
   every command, hooks (event → script), MCP servers declared, rules. Table.
2. Quality pass on each SKILL.md against the Teyla test: *a skill is a procedure done the same way
   every time; constraints belong in rules; facts belong in notes.* Flag skills that mix the three,
   skills over one screen, skills without trigger phrases in the description, two skills whose
   descriptions overlap (ambiguous routing), and a skill that produces two artifact types.
3. Usage: from local transcripts (`~/.claude/projects`), count invocations per skill/command and the
   MCP tools called (names only). List never-used skills. For used ones, the last 5 invocation dates.
4. Failure modes: sessions where a skill was invoked and the next human turn was a correction
   (report count + the correction *shape*, never the text).

**B. Claude activity** — run the portable Teyla miner embedded at the end of this file
(`python3 mine.py ~/.claude/projects teyla-report.json`; stdlib only; aggregates only). If you have exported claude.ai
data (`conversations.json`), pass it as the third argument to count desktop/web conversations and
their tool uses separately.

**C. Connectors — messaging, issue tracker / wiki (e.g. Jira/Confluence), file storage (e.g. Drive).**
Only aggregates, only from local logs:
1. For each connector: number of sessions that used it, tool names called with counts (e.g.
   `search_issues` 41, `get_page` 12), read vs write split (count tools whose name implies a write:
   create/update/post/send/comment/transition).
2. Round-trips per outcome: median number of connector calls between a human turn and the next
   human turn, per connector — high numbers mean the agent is searching blind.
3. Failure rate: tool results that are errors or empty (count only), per connector.
4. Which PM jobs the connector use maps to (bucket by the skill or the human prompt's *shape*:
   status update, ticket triage, spec drafting, release notes, meeting prep, research) — counts only.

## Report

Write `teyla-work-report.md` with these sections, aggregates only:

```
# Teyla work review — <date>
## A. The internal plugin
### Inventory (table)
### Skill quality (table: skill · size · mixes rule/fact? · routing risk · verdict)
### Usage (table: skill · invocations · last used · corrections after)
### Recommendations (≤5: split/merge/retire/rewrite, each with the evidence line)
## B. Claude activity (the headline block from the portable report)
## C. Connectors
### Per-connector table: sessions · calls · read/write · error rate · median round-trips
### Jobs served (counts by bucket)
### Recommendations (≤5: a skill to write, a connector to stop using for X, a rule)
## D. Top 3 changes to make this week (each: evidence → exact edit)
## E. Feedback to Teyla
- what the prompt could not measure here
- which advice looked wrong for a corporate PM context
- what a corporate version of Teyla would need (SSO? no local logs? a Confluence page instead of a repo?)
```

Then: apply the changes that are file edits inside the plugin (after showing the diff), and stop.

## How this feeds Teyla

You share `teyla-work-report.md` (only that file) with the maintainer; it is published under
`docs/case-studies/` only with your consent and after a second redaction pass. Section E is the product feedback: it becomes issues. Sections A and C are the
first evidence of what a *connector-heavy PM* setup looks like, which the personal repos do not have.
Nothing else from the work machine is needed. A work machine usually cannot push to GitHub; the transport is
copy-paste of one markdown file.


## The miner (save as `mine.py`)

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
