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
  2. sips          — macOS native, when it can write its scratch dir.
  3. raw embed     — base64 the original bytes. Always works.

Watermarking itself REQUIRES Pillow — it can never degrade silently to an unmarked
photo (see require_watermarking / datauri(watermark=True)).
"""
import base64, io, shutil, subprocess, tempfile
from pathlib import Path

try:
    from PIL import Image, ImageFilter      # optimisation + watermark path
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False

LOGO_PATH = Path(__file__).resolve().parent / "logo.png"   # white-on-transparent mark
_LOGO_RGBA = None

WATERMARK_NEEDS_PIL = (
    "Watermarking listing photos requires Pillow, which is not installed. "
    "Install it (`pip3 install pillow`, or point PYTHONPATH at a Pillow install) "
    "and rebuild. The build refuses to embed or publish unwatermarked photos."
)


def require_watermarking():
    """Build gate: listing photos MUST be watermarked, so Pillow is mandatory.
    Fail loudly rather than silently publish unwatermarked photography — that is
    the failure mode this whole feature is designed against."""
    if not _HAVE_PIL:
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
        return _pil_uri(path, w, q, watermark=True)
    if _HAVE_PIL:
        try:
            return _pil_uri(path, w, q, watermark=False)
        except Exception:
            pass
    s = _sips_uri(path, w, q)
    if s:
        return s
    return _raw_uri(path)


def dimensions(path):
    """(w, h) via PIL or sips (read-only, no temp needed). None if unknown."""
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
