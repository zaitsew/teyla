"""Models a provider has announced it will remove, with the date and the successor.

`teyla models watch` reports every repo that still names one of these ids in live code, next to the
superseded ids it finds from the catalogue. The catalogue lists only text models, so speech and image
models retire here, by hand, from the provider's deprecations page. The watch skips this file, which names
every id by design.
"""
from __future__ import annotations

# id -> why. Add a row when a provider's deprecations page announces a removal.
RETIRING = {
    "gpt-4o-mini-tts": "OpenAI removes it on 2027-01-06; use gpt-realtime-2.1-mini",
    "tts-1": "OpenAI removes it on 2027-01-06; use gpt-realtime-2.1-mini",
    "tts-1-hd": "OpenAI removes it on 2027-01-06; use gpt-realtime-2.1-mini",
}
