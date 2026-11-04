# Startups: one page per company

Status: 2026-11-04. This file is the data contract for `teyla startup`, the `startup` block in
`teyla portfolio`, and the YC sheet. The apps show what this contract returns and compute nothing.

The page answers one question: **what is the next fact this product is missing?**

## Rules

- **A stage is earned, not typed.** It comes from records a command can read. No command sets it.
- **Zero, unknown and stale are three different answers.** No probe is unknown, not zero. An unknown value is `null`.
- **Every figure has an as-of time.** A usage probe older than 7 days makes its rungs `stale`, and a stale rung earns nothing.
- **Agents do not earn stages.** A record written from an agent session is `claimed` and does not count until the owner
  confirms it. Detection reads the harness environment variables. It stops mistakes, not an attacker on the same account.
- **A product nobody tried to sell is "not tried yet".** Nothing here proposes closing it (POLICY §19).
- **No percent-ready score, and no rank of YC fit across products.**
- **Teyla never submits an application.** It prepares answers. The owner applies.
- **Nothing leaves the machine.** This feature adds no network call. Money comes from the keys a product's own
  `./check.sh usage` prints (`mrr_usd`, `paying_users`, `revenue_30d_usd`, see `templates/analytics/STANDARD.md`).
- **Customer text stays off the relay.** The relay is signed, not encrypted. The `startup` block carries fixed labels and
  numbers only. YC answers live in `~/.teyla/startup/`, mode 0600, and never enter `teyla state`.

## Type

`teyla product set <id> type=<type>`. The owner chooses it. Teyla never infers it. It is stored in `~/.teyla/products.toml`.

| Type | North star | Last rung |
|---|---|---|
| `venture` | Weekly growth of revenue, or of weekly users while it does not charge | Growing |
| `indie` | Revenue above its AI cost | Sustaining |
| `open-source` | People other than the author using it weekly | Retained |
| `personal` | The owner still uses it after 30 days | Kept |
| unset | Uses the `venture` ladder and shows "type not chosen" | Growing |

A `personal` product has no sale rungs. It is left out of the "not tried yet" count and the marketing bonus.

The registry `stage` (`idea, building, beta, live, parked`) stays. It says what the owner is doing with the product.
The earned stage says what the evidence shows. A parked product keeps its rungs and shows `parked`.

## The ladder

Each rung is checked on its own. An achievement out of order stays visible. `stage` is the last rung of the unbroken run
from the start. `next` is the first rung that is not met.

A product with 25 accounts and no sale attempt reads "Built", with Used shown as met and Tried as next. That is the point.

| Rung | Types | Met when | Source |
|---|---|---|---|
| Built | all | someone can install it (`progress.can_install`), registry stage is `beta` or `live`, or accounts exist. `unknown` when Teyla sees no store or site for it | portfolio, usage probe |
| Tried | venture, indie, open-source | at least 1 published post, ad, outreach or ICP meeting not claimed by an agent | growth ledger |
| Used | venture, indie, open-source | at least 1 external account | usage probe |
| Retained | venture, indie, open-source | at least 3 external people returned at day 7 | usage probe |
| Paid | venture, indie | at least 1 payer, or revenue above 0 in 30 days | usage probe |
| Repeating | venture, indie | at least 3 payers, or revenue in 2 consecutive 30-day windows | usage probe, snapshots |
| Growing | venture | at least 5% a week on average over 4 weeks, on revenue, else on weekly users | snapshots |
| Sustaining | indie | revenue in 30 days above AI cost in 30 days | usage probe, session spend |
| Used by me | personal | weekly users of at least 1 | usage probe |
| Kept | personal | weekly users of at least 1 on snapshots 30 days apart | snapshots |

These numbers are operating defaults, not benchmarks and not YC requirements. Paul Graham's 5% to 7% a week describes
companies inside a batch. It is not an entry test. A retention rate is shown only for a cohort of at least 30.

**External people.** A probe may print `external_users`, `external_wau` and `external_retained_7d`. Otherwise Teyla subtracts
one account for the owner from `users_total`, `wau` and `retained_7d`, and the output says `assumed`.

A rung's status is one of `met`, `missing`, `unknown`, `stale`, `not_applicable`.

## Metrics

At most 15. Each is `null` when no source reports it.

| Group | Metric |
|---|---|
| Marketing | Posts in total, posts in 7 days, ads and outreach |
| Sales | ICP conversations in total, in 30 days, last attempt day |
| Usage | External people, weekly users, retained at day 7, new in 7 days |
| Monetization | Enabled, payers, MRR, revenue in 30 days, AI cost in 30 days |
| Growth | Weekly growth rate and the number of weeks behind it |

Snapshots: `~/.teyla/startup/snapshots.jsonl`, one row per product per day, written by `teyla portfolio --refresh` and kept
for 400 days. Growth is `null` until 4 weeks exist.

## The focus product

`teyla startup` leads with one product: the highest external weekly users among products that are not `personal` or parked,
then the highest retained, then the id. `teyla product core` does not change this. Every other product is one line.

## The YC sheet

The boxes are the questions a YC partner asks in the 10-minute interview, taken from a founder's list and not from a YC
script. **A box means "I can answer this honestly, with evidence". It does not mean "this number is good".** A true $0 checks
"What they pay". Revenue never blocks an application.

| Box | Question | Checked when |
|---|---|---|
| `building` | What are you building? | The owner confirmed an answer |
| `customer` | Pick one customer | Used is met, and the owner confirmed an answer |
| `does` | What does it do for them? | The owner confirmed an answer |
| `using` | Are they using it? | Usage is fresh, so the answer is a true number, including 0 |
| `pay` | What do they pay? | Money is known, or monetization is off so the answer is $0 |
| `why_you` | Why you? | The owner confirmed an answer |
| `custom` | Is it custom software per customer? | The owner confirmed an answer |
| `goal` | What is the Demo Day goal? | The owner confirmed an answer |
| `who` | Who does what? | The owner confirmed an answer, including what agents do |
| `talked` | How many customers have you talked to? | At least 1 ICP conversation not claimed by an agent |
| `sell` | How do you sell it? | Tried is met, and the owner confirmed an answer |
| `demo` | Show us the demo | Built is met, and the owner recorded a demo link |
| `first_live` | When did the first customer go live? | Used is met, and the owner confirmed an answer |
| `need` | What do they need most? | The owner confirmed an answer |
| `commit` | Can you commit to the batch? | The owner confirmed an answer. It is in person in San Francisco. Not on the list; added by us |

**All 15 checked: the sheet says "Apply" with the link to `ycombinator.com/apply`.** Otherwise it says how many are checked
and names the next box, with its command. The count is a plain "9 of 15". It is never a percent.

The sheet exists for `venture` and unset products. One application is one company: YC's FAQ advises against two applications.

An agent may draft an answer. A draft does not check a box until the owner confirms it.

### YC facts, read on ycombinator.com on 2026-11-04

They are stored in `src/teyla/startup_yc.py` with this date. The sheet warns when they are older than 90 days.

- Winter 2027 runs January to March in San Francisco. The on-time deadline was November 2. Late applications are open.
- YC says to apply as soon as you are ready. It says about 40% of the companies it funds in each batch are just an idea, and most have no revenue.
- YC regularly accepts solo founders, and says one-person startups are tough.
- The deal is $500,000: $125,000 for 7%, plus $375,000 on an uncapped MFN SAFE.

The sheet prints these beside the count, so an unchecked box never reads as "you may not apply".

## Commands

```
teyla startup [--json]                     the focus product, then one line per product
teyla startup show <id> [--json]           the ladder, the metrics and the next fact
teyla startup yc [<id>] [--json]           the sheet; the focus product when no id is given
teyla startup yc answer <id> <box> <text>  write an answer (from an agent session it stays a draft)
teyla startup yc confirm <id> <box>        confirm a draft; refused in an agent session
teyla startup yc export <id>               the answers as Markdown, for pasting
teyla product set <id> type=<type>         choose the type
```

## JSON

`teyla portfolio --json` adds `startup` to each product, and `teyla state` carries it. Fixed labels and numbers only.

```json
{"type": "venture", "type_set": true, "stage": "built", "stage_title": "Built", "parked": false,
 "as_of": "2026-11-04T10:00:00Z", "stale": false,
 "next": {"rung": "tried", "text": "Nobody has tried to sell it yet.", "command": "teyla growth"},
 "rungs": [{"id": "built", "title": "Built", "status": "met", "detail": "Installable"}],
 "metrics": {
   "marketing": {"posts": 0, "posts_7d": 0, "ads_outreach": 0},
   "sales": {"icp_meetings": 0, "icp_meetings_30d": 0, "last": "", "claimed": 0},
   "usage": {"external": 24, "external_assumed": true, "wau": 7, "retained_7d": 2, "new_7d": 2},
   "money": {"enabled": false, "paying": null, "mrr_usd": null, "revenue_30d_usd": null, "ai_cost_30d_usd": 12.5},
   "growth": {"weekly_pct": null, "weeks": 0, "on": "wau"}},
 "yc": {"eligible": true, "checked": 3, "total": 15, "next_box": "building"}}
```

`teyla startup --json` returns `{"version": 1, "as_of", "focus": <id or null>, "counts": {<stage>: <n>}, "products": [...]}`,
each product with `id`, `title` and this block. `teyla startup yc --json` adds the box rows and the answers, and is for the
Mac app only.
