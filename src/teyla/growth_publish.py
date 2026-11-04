"""Publishing for `teyla growth` (docs/GROWTH.md): the protocol, and the one adapter that exists.

A `Publisher` takes an item the owner approved and returns where it went live. Only `ManualPublisher` exists:
the owner posts from the packet by hand and pastes the URL (`teyla growth published ID URL`). No platform adapter
holds a credential yet. A later adapter implements the same protocol; the rule it must keep is the one the manual
one keeps here: nothing publishes unless the item's status is `approved` or `ready`.
"""
from __future__ import annotations

import dataclasses
import urllib.parse
from typing import Protocol

PUBLISHABLE = ("approved", "ready")

# platform -> the host names a post URL on it may have. A mismatch is a warning (a short link is legitimate),
# never a refusal.
HOSTS = {
    "x": ("x.com", "twitter.com", "t.co"),
    "linkedin": ("linkedin.com", "lnkd.in"),
    "threads": ("threads.com", "threads.net"),
    "instagram": ("instagram.com", "instagr.am"),
    "tiktok": ("tiktok.com",),
    "youtube": ("youtube.com", "youtu.be"),
}


class PublishRefused(Exception):
    """The item may not go live; the message says why."""


@dataclasses.dataclass
class PublishResult:
    ok: bool
    url: str = ""
    warning: str = ""


class Publisher(Protocol):
    name: str

    def publish(self, item: dict, url: str | None = None) -> PublishResult:
        """Make the item public, or record that the owner did. Raises PublishRefused."""
        ...


def _host_ok(platform: str, host: str) -> bool:
    hosts = HOSTS.get(platform)
    if not hosts:
        return True
    host = host.lower().removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in hosts)


class ManualPublisher:
    """The owner posted by hand; Teyla records the URL. It never contacts a platform."""

    name = "manual"

    def publish(self, item: dict, url: str | None = None) -> PublishResult:
        if item.get("status") not in PUBLISHABLE:
            raise PublishRefused(f"{item.get('id')} is {item.get('status')}: only an approved item can be published")
        raw = (url or "").strip()
        parts = urllib.parse.urlparse(raw)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise PublishRefused("paste the post's URL (https://...) from the platform")
        warning = ""
        if not _host_ok(str(item.get("platform") or ""), parts.hostname or ""):
            warning = f"{parts.hostname} is not a usual {item.get('platform')} host; recorded as given"
        return PublishResult(True, raw, warning)


PUBLISHERS: dict[str, Publisher] = {"manual": ManualPublisher()}


def get(name: str = "manual") -> Publisher:
    try:
        return PUBLISHERS[name]
    except KeyError:
        raise PublishRefused(f"no publisher named {name}; only {', '.join(PUBLISHERS)} exist") from None
