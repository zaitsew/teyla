"""Chores: the recurring manual steps an AI session asks the owner to do, and the honest way to hand each one off.

One classifier, two readers. `teyla asks` uses `key_of` to fold repeats of one chore into the newest ask
(docs/ASKS.md, "Same chore"); `teyla you` uses the same key to count chores and to show the path to delegate them
(docs/YOU.md). The classifier is rules, never a model, and a key says *which* chore, not that two questions mean the
same thing: only keys with `collapse=True` are ever folded, and a price, a secret, a device or another person's
matter never is.

`PATHS` is the table of hand-off paths. Each row says what an agent can do, what stays human, and that the path is
"not verified" until the owner marks it tried on this machine (`teyla you chore KEY tried`).
"""
from __future__ import annotations

import dataclasses
import re


@dataclasses.dataclass(frozen=True)
class Chore:
    key: str
    label: str
    path: str           # how to hand it off, as far as it can be handed off
    who: str            # who must still act
    collapse: bool      # asks of this chore may be folded into the newest one


# The order is the priority when a text matches more than one chore. A step on a device comes before any portal,
# so "open Play Console on your phone" is a device step and never folds.
PATHS: tuple[Chore, ...] = (
    Chore("testflight_tap", "Tap View in TestFlight",
          "None. Apple shows a new tester nothing until they tap the invitation e-mail once per app; no API skips it.",
          "You, once per app", False),
    Chore("secret", "Paste an API key, secret or password",
          "One secret store: you paste each secret once, an agent reads it by name and never prints it.",
          "You, once per secret", False),
    Chore("device_check", "Check on a device",
          "A simulator run covers layout. Sensors, Health data and real-network behaviour need the physical device.",
          "You, on the device", False),
    Chore("gcloud_auth", "Sign in to gcloud",
          "A service account for the one project (or workload identity) lets an agent act without your browser. "
          "`gcloud auth login` as yourself needs your browser.",
          "You, once, to create the service account", True),
    Chore("chrome_signin", "Sign Chrome in",
          "Keep a dedicated automation Chrome profile and sign it in once; the session persists. "
          "An agent never types a password or a 2FA code.",
          "You, at each expired session", True),
    Chore("developer_apple", "developer.apple.com",
          "A role-based App Store Connect API key covers identifiers, certificates and profiles. A separate technical "
          "account cannot replace the Account Holder, and scraping the portal is banned by Apple's terms.",
          "You (Account Holder) for agreements and the web sign-in; 2FA stays human", True),
    Chore("app_store_connect", "App Store Connect",
          "A role-based App Store Connect API key (App Manager) covers uploads, builds, metadata and review status "
          "through `testflight`. Agreements, banking and the Account Holder's actions stay with the Account Holder.",
          "You (Account Holder) for agreements; 2FA stays human", True),
    Chore("play_console", "Play Console",
          "A service account with the Google Play Developer API (invited in Play Console, Users and permissions) "
          "covers uploads and release status. Policy forms and the first setup are web-only.",
          "You, once to invite the service account", True),
    Chore("dns", "DNS record",
          "A Cloudflare API token scoped to one zone (DNS edit) lets an agent add records. Registrar changes stay human.",
          "You, once to create the scoped token", False),     # two asks for two different records are two tasks
    Chore("scheduled_task_cleanup", "Scheduled-task cleanup",
          "An agent can list and disable tasks (`teyla schedules`) and ask you to approve the list.",
          "You, to approve the list", True),
)
BY_KEY = {c.key: c for c in PATHS}

_PATTERNS: dict[str, re.Pattern] = {
    "testflight_tap": re.compile(r"view in testflight", re.I),
    "secret": re.compile(
        r"\b(?:api[ -]?keys?|secrets?|passwords?|passcodes?|private keys?|keychain|credentials?|access tokens?|tokens?)\b"
        r"|\.p8\b", re.I),
    "gcloud_auth": re.compile(r"\bgcloud\b.*\b(?:auth|login|credentials)\b|application-default|\bgcloud auth\b", re.I | re.S),
    "chrome_signin": re.compile(
        r"\bchrome\b.{0,80}\b(?:sign(?:ed)?[ -]?in|sign(?:ed)?[ -]?into|log(?:ged)?[ -]?in|session)\b"
        r"|\b(?:sign|log)(?:ged)?[ -]?(?:in|into)\b.{0,80}\bchrome\b|\bsign chrome in\b", re.I | re.S),
    "developer_apple": re.compile(r"developer\.apple\.com|apple developer (?:portal|account|program|website)", re.I),
    "app_store_connect": re.compile(r"app ?store ?connect|appstoreconnect", re.I),
    "play_console": re.compile(r"play console|play developer|play\.google\.com/console", re.I),
    "dns": re.compile(r"\bdns\b|\bcname\b|\bnameservers?\b|\b(?:a|txt|mx) records?\b", re.I),
    "scheduled_task_cleanup": re.compile(
        r"scheduled[- ]tasks?.{0,80}\b(?:disable|delete|remove|clean|turn off|retire|stale)\b"
        r"|\b(?:disable|delete|remove|clean|turn off|retire)\b.{0,80}scheduled[- ]tasks?", re.I | re.S),
    "device_check": re.compile(
        r"\bon (?:your|the|a) (?:real |physical )?(?:iphone|ipad|mac|watch|device|phone|tv)\b|\b(?:physical|real) device\b",
        re.I),
}

# A chore is a request to *do* something. A question that offers a choice or asks for a decision is not one,
# even when it names a portal.
_ACTION = re.compile(
    r"\b(?:sign(?:ed)?[ -]?(?:in|into)|sign \w+ in|log(?:ged)?[ -]?(?:in|into)|login|re-?authenticat\w*|authori[sz]e|tap|click|press|"
    r"open|approve|accept|enable|disable|delete|remove|add|create|paste|set up|invite|renew|refresh|run)\b", re.I)
_CHOICE = re.compile(r"\b(?:which|what|should i|shall i|do you want|would you like|choose|pick|decide|or\b.*\?)", re.I)
MAX_CHARS = 280      # a chore is a short request; a long message is a report or a plan


def key_of(text: str) -> str | None:
    """The chore a text names, by the priority of `PATHS`, or None. Names a chore only: use `is_request` too."""
    t = text or ""
    for c in PATHS:
        if _PATTERNS[c.key].search(t):
            return c.key
    return None


def is_request(text: str, options: int = 0) -> bool:
    """True when the text asks for an action and offers no choice: short, an action word, no options, no
    question about which or what."""
    t = " ".join((text or "").split())
    return bool(t) and not options and len(t) <= MAX_CHARS and bool(_ACTION.search(t)) and not _CHOICE.search(t)


def classify(title: str, question: str, options: int = 0) -> str | None:
    """The chore key of an ask, or None. The title and the question together name the chore; the question
    alone must be a request."""
    key = key_of(f"{title}\n{question}")
    return key if key and is_request(question, options) else None
