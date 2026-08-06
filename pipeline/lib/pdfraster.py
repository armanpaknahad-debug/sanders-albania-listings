#!/usr/bin/env python3
"""pdfraster — preview rasteriser for the plan sheets (proofing only).

Not a general renderer: enough of the imaging model (paths, fills, strokes,
rectangular clips, images with soft masks) to SEE a CAD plan sheet so room
hotspots can be placed against it. JPEG decoding is delegated to ffmpeg.
"""
import sys, os, re, subprocess, tempfile, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdfmini import PDF, Stream, Parser, mul

def ffmpeg_decode(jpeg_bytes, ext="jpg"):
    """JPEG/PNG bytes -> (w,h,rgb bytes) using ffmpeg (no image lib available)."""
    d = tempfile.mkdtemp()
    src, dst = os.path.join(d, "i." + ext), os.path.join(d, "o.ppm")
    open(src, "wb").write(jpeg_bytes)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-pix_fmt", "rgb24", dst],
                       capture_output=True)
    if r.returncode != 0 or not os.path.exists(dst):
        return None
    raw = open(dst, "rb").read()
    # P6\n<w> <h>\n255\n
    m = re.match(rb"P6\s+(\d+)\s+(\d+)\s+(\d+)\s", raw)
    w, h = int(m.group(1)), int(m.group(2))
    return w, h, raw[m.end():m.end() + w * h * 3]


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = bytearray(b"\xff" * (w * h * 3))

    def span(self, y, x0, x1, rgb, alpha=1.0):
        if y < 0 or y >= self.h: return
        x0 = max(0, int(math.floor(x0))); x1 = min(self.w, int(math.ceil(x1)))
        if x1 <= x0: return
        p = self.px; base = (y * self.w) * 3
        r, g, b = rgb
        if alpha >= 0.999:
            row = bytes((r, g, b)) * (x1 - x0)
            p[base + x0 * 3: base + x1 * 3] = row
        else:
            ia = 1 - alpha
            for x in range(x0, x1):
                i = base + x * 3
                p[i]   = int(p[i] * ia + r * alpha)
                p[i+1] = int(p[i+1] * ia + g * alpha)
                p[i+2] = int(p[i+2] * ia + b * alpha)

    def put(self, x, y, rgb, alpha=1.0):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            if alpha >= 0.999:
                self.px[i], self.px[i+1], self.px[i+2] = rgb
            else:
                ia = 1 - alpha
                self.px[i]   = int(self.px[i] * ia + rgb[0] * alpha)
                self.px[i+1] = int(self.px[i+1] * ia + rgb[1] * alpha)
                self.px[i+2] = int(self.px[i+2] * ia + rgb[2] * alpha)

    def write_png(self, path):
        d = tempfile.mkdtemp(); ppm = os.path.join(d, "o.ppm")
        with open(ppm, "wb") as f:
            f.write(b"P6\n%d %d\n255\n" % (self.w, self.h)); f.write(self.px)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", ppm, path], check=True)


def fill_poly(cv, polys, rgb, clip, evenodd=False, alpha=1.0):
    pts = [p for poly in polys for p in poly]
    if not pts: return
    ys = [p[1] for p in pts]
    y0 = max(int(math.floor(min(ys))), int(clip[1]), 0)
    y1 = min(int(math.ceil(max(ys))), int(clip[3]), cv.h - 1)
    edges = []
    for poly in polys:
        n = len(poly)
        for i in range(n):
            ax, ay = poly[i]; bx, by = poly[(i + 1) % n]
            if ay != by: edges.append((ax, ay, bx, by))
    for y in range(y0, y1 + 1):
        yc = y + 0.5
        xs = []
        for ax, ay, bx, by in edges:
            if (ay <= yc < by) or (by <= yc < ay):
                t = (yc - ay) / (by - ay)
                xs.append((ax + t * (bx - ax), 1 if by > ay else -1))
        if not xs: continue
        xs.sort()
        if evenodd:
            for i in range(0, len(xs) - 1, 2):
                cv.span(y, max(xs[i][0], clip[0]), min(xs[i+1][0], clip[2]), rgb, alpha)
        else:
            wind = 0; start = None
            for x, d in xs:
                prev = wind; wind += d
                if prev == 0 and wind != 0: start = x
                elif prev != 0 and wind == 0 and start is not None:
                    cv.span(y, max(start, clip[0]), min(x, clip[2]), rgb, alpha)
                    start = None


def stroke_poly(cv, polys, rgb, width, clip, closed_flags=None, alpha=1.0):
    w = max(width, 0.8)
    half = w / 2.0
    for poly in polys:
        for i in range(len(poly) - 1):
            ax, ay = poly[i]; bx, by = poly[i + 1]
            dx, dy = bx - ax, by - ay
            L = math.hypot(dx, dy)
            if L < 1e-9:
                continue
            nx, ny = -dy / L * half, dx / L * half
            quad = [(ax + nx, ay + ny), (bx + nx, by + ny), (bx - nx, by - ny), (ax - nx, ay - ny)]
            fill_poly(cv, [quad], rgb, clip, alpha=alpha)


def flat_bezier(p0, p1, p2, p3, n=12):
    out = []
    for i in range(1, n + 1):
        t = i / n; mt = 1 - t
        out.append((mt**3*p0[0] + 3*mt*mt*t*p1[0] + 3*mt*t*t*p2[0] + t**3*p3[0],
                    mt**3*p0[1] + 3*mt*mt*t*p1[1] + 3*mt*t*t*p2[1] + t**3*p3[1]))
    return out


class Renderer:
    def __init__(self, pdf, page, scale=2.0):
        self.pdf, self.page = pdf, page
        mb = [float(x) for x in pdf.res(page.get("MediaBox"))]
        self.mb = mb
        self.scale = scale
        w0 = int((mb[2] - mb[0]) * scale); h0 = int((mb[3] - mb[1]) * scale)
        rot = int(pdf.res(page.get("Rotate")) or 0) % 360
        # device matrix: PDF y-up -> raster y-down, then the page's /Rotate
        base = (scale, 0, 0, -scale, -mb[0] * scale, mb[3] * scale)
        if rot == 90:
            self.W, self.H = h0, w0; self.dev = mul(base, (0, 1, -1, 0, h0, 0))
        elif rot == 180:
            self.W, self.H = w0, h0; self.dev = mul(base, (-1, 0, 0, -1, w0, h0))
        elif rot == 270:
            self.W, self.H = h0, w0; self.dev = mul(base, (0, -1, 1, 0, 0, w0))
        else:
            self.W, self.H = w0, h0; self.dev = base
        self.cv = Canvas(self.W, self.H)
        self.imgcache = {}
        self.texts = []

    def run(self):
        res = self.pdf.res(self.page.get("Resources")) or {}
        self._exec(self.pdf.content(self.page), res, self.dev, (0, 0, self.W, self.H), 0)
        return self.cv

    def _tf(self, m, x, y):
        return (m[0]*x + m[2]*y + m[4], m[1]*x + m[3]*y + m[5])

    def _exec(self, content, res, ctm, clip, depth):
        if depth > 5: return
        pdf = self.pdf
        xobjs = pdf.res(res.get("XObject")) or {}
        egs = pdf.res(res.get("ExtGState")) or {}
        p = Parser(content)
        st = []
        fill = (0, 0, 0); stroke = (0, 0, 0); lw = 1.0
        alpha = 1.0; salpha = 1.0
        cur = []; polys = []; start = None; pos = None
        pending_clip = None
        ops = []
        def num(i):
            try: return float(ops[i])
            except Exception: return 0.0
        while True:
            t = p.token()
            if t is None: break
            c = t[:1]
            if c.isdigit() or c in b"+-." or c in b"(</[":
                p.i -= len(t); ops.append(p.obj()); continue
            op = t.decode("latin-1", "replace")
            try:
                if op == "q":
                    st.append((ctm, fill, stroke, lw, clip, alpha, salpha))
                elif op == "Q":
                    if st: ctm, fill, stroke, lw, clip, alpha, salpha = st.pop()
                elif op == "cm":
                    ctm = mul(tuple(float(x) for x in ops[-6:]), ctm)
                elif op == "w": lw = num(-1)
                elif op == "gs":
                    g = pdf.res(egs.get(str(ops[-1]))) if ops else None
                    if isinstance(g, dict):
                        if "ca" in g: alpha = float(pdf.res(g["ca"]))
                        if "CA" in g: salpha = float(pdf.res(g["CA"]))
                elif op == "m":
                    if cur: polys.append(cur)
                    pos = self._tf(ctm, num(-2), num(-1)); cur = [pos]; start = pos
                elif op == "l":
                    pos = self._tf(ctm, num(-2), num(-1)); cur.append(pos)
                elif op == "c":
                    a = self._tf(ctm, num(-6), num(-5)); b = self._tf(ctm, num(-4), num(-3))
                    e = self._tf(ctm, num(-2), num(-1))
                    cur += flat_bezier(pos or a, a, b, e); pos = e
                elif op == "v":
                    b = self._tf(ctm, num(-4), num(-3)); e = self._tf(ctm, num(-2), num(-1))
                    cur += flat_bezier(pos or b, pos or b, b, e); pos = e
                elif op == "y":
                    a = self._tf(ctm, num(-4), num(-3)); e = self._tf(ctm, num(-2), num(-1))
                    cur += flat_bezier(pos or a, a, e, e); pos = e
                elif op == "h":
                    if cur and start: cur.append(start)
                elif op == "re":
                    x, y, w_, h_ = num(-4), num(-3), num(-2), num(-1)
                    q = [self._tf(ctm, x, y), self._tf(ctm, x+w_, y), self._tf(ctm, x+w_, y+h_), self._tf(ctm, x, y+h_)]
                    if cur: polys.append(cur)
                    cur = q + [q[0]]; polys.append(cur); cur = []; start = q[0]; pos = q[0]
                elif op in ("W", "W*"):
                    pending_clip = True
                elif op in ("n","f","F","f*","B","B*","b","b*","S","s"):
                    if cur: polys.append(cur); cur = []
                    if op in ("s","b","b*") and polys and start:
                        polys[-1].append(start)
                    sw = abs(lw * math.hypot(ctm[0], ctm[1]))
                    if op in ("f","F","f*","B","B*","b","b*"):
                        fill_poly(self.cv, polys, fill, clip, evenodd=op.endswith("*"), alpha=alpha)
                    if op in ("S","s","B","B*","b","b*"):
                        stroke_poly(self.cv, polys, stroke, sw, clip, alpha=salpha)
                    if pending_clip:
                        pts = [pt for pl in polys for pt in pl]
                        if pts:
                            nb = (max(clip[0], min(q[0] for q in pts)), max(clip[1], min(q[1] for q in pts)),
                                  min(clip[2], max(q[0] for q in pts)), min(clip[3], max(q[1] for q in pts)))
                            clip = nb
                        pending_clip = None
                    polys = []; start = None; pos = None
                elif op == "rg": fill = tuple(int(255*num(i)) for i in (-3,-2,-1))
                elif op == "RG": stroke = tuple(int(255*num(i)) for i in (-3,-2,-1))
                elif op == "g": fill = (int(255*num(-1)),)*3
                elif op == "G": stroke = (int(255*num(-1)),)*3
                elif op == "k": fill = self._cmyk(*[num(i) for i in (-4,-3,-2,-1)])
                elif op == "K": stroke = self._cmyk(*[num(i) for i in (-4,-3,-2,-1)])
                elif op in ("sc","scn"):
                    v=[o for o in ops if isinstance(o,(int,float))]
                    if len(v)>=3: fill=tuple(int(255*float(x)) for x in v[-3:])
                    elif len(v)==1: fill=(int(255*float(v[0])),)*3
                elif op in ("SC","SCN"):
                    v=[o for o in ops if isinstance(o,(int,float))]
                    if len(v)>=3: stroke=tuple(int(255*float(x)) for x in v[-3:])
                    elif len(v)==1: stroke=(int(255*float(v[0])),)*3
                elif op == "Do":
                    xo = pdf.res(xobjs.get(str(ops[-1])))
                    if isinstance(xo, Stream):
                        sub = str(pdf.res(xo.dict.get("Subtype")))
                        if sub == "Form":
                            mtx = pdf.res(xo.dict.get("Matrix")) or [1,0,0,1,0,0]
                            r2 = pdf.res(xo.dict.get("Resources")) or res
                            self._exec(pdf.data(xo), r2, mul(tuple(float(x) for x in mtx), ctm), clip, depth+1)
                        elif sub == "Image":
                            self._image(xo, ctm, clip, alpha)
            except Exception:
                pass
            ops = []

    @staticmethod
    def _cmyk(c,m,y,k):
        return (int(255*(1-min(1,c+k))), int(255*(1-min(1,m+k))), int(255*(1-min(1,y+k))))

    def _decode_img(self, xo):
        key = id(xo)
        if key in self.imgcache: return self.imgcache[key]
        pdf = self.pdf
        f = pdf.res(xo.dict.get("Filter")) or []
        if not isinstance(f, list): f = [f]
        f = [str(x) for x in f]
        data = pdf.data(xo)
        w = int(pdf.res(xo.dict.get("Width"))); h = int(pdf.res(xo.dict.get("Height")))
        rgb = None
        if "DCTDecode" in f:
            r = ffmpeg_decode(data, "jpg")
            if r: w, h, rgb = r
        else:
            bpc = pdf.res(xo.dict.get("BitsPerComponent")) or 8
            cs = str(pdf.res(xo.dict.get("ColorSpace")) or "")
            if pdf.res(xo.dict.get("ImageMask")):
                rgb = None
            elif bpc == 8 and "RGB" in cs and len(data) >= w*h*3:
                rgb = data[:w*h*3]
            elif bpc == 8 and "Gray" in cs and len(data) >= w*h:
                rgb = bytes(b for v in data[:w*h] for b in (v, v, v))
        # soft mask
        alpha = None
        sm = pdf.res(xo.dict.get("SMask"))
        if isinstance(sm, Stream):
            sf = pdf.res(sm.dict.get("Filter")) or []
            if not isinstance(sf, list): sf = [sf]
            sf = [str(x) for x in sf]
            sw = int(pdf.res(sm.dict.get("Width"))); sh = int(pdf.res(sm.dict.get("Height")))
            sd = pdf.data(sm)
            if "DCTDecode" in sf:
                r = ffmpeg_decode(sd, "jpg")
                if r: sw, sh, sd3 = r; alpha = (sw, sh, bytes(sd3[i] for i in range(0, len(sd3), 3)))
            elif len(sd) >= sw*sh:
                alpha = (sw, sh, sd[:sw*sh])
        out = (w, h, rgb, alpha)
        self.imgcache[key] = out
        return out

    def _image(self, xo, ctm, clip, galpha):
        w, h, rgb, amask = self._decode_img(xo)
        if rgb is None: return
        # unit square -> device via ctm; invert to sample
        a,b,c,d,e,f = ctm
        det = a*d - b*c
        if abs(det) < 1e-12: return
        ia, ib, ic, id_ = d/det, -b/det, -c/det, a/det
        ie = -(e*ia + f*ic); iff = -(e*ib + f*id_)
        corners = [(e,f),(a+e,b+f),(c+e,d+f),(a+c+e,b+d+f)]
        x0 = max(int(min(p[0] for p in corners)), int(clip[0]), 0)
        x1 = min(int(max(p[0] for p in corners))+1, int(clip[2]), self.cv.w)
        y0 = max(int(min(p[1] for p in corners)), int(clip[1]), 0)
        y1 = min(int(max(p[1] for p in corners))+1, int(clip[3]), self.cv.h)
        for py in range(y0, y1):
            for px in range(x0, x1):
                ux = (px+0.5)*ia + (py+0.5)*ic + ie
                uy = (px+0.5)*ib + (py+0.5)*id_ + iff
                if not (0 <= ux < 1 and 0 <= uy < 1): continue
                sx = int(ux*w); sy = int((1-uy)*h)
                if sx >= w: sx = w-1
                if sy >= h: sy = h-1
                i = (sy*w+sx)*3
                if i+2 >= len(rgb): continue
                al = galpha
                if amask:
                    aw, ah, ad = amask
                    ax = min(int(ux*aw), aw-1); ay = min(int((1-uy)*ah), ah-1)
                    j = ay*aw+ax
                    if j < len(ad): al = galpha * (ad[j]/255.0)
                if al <= 0.02: continue
                self.cv.put(px, py, (rgb[i], rgb[i+1], rgb[i+2]), al)


if __name__ == "__main__":
    src, out = sys.argv[1], sys.argv[2]
    sc = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
    doc = PDF(src)
    r = Renderer(doc, doc.pages()[0], sc)
    r.run().write_png(out)
    print("wrote", out, r.W, "x", r.H)
