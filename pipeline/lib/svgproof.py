#!/usr/bin/env python3
"""svgproof — rasterise a plansvg output so a human (or Claude) can LOOK at it.

The plan SVG is the single highest-risk artifact in a listing: it is generated,
self-contained, and if the converter drops a layer the page still "works" while
showing a broken drawing. This renders the SVG we are actually about to ship —
not the PDF it came from — so the proof covers the converter too.

Deliberately narrow: it understands only the subset plansvg emits (flat <rect>,
<path> with M/L/C/Z, <image> with a matrix transform, <clipPath>, <mask>,
<text>). Text is drawn as a baseline rule rather than glyphs (no font engine
here); `--list-text` prints the runs so their content can be checked separately.
JPEG decoding is delegated to ffmpeg.
"""
import argparse, base64, math, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pdfraster import Canvas, fill_poly, stroke_poly, flat_bezier, ffmpeg_decode

ATTR = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')
ELEM = re.compile(r"<(\w+)\b([^>]*?)/?>")
NUM = re.compile(r"-?\d*\.?\d+(?:e-?\d+)?")


def attrs(s):
    return dict(ATTR.findall(s))


def matrix(s):
    m = re.search(r"matrix\(([^)]*)\)", s or "")
    if not m:
        return (1, 0, 0, 1, 0, 0)
    v = [float(x) for x in NUM.findall(m.group(1))]
    return tuple(v[:6]) if len(v) >= 6 else (1, 0, 0, 1, 0, 0)


def parse_path(d):
    """d -> list of polylines (already flattened)."""
    toks = re.findall(r"([MLCZmlcz])|(-?\d*\.?\d+(?:e-?\d+)?)", d)
    out = []; cur = []; pos = (0, 0); start = (0, 0)
    i = 0; cmd = None; nums = []
    seq = []
    for c, n in toks:
        if c:
            seq.append(("cmd", c))
        else:
            seq.append(("num", float(n)))
    k = 0
    while k < len(seq):
        kind, val = seq[k]
        if kind == "cmd":
            cmd = val; k += 1
            if cmd in "Zz":
                if cur:
                    cur.append(start); out.append(cur); cur = []
                pos = start
            continue
        need = {"M": 2, "L": 2, "C": 6}.get((cmd or "L").upper(), 2)
        args = []
        while len(args) < need and k < len(seq) and seq[k][0] == "num":
            args.append(seq[k][1]); k += 1
        if len(args) < need:
            break
        c0 = (cmd or "L").upper()
        if c0 == "M":
            if cur:
                out.append(cur)
            pos = (args[0], args[1]); start = pos; cur = [pos]
        elif c0 == "L":
            pos = (args[0], args[1]); cur.append(pos)
        elif c0 == "C":
            p1, p2, p3 = (args[0], args[1]), (args[2], args[3]), (args[4], args[5])
            cur += flat_bezier(pos, p1, p2, p3); pos = p3
        if c0 == "M":
            cmd = "L"                      # implicit lineto for repeated pairs
    if cur:
        out.append(cur)
    return out


def rgb(s, default=(0, 0, 0)):
    if not s or s == "none":
        return None
    s = s.strip()
    if s.startswith("#") and len(s) == 7:
        return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
    if s.startswith("#") and len(s) == 4:
        return tuple(int(c * 2, 16) for c in s[1:])
    return default


def render(svg_text, scale=2.0, list_text=False):
    vb = re.search(r'viewBox="([^"]+)"', svg_text)
    x0, y0, vw, vh = [float(v) for v in NUM.findall(vb.group(1))[:4]]
    W, H = int(vw * scale), int(vh * scale)
    cv = Canvas(W, H)

    def dev(p):
        return ((p[0] - x0) * scale, (p[1] - y0) * scale)

    # defs: clip bboxes and mask images
    clips = {}
    for m in re.finditer(r'<clipPath id="([^"]+)"[^>]*>(.*?)</clipPath>', svg_text, re.S):
        polys = []
        for pm in re.finditer(r'<path\b([^>]*?)/?>', m.group(2)):
            polys += parse_path(attrs(pm.group(1)).get("d", ""))
        pts = [dev(p) for poly in polys for p in poly]
        clips[m.group(1)] = ((min(q[0] for q in pts), min(q[1] for q in pts),
                              max(q[0] for q in pts), max(q[1] for q in pts))
                             if pts else (0, 0, W, H))
    masks = {}
    for m in re.finditer(r'<mask id="([^"]+)"[^>]*>(.*?)</mask>', svg_text, re.S):
        im = re.search(r'<image\b([^>]*?)/?>', m.group(2))
        if im:
            masks[m.group(1)] = attrs(im.group(1))

    body = svg_text.split("</defs>", 1)[-1]
    texts = []
    full = (0, 0, W, H)
    for m in ELEM.finditer(body):
        tag, a = m.group(1), attrs(m.group(2))
        clip = clips.get(_url(a.get("clip-path")), full)
        if tag == "rect":
            q = [dev((float(a["x"]), float(a["y"]))),
                 dev((float(a["x"]) + float(a["width"]), float(a["y"]))),
                 dev((float(a["x"]) + float(a["width"]), float(a["y"]) + float(a["height"]))),
                 dev((float(a["x"]), float(a["y"]) + float(a["height"])))]
            col = rgb(a.get("fill"))
            if col:
                fill_poly(cv, [q], col, clip)
        elif tag == "path":
            polys = [[dev(p) for p in poly] for poly in parse_path(a.get("d", ""))]
            if not polys:
                continue
            fc = rgb(a.get("fill"))
            if fc:
                fill_poly(cv, polys, fc, clip,
                          evenodd=a.get("fill-rule") == "evenodd",
                          alpha=float(a.get("fill-opacity", 1)))
            sc = rgb(a.get("stroke"), None)
            if sc:
                stroke_poly(cv, polys, sc, float(a.get("stroke-width", 1)) * scale, clip,
                            alpha=float(a.get("stroke-opacity", 1)))
        elif tag == "image":
            _image(cv, a, masks, dev, scale, clip, x0, y0)
        elif tag == "text":
            t = re.search(r'<text\b[^>]*>(.*?)</text>', body[m.start():m.start() + 4000], re.S)
            txt = re.sub(r"<[^>]+>", "", t.group(1)) if t else ""
            mt = matrix(a.get("transform"))
            p = dev((mt[4], mt[5]))
            fs = float(a.get("font-size", 8)) * scale * math.hypot(mt[0], mt[1])
            texts.append((txt, mt[4], mt[5], fs / scale))
            # baseline rule: shows placement + run width without a font engine
            wpx = fs * 0.56 * max(len(txt), 1)
            ang = math.atan2(mt[1], mt[0])
            end = (p[0] + wpx * math.cos(ang), p[1] + wpx * math.sin(ang))
            stroke_poly(cv, [[p, end]], (200, 60, 40), max(1.0, fs * 0.10), clip, alpha=0.85)
    if list_text:
        for t, tx, ty, fs in texts:
            print("  text @%7.1f,%7.1f  %4.1fpt  %r" % (tx, ty, fs, t))
    return cv, texts


def _url(v):
    m = re.match(r"url\(#([^)]+)\)", v or "")
    return m.group(1) if m else None


def _decode_uri(uri):
    head, _, b64 = (uri or "").partition(",")
    if not b64:
        return None
    raw = base64.b64decode(b64)
    if "svg" in head:
        return None
    return ffmpeg_decode(raw, "png" if "png" in head else "jpg")


def _image(cv, a, masks, dev, scale, clip, vx0, vy0):
    src = _decode_uri(a.get("href") or a.get("xlink:href"))
    if not src:
        return
    w, h, rgbdata = src
    mt = matrix(a.get("transform"))
    amask = None
    mid = _url(a.get("mask"))
    if mid and mid in masks:
        ms = _decode_uri(masks[mid].get("href") or masks[mid].get("xlink:href"))
        if ms:
            mw, mh, md = ms
            amask = (mw, mh, bytes(md[i] for i in range(0, len(md), 3)))
    # unit square -> user space -> device
    a_, b_, c_, d_, e_, f_ = mt
    corners = [dev((e_, f_)), dev((a_ + e_, b_ + f_)), dev((c_ + e_, d_ + f_)),
               dev((a_ + c_ + e_, b_ + d_ + f_))]
    X0 = max(int(min(p[0] for p in corners)), int(clip[0]), 0)
    X1 = min(int(max(p[0] for p in corners)) + 1, int(clip[2]), cv.w)
    Y0 = max(int(min(p[1] for p in corners)), int(clip[1]), 0)
    Y1 = min(int(max(p[1] for p in corners)) + 1, int(clip[3]), cv.h)
    det = a_ * d_ - b_ * c_
    if abs(det) < 1e-12:
        return
    ia, ib, ic, id_ = d_ / det, -b_ / det, -c_ / det, a_ / det
    ie, iff = -(e_ * ia + f_ * ic), -(e_ * ib + f_ * id_)
    alpha = float(a.get("opacity", 1))
    for py in range(Y0, Y1):
        uy_base = py / scale + vy0
        for px in range(X0, X1):
            ux_ = px / scale + vx0
            u = ux_ * ia + uy_base * ic + ie
            v = ux_ * ib + uy_base * id_ + iff
            if not (0 <= u < 1 and 0 <= v < 1):
                continue
            sx = min(int(u * w), w - 1); sy = min(int(v * h), h - 1)
            i = (sy * w + sx) * 3
            if i + 2 >= len(rgbdata):
                continue
            al = alpha
            if amask:
                mw, mh, md = amask
                mx = min(int(u * mw), mw - 1); my = min(int(v * mh), mh - 1)
                j = my * mw + mx
                if j < len(md):
                    al = alpha * (md[j] / 255.0)
            if al <= 0.02:
                continue
            cv.put(px, py, (rgbdata[i], rgbdata[i + 1], rgbdata[i + 2]), al)


def overlay_grid(cv, x0, y0, scale, step=25):
    """Faint ruled grid in SVG user units — lets room polygons be read off the
    proof by eye instead of guessed at."""
    x = math.ceil(x0 / step) * step
    while (x - x0) * scale < cv.w:
        px = int((x - x0) * scale)
        major = (round(x) % (step * 4) == 0)
        for py in range(0, cv.h, 1 if major else 3):
            cv.put(px, py, (150, 170, 210) if major else (205, 215, 230), 0.55)
        x += step
    y = math.ceil(y0 / step) * step
    while (y - y0) * scale < cv.h:
        py = int((y - y0) * scale)
        major = (round(y) % (step * 4) == 0)
        for px in range(0, cv.w, 1 if major else 3):
            cv.put(px, py, (150, 170, 210) if major else (205, 215, 230), 0.55)
        y += step


def overlay_rooms(cv, rooms, x0, y0, scale):
    """Draw the hotspot polygons over the plan so their fit can be checked."""
    palette = [(192, 98, 60), (28, 58, 46), (201, 169, 97), (60, 110, 150),
               (140, 70, 140), (40, 130, 110)]
    for k, r in enumerate(rooms):
        pts = [tuple(map(float, p.split(","))) for p in r["points"].split()]
        dev = [((px - x0) * scale, (py - y0) * scale) for px, py in pts]
        col = palette[k % len(palette)]
        fill_poly(cv, [dev], col, (0, 0, cv.w, cv.h), alpha=0.20)
        stroke_poly(cv, [dev + [dev[0]]], col, 2.4, (0, 0, cv.w, cv.h), alpha=0.95)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("svg"); ap.add_argument("out")
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--list-text", action="store_true")
    ap.add_argument("--grid", type=float, default=0, help="grid step in user units")
    ap.add_argument("--rooms", help="rooms.json (or a level JSON) to overlay")
    args = ap.parse_args()
    txt = Path(args.svg).read_text(encoding="utf-8")
    cv, texts = render(txt, args.scale, args.list_text)
    vb = re.search(r'viewBox="([^"]+)"', txt)
    x0, y0 = [float(v) for v in NUM.findall(vb.group(1))[:2]]
    if args.grid:
        overlay_grid(cv, x0, y0, args.scale, args.grid)
    if args.rooms:
        import json
        data = json.loads(Path(args.rooms).read_text(encoding="utf-8"))
        rooms = data["levels"][0]["rooms"] if "levels" in data else data["rooms"]
        overlay_rooms(cv, rooms, x0, y0, args.scale)
    cv.write_png(args.out)
    print("proofed %s -> %s  (%dx%d, %d text runs)" % (args.svg, args.out, cv.w, cv.h, len(texts)))


if __name__ == "__main__":
    main()
