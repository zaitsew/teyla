#!/usr/bin/env python3
"""Gives the iPhone sample (apps/ios/Teyla/Resources/sample-state.json) the `activity` block the Growth tab draws.

The block is what the Mac writes into the relay snapshot: the last 17 weeks as counts only. It is built from the invented graph of
`apps/mac/Tools/make_activity_fixture.py` with the relay's own `activity_view`, so the sample can never drift from the real shape.
It can be run again: the block is replaced.

    python3 apps/ios/Tools/add_activity_sample.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "apps" / "mac" / "Tools"))
from make_activity_fixture import build  # noqa: E402
from teyla import relay  # noqa: E402

SAMPLE = ROOT / "apps" / "ios" / "Teyla" / "Resources" / "sample-state.json"


def main():
    data = json.loads(SAMPLE.read_text())
    report = json.dumps(build())
    view = relay.activity_view(lambda cmd, timeout: (0, report, ""), ["teyla"])
    assert view is not None
    data["activity"] = view
    SAMPLE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"wrote {SAMPLE.relative_to(ROOT)}: {len(view['days'])} days, today {view['today_count']}, streak {view['streak']}")


if __name__ == "__main__":
    main()
