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

    # normalise the summary tiles. The viewer renders each total as
    # `t.value` / `t.label`, so a [label, value] pair (or {k:v}) would print
    # "undefined". Coerce any shape into {label, value} objects here so the
    # tiles are always correct regardless of how rooms.json was authored.
    def _norm_total(t):
        if isinstance(t, dict):
            if "label" in t and "value" in t:
                return {"label": t["label"], "value": t["value"]}
            k, v = next(iter(t.items()))
            return {"label": k, "value": v}
        if isinstance(t, (list, tuple)) and len(t) == 2:
            return {"label": t[0], "value": t[1]}
        return {"label": "", "value": str(t)}
    if data.get("totals"):
        data["totals"] = [_norm_total(t) for t in data["totals"]]

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

    # ---- label placement + fit (image-mode plans) -------------------------
    # Two problems the viewer's naive approach caused: a single fixed font size
    # for every room (labels overflow small rooms and collide), and a vertex-
    # average "centroid" (wrong for L-shapes — the Hall label lands off-centre or
    # outside). Compute both correctly here, per room, and bake them into the data.
    def _pts(s):
        return [tuple(map(float, p.split(","))) for p in s.split()]

    def _bbox(p):
        xs = [x for x, _ in p]; ys = [y for _, y in p]
        return min(xs), min(ys), max(xs), max(ys)

    def _area_centroid(p):
        A = cx = cy = 0.0
        for i in range(len(p)):
            x0, y0 = p[i]; x1, y1 = p[(i + 1) % len(p)]
            cr = x0 * y1 - x1 * y0
            A += cr; cx += (x0 + x1) * cr; cy += (y0 + y1) * cr
        if abs(A) < 1e-6:
            x0, y0, x1, y1 = _bbox(p); return ((x0 + x1) / 2, (y0 + y1) / 2)
        A *= 0.5
        return (cx / (6 * A), cy / (6 * A))

    def _inside(pt, p):
        x, y = pt; c = False; n = len(p); j = n - 1
        for i in range(n):
            xi, yi = p[i]; xj, yj = p[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
                c = not c
            j = i
        return c

    def _place(p):
        """Area centroid if it falls inside; else the inside grid point nearest it;
        else the bbox centre."""
        ac = _area_centroid(p)
        if _inside(ac, p):
            return ac
        x0, y0, x1, y1 = _bbox(p)
        best = None; bd = 1e18
        for gy in range(1, 20):
            for gx in range(1, 20):
                q = (x0 + (x1 - x0) * gx / 20, y0 + (y1 - y0) * gy / 20)
                if _inside(q, p):
                    d = (q[0] - ac[0]) ** 2 + (q[1] - ac[1]) ** 2
                    if d < bd:
                        bd = d; best = q
        return best or ((x0 + x1) / 2, (y0 + y1) / 2)

    def _wrap(words, n):
        """Split words into n balanced lines by character length."""
        if n <= 1:
            return [" ".join(words)]
        total = sum(len(w) for w in words) + len(words) - 1
        target = total / n; lines = [[]]; cur = 0
        for w in words:
            if lines and cur > 0 and cur + 1 + len(w) > target and len(lines) < n:
                lines.append([]); cur = 0
            lines[-1].append(w); cur += len(w) + 1
        return [" ".join(l) for l in lines if l]

    CW, LH = 0.56, 1.16          # DM Sans avg glyph width (em); line height
    for lvl in data.get("levels", []):
        vbw = float(str(lvl.get("viewbox", "0 0 1000 1000")).split()[2] or 1000)
        MAXF, MINF = vbw * 0.030, vbw * 0.013
        for r in lvl.get("rooms", []):
            p = _pts(r["points"])
            r["labelAt"] = [round(v, 1) for v in _place(p)]
            bx0, by0, bx1, by1 = _bbox(p)
            aw, ah = (bx1 - bx0) * 0.85, (by1 - by0) * 0.62
            text = (r.get("label") or r["name"]).replace("\n", " ")
            words = text.split()
            best = None                      # (font, lines)
            for n in (1, 2, 3):
                lines = _wrap(words, n)
                longest = max(len(l) for l in lines)
                fw = aw / (longest * CW) if longest else MAXF
                fh = ah / (len(lines) * LH)
                f = min(fw, fh, MAXF)
                if best is None or f > best[0]:
                    best = (f, lines)
            if best[0] >= MINF:
                r["fontSize"] = int(round(best[0]))
                r["label"] = "\n".join(best[1])
            else:
                r["dropLabel"] = True        # too small to be legible → hotspot only

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
