#!/usr/bin/env python3
"""Writes apps/ios/Tools/fixtures/long-text-state.json: the iPhone sample with very long names and sentences.

Used to look at every screen with text that does not fit on one line (launch with
`-TEYLA_STATE_FIXTURE <path to the file>`). All words are invented and ASCII. It reads the sample, so run it again
after the sample changes:

    python3 apps/ios/Tools/long_text_fixture.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE.parent / "Teyla" / "Resources" / "sample-state.json"
OUT = HERE / "fixtures" / "long-text-state.json"

LONG_NAME = "Sample Application With An Unreasonably Long Product Name That Keeps Going"
LONG_SENTENCE = ("The nightly backup of the sample application has not completed for three days in a row because the "
                 "storage volume it writes to was renamed and nothing was told")
UNBROKEN = "SampleIdentifierWithoutAnySpacesAtAll" * 3


def main() -> None:
    state = json.loads(SAMPLE.read_text(encoding="utf-8"))
    for i, product in enumerate(state["portfolio"]["products"][:3]):
        product["title"] = f"{LONG_NAME} {i + 1}"
        product["reasons"] = [LONG_SENTENCE]
    for ask in state["asks"][:2]:
        ask["title"] = ask["question"] = LONG_SENTENCE + "?"
    console = state["console"]
    console["money"]["next_renewal"]["name"] = LONG_NAME
    for failure in console["operations"]["failures"]:
        failure["title"] = LONG_SENTENCE
        failure["detail"] = LONG_SENTENCE + ". " + UNBROKEN
    console["playbook"]["you"] = {"quote": " ".join([LONG_SENTENCE] * 4), "chores_open": 3}
    console["growth"]["not_tried"] = [p["id"] for p in state["portfolio"]["products"][:3]] + console["growth"]["not_tried"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(state, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
