# Review notes: template

Copy this into the product's `docs/APP-STORE.md` (and the Play Console's app-access note). Fill every
bracket. The example product, "Trailnote", is invented. Never put an infrastructure detail here: no
host names, project ids, keys or internal paths. `teyla shield check <repo> --release` fails when the
DATA paragraph is missing.

## Reviewer instructions

Sign in with the demo account in the review information field (a plan that unlocks every feature).
Trailnote works offline after sign-in. Open the Map tab to see sample trips, which are bundled and
need no account. Tap the microphone in a note to record a voice memo; the system asks for permission
once.

## DATA

DATA: Trailnote collects the account e-mail address, the notes and photos you add, and your location
while a trip is recording. Notes and photos are stored on the device and, when you turn on sync, in
the app's own database, protected by per-user access rules. Location is used on the device to draw a
trip and is uploaded only for trips you choose to share. Voice memos are sent to a speech-to-text
provider and the text is returned; the audio is not kept. Providers that receive data: the speech
provider (voice memos), and the hosting provider (synced notes). No data is sold, used for tracking
or shared with advertisers. To delete: Settings, Account, Delete account removes the account and
every synced note and photo within 30 days. Generated text is labelled, and a report button sits on
every generated result.

## BUSINESS MODEL

Trailnote is free. There is no purchase, subscription or paywall in this build. The included
transcription allowance is free: 30 minutes a month, resetting on the first of the month. The app has
no field for a personal API key.

## CAPABILITIES

- Location (while using): draws the trip path on the Map tab. Open any trip, then tap Record.
- Microphone: voice memos in a note. Open a note, then tap the microphone.
- Photos (add only): attach a picture to a note. The app cannot read the rest of the library.
- Notifications: a reminder on the day of a trip. Settings, Reminders.
- China mainland is excluded from availability because the generative features need a permit that
  the providers do not hold.
