# Teyla for iPhone: App Store listing and review notes

The text to paste into App Store Connect for `com.zaitsew.teyla` (iPhone). It follows POLICY section 15:
no model provider in the listing, a reviewer who reaches every feature without an account, China
mainland off. The Mac store build shares the record; its text is in `apps/store/listing/macos/`.

The App Store Connect record exists since 2026-10-26: app id **6827052748**, one record for iOS and macOS
(both builds share `com.zaitsew.teyla`), name "Teyla — AI studio inbox", SKU `teyla`, Full Access. The
listing is written by `apps/store/app-store.py` from `apps/store/listing/`; this file keeps the reasons.

## Record

| Field | Value |
|---|---|
| App id | 6827052748 |
| Platform | iOS (iPhone only, `TARGETED_DEVICE_FAMILY` 1) and macOS (the `TeylaStore` target) |
| Name (30 max) | Teyla — AI studio inbox (23). Fallback if taken: Teyla: Studio Inbox (19) |
| Bundle ID | `com.zaitsew.teyla` |
| SKU | `teyla` |
| Primary language | English (U.S.) |
| User access | Full Access |
| Category | Developer Tools (secondary: Productivity) |
| Price | Free, no in-app purchases |
| Availability | Every storefront except China mainland (`CHN`) |
| Version / build | `CFBundleShortVersionString` 0.32.0; `CFBundleVersion` is `CURRENT_PROJECT_VERSION`, which the release script raises |
| Support URL | https://github.com/zaitsew/teyla |
| Privacy policy URL | https://github.com/zaitsew/teyla/blob/main/docs/PRIVACY.md |

**China mainland is excluded** from the first submission. The Mac companion runs AI coding tools, and the
generative-AI rules in China need a permit that no model provider we use holds. An app there also needs an
ICP filing, which needs a Chinese entity. Re-including it is the owner's call.

## Text

**Subtitle (30 max, 29):** Questions, builds, one screen

**Promotional text (170 max, 143):**
See what waits on you and where every product stands on every platform. Answer from your iPhone; your Mac does the work. No account, no server.

**Description:**

```
Teyla is the inbox for a one-person software studio. It shows what waits on you, where every product
stands, and what got done while you were away.

Today
- One sentence on what matters now, then the questions only you can answer, ranked by what they unblock.
- Answer by text or by voice. Voice is turned into text on your iPhone; nothing is sent until you tap Send.
- The tasks only you can do: a pull request to merge, an issue assigned to you.
- What finished since yesterday, and what runs now.
- Questions that have waited more than a week fold into one "Older" section, so fresh ones stay on top.

Portfolio
- Every product with a health word: off track, at risk, on track or parked, and the reason in one line.
- Each platform on its own line: iOS, macOS, Android, web. Version, build and state, such as "current" or "behind".
- Open pull requests, pull requests that wait on you, recent activity and the next step.

How it works
Teyla for iPhone is the companion of Teyla for Mac. The Mac does the work. The iPhone reads a folder in your
own iCloud Drive and leaves signed answers there. There is no Teyla server and no account, and the app
collects no data. No Mac yet? Tap "See a sample" to try every screen with made-up data.

Teyla for iPhone needs Teyla on a Mac to show your own products. It is free and open source.
```

**Keywords (100 max, 94):** `developer,productivity,dashboard,projects,releases,status,portfolio,tasks,builds,agents,coding`

**What's New (0.32.0):** The Portfolio tab shows every product's health and platforms. Questions older than a week fold away. "See a sample" lets you try Teyla without a Mac.

## Age rating

Every question is answered None or No: no violence, sexual content, profanity, horror, alcohol, gambling or
contests, medical content, or unrestricted web access. The app shows text that tools wrote on the user's own
Mac; it generates nothing itself. Result: 4+.

## App Privacy

**Data Not Collected.** The app has no server, no account, no analytics and no advertising. It reads and
writes one iCloud Drive folder the user picks, and recognises speech on the device
(`requiresOnDeviceRecognition`). `PrivacyInfo.xcprivacy` declares no tracking, no tracking domains, no
collected data types, and one required-reason API: UserDefaults (`CA92.1`), for the dictation language, the
chosen folder and unsent answers.

Export compliance: `ITSAppUsesNonExemptEncryption` is `NO`. The app uses HMAC-SHA256 only to authenticate the
files it exchanges with the Mac, and the system Keychain for the shared key. It encrypts nothing itself.

## Review notes

Paste into App Review Information. Sign-in required: No. No demo account is needed.

```
HOW TO SEE EVERYTHING (no account, no Mac needed)
Teyla for iPhone is the companion of Teyla for Mac. A reviewer has no paired Mac, so the app has a sample mode.
1. Launch the app. Tap "See a sample" at the bottom of the first screen.
2. The app opens on Today with made-up data and a banner "Sample data - pair with your Mac to see yours".
   - Today: questions, tasks, finished work, running sessions. Older questions are under "Older".
   - Portfolio: products with health, platforms and reasons. Tap a row for its detail. "Needs attention" filters it.
   - Products: one card per product.
   - Settings (gear icon, top left): version, voice language.
3. Every send action (answering a question, "New task", "Correct") works in the sample, but nothing is sent.
   The app says "Sample: nothing was sent". The banner's Pair button leaves sample mode.

WHAT THE APP DOES WITH A MAC
With Teyla for Mac installed (free, open source: https://github.com/zaitsew/teyla), the owner runs "teyla relay on".
That creates a folder named Teyla in the owner's own iCloud Drive. The iPhone app asks the user to pick that folder
in the system document picker, and pairs by scanning a QR code or pasting a string. The Mac writes a signed state
file there; the iPhone verifies the signature before it shows anything and leaves signed answers for the Mac.
Teyla runs no server and receives nothing.

DECLARED CAPABILITIES
- Camera: scans the pairing QR code shown on the Mac. Needed only when pairing; sample mode never asks for it.
  Camera scanning does not work in the simulator.
- Microphone and Speech Recognition: dictation in the answer field. Recognition runs on the device only
  (requiresOnDeviceRecognition); there is no server fallback, and nothing is sent until the user taps Send.
- No location, no HealthKit, no background modes, no push notifications, no iCloud entitlement (the folder is
  opened through the document picker).

PRIVACY AND DATA
The app collects no data and has no analytics or tracking. App Privacy: Data Not Collected. It does not use the
VPN APIs, and it does not collect data using a VPN.

AI CONTENT
The app does not generate content. It shows text that coding tools wrote on the user's own Mac, such as a question
for the owner. Nothing is generated or filtered on the phone, so there is no in-app reporting flow. Questions and
issues go to the support URL above.

BUSINESS MODEL
Teyla for iPhone is free. Nothing is sold: no in-app purchase, no subscription, no ads, no paid features, no
bring-your-own-key field, and no payment of any kind. The app is the free companion of an open-source tool.

REGIONS
China mainland is excluded. The Mac companion runs AI coding tools, and the generative-AI rules there need a permit
that no model provider we use holds.
```

## Assets

- **Icon.** `Teyla/Assets.xcassets/AppIcon.appiconset/icon-1024.png`, 1024 px, opaque, the brand mark on the
  indigo body filling the whole square. iOS rounds the corners. Regenerate with
  `swift apps/ios/Tools/make_icon.swift`.
- **Screenshots.** The 6.9-inch iPhone set (1320 by 2868 px), five or six images in this order: Today,
  Portfolio, a product detail, Older questions, Products, first screen. `apps/ios/Tools/screenshots.sh`
  makes them from sample mode on a booted simulator and writes them where you point it. The images are not
  committed. The app runs on iPhone only, so no iPad set is needed. Apple scales 6.9-inch images down for the
  smaller iPhones.

## Release

```sh
~/ops/bin/testflight release --project apps/ios/Teyla.xcodeproj --scheme Teyla --bundle-id com.zaitsew.teyla
```

The release tool passes `DEVELOPMENT_TEAM` and raises `CURRENT_PROJECT_VERSION`. Before every submission
check: icon present, `PrivacyInfo.xcprivacy` in the bundle, the built `Info.plist` lists no iPad device family,
the review notes above are pasted, China is off, and the privacy policy URL answers.

## Rejections

A rejection goes here with the guideline, the reason text from the App Review page, the cause and the fix.

### 0.32.0 (1), iOS and macOS — Guideline 4.3(a), Design — Spam (2026-10-26)

Submissions `00ff5f67` (iOS) and `2d865297` (macOS), sent 2026-10-26 09:22 UTC, rejected the same day at 16:30
and 16:31 UTC. Both messages carry the same text. The reason, verbatim from the App Review page:

> We noticed the app shares a similar binary, metadata, and/or concept as apps submitted to the App Store by you
> or other developers, with only minor differences.

Each message adds an "Extended Review" warning: repeated submissions of apps with these issues get longer review
times, and accounts that repeat them face removal from the Apple Developer Program.

**Cause, as far as we can see.** It is not shared code: no Swift file in `apps/` overlaps more than 30% with any
other repository on this machine (shingle comparison, 2026-10-27). Another app on the same team, unrelated in
concept, got the identical 4.3(a) text in the same minute. The team had 15 app records then, most of them created in
the six weeks before, including a second record for an app already on sale and a journal app built on the same
idea as another one on the team. The likeliest reading is an account-level spam signal, not something in Teyla's
binary. Apple has not confirmed it.

**Fix.** No code change answers this. The plan is a reply to App Review that explains what is unique in Teyla and
asks which app it resembles, without a new binary. A resubmission waits until App Review answers or the owner
decides otherwise.

**Sent 2026-10-27, 01:03 UTC**, the same reply on both submissions, on the owner's go-ahead. It says Teyla is the
companion of the owner's own open-source tool in this repository (public since 2026-09-10, 870+ commits), describes
the signed iCloud Drive sync, states that the apps use no template and share no code or assets with other apps on
the account, asks which app Teyla is said to resemble, and points the reviewer to "See a sample". Waiting for App
Review's answer; check it on the App Review page, since the e-mail carries no text.
