"""teyla.dev: the rules in site/README.md."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "site" / "public"
PAGES = sorted(PUBLIC.rglob("*.html"))
TOKENS = (PUBLIC / "assets" / "tokens.css").read_text()
SITE_CSS = (PUBLIC / "assets" / "site.css").read_text()
README = (ROOT / "README.md").read_text()


def css_block(selector_marker: str) -> str:
    return TOKENS[TOKENS.index(selector_marker) :]


@pytest.mark.parametrize("scheme,start", [("light", ":root {"), ("dark", "prefers-color-scheme: dark")])
def test_colours_match_brand_tokens(scheme, start):
    colours = json.loads((ROOT / "brand" / "tokens.json").read_text())["color"][scheme]
    block = css_block(start)
    names = {
        "--bg": "background",
        "--surface": "surface",
        "--border": "border",
        "--text": "text",
        "--text-2": "text-secondary",
        "--primary": "primary",
        "--on-primary": "on-primary",
        "--needs-you": "needs-you",
        "--saving": "saving",
    }
    for var, token in names.items():
        found = re.search(re.escape(var) + r":\s*(#[0-9A-Fa-f]{6})", block)
        assert found, var
        assert found.group(1).upper() == colours[token].upper(), var


def test_site_css_adds_no_colours_or_font_sizes():
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(", SITE_CSS)
    sizes = set(re.findall(r"font-size:\s*([^;]+);", SITE_CSS))
    assert sizes <= {"var(--type-title)", "var(--type-head)", "var(--type-body)"}


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(PUBLIC)))
def test_pages_load_nothing_from_another_host(page):
    html = re.sub(r'<link rel="canonical"[^>]*>', "", page.read_text())
    assert not re.search(r"<(script|img|link|iframe)\b[^>]*\b(src|href)=\"(https?:)?//", html)
    assert "<style" not in html and " style=" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert not re.search(r"analytics|gtag|posthog|plausible|sentry|cloudflareinsights", html, re.I)


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(PUBLIC)))
def test_local_references_exist(page):
    for ref in re.findall(r"(?:src|href)=\"(/[^\"#]*)", page.read_text()):
        target = PUBLIC / ref.lstrip("/")
        assert target.is_file() or (target / "index.html").is_file(), ref


def test_headers_set_the_strict_policy():
    headers = (PUBLIC / "_headers").read_text()
    assert "default-src 'none'" in headers
    assert "script-src 'self'" in headers
    assert "unsafe" not in headers


def test_commands_match_the_readme():
    for page in (PUBLIC / "index.html", PUBLIC / "b" / "index.html"):
        html = page.read_text()
        for pre in re.findall(r"<pre id=\"[^\"]+\">([^<]+)</pre>", html):
            assert pre in README, pre


def test_no_store_link_while_the_apps_are_not_on_sale():
    for page in PAGES:
        assert not re.search(r"apps\.apple\.com|testflight\.apple\.com|play\.google\.com", page.read_text())


@pytest.mark.parametrize(
    "copy,source",
    [("img/lockup.svg", "brand/lockup.svg"), ("img/lockup-dark.svg", "brand/lockup-dark.svg"),
     ("favicon.svg", "brand/icon-small.svg"), ("img/web-start.png", "docs/img/web-start.png")],
)
def test_copied_assets_match_their_source(copy, source):
    assert (PUBLIC / copy).read_bytes() == (ROOT / source).read_bytes()
