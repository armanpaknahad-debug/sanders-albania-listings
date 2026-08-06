#!/usr/bin/env python3
"""
imaging.py — image → base64 data URI, degrading gracefully by environment.

The listing pages are self-contained (base64-embedded images). Downscaling keeps
pages light, but it is an optimisation, not a requirement: cropping to the page's
aspect ratios is done in CSS (object-fit: cover), so a raw embed still renders
identically — just heavier.

Shared with the Tirana repo (one implementation, two repos, same behaviour): every
listing photo is watermarked with the Sanders mark at render time, applied AFTER the
downscale so the mark stays a constant proportion and cannot be scaled away.

Resolution order for non-photo assets (best available wins, never dead-ends):
  1. Pillow (PIL)  — resize + JPEG re-encode. Present on the real deploy box.
  2. ffmpeg        — scale + JPEG re-encode. Present wherever the film pipeline runs.
  3. sips          — macOS native, when it can write its scratch dir.
  4. raw embed     — base64 the original bytes. Always works.

Watermarking REQUIRES a real compositor — Pillow OR ffmpeg. It can never degrade
silently to an unmarked photo (see require_watermarking / datauri(watermark=True)).
Both backends implement the SAME spec (12% width, 3.5% margin, 90% opacity, soft
shadow), so a photo marked on either box is indistinguishable.
"""
import base64, io, os, shutil, subprocess, tempfile
from pathlib import Path

try:
    from PIL import Image, ImageFilter      # optimisation + watermark path
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False

_FFMPEG = shutil.which("ffmpeg")

LOGO_PATH = Path(__file__).resolve().parent / "logo.png"   # white-on-transparent mark
_LOGO_RGBA = None

WATERMARK_NEEDS_PIL = (
    "Watermarking listing photos requires Pillow or ffmpeg, and neither is "
    "available. Install one (`pip3 install pillow`, or `brew install ffmpeg`) and "
    "rebuild. The build refuses to embed or publish unwatermarked photos."
)


def require_watermarking():
    """Build gate: listing photos MUST be watermarked, so a compositor is
    mandatory. Fail loudly rather than silently publish unwatermarked
    photography — that is the failure mode this whole feature is designed
    against."""
    if not _HAVE_PIL and not _FFMPEG:
        raise RuntimeError(WATERMARK_NEEDS_PIL)


def _logo():
    global _LOGO_RGBA
    if _LOGO_RGBA is None:
        _LOGO_RGBA = Image.open(LOGO_PATH).convert("RGBA")
    return _LOGO_RGBA


def apply_watermark(im):
    """Composite the Sanders logo onto an ALREADY-DOWNSCALED RGB image, bottom-right.

    Sized as a constant proportion of the delivered image (12% of width, min 90px),
    so it renders the same everywhere and cannot be scaled away. A soft black drop
    shadow sits beneath it so the white mark stays legible on pale photos (bathroom,
    landing). Brand consistency only — this is NOT a price/marketing banner.
    Spec: margin 3.5% of width, opacity 90%, shadow ~60% opacity / blur ~3% of mark
    width, LANCZOS resample.
    """
    require_watermarking()
    base = im.convert("RGBA")
    W, H = base.size
    lw = max(90, int(round(W * 0.12)))                      # width: 12% of image, min 90px
    logo0 = _logo()
    lh = max(1, int(round(logo0.height * lw / logo0.width)))
    logo = logo0.resize((lw, lh), Image.LANCZOS)            # preserve aspect, LANCZOS
    alpha = logo.split()[3]
    margin = int(round(W * 0.035))                          # 3.5% of width from each edge
    x, y = W - lw - margin, H - lh - margin
    # drop shadow: black silhouette at ~35% opacity, offset 0, blur ~2% of mark width
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    blk = Image.new("RGBA", (lw, lh), (0, 0, 0, 255))
    blk.putalpha(alpha.point(lambda a: int(a * 0.60)))
    shadow.paste(blk, (x, y), blk)
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, int(round(lw * 0.03)))))
    # the mark itself at 90% opacity
    mark = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    lg = logo.copy()
    lg.putalpha(alpha.point(lambda a: int(a * 0.90)))
    mark.paste(lg, (x, y), lg)
    out = Image.alpha_composite(Image.alpha_composite(base, shadow), mark)
    return out.convert("RGB")


# ---------------------------------------------------------------- ffmpeg backend
def _probe(path):
    """(w, h) via ffprobe."""
    if not _FFMPEG:
        return None
    out = subprocess.run([_FFMPEG.replace("ffmpeg", "ffprobe"), "-v", "error",
                          "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0:s=x", str(path)], capture_output=True, text=True).stdout.strip()
    try:
        w, h = out.split("x")[:2]
        return int(w), int(h)
    except Exception:
        return None


def _qscale(q):
    """JPEG quality 0-100 -> mjpeg qscale 2-31 (lower is better)."""
    return max(2, min(31, int(round((100 - q) / 5.0)) or 2))


def _ffmpeg_render(path, out, w, q, watermark, cover=None):
    """Scale to width `w` and (optionally) composite the Sanders mark.

    Same spec as apply_watermark(): mark 12% of the delivered width (min 90px),
    3.5% margin, 90% opacity, over a 60%-opacity shadow blurred at ~3% of the
    mark width — applied AFTER the downscale so it stays a constant proportion.

    `cover=(W, H)` delivers exactly those pixels, scaling up to fill and centre-
    cropping the overflow — used for the OG/card thumbnail, whose dimensions are
    declared in the page's meta tags and so must be exact.
    """
    dims = _probe(path)
    if not dims:
        return False
    iw, ih = dims
    if cover:
        ow, oh = cover
        pre = (f"scale={ow}:{oh}:force_original_aspect_ratio=increase:flags=lanczos,"
               f"crop={ow}:{oh}")
    else:
        ow = min(iw, w) if w else iw
        ow -= ow % 2
        oh = max(2, int(round(ih * ow / iw)));  oh -= oh % 2
        pre = f"scale={ow}:{oh}:flags=lanczos"
    args = [_FFMPEG, "-v", "error", "-y", "-i", str(path)]
    if not watermark:
        args += ["-vf", pre, "-q:v", str(_qscale(q)), str(out)]
        return subprocess.run(args, capture_output=True).returncode == 0
    ldims = _probe(LOGO_PATH)
    if not ldims:
        return False
    lw = max(90, int(round(ow * 0.12)))
    lh = max(1, int(round(ldims[1] * lw / ldims[0])))
    margin = int(round(ow * 0.035))
    x, y = ow - lw - margin, oh - lh - margin
    blur = max(1, int(round(lw * 0.03)))
    pad = blur * 3                                    # room for the shadow to fall off
    graph = (
        f"[0:v]{pre},format=rgba[bg];"
        f"[1:v]scale={lw}:{lh}:flags=lanczos,format=rgba,split[l1][l2];"
        f"[l1]colorchannelmixer=rr=0:rg=0:rb=0:gr=0:gg=0:gb=0:br=0:bg=0:bb=0:aa=0.60,"
        f"pad={lw + 2 * pad}:{lh + 2 * pad}:{pad}:{pad}:color=black@0,gblur=sigma={blur}[sh];"
        f"[bg][sh]overlay=x={x - pad}:y={y - pad}[b2];"
        f"[l2]colorchannelmixer=aa=0.90[mk];"
        f"[b2][mk]overlay=x={x}:y={y},format=yuvj420p[out]"
    )
    args += ["-i", str(LOGO_PATH), "-filter_complex", graph, "-map", "[out]",
             "-q:v", str(_qscale(q)), str(out)]
    return subprocess.run(args, capture_output=True).returncode == 0


def _ffmpeg_uri(path, w, q, watermark):
    d = Path(tempfile.mkdtemp(prefix="ffwm_"))
    out = d / "out.jpg"
    try:
        if not _ffmpeg_render(path, out, w, q, watermark) or not out.exists():
            return None
        return "data:image/jpeg;base64," + base64.b64encode(out.read_bytes()).decode()
    finally:
        try:
            out.unlink(); d.rmdir()
        except Exception:
            pass


def _raw_uri(path):
    """Last-resort: embed the original file bytes, no transform."""
    data = Path(path).read_bytes()
    ext = Path(path).suffix.lower().lstrip(".") or "jpeg"
    mime = "png" if ext == "png" else "jpeg"
    return f"data:image/{mime};base64," + base64.b64encode(data).decode()


def _pil_uri(path, w, q, watermark=False):
    im = Image.open(path).convert("RGB")
    if im.width > w:
        im = im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
    if watermark:
        im = apply_watermark(im)               # AFTER downscaling → constant proportion
    b = io.BytesIO(); im.save(b, "JPEG", quality=q, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def _sips_uri(path, w, q):
    """macOS sips resize; returns None if sips can't write (sandboxed temp)."""
    if not shutil.which("sips"):
        return None
    try:
        tmp = Path(tempfile.mkdtemp(prefix="sips_")) / "out.jpg"
    except Exception:
        return None
    r = subprocess.run(["sips", "-Z", str(w), "-s", "format", "jpeg",
                        "-s", "formatOptions", str(q),   # honor quality (was ignored → huge files)
                        str(path), "--out", str(tmp)],
                       capture_output=True)
    if r.returncode != 0 or not tmp.exists():
        return None
    data = tmp.read_bytes()
    try: tmp.unlink(); tmp.parent.rmdir()
    except Exception: pass
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


def datauri(path, w=1600, q=82, watermark=True):
    """Best-available base64 data URI for `path`, downscaled to width `w`.

    Listing photos are watermarked (the default). Watermarking needs Pillow and must
    NEVER degrade silently, so with watermark=True and no Pillow this raises loudly.
    Non-photo assets (floor plans, diagrams) pass watermark=False and keep the
    graceful Pillow → sips → raw fallback chain."""
    path = str(path)
    if watermark:
        require_watermarking()                 # loud failure — never an unmarked photo
        if _HAVE_PIL:
            return _pil_uri(path, w, q, watermark=True)
        u = _ffmpeg_uri(path, w, q, watermark=True)
        if not u:
            raise RuntimeError("ffmpeg failed to watermark %s — refusing to embed it unmarked" % path)
        return u
    if _HAVE_PIL:
        try:
            return _pil_uri(path, w, q, watermark=False)
        except Exception:
            pass
    if _FFMPEG:
        u = _ffmpeg_uri(path, w, q, watermark=False)
        if u:
            return u
    s = _sips_uri(path, w, q)
    if s:
        return s
    return _raw_uri(path)


def dimensions(path):
    """(w, h) via PIL, ffprobe or sips (read-only, no temp needed). None if unknown."""
    if _FFMPEG:
        d = _probe(path)
        if d:
            return d
    if _HAVE_PIL:
        try:
            im = Image.open(path)
            return im.width, im.height
        except Exception:
            pass
    if shutil.which("sips"):
        try:
            out = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
                                 capture_output=True, text=True).stdout
            w = h = None
            for ln in out.splitlines():
                if "pixelWidth:" in ln: w = int(ln.split(":")[1])
                if "pixelHeight:" in ln: h = int(ln.split(":")[1])
            if w and h:
                return w, h
        except Exception:
            pass
    return None


def file_uri_from_bytes(data, mime="jpeg"):
    return f"data:image/{mime};base64," + base64.b64encode(data).decode()
