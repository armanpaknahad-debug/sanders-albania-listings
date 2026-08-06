#!/usr/bin/env python3
"""plansvg — turn a developer plan sheet (PDF) into a clean, croppable SVG.

Why SVG and not a raster: the standardiser has to *remove* things from the sheet
(the sales-album header, the legal entity line, apartment and section codes) and
*retypeset* others in English. You can only do that to a drawing you still hold
as objects. A rasterised sheet would force us to paint over line art, which is
exactly what the house rules forbid.

Each drawing operation is emitted with its device-space bounding box, so callers
can crop to a region (the plan itself, the position insets, …) after the fact
rather than guessing at extraction time.

Text is routed through a caller-supplied `text_filter(text, x, y, size) -> str|None`
(None drops the run), which is where stripping and translation happen.

Dependency-free: PDF parsing via pdfmini, PNG encoding via zlib.
"""
import base64, math, re, sys, zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pdfmini import PDF, Parser, Stream, mul


# ---------------------------------------------------------------- PNG writer
def png_bytes(w, h, data, gray=False):
    """Minimal PNG encoder (no Pillow in this environment)."""
    ct, stride = (0, w) if gray else (2, w * 3)
    raw = b"".join(b"\0" + data[y * stride:(y + 1) * stride] for y in range(h))

    def chunk(tag, payload):
        return (len(payload).to_bytes(4, "big") + tag + payload +
                (zlib.crc32(tag + payload) & 0xFFFFFFFF).to_bytes(4, "big"))

    ihdr = w.to_bytes(4, "big") + h.to_bytes(4, "big") + bytes([8, ct, 0, 0, 0])
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _fmt(v):
    """Compact number formatting — plan sheets emit tens of thousands of these.

    One decimal place is ~0.1pt: finer than the drawing's own linework and far
    finer than any screen the plan renders on, and it takes about 15% off the
    file compared with two.
    """
    if v == int(v):
        return str(int(v))
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _rgb(c):
    return "#%02x%02x%02x" % c


class Item:
    """One emitted SVG element plus the device bbox used for cropping."""
    __slots__ = ("svg", "bbox", "kind", "text")

    def __init__(self, svg, bbox, kind, text=""):
        self.svg, self.bbox, self.kind, self.text = svg, bbox, kind, text


class PlanSVG:
    def __init__(self, path, page_index=0, text_filter=None, scale=1.0):
        self.pdf = PDF(str(path))
        self.page = self.pdf.pages()[page_index]
        self.text_filter = text_filter or (lambda t, x, y, s: t)
        mb = [float(x) for x in self.pdf.res(self.page.get("MediaBox"))]
        w0, h0 = (mb[2] - mb[0]) * scale, (mb[3] - mb[1]) * scale
        rot = int(self.pdf.res(self.page.get("Rotate")) or 0) % 360
        base = (scale, 0, 0, -scale, -mb[0] * scale, mb[3] * scale)
        if rot == 90:
            self.W, self.H = h0, w0; self.dev = mul(base, (0, 1, -1, 0, h0, 0))
        elif rot == 180:
            self.W, self.H = w0, h0; self.dev = mul(base, (-1, 0, 0, -1, w0, h0))
        elif rot == 270:
            self.W, self.H = h0, w0; self.dev = mul(base, (0, -1, 1, 0, 0, w0))
        else:
            self.W, self.H = w0, h0; self.dev = base
        self.items = []
        self.defs = []
        self.clip_bbox = {}
        self.band_x0 = None   # set by drawing_crop(); nothing right of it is drawing
        self._clip_n = 0
        self._mask_n = 0
        self._img_cache = {}

    # ------------------------------------------------------------------ run
    def parse(self):
        res = self.pdf.res(self.page.get("Resources")) or {}
        self._exec(self.pdf.content(self.page), res, self.dev, None, 0)
        return self

    def _tf(self, m, x, y):
        return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])

    # --------------------------------------------------------------- images
    def _image_uri(self, xo):
        key = id(xo)
        if key in self._img_cache:
            return self._img_cache[key]
        pdf = self.pdf
        f = pdf.res(xo.dict.get("Filter")) or []
        if not isinstance(f, list):
            f = [f]
        f = [str(x) for x in f]
        w = int(pdf.res(xo.dict.get("Width")) or 0)
        h = int(pdf.res(xo.dict.get("Height")) or 0)
        cs = str(pdf.res(xo.dict.get("ColorSpace")) or "")
        bpc = int(pdf.res(xo.dict.get("BitsPerComponent")) or 8)
        data = pdf.data(xo)
        uri = None
        if "DCTDecode" in f:
            uri = "data:image/jpeg;base64," + base64.b64encode(data).decode()
        elif bpc == 8 and "RGB" in cs and len(data) >= w * h * 3:
            uri = "data:image/png;base64," + base64.b64encode(
                png_bytes(w, h, data[:w * h * 3])).decode()
        elif bpc == 8 and ("Gray" in cs or pdf.res(xo.dict.get("ImageMask"))) and len(data) >= w * h:
            uri = "data:image/png;base64," + base64.b64encode(
                png_bytes(w, h, data[:w * h], gray=True)).decode()
        self._img_cache[key] = uri
        return uri

    def _emit_image(self, xo, ctm, clip, alpha):
        uri = self._image_uri(xo)
        if not uri:
            return
        # PDF images live on the unit square with row 0 at the TOP (y = 1),
        # so flip before applying the CTM to land them the right way up in SVG.
        m = mul((1, 0, 0, -1, 0, 1), ctm)
        corners = [self._tf(ctm, x, y) for x, y in ((0, 0), (1, 0), (0, 1), (1, 1))]
        bbox = (min(p[0] for p in corners), min(p[1] for p in corners),
                max(p[0] for p in corners), max(p[1] for p in corners))
        mt = "matrix(%s)" % ",".join(_fmt(v) for v in m)
        extra = ""
        sm = self.pdf.res(xo.dict.get("SMask"))
        if isinstance(sm, Stream):
            suri = self._image_uri(sm)
            if suri:
                self._mask_n += 1
                mid = "m%d" % self._mask_n
                pad = 2
                self.defs.append(
                    '<mask id="%s" maskUnits="userSpaceOnUse" x="%s" y="%s" width="%s" height="%s">'
                    '<image href="%s" width="1" height="1" preserveAspectRatio="none" '
                    'transform="%s" style="image-rendering:auto"/></mask>' % (
                        mid, _fmt(bbox[0] - pad), _fmt(bbox[1] - pad),
                        _fmt(bbox[2] - bbox[0] + 2 * pad), _fmt(bbox[3] - bbox[1] + 2 * pad),
                        suri, mt))
                extra += ' mask="url(#%s)"' % mid
        if alpha < 0.999:
            extra += ' opacity="%s"' % _fmt(round(alpha, 3))
        if clip:
            extra += ' clip-path="url(#%s)"' % clip
        self.items.append(Item(
            '<image href="%s" width="1" height="1" preserveAspectRatio="none" transform="%s"%s/>'
            % (uri, mt, extra), bbox, "image"))

    # ---------------------------------------------------------------- paths
    def _path_d(self, segs):
        out = []
        for seg in segs:
            for i, (op, pts) in enumerate(seg):
                if op == "M":
                    out.append("M%s %s" % (_fmt(pts[0]), _fmt(pts[1])))
                elif op == "L":
                    out.append("L%s %s" % (_fmt(pts[0]), _fmt(pts[1])))
                elif op == "C":
                    out.append("C%s" % " ".join(_fmt(v) for v in pts))
                elif op == "Z":
                    out.append("Z")
        return "".join(out)

    def _exec(self, content, res, ctm, clip, depth):
        if depth > 5:
            return
        pdf = self.pdf
        xobjs = pdf.res(res.get("XObject")) or {}
        egs = pdf.res(res.get("ExtGState")) or {}
        fonts = _font_map(pdf, res)
        p = Parser(content)
        gs = []
        fill = (0, 0, 0); stroke = (0, 0, 0); lw = 1.0
        alpha = salpha = 1.0
        dash = ""
        segs = []; cur = []; startpt = None; pos = None
        pts_all = []
        pending_clip = 0          # 0 none, 1 nonzero, 2 evenodd
        tm = tlm = (1, 0, 0, 1, 0, 0)
        tfs = 0.0; tfont = None; leading = 0.0; trise = 0.0; thscale = 1.0
        ops = []

        def num(i):
            try:
                return float(ops[i])
            except Exception:
                return 0.0

        def close_sub():
            nonlocal cur
            if cur:
                segs.append(cur); cur = []

        def finish(paint):
            nonlocal segs, cur, startpt, pos, pending_clip, clip, pts_all
            close_sub()
            if segs:
                d = self._path_d(segs)
                bbox = (min(q[0] for q in pts_all), min(q[1] for q in pts_all),
                        max(q[0] for q in pts_all), max(q[1] for q in pts_all)) if pts_all else (0, 0, 0, 0)
                sw = abs(lw) * math.hypot(ctm[0], ctm[1])
                attrs = []
                if paint["fill"]:
                    attrs.append('fill="%s"' % _rgb(fill))
                    if paint["eo"]:
                        attrs.append('fill-rule="evenodd"')
                    if alpha < 0.999:
                        attrs.append('fill-opacity="%s"' % _fmt(round(alpha, 3)))
                else:
                    attrs.append('fill="none"')
                if paint["stroke"]:
                    attrs.append('stroke="%s"' % _rgb(stroke))
                    attrs.append('stroke-width="%s"' % _fmt(round(max(sw, 0.12), 2)))
                    if salpha < 0.999:
                        attrs.append('stroke-opacity="%s"' % _fmt(round(salpha, 3)))
                    if dash:
                        attrs.append('stroke-dasharray="%s"' % dash)
                if clip:
                    attrs.append('clip-path="url(#%s)"' % clip)
                if paint["fill"] or paint["stroke"]:
                    self.items.append(Item('<path d="%s" %s/>' % (d, " ".join(attrs)),
                                           bbox, "path"))
                if pending_clip:
                    self._clip_n += 1
                    cid = "c%d" % self._clip_n
                    self.defs.append('<clipPath id="%s" clipPathUnits="userSpaceOnUse">'
                                     '<path d="%s"%s/></clipPath>'
                                     % (cid, d, ' clip-rule="evenodd"' if pending_clip == 2 else ""))
                    self.clip_bbox[cid] = bbox
                    clip = cid
            pending_clip = 0
            segs = []; cur = []; startpt = None; pos = None; pts_all = []

        while True:
            t = p.token()
            if t is None:
                break
            c = t[:1]
            if c.isdigit() or c in b"+-." or c in b"(</[":
                p.i -= len(t); ops.append(p.obj()); continue
            op = t.decode("latin-1", "replace")
            try:
                if op == "q":
                    gs.append((ctm, fill, stroke, lw, clip, alpha, salpha, dash))
                elif op == "Q":
                    if gs:
                        ctm, fill, stroke, lw, clip, alpha, salpha, dash = gs.pop()
                elif op == "cm":
                    ctm = mul(tuple(float(x) for x in ops[-6:]), ctm)
                elif op == "w":
                    lw = num(-1)
                elif op == "d":
                    arr = ops[-2] if len(ops) >= 2 and isinstance(ops[-2], list) else []
                    sc = math.hypot(ctm[0], ctm[1])
                    dash = " ".join(_fmt(round(float(v) * sc, 2)) for v in arr if isinstance(v, (int, float))) if arr else ""
                elif op == "gs":
                    g = pdf.res(egs.get(str(ops[-1]))) if ops else None
                    if isinstance(g, dict):
                        if "ca" in g: alpha = float(pdf.res(g["ca"]))
                        if "CA" in g: salpha = float(pdf.res(g["CA"]))
                elif op == "m":
                    close_sub()
                    pos = self._tf(ctm, num(-2), num(-1))
                    cur = [("M", pos)]; startpt = pos; pts_all.append(pos)
                elif op == "l":
                    pos = self._tf(ctm, num(-2), num(-1))
                    cur.append(("L", pos)); pts_all.append(pos)
                elif op in ("c", "v", "y"):
                    if op == "c":
                        a = self._tf(ctm, num(-6), num(-5)); b = self._tf(ctm, num(-4), num(-3))
                        e = self._tf(ctm, num(-2), num(-1))
                    elif op == "v":
                        a = pos or self._tf(ctm, num(-4), num(-3))
                        b = self._tf(ctm, num(-4), num(-3)); e = self._tf(ctm, num(-2), num(-1))
                    else:
                        a = self._tf(ctm, num(-4), num(-3)); e = self._tf(ctm, num(-2), num(-1)); b = e
                    cur.append(("C", (a[0], a[1], b[0], b[1], e[0], e[1])))
                    pts_all += [a, b, e]; pos = e
                elif op == "h":
                    if cur:
                        cur.append(("Z", ()));  pos = startpt
                elif op == "re":
                    x, y, w_, h_ = num(-4), num(-3), num(-2), num(-1)
                    q = [self._tf(ctm, x, y), self._tf(ctm, x + w_, y),
                         self._tf(ctm, x + w_, y + h_), self._tf(ctm, x, y + h_)]
                    close_sub()
                    segs.append([("M", q[0]), ("L", q[1]), ("L", q[2]), ("L", q[3]), ("Z", ())])
                    pts_all += q; startpt = q[0]; pos = q[0]
                elif op == "W":
                    pending_clip = 1
                elif op == "W*":
                    pending_clip = 2
                elif op in ("n", "f", "F", "f*", "B", "B*", "b", "b*", "S", "s"):
                    if op in ("s", "b", "b*") and cur:
                        cur.append(("Z", ()))
                    finish({"fill": op in ("f", "F", "f*", "B", "B*", "b", "b*"),
                            "stroke": op in ("S", "s", "B", "B*", "b", "b*"),
                            "eo": op.endswith("*")})
                elif op == "rg":
                    fill = tuple(max(0, min(255, int(255 * num(i)))) for i in (-3, -2, -1))
                elif op == "RG":
                    stroke = tuple(max(0, min(255, int(255 * num(i)))) for i in (-3, -2, -1))
                elif op == "g":
                    fill = (max(0, min(255, int(255 * num(-1)))),) * 3
                elif op == "G":
                    stroke = (max(0, min(255, int(255 * num(-1)))),) * 3
                elif op == "k":
                    fill = _cmyk(*[num(i) for i in (-4, -3, -2, -1)])
                elif op == "K":
                    stroke = _cmyk(*[num(i) for i in (-4, -3, -2, -1)])
                elif op in ("sc", "scn", "SC", "SCN"):
                    v = [o for o in ops if isinstance(o, (int, float))]
                    col = None
                    if len(v) >= 4: col = _cmyk(*[float(x) for x in v[-4:]])
                    elif len(v) == 3: col = tuple(max(0, min(255, int(255 * float(x)))) for x in v)
                    elif len(v) == 1: col = (max(0, min(255, int(255 * float(v[0])))),) * 3
                    if col:
                        if op in ("sc", "scn"): fill = col
                        else: stroke = col
                elif op == "BT":
                    tm = tlm = (1, 0, 0, 1, 0, 0)
                elif op == "Tf":
                    tfont = fonts.get(str(ops[-2])) if len(ops) >= 2 else None
                    tfs = num(-1)
                elif op == "TL": leading = num(-1)
                elif op == "Ts": trise = num(-1)
                elif op == "Tz": thscale = num(-1) / 100.0
                elif op == "Td":
                    tlm = mul((1, 0, 0, 1, num(-2), num(-1)), tlm); tm = tlm
                elif op == "TD":
                    leading = -num(-1)
                    tlm = mul((1, 0, 0, 1, num(-2), num(-1)), tlm); tm = tlm
                elif op == "Tm":
                    tm = tlm = tuple(float(x) for x in ops[-6:])
                elif op == "T*":
                    tlm = mul((1, 0, 0, 1, 0, -leading), tlm); tm = tlm
                elif op in ("Tj", "TJ", "'", '"'):
                    if op in ("'", '"'):
                        tlm = mul((1, 0, 0, 1, 0, -leading), tlm); tm = tlm
                    arr = ops[-1] if ops else b""
                    parts = arr if isinstance(arr, list) else [arr]
                    buf = ""
                    for el in parts:
                        if isinstance(el, bytes):
                            buf += tfont.decode(el) if tfont else el.decode("latin-1", "replace")
                        elif isinstance(el, (int, float)) and el < -180:
                            buf += " "
                    M = mul(mul((1, 0, 0, 1, 0, trise), tm), ctm)
                    self._emit_text(buf, M, tfs, fill, clip, alpha, thscale)
                    adv = sum(len(e) for e in parts if isinstance(e, bytes)) * 0.5 * tfs * thscale
                    tm = mul((1, 0, 0, 1, adv, 0), tm)
                elif op == "Do":
                    xo = pdf.res(xobjs.get(str(ops[-1])))
                    if isinstance(xo, Stream):
                        sub = str(pdf.res(xo.dict.get("Subtype")))
                        if sub == "Form":
                            mtx = pdf.res(xo.dict.get("Matrix")) or [1, 0, 0, 1, 0, 0]
                            r2 = pdf.res(xo.dict.get("Resources")) or res
                            self._exec(pdf.data(xo), r2,
                                       mul(tuple(float(x) for x in mtx), ctm), clip, depth + 1)
                        elif sub == "Image":
                            self._emit_image(xo, ctm, clip, alpha)
            except Exception:
                pass
            ops = []

    def _emit_text(self, text, M, size, fill, clip, alpha, hscale):
        if not text.strip():
            return
        x, y = M[4], M[5]
        out = self.text_filter(text, x, y, abs(size * math.hypot(M[0], M[1])))
        if not out:
            return
        # glyphs are laid out y-up in text space; SVG draws them y-down
        f = (M[0], M[1], -M[2], -M[3], M[4], M[5])
        sc = math.hypot(M[0], M[1]) or 1.0
        em = abs(size * sc)
        # the run advances along its own writing direction, which on these sheets
        # is often vertical — a direction-blind box would reach back across the
        # drawing and drag unrelated content into every crop.
        adv = em * 0.62 * len(out)
        ex, ey = x + adv * (M[0] / sc), y + adv * (M[1] / sc)
        bbox = (min(x, ex) - em, min(y, ey) - em, max(x, ex) + em, max(y, ey) + em)
        esc = (out.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        attrs = 'font-size="%s" fill="%s"' % (_fmt(round(size, 2)), _rgb(fill))
        if hscale and abs(hscale - 1) > 0.01:
            attrs += ' textLength-adjust="spacing"'
        if clip:
            attrs += ' clip-path="url(#%s)"' % clip
        self.items.append(Item(
            '<text transform="matrix(%s)" %s>%s</text>'
            % (",".join(_fmt(round(v, 4)) for v in f), attrs, esc),
            bbox, "text", out))

    # ----------------------------------------------------------------- emit
    def content_bbox(self, kinds=("path", "image"), inside=None):
        xs0 = ys0 = 1e18; xs1 = ys1 = -1e18
        for it in self.items:
            if it.kind not in kinds:
                continue
            b = it.bbox
            if inside and not _overlaps(b, inside):
                continue
            if b[2] - b[0] > self.W * 0.99 and b[3] - b[1] > self.H * 0.99:
                continue                      # full-page background rectangle
            xs0 = min(xs0, b[0]); ys0 = min(ys0, b[1])
            xs1 = max(xs1, b[2]); ys1 = max(ys1, b[3])
        return (xs0, ys0, xs1, ys1)

    def drawing_crop(self, margin=6):
        """Bounding box of the drawing alone, with the developer's title band cut off.

        These sheets put a coloured band down one side carrying the sales-album
        branding, a render and the position insets. The band is the largest solid
        fill touching a vertical page edge; everything beyond it is the drawing.
        Edge slivers (band borders that wrap the page) are ignored so a 1.5pt
        artefact cannot stretch the crop to the full sheet.
        """
        page_area = self.W * self.H
        band_x0, band_x1 = self.W, 0.0
        for it in self.items:
            b = it.bbox
            if it.kind != "path" or 'fill="none"' in it.svg:
                continue
            if (b[2] - b[0]) * (b[3] - b[1]) < page_area * 0.06:
                continue
            if b[3] - b[1] < self.H * 0.5:
                continue
            if b[2] > self.W - margin:
                band_x0 = min(band_x0, b[0])       # band on the right
            elif b[0] < margin:
                band_x1 = max(band_x1, b[2])       # band on the left
        lo, hi = band_x1, band_x0
        self.band_x0 = band_x0 if band_x0 < self.W else None
        xs = []
        for it in self.items:
            if it.kind not in ("path", "image"):
                continue
            b = it.bbox
            if b[0] < lo - 1 or b[2] > hi + 1:
                continue
            w, h = b[2] - b[0], b[3] - b[1]
            if min(w, h) < 5 and (b[0] < 3 or b[1] < 3 or b[2] > self.W - 3 or b[3] > self.H - 3):
                continue                            # page-edge sliver
            if w * h > page_area * 0.6:
                continue                            # full-sheet background
            xs.append(b)
        if not xs:
            return (0, 0, self.W, self.H)
        return (min(b[0] for b in xs), min(b[1] for b in xs),
                max(b[2] for b in xs), max(b[3] for b in xs))

    def svg(self, crop=None, pad=8, background="#ffffff", extra=""):
        crop = crop or (0, 0, self.W, self.H)
        x0, y0, x1, y1 = crop[0] - pad, crop[1] - pad, crop[2] + pad, crop[3] + pad
        # A CAD sheet is tens of thousands of hairlines that share a handful of
        # styles. Emitted one <path> per operation the file is ~5x bigger than it
        # needs to be, so coalesce runs of adjacent same-styled paths into one
        # element. Adjacent only — reordering would change what paints over what.
        crop_box = (x0, y0, x1, y1)
        body = []
        run_attrs, run_d = None, []

        def flush():
            if run_d:
                body.append('<path d="%s" %s/>' % ("".join(run_d), run_attrs))
            del run_d[:]

        def strip_noop_clip(svg):
            """A clip that already contains the whole crop paints nothing extra —
            dropping it lets far more paths coalesce."""
            m = _CLIP_RE.search(svg)
            if not m:
                return svg
            b = self.clip_bbox.get(m.group(1))
            if b and b[0] <= x0 and b[1] <= y0 and b[2] >= x1 and b[3] >= y1:
                return svg.replace(m.group(0), "").replace("  ", " ").replace(" />", "/>")
            return svg

        for it in self.items:
            if not _overlaps(it.bbox, crop_box):
                continue
            if self.band_x0 is not None and it.bbox[0] >= self.band_x0:
                continue                      # developer's sales band, never the drawing
            svg = strip_noop_clip(it.svg)
            m = _PATH_RE.match(svg) if it.kind == "path" else None
            if m and "clip-path" not in m.group(2):
                if m.group(2) != run_attrs:
                    flush(); run_attrs = m.group(2)
                run_d.append(m.group(1))
                continue
            flush(); run_attrs = None
            body.append(svg)
        flush()
        used = "".join(body)
        defs = [d for d in self.defs
                if re.search(r'id="([^"]+)"', d) and
                ('url(#%s)' % re.search(r'id="([^"]+)"', d).group(1)) in used]
        w, h = x1 - x0, y1 - y0
        bg = ('<rect x="%s" y="%s" width="%s" height="%s" fill="%s"/>'
              % (_fmt(x0), _fmt(y0), _fmt(w), _fmt(h), background)) if background else ""
        return ('<svg xmlns="http://www.w3.org/2000/svg" '
                'xmlns:xlink="http://www.w3.org/1999/xlink" '
                'viewBox="%s %s %s %s" width="%s" height="%s" '
                'font-family="Inter, Helvetica, Arial, sans-serif">'
                '<defs>%s</defs>%s%s%s</svg>'
                % (_fmt(x0), _fmt(y0), _fmt(w), _fmt(h), _fmt(round(w)), _fmt(round(h)),
                   "".join(defs), bg, used, extra))

    def data_uri(self, **kw):
        return "data:image/svg+xml;base64," + base64.b64encode(
            self.svg(**kw).encode("utf-8")).decode()


_PATH_RE = re.compile(r'^<path d="([^"]*)" (.*?)\s*/>$')
_CLIP_RE = re.compile(r'\s*clip-path="url\(#([^)]+)\)"')


def _overlaps(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _cmyk(c, m, y, k):
    return (max(0, min(255, int(255 * (1 - min(1, c + k))))),
            max(0, min(255, int(255 * (1 - min(1, m + k))))),
            max(0, min(255, int(255 * (1 - min(1, y + k))))))


def _font_map(pdf, res):
    from pdfmini import Font
    fr = pdf.res(res.get("Font")) or {}
    out = {}
    for k, v in fr.items():
        fd = pdf.res(v)
        if isinstance(fd, dict):
            try:
                out[k] = Font(pdf, fd)
            except Exception:
                pass
    return out
