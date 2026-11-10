# Usage capture: the paperwork for a product that adopts it

Copy this into the product's PR that wires `TeylaUsage` (POLICY section 17: the paperwork ships in the
same PR). It states what the package records. Do not widen a sentence without widening the code first,
and do not narrow it: `packages/review-ios/Tests/TeylaReviewTests/UsageTests.swift` holds the facts.

Fill the `<…>` marks. Everything else is true for every product that uses the package unchanged.

## 1. Privacy policy: the line to add

> **Test builds.** If you install a test version of the app (through TestFlight), it can record which screens
> you open, which buttons you use and how each action ended, how long a task takes, and which design option
> was switched on, together with the build number. It never records what you type, titles, names, contacts or
> your location. Events carry a random number made for this installation, not your name, account or device
> name. The app asks you once before it sends anything; if you choose "Not now", nothing is sent and what was
> recorded is deleted. They go to a server run by <owner>, which deletes its copy when the developer collects
> it, usually within the hour. The developer keeps the events for 180 days. The version in the App Store
> records and sends nothing of this kind.

Keep the store policy's "no analytics" statement true: it stays true because the store build holds none of
this. If the owner's own device sends without a notice, say so only in the internal notes below, not to the
public: the owner is the developer.

## 2. `docs/ANALYTICS.md`: the section to add

```markdown
## Usage capture (test builds only)

- **Package:** TeylaReview `TeylaUsage` (packages/review-ios), no third-party SDK.
- **Where it runs:** Debug and TestFlight (`TeylaReview.isActive`). The App Store configuration defines no
  `TEYLA_REVIEW_ENABLED` and holds no channel key, so it records and sends nothing; `teyla review store-check`
  runs before every store upload.
- **Events:** session (start, background, end), screen, action (id and result), task (start, success, cancel,
  with duration), dead_end, repeat_tap. Fields: time, kind, id, result, milliseconds, build, design variants.
- **Declared ids:** screens <list or "see the configure call in <file>">, actions <…>, tasks <…>.
  Anything else is dropped on the device.
- **Identity:** a random UUID made on first use, kept in the app's defaults. No IDFA, no vendor id, no device
  name, no account id, no free text.
- **Consent:** the owner's device (paired with the owner's Mac) sends on its own; every other tester sees one
  Allow / Not now notice. Not now deletes the buffer and stops recording.
- **Storage:** on the device, a ring buffer of 5,000 events or 1 MB. On the review server, until the Mac's next
  pull (within the hour). On the Mac, `~/.teyla/usage/<product>/`, 180 days.
- **Questions it answers:** <the decision ids this product measures, one line each, for example
  "nav: do people reach Trips faster with the bottom bar?" → `teyla usage <product> --before <build> --after <build>`>.
- **Not done:** funnels across weeks, per-person profiles, session replay, any text content.
```

## 3. App Privacy answer (App Store Connect) for test builds

TestFlight builds are not reviewed against the App Privacy label. The label describes the App Store build,
which records nothing: answer "Data Not Collected" for usage data as long as the store configuration holds
no usage capture. If a later store version ships `TeylaUsage` on, the answers become:

| Question | Answer |
|---|---|
| Data type | Usage Data > Product Interaction |
| Collected | Yes |
| Linked to the user's identity | No (a random install id; no account, no device name) |
| Used for tracking | No |
| Purposes | Analytics, App Functionality |

That change is a store submission with its own review: do not ship it by accident. `store-check` fails an
archive that holds the channel key.

## 4. `PrivacyInfo.xcprivacy`

- **No change** while the store build records nothing: the package adds no tracking domain and uses no
  required-reason API for this feature. It reads `UserDefaults` (already declared by most apps, reason
  `CA92.1`) for the consent answer and the install id, and writes a file in Application Support. File
  timestamps are not read.
- `NSPrivacyTracking` stays `false` and `NSPrivacyTrackingDomains` stays empty.
- If the store build ever turns capture on, add `NSPrivacyCollectedDataTypeProductInteraction` with
  `NSPrivacyCollectedDataTypeLinked` false, `NSPrivacyCollectedDataTypeTracking` false and purposes
  `NSPrivacyCollectedDataTypePurposeAnalytics`.

## 5. Internal notes (not public)

- Wire it with `TeylaUsage.configure(screens:actions:tasks:)` at launch and `.usageConsentNotice()` on the root
  view. Translate `ReviewStrings.usage*` into every language the product ships, like the capture notice.
- Declare ids only: route names, accessibility identifiers, job names. Never a title, a name or a value read
  from the user's data. A dynamic suffix (`row.<uuid>`, `row-12`) is stripped before the check.
- The channel service must run the version of `packages/review-channel/server.py` that accepts `usage.json`.
- After the PR: `teyla review pull --channel`, then `teyla usage <product>`.
