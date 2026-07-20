#!/usr/bin/env python3
"""
build_plan.py — Sanders interactive floor-plan builder.

Takes one unit's room schema (rooms.json) and emits a single self-contained
HTML file: the Cypress-styled plan where every room is a clickable polygon that
reveals its m² in the detail panel. This is the SAME experience as Séraphine —
every unit gets it, no exceptions.

Usage:
    python3 build_plan.py rooms.json  ->  <slug>.html   (slug from --slug or name)
    python3 build_plan.py rooms.json --out seraphine/plan.html

rooms.json schema — see rooms.example.json. Required per room: name, area (with
"m²"), points (SVG polygon points in the level's viewBox). outdoor:true = dashed
gold styling for verandas/terraces. Redraw the real plan geometry per unit;
never fabricate room sizes — read them off the registered plan.
"""
import json, sys, re, argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "plan_interactive.html"

def slugify(s):
    s = re.sub(r"[^\w\s-]", "", s.lower()).strip()
    return re.sub(r"[\s_]+", "-", s)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rooms", help="path to rooms.json")
    ap.add_argument("--out", help="output html path")
    ap.add_argument("--slug", help="override slug")
    args = ap.parse_args()

    data = json.loads(Path(args.rooms).read_text(encoding="utf-8"))

    # minimal validation — fail loud rather than ship a broken plan
    assert data.get("name"), "rooms.json needs a unit 'name'"
    assert data.get("levels"), "rooms.json needs at least one level"
    for lvl in data["levels"]:
        assert lvl.get("viewbox") and lvl.get("rooms"), "each level needs viewbox + rooms"
        for r in lvl["rooms"]:
            # area is optional: interior rooms show name only (no fabricated area);
            # outdoor spaces carry the certified m² from the spec table.
            assert r.get("name") and r.get("points"), \
                f"room missing name/points: {r}"

    tpl = TEMPLATE.read_text(encoding="utf-8")

    # 1) swap the whole sample UNIT = {...}; block for real data.
    # Use a function replacement — a plain string replacement makes re.sub
    # interpret backslashes (e.g. an escaped \n in a JSON string, or \1) as
    # regex escapes, corrupting the emitted JS. A lambda returns it verbatim.
    unit_js = "const UNIT = " + json.dumps(data, ensure_ascii=False, indent=2) + ";"
    tpl = re.sub(r"const UNIT = \{.*?\n\};", lambda _m: unit_js, tpl, count=1, flags=re.S)

    # 2) fill the static placeholders (correct first paint before JS runs)
    tpl = tpl.replace("__UNIT_NAME__", data["name"])
    tpl = tpl.replace("__DEVELOPMENT__", data.get("development", ""))

    slug = args.slug or slugify(data["name"])
    out = Path(args.out) if args.out else Path(f"{slug}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(tpl, encoding="utf-8")
    print(f"built {out}  ({slug})")

if __name__ == "__main__":
    main()
