#!/usr/bin/env python3
"""
build_listing.py — turn a unit config.json (+ image files) into a self-contained
listing page: <slug>/index.html. Cypress brand system, real Sanders logo, mobile
spacing baked in, and the interactive plan embedded via <iframe src="plan.html">.

Usage:
    python3 build_listing.py path/to/config.json

Config schema — see config.example.json. Images referenced in the config are read
from disk, downscaled, JPEG-compressed and base64-embedded so the page is one file.
Writes <slug>/index.html (slug from config). plan.html + thumb.jpg are produced by
the other steps (build_plan.py / onboard.py).
"""
import json, sys, base64, io, os
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
# The mark ships in two tones. The rule, applied everywhere: the white mark only
# ever sits on the forest-green bands; the dark mark on ivory/light backgrounds.
LOGO = HERE / "lib" / "logo.png"           # white — for dark green backgrounds
LOGO_DARK = HERE / "lib" / "logo-dark.png"  # #1C3A2E — for ivory/light backgrounds

def datauri(path, w, q=82):
    im = Image.open(path).convert("RGB")
    if im.width > w:
        im = im.resize((w, int(im.height*w/im.width)), Image.LANCZOS)
    b = io.BytesIO(); im.save(b, "JPEG", quality=q, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()

def logo_uri(dark=False):
    """The real Sanders mark. dark=True returns the #1C3A2E variant for light bands."""
    src = LOGO_DARK if dark else LOGO
    if dark and not src.exists():
        raise SystemExit(f"missing {src} — generate it from logo.png before building")
    return "data:image/png;base64," + base64.b64encode(src.read_bytes()).decode()

def esc(s): return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def build(cfg, base):
    slug = cfg["slug"]
    hero = datauri(base/cfg["hero"], 1700)
    gal  = [(datauri(base/g[0], 1200), g[1]) for g in cfg.get("gallery", [])]
    spec = cfg.get("spec", [])
    hl   = cfg.get("highlights", [])
    LG_DARK = logo_uri(dark=True)   # nav sits on ivory
    LG      = logo_uri()            # footer sits on forest green

    spec_html = "".join(
        f'<div><div class="n">{esc(str(v))}</div><div class="k">{esc(k)}</div></div>'
        for k, v in spec)
    gal_html = "".join(
        f'<figure><img src="{u}" alt="{esc(cap)}"><figcaption>{esc(cap)}</figcaption></figure>'
        for u, cap in gal)
    hl_html = "".join(f"<div>{esc(x)}</div>" for x in hl)

    # Position within the village (brochure "The Position" page): copy + village plan + 3D view
    pos_copy = cfg.get("position_copy", "")
    vill = datauri(base/cfg["village_img"], 1500) if cfg.get("village_img") else ""
    p3d  = datauri(base/cfg["pos3d_img"], 1500) if cfg.get("pos3d_img") else ""
    position_html = ""
    if pos_copy and vill and p3d:
        position_html = (
            "<section style='padding-top:0'><div class='wrap'>"
            "<p class='eyebrow'>Position within Green Coast</p>"
            f"<h2>Where {esc(cfg['name'])} sits</h2>"
            f"<p class='lead'>{esc(pos_copy)}</p>"
            "<div class='posimgs'>"
            f"<figure><img src='{vill}' alt='{esc(cfg['name'])} marked on the Green Coast village plan'>"
            f"<figcaption>The village plan · {esc(cfg['name'])} marked</figcaption></figure>"
            f"<figure><img src='{p3d}' alt='Position in three dimensions'>"
            "<figcaption>Position in three dimensions</figcaption></figure>"
            "</div></div></section>")

    # interactive plan section — omitted for units whose plan isn't ready yet
    plan_html = ""
    if cfg.get("has_plan", True):
        plan_html = (
            '<section style="padding-top:0"><div class="wrap">'
            '<p class="eyebrow">Explore the residence</p><h2>Walk it, room by room</h2>'
            '<p class="lead">Tap any room on the plan to see its size.</p>'
            '<div class="plancard"><iframe class="plan-embed" src="plan.html" title="Interactive floor plan" loading="lazy"></iframe></div>'
            '<script>(function(){window.addEventListener("message",function(e){var h=e.data&&e.data.sandersPlanHeight;'
            'if(!h)return;var f=document.querySelector(".plan-embed");if(!f)return;f.style.minHeight="0";'
            'f.style.height=(h+2)+"px";});})();</script>'
            '</div></section>')

    site = cfg.get("site", "https://listings.sandersalbania.com")
    page_url = f"{site}/{slug}/"
    og_img = f"{site}/{slug}/thumb.jpg"
    og_title = f"{cfg['name']} — {cfg.get('development','')} · Sanders"

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<link rel="icon" href="/favicon.ico" sizes="any"><link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png"><link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(cfg['name'])} — {esc(cfg.get('development',''))} · Sanders</title>
<meta name="description" content="{esc(cfg.get('sub',''))}">
<link rel="canonical" href="{page_url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Sanders Albania">
<meta property="og:title" content="{esc(og_title)}">
<meta property="og:description" content="{esc(cfg.get('sub',''))}">
<meta property="og:url" content="{page_url}">
<meta property="og:image" content="{og_img}">
<meta property="og:image:width" content="900">
<meta property="og:image:height" content="675">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(og_title)}">
<meta name="twitter:description" content="{esc(cfg.get('sub',''))}">
<meta name="twitter:image" content="{og_img}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;1,500;1,600&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{{--green:#1C3A2E;--ivory:#F4F0E6;--ivory2:#faf7ef;--terra:#C0623C;--gold:#C9A961;--ink:#20302a;
--sans:"DM Sans",system-ui,-apple-system,Segoe UI,Roboto,sans-serif;--disp:"Cormorant Garamond",Georgia,serif;}}
*{{box-sizing:border-box}}html,body{{margin:0}}
body{{font-family:var(--sans);color:var(--ink);background:var(--ivory);-webkit-font-smoothing:antialiased;line-height:1.6}}
img{{display:block;max-width:100%}}
.wrap{{max-width:1160px;margin:0 auto;padding:0 clamp(22px,6vw,56px)}}
.eyebrow{{font-size:11px;letter-spacing:.30em;text-transform:uppercase;color:var(--terra);font-weight:600;margin:0 0 14px}}
h2{{font-family:var(--disp);font-style:italic;font-weight:600;font-size:clamp(28px,6vw,44px);line-height:1.04;margin:0 0 18px;color:var(--green)}}
.lead{{font-size:clamp(15px,4vw,16px);color:#4c5a52;max-width:62ch;line-height:1.6}}
nav{{position:sticky;top:0;z-index:20;background:rgba(244,240,230,.92);backdrop-filter:blur(8px);border-bottom:1px solid rgba(28,58,46,.12);padding-top:env(safe-area-inset-top)}}
.navin{{max-width:1160px;margin:0 auto;padding:12px clamp(22px,6vw,56px);padding-left:max(clamp(22px,6vw,56px),env(safe-area-inset-left));padding-right:max(clamp(22px,6vw,56px),env(safe-area-inset-right));display:flex;align-items:center;justify-content:space-between;gap:10px 16px;flex-wrap:wrap}}
.brand{{display:flex;align-items:center;gap:10px;font-weight:600;letter-spacing:.26em;font-size:13px;color:var(--green)}}
.brand img{{width:22px;height:auto}}
.navmid{{font-size:11px;letter-spacing:.20em;color:#6b7a71;text-transform:uppercase;display:none}}
@media(min-width:900px){{.navmid{{display:block}}}}
.btn{{display:inline-flex;align-items:center;justify-content:center;min-height:44px;font-weight:600;font-size:12px;letter-spacing:.14em;text-transform:uppercase;padding:12px 22px;border-radius:2px;text-decoration:none;transition:.18s}}
.btn-out{{background:transparent;color:var(--green);border:1px solid rgba(28,58,46,.4)}}.btn-out:hover{{border-color:var(--green)}}
.btn-terra{{background:var(--terra);color:#fff;border:1px solid var(--terra)}}.btn-terra:hover{{background:#a8512f}}
.hero{{position:relative;min-height:82vh;min-height:82dvh;display:flex;align-items:flex-end;color:var(--ivory2);background:#0d1a14 center/cover no-repeat}}
.hero::after{{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(13,26,20,.12) 0%,rgba(13,26,20,.18) 45%,rgba(28,58,46,.93) 100%)}}
.hero .wrap{{position:relative;z-index:2;padding-top:clamp(96px,20vw,120px);padding-bottom:clamp(40px,8vw,54px);width:100%}}
.hero .eyebrow{{color:var(--terra)}}
.hero h1{{font-family:var(--disp);font-style:italic;font-weight:600;font-size:clamp(44px,12vw,86px);line-height:.98;margin:0 0 14px}}
.hero p.sub{{font-size:clamp(15px,4.3vw,17px);max-width:52ch;color:rgba(244,240,230,.9);margin:0 0 24px}}
.priceRow{{display:flex;align-items:flex-end;gap:22px;flex-wrap:wrap}}
.priceRow .lbl{{font-size:11px;letter-spacing:.26em;text-transform:uppercase;color:rgba(244,240,230,.7);margin:0 0 4px}}
.priceRow .price{{font-family:var(--disp);font-weight:600;font-size:clamp(32px,8vw,52px);line-height:1}}
.specbar{{background:var(--green);color:var(--ivory2)}}
.specgrid{{max-width:1160px;margin:0 auto;padding:26px clamp(22px,6vw,56px);display:grid;grid-template-columns:repeat({max(1,min(5,len(spec)))},1fr);gap:16px 10px;text-align:center}}
@media(max-width:720px){{.specgrid{{grid-template-columns:repeat(2,1fr);gap:20px 12px}}}}
.specgrid .n{{font-family:var(--disp);font-weight:600;font-size:clamp(22px,5vw,34px);line-height:1}}
.specgrid .k{{font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:rgba(244,240,230,.62);margin-top:6px}}
section{{padding:clamp(46px,9vw,84px) 0}}
.plancard{{margin-top:30px;background:var(--ivory2);border:1px solid rgba(28,58,46,.1);border-radius:10px;box-shadow:0 12px 38px rgba(28,58,46,.09);overflow:hidden}}
.plancard iframe{{width:100%;border:0;display:block;height:auto;min-height:0}}
.gal{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-top:8px}}
@media(max-width:680px){{.gal{{grid-template-columns:1fr}}}}
.gal figure{{margin:0;position:relative;border-radius:10px;overflow:hidden;aspect-ratio:16/10}}
.gal img{{width:100%;height:100%;object-fit:cover}}
.gal figcaption{{position:absolute;left:14px;bottom:12px;color:#fff;font-size:11px;letter-spacing:.20em;text-transform:uppercase;text-shadow:0 1px 6px rgba(0,0,0,.5)}}
.posimgs{{display:grid;grid-template-columns:1.35fr 1fr;gap:14px;margin-top:26px}}
@media(max-width:680px){{.posimgs{{grid-template-columns:1fr}}}}
.posimgs figure{{margin:0;background:var(--ivory2);border:1px solid rgba(28,58,46,.1);border-radius:10px;overflow:hidden}}
.posimgs img{{width:100%;height:auto;display:block}}
.posimgs figcaption{{padding:10px 14px 12px;font-size:10.5px;letter-spacing:.18em;text-transform:uppercase;color:#6b7a71}}
.loc{{background:var(--green);color:var(--ivory2)}}.loc h2{{color:var(--ivory2)}}.loc .lead{{color:rgba(244,240,230,.86)}}
.hl{{display:grid;grid-template-columns:1fr 1fr;gap:12px 28px;margin-top:24px;max-width:720px}}
@media(max-width:560px){{.hl{{grid-template-columns:1fr}}}}
.hl div{{font-size:15px;color:rgba(244,240,230,.92);padding-left:18px;position:relative}}
.hl div::before{{content:"";position:absolute;left:0;top:9px;width:7px;height:7px;background:var(--terra)}}
footer{{background:var(--green);color:rgba(244,240,230,.82);padding:clamp(44px,8vw,66px) 0 38px}}
.fgrid{{display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:28px}}@media(max-width:720px){{.fgrid{{grid-template-columns:1fr}}}}
footer .b{{font-family:var(--disp);font-style:italic;font-size:23px;color:var(--ivory2);margin:0 0 4px}}
footer .k{{font-size:10px;letter-spacing:.20em;text-transform:uppercase;color:var(--terra);margin:0 0 10px}}
footer a{{color:rgba(244,240,230,.82);text-decoration:none}}footer a:hover{{color:#fff}}
.disc{{margin-top:30px;padding-top:18px;border-top:1px solid rgba(244,240,230,.14);font-size:11.5px;color:rgba(244,240,230,.5);max-width:80ch}}
.back{{display:inline-block;margin-top:20px;font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:rgba(244,240,230,.7);text-decoration:none}}
.social{{display:flex;gap:10px;margin-top:14px}}
.social a{{display:inline-flex;align-items:center;justify-content:center;width:44px;height:44px;border:1px solid rgba(244,240,230,.28);border-radius:50%;transition:.18s}}
.flogo{{width:30px;height:auto;margin-bottom:10px}}
.social a:hover{{border-color:var(--terra);background:rgba(192,98,60,.18)}}
.social svg{{width:17px;height:17px;fill:rgba(244,240,230,.86)}}
.social a:hover svg{{fill:#fff}}
</style></head><body>
<nav><div class="navin">
 <div class="brand"><img src="{LG_DARK}" alt="Sanders">SANDERS</div>
 <div class="navmid">{esc(cfg['name'])} · {esc(cfg.get('development',''))}</div>
 <a class="btn btn-out" href="mailto:sales@sandersalbania.com?subject={esc(cfg['name'])}%20enquiry">Enquire</a>
</div></nav>
<header class="hero" style="background-image:url({hero})"><div class="wrap">
 <p class="eyebrow">{esc(cfg.get('eyebrow',''))}</p>
 <h1>{esc(cfg['name'])}</h1>
 <p class="sub">{esc(cfg.get('sub',''))}</p>
 <div class="priceRow"><div><p class="lbl">Guide price</p><div class="price">{esc(cfg.get('price',''))}</div></div>
 <a class="btn btn-terra" href="mailto:sales@sandersalbania.com?subject={esc(cfg['name'])}%20viewing">Book a viewing</a></div>
</header>
<div class="specbar"><div class="specgrid">{spec_html}</div></div>
<section><div class="wrap">
 <p class="eyebrow">The residence</p><h2>{esc(cfg['name'])}</h2>
 <p class="lead">{esc(cfg.get('description',''))}</p>
</div></section>
{plan_html}
{"<section style='padding-top:0'><div class='wrap'><div class='gal'>"+gal_html+"</div></div></section>" if gal_html else ""}
{position_html}
<section class="loc"><div class="wrap">
 <p class="eyebrow">Location &amp; setting</p><h2>{esc(cfg.get('location_h2','Location & setting'))}</h2>
 <p class="lead">{esc(cfg.get('location_body',''))}</p>
 {"<div class='hl'>"+hl_html+"</div>" if hl_html else ""}
 <a class="back" href="/">← The Collection</a>
</div></section>
<footer><div class="wrap"><div class="fgrid">
 <div><img class="flogo" src="{LG}" alt="Sanders"><p class="b">Sanders International</p><div style="font-size:13px">London — Tirana</div></div>
 <div><p class="k">Enquiries</p><div><a href="mailto:sales@sandersalbania.com">sales@sandersalbania.com</a></div><div><a href="tel:+447414444782">+44 7414 444782</a></div><div><a href="https://sandersalbania.com">sandersalbania.com</a></div>
  <div class="social">
   <a href="https://www.linkedin.com/company/sanders-albania/" target="_blank" rel="noopener" aria-label="Sanders on LinkedIn"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM3 9h4v12H3zM9 9h3.8v1.7h.05c.53-1 1.83-2.05 3.77-2.05C20.6 8.65 22 11 22 14.4V21h-4v-5.9c0-1.4-.03-3.2-1.95-3.2-1.95 0-2.25 1.52-2.25 3.1V21H9z"/></svg></a>
   <a href="https://www.instagram.com/sanders_int/" target="_blank" rel="noopener" aria-label="Sanders on Instagram"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.2c3.2 0 3.58.01 4.85.07 1.17.05 1.8.25 2.23.41.56.22.96.48 1.38.9.42.42.68.82.9 1.38.16.42.36 1.06.41 2.23.06 1.27.07 1.65.07 4.85s-.01 3.58-.07 4.85c-.05 1.17-.25 1.8-.41 2.23-.22.56-.48.96-.9 1.38-.42.42-.82.68-1.38.9-.42.16-1.06.36-2.23.41-1.27.06-1.65.07-4.85.07s-3.58-.01-4.85-.07c-1.17-.05-1.8-.25-2.23-.41-.56-.22-.96-.48-1.38-.9-.42-.42-.68-.82-.9-1.38-.16-.42-.36-1.06-.41-2.23C2.21 15.58 2.2 15.2 2.2 12s.01-3.58.07-4.85c.05-1.17.25-1.8.41-2.23.22-.56.48-.96.9-1.38.42-.42.82-.68 1.38-.9.42-.16 1.06-.36 2.23-.41C8.42 2.21 8.8 2.2 12 2.2zm0 1.8c-3.14 0-3.51.01-4.75.07-.9.04-1.39.19-1.71.32-.43.17-.74.37-1.06.69-.32.32-.52.63-.69 1.06-.13.32-.28.81-.32 1.71C3.41 8.49 3.4 8.86 3.4 12s.01 3.51.07 4.75c.4.9.19 1.39.32 1.71.17.43.37.74.69 1.06.32.32.63.52 1.06.69.32.13.81.28 1.71.32 1.24.06 1.61.07 4.75.07s3.51-.01 4.75-.07c.9-.04 1.39-.19 1.71-.32.43-.17.74-.37 1.06-.69.32-.32.52-.63.69-1.06.13-.32.28-.81.32-1.71.06-1.24.07-1.61.07-4.75s-.01-3.51-.07-4.75c-.04-.9-.19-1.39-.32-1.71a2.85 2.85 0 0 0-.69-1.06 2.85 2.85 0 0 0-1.06-.69c-.32-.13-.81-.28-1.71-.32C15.51 4.01 15.14 4 12 4zm0 3.05a4.95 4.95 0 1 1 0 9.9 4.95 4.95 0 0 1 0-9.9zm0 1.8a3.15 3.15 0 1 0 0 6.3 3.15 3.15 0 0 0 0-6.3zm5.15-3.24a1.16 1.16 0 1 1 0 2.32 1.16 1.16 0 0 1 0-2.32z"/></svg></a>
  </div></div>
 <div><p class="k">Offices</p><div>Fox Court, 14 Gray's Inn Road, London WC1X 8HN</div><div style="margin-top:8px">Rruga Mihal Duri 1001, Tirana, Albania</div></div>
</div><p class="disc">Particulars prepared by Sanders International for guidance only and do not form part of any contract. Areas are approximate and taken from developer drawings. Guide price is indicative and subject to change.</p></div></footer>
</body></html>"""

def main():
    cfg_path = Path(sys.argv[1])
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    base = cfg_path.parent
    out = Path(cfg["slug"]) / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    html = build(cfg, base)
    out.write_text(html, encoding="utf-8")
    print(f"built {out}  ({len(html)//1024} KB)")

if __name__ == "__main__":
    main()
