# Design sources

What `teyla scout design` reads each week to see what changed in design (docs/SCOUT.md). Seeded on
2026-10-30 with the feeds that answered a fetch that day (docs/STUDIO.md §3). A source that stops
answering is marked in the weekly file under "Not read"; remove its row after three weeks of that.

The scout reads the rows of the tables below whose **Kind** is `rss`, `atom` or `hig`. A row of any
other kind is a note for a person or an agent and is never fetched. To use another list, copy this file
and run `teyla scout design --sources FILE`. Sources are free; X and paid libraries sit in the last section
and stay off until a priced yes (POLICY §11).

| Kind | How the scout reads it |
|---|---|
| `rss` | RSS 2.0: each `item` with a title, an https link and a date |
| `atom` | Atom: each `entry` with a title, an https alternate link and an `updated` or `published` date |
| `hig` | One JSON per Apple HIG page. The **Pages** cell lists the slugs; `metadata.customMetadata` holds `alert-date` and `alert-text`, the date and the one-line summary of the page's latest change |
| `html` | Not fetched. A page a person or an agent opens |

## Read every week (on by default)

| Source | Kind | URL | Pages | How to read it |
|---|---|---|---|---|
| Apple Developer News | rss | https://developer.apple.com/news/rss/news.rss | | Platform and design announcements. The feed is about 400 KB; only the newest items matter |
| Apple Developer Releases | rss | https://developer.apple.com/news/releases/rss/releases.rss | | OS and tool releases: what a new iOS or Xcode build changes for a screen |
| Apple Newsroom | atom | https://www.apple.com/newsroom/rss-feed.rss | | Press releases, including the Apple Design Awards winners |
| MacStories | rss | https://www.macstories.net/feed/ | | What the system UI just did, with screenshots; the iOS and iPadOS review each September |
| Daring Fireball | atom | https://daringfireball.net/feeds/main | | Short link posts and essays on Apple platforms and interface taste |
| Nielsen Norman Group | rss | https://www.nngroup.com/feed/rss/ | | Research-backed articles on usability; the source for any claim with a number |
| Smashing Magazine | rss | https://www.smashingmagazine.com/feed/ | | Mostly web; the interface, accessibility and design-system pieces apply |
| UX Collective | rss | https://uxdesign.cc/feed | | Community essays; read for the pattern, check the claim elsewhere |
| iOS Dev Weekly | rss | https://iosdevweekly.com/issues.rss | | One issue a week: the best links of the iOS week, SwiftUI first |
| SwiftLee | rss | https://www.avanderlee.com/feed/ | | SwiftUI and Xcode practice, short and dated |
| Swift with Majid | atom | https://swiftwithmajid.com/feed.xml | | SwiftUI APIs and what changed in them each release |
| Sarunw | rss | https://sarunw.com/rss.xml | | Small SwiftUI and UIKit how-tos |
| Lenny's Newsletter | rss | https://www.lennysnewsletter.com/feed | | Product practice; onboarding, activation and retention |
| Apple Human Interface Guidelines | hig | https://developer.apple.com/tutorials/data/design/human-interface-guidelines/<slug>.json | writing, buttons, tab-bars, toolbars, sheets, searching, onboarding, accessibility, typography, color, layout, settings, loading, dark-mode, materials | The page behind a rule in the standard. An item appears the week its `alert-date` falls in the window. The human page is `https://developer.apple.com/design/human-interface-guidelines/<slug>` |

## Read by hand or by an agent (no feed)

| Source | Kind | URL | Pages | How to read it |
|---|---|---|---|---|
| Apple Design Awards | html | https://developer.apple.com/design/awards/ | | Once a year, in June. The 2026 winners and finalists (Moonlitt for interaction, grug for delight, Structured a finalist) feed `REFERENCE.md`. Each app's description is on the page |
| Dribbble | html | https://dribbble.com/ | | Behind a bot wall on 2026-10-30; not fetched |
| Growth.Design | html | https://growth.design/ | | Case studies, no feed on 2026-10-30 |

## Needs a priced yes (X reads cost $0.005 a post)

Off by default, and the scout has no fetcher for these kinds. X's API charges $0.005 per post read and
$0.015 per post written (https://docs.x.com/x-api/getting-started/pricing). Turning this section on is a
POLICY §11 charge: state the price per week, ask twice, and only then add a fetcher. A weekly scrape of X
"will learn listicles and prompt art", so the 20-item cap and the two-proposal cap stand. Paid reference
libraries (Mobbin's and Refero's MCP servers) belong here too: look the price up before asking.

| Source | Kind | URL | Pages | How to read it |
|---|---|---|---|---|
| @viticci | x | https://x.com/viticci | | What the system UI just did, with screenshots |
| @Dimillian | x | https://x.com/Dimillian | | UI a strong indie shipped |
| @drbarnard | x | https://x.com/drbarnard | | When a design skill or a library fails, by name |
