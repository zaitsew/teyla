#!/usr/bin/env python3
"""app-store - Teyla's App Store record, written from the repository.

One App Store Connect record (bundle id com.zaitsew.teyla) holds the iPhone and the Mac version.
This script writes everything App Store Connect asks for before a version can go to App Review,
except the App Privacy label (the API cannot write it; docs/APP-STORE.md says what to tick) and
the record itself (the API cannot create it: Apps, +, New App, in the website). The text lives in
apps/store/listing/<ios|macos>/en-US/, the answers in this file, and one command puts them where
Apple wants them:

  apps/store/app-store.py status                 # read-only: what the record holds
  apps/store/app-store.py push --dry-run         # every request it would send
  apps/store/app-store.py push                   # listing, answers, review detail
  apps/store/app-store.py screenshots DIR        # DIR/iphone69/en-US/*.png, DIR/mac/en-US/*.png
  apps/store/app-store.py screenshots DIR --replace   # again, when Apple's processing stalled
  apps/store/app-store.py submit --build 3       # attach the build, send to App Review

  apps/store/app-store.py --platform macos push  # the same, for the macOS version

`--platform ios|macos` (default ios) picks the version of the record. Name, subtitle, privacy URL,
categories, age rating, content rights, price and availability are app-level: the iOS `push` writes
them and the macOS `push` leaves them alone, except the territories in EXCLUDED_TERRITORIES, which
either push keeps switched off. `push` creates the macOS version when the record has none.

`push` is idempotent: it PATCHes what exists and POSTs only what is missing. `screenshots`
replaces a set only when the files differ. Before any request, `push` checks the listing files
against Apple's character limits and the store rules (no model provider named in the listing, the
review notes carry the sections a reviewer asks for) and refuses to run on a violation.

The API key, the JWT and `api()` come from ~/ops/bin/testflight, loaded as a module. Nothing
secret is printed. The reviewer contact comes from the environment of whoever runs `push`:
TEYLA_REVIEW_PHONE (never invented: unset leaves the phone in App Store Connect as it is),
TEYLA_REVIEW_FIRST_NAME, TEYLA_REVIEW_LAST_NAME, TEYLA_REVIEW_EMAIL (unset: the Beta App Review
record's value is used), TEYLA_COPYRIGHT.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import struct
import sys
import urllib.request
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LISTING = Path(__file__).resolve().parent / "listing"
TOOL = Path.home() / "ops" / "bin" / "testflight"

BUNDLE_ID = "com.zaitsew.teyla"
PLATFORM = "IOS"                            # "MAC_OS" under --platform macos, see configure()
VERSION = "0.32.0"                          # per platform, set by configure() from VERSIONS
VERSIONS = {"IOS": "0.32.0", "MAC_OS": "0.32.0"}
# Storefronts the app is not offered in, with the reason. POLICY section 15: China mainland is
# off from the first submission. Generative-AI apps in the China storefront need a permit
# (MIIT / CAC) that no model provider we use holds, and an ICP filing, which needs a Chinese
# entity. Re-including it is the owner's call.
EXCLUDED_TERRITORIES = {"CHN": "generative-AI apps need an MIIT/CAC permit in China mainland; no provider we use has one"}
LOCALES = ("en-US",)                        # en-US is the record's primary locale
PRIMARY_CATEGORY = "DEVELOPER_TOOLS"
SECONDARY_CATEGORY = "PRODUCTIVITY"
# The app shows the owner's own pull requests and sessions, not content from somebody else.
CONTENT_RIGHTS = "DOES_NOT_USE_THIRD_PARTY_CONTENT"
# TODO(owner): the copyright holder. The repository's licence names none. Set TEYLA_COPYRIGHT
# (for example "2026 Name") when running `push`; without it the field is left as it is.
COPYRIGHT = os.environ.get("TEYLA_COPYRIGHT", "").strip() or None

# App Review contact. The e-mail and the phone number are personal data in a public repository:
# they come from the environment (or the Beta App Review record), not from this file.
# The reviewer contact (name, e-mail, phone) comes from the environment, never from this public
# file: TEYLA_REVIEW_FIRST_NAME, TEYLA_REVIEW_LAST_NAME, TEYLA_REVIEW_EMAIL, TEYLA_REVIEW_PHONE.
CONTACT_ENV = {"contactFirstName": "TEYLA_REVIEW_FIRST_NAME", "contactLastName": "TEYLA_REVIEW_LAST_NAME",
               "contactEmail": "TEYLA_REVIEW_EMAIL", "contactPhone": "TEYLA_REVIEW_PHONE"}

# The age-rating questionnaire, every field answered (Apple refuses a partial one), every
# answer None or No: the app shows text that tools wrote on the owner's own Mac and generates
# nothing, has no messaging between people, no user-generated content, no web browser. 4+.
AGE_RATING = {
    "alcoholTobaccoOrDrugUseOrReferences": "NONE",
    "contests": "NONE", "gamblingSimulated": "NONE", "medicalOrTreatmentInformation": "NONE",
    "profanityOrCrudeHumor": "NONE", "sexualContentGraphicAndNudity": "NONE",
    "sexualContentOrNudity": "NONE", "horrorOrFearThemes": "NONE",
    "matureOrSuggestiveThemes": "NONE", "violenceCartoonOrFantasy": "NONE",
    "violenceRealistic": "NONE", "violenceRealisticProlongedGraphicOrSadistic": "NONE",
    "gunsOrOtherWeapons": "NONE",
    "healthOrWellnessTopics": False, "gambling": False, "unrestrictedWebAccess": False,
    "lootBox": False, "advertising": False, "parentalControls": False, "ageAssurance": False,
    "messagingAndChat": False, "userGeneratedContent": False,
}

# Screenshot slots: the folder name under DIR, Apple's display type, and the size in pixels
# the files must have. 6.9" is the required iPhone set (the app is iPhone-only, so no iPad set).
SHOT_SLOTS_IOS = {"iphone69": ("APP_IPHONE_67", (1320, 2868))}
# The Mac takes one set: a 2880 x 1800 desktop screenshot.
SHOT_SLOTS_MAC = {"mac": ("APP_DESKTOP", (2880, 1800))}
SHOT_SLOTS = SHOT_SLOTS_IOS

PLATFORMS = {"ios": "IOS", "macos": "MAC_OS"}
PLATFORM_DIRS = {"IOS": "ios", "MAC_OS": "macos"}

# The listing files, one plain text file per field: <field>.txt in listing/<platform>/<locale>/.
# name, subtitle and privacy_url are app-level and always come from the iOS listing; the macOS
# folder holds copies, and the check below refuses a copy that differs.
FIELDS = ("name", "subtitle", "promotional_text", "description", "keywords", "whats_new",
          "review_notes", "support_url", "privacy_url")
OPTIONAL_FIELDS = ("marketing_url",)
APP_LEVEL_FIELDS = ("name", "subtitle", "privacy_url")
LIMITS = {"name": 30, "subtitle": 30, "promotional_text": 170, "keywords": 100,
          "description": 4000, "whats_new": 4000, "review_notes": 4000}
# POLICY section 15: no model provider in the name, subtitle, description, keywords,
# promotional text or What's New. The privacy policy and the review notes may name them.
BANNED_IN = ("name", "subtitle", "promotional_text", "description", "keywords", "whats_new")
BANNED = re.compile(r"openai|chatgpt|\bgpt|claude|anthropic|gemini|grok|codex", re.I)
# What a reviewer would otherwise ask (POLICY section 15, "The review notes say ...").
NOTE_SECTIONS = ("HOW TO SEE EVERYTHING", "DECLARED CAPABILITIES", "PRIVACY AND DATA",
                 "AI CONTENT", "BUSINESS MODEL", "REGIONS")
TODO = re.compile(r"TODO\(owner\)")


def configure(platform: str) -> None:
    """Point the module at one platform of the record. Called once, before any request."""
    global PLATFORM, SHOT_SLOTS, VERSION
    PLATFORM = PLATFORMS[platform]
    VERSION = VERSIONS[PLATFORM]
    SHOT_SLOTS = SHOT_SLOTS_MAC if PLATFORM == "MAC_OS" else SHOT_SLOTS_IOS


def is_mac() -> bool:
    return PLATFORM == "MAC_OS"


# ------------------------------------------------------------------ the listing files

def listing_dir(platform: str, locale: str, root: Path | None = None) -> Path:
    return (root or LISTING) / PLATFORM_DIRS[platform] / locale


def read_field(platform: str, locale: str, field: str, root: Path | None = None) -> str:
    """The text of one field for one platform, "" when the file is missing. App-level
    fields always come from the iOS listing."""
    owner = "IOS" if field in APP_LEVEL_FIELDS else platform
    path = listing_dir(owner, locale, root) / f"{field}.txt"
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def text(field: str, locale: str = "en-US") -> str:
    return read_field(PLATFORM, locale, field)


def check_listing(platforms: tuple[str, ...] = ("IOS", "MAC_OS"), root: Path | None = None) -> list[str]:
    """Apple's character limits and the store rules, checked before anything is sent.
    Returns one line per problem; an empty list means the listing may be pushed."""
    problems: list[str] = []
    for platform in platforms:
        for locale in LOCALES:
            where = f"{PLATFORM_DIRS[platform]}/{locale}"
            for field in FIELDS:
                path = listing_dir(platform, locale, root) / f"{field}.txt"
                if not path.is_file() or not path.read_text(encoding="utf-8").strip():
                    problems.append(f"{where}/{field}.txt is missing or empty")
            values = {f: read_field(platform, locale, f, root) for f in FIELDS + OPTIONAL_FIELDS}
            for field, limit in LIMITS.items():
                if len(values[field]) > limit:
                    problems.append(f"{where}/{field}.txt is {len(values[field])} characters, limit {limit}")
            for field in BANNED_IN:
                hit = BANNED.search(values[field])
                if hit:
                    problems.append(f"{where}/{field}.txt names a model provider ({hit.group(0)!r}); "
                                    "POLICY section 15 keeps them out of the listing")
            if ", " in values["keywords"]:
                problems.append(f"{where}/keywords.txt has a space after a comma (wasted characters)")
            for field in ("support_url", "privacy_url", "marketing_url"):
                if values[field] and not values[field].startswith("https://"):
                    problems.append(f"{where}/{field}.txt is not an https:// URL")
            for section in NOTE_SECTIONS:
                if section not in values["review_notes"]:
                    problems.append(f"{where}/review_notes.txt has no {section} section")
            if "China" not in values["review_notes"]:
                problems.append(f"{where}/review_notes.txt does not say why China is excluded")
            for field, value in values.items():
                if TODO.search(value):
                    problems.append(f"{where}/{field}.txt still has a TODO(owner)")
            if platform != "IOS":
                for field in APP_LEVEL_FIELDS:
                    own = listing_dir(platform, locale, root) / f"{field}.txt"
                    if own.is_file() and own.read_text(encoding="utf-8").strip() != read_field("IOS", locale, field, root):
                        problems.append(f"{where}/{field}.txt differs from the iOS file "
                                        "(app-level: the iOS listing is the one that is sent)")
    return problems


def png_size(path: Path) -> tuple[int, int] | None:
    """Width and height from the PNG header, or None when the file is not a PNG."""
    with path.open("rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def check_screenshots(root: Path, slots: dict[str, tuple[str, tuple[int, int]]] | None = None) -> list[str]:
    """Every PNG under root/<folder>/<locale>/ has the size Apple takes for that slot."""
    problems = []
    for folder, (_display, size) in (slots or SHOT_SLOTS).items():
        for locale in LOCALES:
            for f in sorted((root / folder / locale).glob("*.png")):
                got = png_size(f)
                if got != size:
                    problems.append(f"{folder}/{locale}/{f.name} is {'x'.join(map(str, got)) if got else 'not a PNG'}, "
                                    f"expected {size[0]}x{size[1]}")
    return problems


def review_contact(env: dict[str, str] | None = None) -> dict[str, str]:
    """The reviewer contact the environment supplies. The phone number is never invented:
    when TEYLA_REVIEW_PHONE is unset the key is absent and App Store Connect keeps its own."""
    env = os.environ if env is None else env
    return {field: env[var].strip() for field, var in CONTACT_ENV.items() if env.get(var, "").strip()}


# ------------------------------------------------------------------ plumbing

def _tf():
    loader = SourceFileLoader("testflight", str(TOOL))
    spec = importlib.util.spec_from_loader("testflight", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


SECRET_KEYS = ("demoAccountPassword", "contactPhone")


def _redact(body):
    if isinstance(body, dict):
        return {k: ("<redacted>" if k in SECRET_KEYS else _redact(v)) for k, v in body.items()}
    if isinstance(body, list):
        return [_redact(v) for v in body]
    return body


class Ctx:
    def __init__(self, dry: bool):
        if not TOOL.exists():
            sys.exit(f"no release tool at {TOOL}")
        self.tf = _tf()
        self.dry = dry
        self.cfg = self.tf.load_config()
        self.app_id = self.tf._app_id(self.cfg, BUNDLE_ID)

    def get(self, path: str, soft: tuple[int, ...] = ()) -> dict:
        return self.tf.api(self.cfg, path, soft=soft) if soft else self.tf.api(self.cfg, path)

    def write(self, path: str, method: str, body: dict | None = None) -> dict:
        if self.dry:
            print(f"    would {method} {path}")
            if body is not None:
                for line in json.dumps(_redact(body), indent=2, ensure_ascii=False).splitlines():
                    print("      " + line)
            return {}
        return self.tf.api(self.cfg, path, method=method, body=body)

    def all(self, path: str) -> list[dict]:
        out, nxt = [], path
        while nxt:
            r = self.get(nxt)
            out += r.get("data", [])
            link = (r.get("links") or {}).get("next")
            nxt = link.replace(self.tf.API, "") if link else None
        return out


# ------------------------------------------------------------------ the record

NEW = "<new>"      # the id a dry run gives to a record it would have created


def editable_info(ctx: Ctx) -> dict:
    infos = ctx.all(f"/v1/apps/{ctx.app_id}/appInfos")
    live = {"READY_FOR_DISTRIBUTION", "READY_FOR_SALE"}
    return next((i for i in infos if (i["attributes"].get("state") or "") not in live), infos[0])


def the_version(ctx: Ctx, create: bool = False) -> dict:
    """The record's version for this platform. With create=True (only `push` passes it) a
    missing macOS version is created: it does not exist until someone adds it, unlike the iOS
    one the record was opened with. In a dry run the placeholder id "<new>" stands for it."""
    versions = ctx.all(f"/v1/apps/{ctx.app_id}/appStoreVersions?filter[platform]={PLATFORM}")
    for v in versions:
        if v["attributes"]["versionString"] == VERSION:
            return v
    # A version that never went live and is open for edits takes the new number instead of a
    # second version beside it: the 1.0 that App Store Connect opens becomes 0.32.0.
    editable = {"PREPARE_FOR_SUBMISSION", "REJECTED", "METADATA_REJECTED", "DEVELOPER_REJECTED"}
    open_one = next((v for v in versions if v["attributes"].get("appStoreState") in editable), None)
    if open_one:
        if create:      # only `push` renames; status and submit read it as it is
            was = open_one["attributes"]["versionString"]
            print(f"· {PLATFORM} version {was} ({open_one['attributes']['appStoreState']}) renamed to {VERSION}")
            ctx.write(f"/v1/appStoreVersions/{open_one['id']}", "PATCH", {"data": {
                "type": "appStoreVersions", "id": open_one["id"], "attributes": {"versionString": VERSION}}})
        return open_one
    if create and is_mac():
        print(f"· no {PLATFORM} version {VERSION} yet: creating it")
        made = ctx.write("/v1/appStoreVersions", "POST", {"data": {
            "type": "appStoreVersions",
            "attributes": {"platform": PLATFORM, "versionString": VERSION,
                           "releaseType": "AFTER_APPROVAL"},
            "relationships": {"app": {"data": {"type": "apps", "id": ctx.app_id}}}}})
        return made.get("data") or {"id": NEW, "attributes": {"versionString": VERSION}}
    hint = "run `push` to create it" if is_mac() else "create it in App Store Connect"
    sys.exit(f"no {PLATFORM} version {VERSION} on the record - {hint}")


def push_app_info(ctx: Ctx, info: dict) -> None:
    print("· app info: categories, localizations")
    ctx.write(f"/v1/appInfos/{info['id']}", "PATCH", {"data": {
        "type": "appInfos", "id": info["id"],
        "relationships": {
            "primaryCategory": {"data": {"type": "appCategories", "id": PRIMARY_CATEGORY}},
            "secondaryCategory": {"data": {"type": "appCategories", "id": SECONDARY_CATEGORY}}}}})
    have = {l["attributes"]["locale"]: l for l in ctx.all(f"/v1/appInfos/{info['id']}/appInfoLocalizations")}
    for locale in LOCALES:
        attrs = {"name": text("name", locale), "subtitle": text("subtitle", locale),
                 "privacyPolicyUrl": text("privacy_url", locale)}
        if locale in have:
            ctx.write(f"/v1/appInfoLocalizations/{have[locale]['id']}", "PATCH", {"data": {
                "type": "appInfoLocalizations", "id": have[locale]["id"], "attributes": attrs}})
        else:
            ctx.write("/v1/appInfoLocalizations", "POST", {"data": {
                "type": "appInfoLocalizations", "attributes": {"locale": locale, **attrs},
                "relationships": {"appInfo": {"data": {"type": "appInfos", "id": info["id"]}}}}})


def push_age_rating(ctx: Ctx, info: dict) -> None:
    print("· age rating: every answer None or No (4+)")
    decl = ctx.get(f"/v1/appInfos/{info['id']}/ageRatingDeclaration")["data"]
    ctx.write(f"/v1/ageRatingDeclarations/{decl['id']}", "PATCH", {"data": {
        "type": "ageRatingDeclarations", "id": decl["id"], "attributes": AGE_RATING}})


def push_app(ctx: Ctx) -> None:
    print("· app: content rights")
    ctx.write(f"/v1/apps/{ctx.app_id}", "PATCH", {"data": {
        "type": "apps", "id": ctx.app_id,
        "attributes": {"contentRightsDeclaration": CONTENT_RIGHTS}}})


def push_price(ctx: Ctx) -> None:
    """Free, from today, with the US as the base territory. No in-app purchases exist."""
    print("· price: free")
    sched = ctx.get(f"/v1/appPriceSchedules/{ctx.app_id}/manualPrices?include=appPricePoint", soft=(404,))
    if sched and sched.get("data"):
        print("    a price schedule exists - left alone")
        return
    points = ctx.get(f"/v1/apps/{ctx.app_id}/appPricePoints?filter[territory]=USA&limit=200")["data"]
    free = next(p for p in points if float(p["attributes"]["customerPrice"]) == 0.0)
    ctx.write("/v1/appPriceSchedules", "POST", {
        "data": {"type": "appPriceSchedules", "relationships": {
            "app": {"data": {"type": "apps", "id": ctx.app_id}},
            "baseTerritory": {"data": {"type": "territories", "id": "USA"}},
            "manualPrices": {"data": [{"type": "appPrices", "id": "${free}"}]}}},
        "included": [{"type": "appPrices", "id": "${free}", "attributes": {"startDate": None},
                      "relationships": {"appPricePoint": {"data": {"type": "appPricePoints", "id": free["id"]}}}}]})


def push_availability(ctx: Ctx) -> None:
    """Every territory, and new ones as Apple adds them, except EXCLUDED_TERRITORIES."""
    print("· availability: all territories")
    have = ctx.get(f"/v1/apps/{ctx.app_id}/appAvailabilityV2", soft=(404,))
    if have and have.get("data"):
        print("    availability exists - left alone")
        return
    territories = [t["id"] for t in ctx.all("/v1/territories?limit=200")]
    ctx.write("/v2/appAvailabilities", "POST", {
        "data": {"type": "appAvailabilities", "attributes": {"availableInNewTerritories": True},
                 "relationships": {
                     "app": {"data": {"type": "apps", "id": ctx.app_id}},
                     "territoryAvailabilities": {"data": [
                         {"type": "territoryAvailabilities", "id": f"${{{t}}}"} for t in territories]}}},
        "included": [{"type": "territoryAvailabilities", "id": f"${{{t}}}",
                      "attributes": {"available": t not in EXCLUDED_TERRITORIES},
                      "relationships": {"territory": {"data": {"type": "territories", "id": t}}}}
                     for t in territories]})
    print(f"    {len(territories)} territories, {len(EXCLUDED_TERRITORIES)} switched off")


def push_exclusions(ctx: Ctx) -> None:
    """Switch off each territory in EXCLUDED_TERRITORIES that is on. App-level, so it runs on
    either platform's push; a territory already off is left alone."""
    print(f"· availability: off in {', '.join(EXCLUDED_TERRITORIES)}")
    have = ctx.get(f"/v1/apps/{ctx.app_id}/appAvailabilityV2", soft=(404,))
    if not (have and have.get("data")):
        print("    no availability yet - the iOS push creates it without them")
        return
    rows = ctx.all(f"/v2/appAvailabilities/{have['data']['id']}/territoryAvailabilities"
                   "?include=territory&limit=200")
    for row in rows:
        territory = row["relationships"]["territory"]["data"]["id"]
        if territory in EXCLUDED_TERRITORIES and row["attributes"].get("available"):
            print(f"    {territory}: off ({EXCLUDED_TERRITORIES[territory]})")
            ctx.write(f"/v1/territoryAvailabilities/{row['id']}", "PATCH", {"data": {
                "type": "territoryAvailabilities", "id": row["id"], "attributes": {"available": False}}})


def has_been_live(ctx: Ctx) -> bool:
    """App Store Connect refuses "What's New" on the first version of an app."""
    live = {"READY_FOR_SALE", "REPLACED_WITH_NEW_VERSION"}
    # Per platform: the Mac's first version is a first version even after iOS shipped.
    return any(v["attributes"].get("appStoreState") in live
               for v in ctx.all(f"/v1/apps/{ctx.app_id}/appStoreVersions?filter[platform]={PLATFORM}"))


def push_version(ctx: Ctx, version: dict) -> None:
    print(f"· version {VERSION}: copyright, release, localizations")
    attrs = {"releaseType": "AFTER_APPROVAL"}
    if COPYRIGHT:
        attrs["copyright"] = COPYRIGHT
    else:
        print("    TEYLA_COPYRIGHT not set: the copyright in App Store Connect is left as it is")
    ctx.write(f"/v1/appStoreVersions/{version['id']}", "PATCH", {"data": {
        "type": "appStoreVersions", "id": version["id"], "attributes": attrs}})
    whats_new = has_been_live(ctx)
    if not whats_new:
        print("    first release: What's New is not sent (App Store Connect refuses it)")
    have = {} if version["id"] == NEW else {l["attributes"]["locale"]: l for l in
            ctx.all(f"/v1/appStoreVersions/{version['id']}/appStoreVersionLocalizations")}
    for locale in LOCALES:
        attrs = {"description": text("description", locale), "keywords": text("keywords", locale),
                 "promotionalText": text("promotional_text", locale), "supportUrl": text("support_url", locale)}
        if text("marketing_url", locale):
            attrs["marketingUrl"] = text("marketing_url", locale)
        if whats_new:
            attrs["whatsNew"] = text("whats_new", locale)
        if locale in have:
            ctx.write(f"/v1/appStoreVersionLocalizations/{have[locale]['id']}", "PATCH", {"data": {
                "type": "appStoreVersionLocalizations", "id": have[locale]["id"], "attributes": attrs}})
        else:
            ctx.write("/v1/appStoreVersionLocalizations", "POST", {"data": {
                "type": "appStoreVersionLocalizations", "attributes": {"locale": locale, **attrs},
                "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": version["id"]}}}}})


def push_review_detail(ctx: Ctx, version: dict) -> None:
    """No sign-in, so no demo account: the app has a sample mode (the notes say how to reach
    it). The contact comes from the environment, else the Beta App Review record."""
    print("· App Review information")
    attrs = {**review_contact(), "demoAccountRequired": False, "notes": text("review_notes")}
    missing = [f for f in ("contactFirstName", "contactLastName", "contactEmail") if f not in attrs]
    if missing:
        beta = ctx.get(f"/v1/apps/{ctx.app_id}/betaAppReviewDetail", soft=(404,))
        known = (((beta or {}).get("data") or {}).get("attributes") or {})
        for field in missing:
            if known.get(field):
                attrs[field] = known[field]
                print(f"    {CONTACT_ENV[field]} not set: using the Beta App Review record's value")
            else:
                print(f"    {CONTACT_ENV[field]} not set: the value in App Store Connect is left as it is")
    if "contactPhone" not in attrs:
        print("    TEYLA_REVIEW_PHONE not set: the phone number in App Store Connect is left as it is")
    have = None if version["id"] == NEW else ctx.get(
        f"/v1/appStoreVersions/{version['id']}/appStoreReviewDetail", soft=(404,))
    if have and have.get("data"):
        rid = have["data"]["id"]
        ctx.write(f"/v1/appStoreReviewDetails/{rid}", "PATCH", {"data": {
            "type": "appStoreReviewDetails", "id": rid, "attributes": attrs}})
    else:
        ctx.write("/v1/appStoreReviewDetails", "POST", {"data": {
            "type": "appStoreReviewDetails", "attributes": attrs,
            "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": version["id"]}}}}})


# ------------------------------------------------------------------ screenshots

def _upload(ctx: Ctx, set_id: str, path: Path) -> None:
    data = path.read_bytes()
    made = ctx.write("/v1/appScreenshots", "POST", {"data": {
        "type": "appScreenshots", "attributes": {"fileName": path.name, "fileSize": len(data)},
        "relationships": {"appScreenshotSet": {"data": {"type": "appScreenshotSets", "id": set_id}}}}})
    if ctx.dry:
        return
    shot = made["data"]
    for op in shot["attributes"].get("uploadOperations") or []:
        chunk = data[op["offset"]:op["offset"] + op["length"]]
        req = urllib.request.Request(op["url"], data=chunk, method=op["method"],
                                     headers={h["name"]: h["value"] for h in op.get("requestHeaders", [])})
        with urllib.request.urlopen(req, timeout=120):
            pass
    ctx.write(f"/v1/appScreenshots/{shot['id']}", "PATCH", {"data": {
        "type": "appScreenshots", "id": shot["id"],
        "attributes": {"uploaded": True, "sourceFileChecksum": hashlib.md5(data).hexdigest()}}})


def push_screenshots(ctx: Ctx, root: Path, replace: bool = False) -> None:
    version = the_version(ctx)
    locs = {l["attributes"]["locale"]: l for l in
            ctx.all(f"/v1/appStoreVersions/{version['id']}/appStoreVersionLocalizations")}
    for folder, (display, _size) in SHOT_SLOTS.items():
        for locale in LOCALES:
            files = sorted((root / folder / locale).glob("*.png"))
            if not files:
                print(f"· {folder}/{locale}: no files - skipped")
                continue
            if locale not in locs:
                print(f"· {folder}/{locale}: no localization yet - run push first")
                continue
            sets = ctx.get(f"/v1/appStoreVersionLocalizations/{locs[locale]['id']}/appScreenshotSets"
                           f"?filter[screenshotDisplayType]={display}&include=appScreenshots")
            # In file-name order, which is the order they are shown in: a rename that
            # reorders the set is a change, not "already there".
            sums = [hashlib.md5(f.read_bytes()).hexdigest() for f in files]
            if sets["data"]:
                set_id = sets["data"][0]["id"]
                shots = ctx.all(f"/v1/appScreenshotSets/{set_id}/appScreenshots")
                stuck = [s["attributes"].get("fileName") for s in shots
                         if ((s["attributes"].get("assetDeliveryState") or {}).get("state")) != "COMPLETE"]
                if not replace and [(s["attributes"].get("sourceFileChecksum") or "") for s in shots] == sums:
                    print(f"· {folder}/{locale}: {len(files)} already there")
                    # Apple sometimes never finishes processing an upload (UPLOAD_COMPLETE for
                    # hours, 2026-10-26), and App Review then refuses the version with
                    # ASSET_IN_POST_PROCESSING. The same file again does not count as a change.
                    if stuck:
                        print(f"  still processing at Apple: {', '.join(stuck)}"
                              " - if it stays so, run again with --replace")
                    continue
                for s in shots:
                    ctx.write(f"/v1/appScreenshots/{s['id']}", "DELETE")
            else:
                made = ctx.write("/v1/appScreenshotSets", "POST", {"data": {
                    "type": "appScreenshotSets", "attributes": {"screenshotDisplayType": display},
                    "relationships": {"appStoreVersionLocalization": {"data": {
                        "type": "appStoreVersionLocalizations", "id": locs[locale]["id"]}}}}})
                set_id = (made.get("data") or {}).get("id", NEW)
            print(f"· {folder}/{locale}: uploading {len(files)}")
            for f in files:
                _upload(ctx, set_id, f)


# ------------------------------------------------------------------ submission

def submit(ctx: Ctx, build_number: str) -> None:
    version = the_version(ctx)
    builds = ctx.get(f"/v1/builds?filter[app]={ctx.app_id}&filter[version]={build_number}"
                     f"&filter[preReleaseVersion.platform]={PLATFORM}"
                     f"&filter[preReleaseVersion.version]={VERSION}&include=preReleaseVersion")["data"]
    if not builds:
        sys.exit(f"no {PLATFORM} build {build_number} of version {VERSION}")
    build = builds[0]
    state = build["attributes"].get("processingState")
    if state != "VALID":
        sys.exit(f"build {build_number} is {state}, not VALID - wait for processing")
    print(f"· attach build {build_number} to {VERSION}")
    ctx.write(f"/v1/appStoreVersions/{version['id']}/relationships/build", "PATCH",
              {"data": {"type": "builds", "id": build["id"]}})
    drafts = ctx.all(f"/v1/reviewSubmissions?filter[app]={ctx.app_id}"
                     f"&filter[platform]={PLATFORM}&filter[state]=UNRESOLVED_ISSUES,READY_FOR_REVIEW")
    # A rejected submission (UNRESOLVED_ISSUES) is found and reused: Apple keeps one open
    # submission per platform. Resubmitting a rejected one through the API was refused with
    # a 409 for Iron U (2026-10-16) while the web page's "Resubmit to App Review" went through:
    # after a rejection, run `submit` to attach the build, then press that button.
    if drafts:
        sub_id = drafts[0]["id"]
    else:
        made = ctx.write("/v1/reviewSubmissions", "POST", {"data": {
            "type": "reviewSubmissions", "attributes": {"platform": PLATFORM},
            "relationships": {"app": {"data": {"type": "apps", "id": ctx.app_id}}}}})
        sub_id = (made.get("data") or {}).get("id", NEW)
    items = [] if sub_id == NEW else ctx.get(
        f"/v1/reviewSubmissions/{sub_id}/items?include=appStoreVersion").get("data", [])
    if not any(((i.get("relationships", {}).get("appStoreVersion") or {}).get("data") or {}).get("id")
               == version["id"] for i in items):
        ctx.write("/v1/reviewSubmissionItems", "POST", {"data": {
            "type": "reviewSubmissionItems", "relationships": {
                "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": sub_id}},
                "appStoreVersion": {"data": {"type": "appStoreVersions", "id": version["id"]}}}}})
    done = ctx.write(f"/v1/reviewSubmissions/{sub_id}", "PATCH", {"data": {
        "type": "reviewSubmissions", "id": sub_id, "attributes": {"submitted": True}}})
    if not ctx.dry:
        print(f"· submitted - review submission {sub_id[:8]} "
              f"{(done.get('data') or {}).get('attributes', {}).get('state')}")


def status(ctx: Ctx) -> None:
    info = editable_info(ctx)
    version = the_version(ctx)
    va = version["attributes"]
    print(f"app {ctx.app_id}  version {va['versionString']} {va['appStoreState']}  release {va['releaseType']}")
    cats = [((ctx.get(f"/v1/appInfos/{info['id']}/{rel}", soft=(404,)) or {}).get("data") or {}).get("id")
            for rel in ("primaryCategory", "secondaryCategory")]
    print(f"categories {cats}")
    decl = ctx.get(f"/v1/appInfos/{info['id']}/ageRatingDeclaration")["data"]["attributes"]
    unanswered = [k for k, v in decl.items() if v is None and k in AGE_RATING]
    print(f"age rating: {'complete' if not unanswered else 'unanswered ' + ', '.join(unanswered)}")
    for l in ctx.all(f"/v1/appStoreVersions/{version['id']}/appStoreVersionLocalizations"):
        a = l["attributes"]
        sets = ctx.get(f"/v1/appStoreVersionLocalizations/{l['id']}/appScreenshotSets")["data"]
        counts = {s["attributes"]["screenshotDisplayType"]:
                  len(ctx.all(f"/v1/appScreenshotSets/{s['id']}/appScreenshots")) for s in sets}
        print(f"  {a['locale']:6} description {len(a.get('description') or '')} chars, "
              f"keywords {'yes' if a.get('keywords') else 'no'}, screenshots {counts or 'none'}")
    build = ctx.get(f"/v1/appStoreVersions/{version['id']}/build", soft=(404,))
    print(f"build attached: {((build or {}).get('data') or {}).get('attributes', {}).get('version')}")
    review = ctx.get(f"/v1/appStoreVersions/{version['id']}/appStoreReviewDetail", soft=(404,))
    print(f"review detail: {'set' if review and review.get('data') else 'missing'}")
    have = ctx.get(f"/v1/apps/{ctx.app_id}/appAvailabilityV2", soft=(404,))
    if have and have.get("data"):
        rows = ctx.all(f"/v2/appAvailabilities/{have['data']['id']}/territoryAvailabilities"
                       "?include=territory&limit=200")
        off = sorted(r["relationships"]["territory"]["data"]["id"] for r in rows
                     if not r["attributes"].get("available"))
        print(f"availability: {len(rows) - len(off)} of {len(rows)} territories, off: {off or 'none'}")
    for s in ctx.all(f"/v1/reviewSubmissions?filter[app]={ctx.app_id}&filter[platform]={PLATFORM}"):
        print(f"submission {s['id'][:8]} {s['attributes'].get('state')} {s['attributes'].get('submittedDate')}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--platform", choices=sorted(PLATFORMS), default="ios",
                   help="which version of the record to work on (default: ios)")
    # The same option after the subcommand (`push --platform macos`); absent there, the top-level value stays.
    both = argparse.ArgumentParser(add_help=False)
    both.add_argument("--platform", choices=sorted(PLATFORMS), default=argparse.SUPPRESS,
                      help="which version of the record to work on (default: ios)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", parents=[both], help="read-only: what the record holds")
    push = sub.add_parser("push", parents=[both], help="listing, answers and review detail")
    push.add_argument("--dry-run", action="store_true", help="print every request instead of sending it")
    shots = sub.add_parser("screenshots", parents=[both], help="upload DIR/<folder>/en-US/*.png")
    shots.add_argument("dir", type=Path)
    shots.add_argument("--dry-run", action="store_true", help="print every request instead of sending it")
    shots.add_argument("--replace", action="store_true",
                       help="upload every set again, even when the files are already there")
    sm = sub.add_parser("submit", parents=[both], help="attach a build and send the version to App Review")
    sm.add_argument("--build", required=True, help="the build number (CFBundleVersion)")
    sm.add_argument("--dry-run", action="store_true", help="print every request instead of sending it")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure(args.platform)

    if args.cmd in ("push", "submit"):
        problems = check_listing()
        if problems:
            sys.exit("listing not ready:\n  " + "\n  ".join(problems))
    if args.cmd == "screenshots":
        problems = check_screenshots(args.dir)
        if problems:
            sys.exit("screenshots not ready:\n  " + "\n  ".join(problems))
    ctx = Ctx(dry=getattr(args, "dry_run", False))
    if args.cmd == "status":
        status(ctx)
    elif args.cmd == "push":
        version = the_version(ctx, create=True)
        if is_mac():
            # Name, subtitle, categories, age rating, content rights, price and availability
            # are app-level: the iOS push already wrote them, and the Mac version shares them.
            # While a version is in review the app-info PATCHes can be refused, so the Mac
            # push leaves them alone. Change one on iOS (`push`), not here.
            print("· app-level answers (info, age rating, price, availability): shared with iOS, left alone")
            print("  (except the excluded territories, which either platform's push keeps off)")
        else:
            info = editable_info(ctx)
            push_app(ctx)
            push_app_info(ctx, info)
            push_age_rating(ctx, info)
            push_price(ctx)
            push_availability(ctx)
        push_exclusions(ctx)
        push_version(ctx, version)
        push_review_detail(ctx, version)
    elif args.cmd == "screenshots":
        push_screenshots(ctx, args.dir, replace=args.replace)
    elif args.cmd == "submit":
        submit(ctx, args.build)
    return 0


if __name__ == "__main__":
    sys.exit(main())
