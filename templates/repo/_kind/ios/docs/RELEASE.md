# Release — {{name}}

## TestFlight and the App Store

Go through the App Store Connect API key. **Never** a password, never the
Xcode GUI, never an app-specific password.

```
<your-release-tool> release --project <path>.xcodeproj --scheme <Scheme> \
    --bundle-id <id> [--also-bundle-id <widget id>]
```

Credentials live once, in `~/.appstoreconnect/`: `config.env` holds the key
id, issuer id and team id (identifiers, not secrets), and
`private_keys/*.p8` is the secret, mode 600 — never print it, never copy it
into this repo. Any agent may cut a release with it; none of it requires
the account holder at the keyboard.

A new machine, or "no signing certificate found", needs

```
<your-release-tool> bootstrap --bundle-id <id>
```

once. If the team cannot use cloud-managed distribution certificates, the
certificate is minted through the REST API with its private key kept local,
and signing is manual. Don't run bootstrap by habit — a second run mints a
second certificate, and Apple allows few.

## Public beta (TestFlight)

1. Ship a build through the release command above.
2. Fill in the beta app review questionnaire in full (age rating included —
   a partial submission gets bounced) before requesting public review.
3. Wait for Apple's beta app review to clear the build for public
   TestFlight — this is separate from, and slower than, internal testing.
4. Share the public link once review clears. Internal testers never need
   this step; they see new builds immediately.

## What never happens here

No password typed into Xcode, no app-specific password, no manual upload
through the Xcode Organizer. If the release command fails on an expired
Xcode session or similar, fix the credential path — don't fall back to the
GUI.
