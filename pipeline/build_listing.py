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
LOGO = HERE / "lib" / "logo.png"

def datauri(path, w, q=82):
    im = Image.open(path).convert("RGB")
    if im.width > w:
        im = im.resize((w, int(im.height*w/im.width)), Image.LANCZOS)
    b = io.BytesIO(); im.save(b, "JPEG", quality=q, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()

def logo_uri():
    return "data:image/png;base64," + base64.b64encode(LOGO.read_bytes()).decode()

def esc(s): return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def build(cfg, base):
    slug = cfg["slug"]
    hero = datauri(base/cfg["hero"], 1700)
    gal  = [(datauri(base/g[0], 1200), g[1]) for g in cfg.get("gallery", [])]
    spec = cfg.get("spec", [])
    hl   = cfg.get("highlights", [])
    LG   = logo_uri()

    spec_html = "".join(
        f'<div><div class="n">{esc(str(v))}</div><div class="k">{esc(k)}</div></div>'
        for k, v in spec)
    gal_html = "".join(
        f'<figure><img src="{u}" alt="{esc(cap)}"><figcaption>{esc(cap)}</figcaption></figure>'
        for u, cap in gal)
    hl_html = "".join(f"<div>{esc(x)}</div>" for x in hl)

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<link rel="icon" href="/favicon.ico" sizes="any"><link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(cfg['name'])} — {esc(cfg.get('development',''))} · Sanders</title>
<meta name="description" content="{esc(cfg.get('sub',''))}">
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
nav{{position:sticky;top:0;z-index:20;background:rgba(244,240,230,.92);backdrop-filter:blur(8px);border-bottom:1px solid rgba(28,58,46,.12)}}
.navin{{max-width:1160px;margin:0 auto;padding:12px clamp(22px,6vw,56px);display:flex;align-items:center;justify-content:space-between;gap:10px 16px;flex-wrap:wrap}}
.brand{{display:flex;align-items:center;gap:10px;font-weight:600;letter-spacing:.26em;font-size:13px;color:var(--green)}}
.brand img{{width:22px;height:auto}}
.navmid{{font-size:11px;letter-spacing:.20em;color:#6b7a71;text-transform:uppercase;display:none}}
@media(min-width:900px){{.navmid{{display:block}}}}
.btn{{display:inline-block;font-weight:600;font-size:12px;letter-spacing:.14em;text-transform:uppercase;padding:11px 20px;border-radius:2px;text-decoration:none;transition:.18s}}
.btn-out{{background:transparent;color:var(--green);border:1px solid rgba(28,58,46,.4)}}.btn-out:hover{{border-color:var(--green)}}
.btn-terra{{background:var(--terra);color:#fff;border:1px solid var(--terra)}}.btn-terra:hover{{background:#a8512f}}
.hero{{position:relative;min-height:82vh;display:flex;align-items:flex-end;color:var(--ivory2);background:#0d1a14 center/cover no-repeat}}
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
.plancard iframe{{width:100%;border:0;display:block;min-height:340px}}
.gal{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-top:8px}}
@media(max-width:680px){{.gal{{grid-template-columns:1fr}}}}
.gal figure{{margin:0;position:relative;border-radius:10px;overflow:hidden;aspect-ratio:16/10}}
.gal img{{width:100%;height:100%;object-fit:cover}}
.gal figcaption{{position:absolute;left:14px;bottom:12px;color:#fff;font-size:11px;letter-spacing:.20em;text-transform:uppercase;text-shadow:0 1px 6px rgba(0,0,0,.5)}}
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
</style></head><body>
<nav><div class="navin">
 <div class="brand"><img src="{LG}" alt="Sanders">SANDERS</div>
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
<section style="padding-top:0"><div class="wrap">
 <p class="eyebrow">Explore the residence</p><h2>Walk it, room by room</h2>
 <p class="lead">Tap any room on the plan to see its size.</p>
 <div class="plancard"><iframe class="plan-embed" src="plan.html" title="Interactive floor plan" loading="lazy"
   onload="window.addEventListener('message',function(e){{if(e.data&&e.data.sandersPlanHeight){{var f=document.querySelector('.plan-embed');if(f)f.style.height=(e.data.sandersPlanHeight+8)+'px';}}}})"></iframe></div>
</div></section>
{"<section style='padding-top:0'><div class='wrap'><div class='gal'>"+gal_html+"</div></div></section>" if gal_html else ""}
<section class="loc"><div class="wrap">
 <p class="eyebrow">Location &amp; setting</p><h2>{esc(cfg.get('location_h2','Location & setting'))}</h2>
 <p class="lead">{esc(cfg.get('location_body',''))}</p>
 {"<div class='hl'>"+hl_html+"</div>" if hl_html else ""}
 <a class="back" href="/">← The Collection</a>
</div></section>
<footer><div class="wrap"><div class="fgrid">
 <div><p class="b">Sanders International</p><div style="font-size:13px">London — Tirana</div></div>
 <div><p class="k">Enquiries</p><div><a href="mailto:sales@sandersalbania.com">sales@sandersalbania.com</a></div><div><a href="tel:+447414444782">+44 7414 444782</a></div><div><a href="https://sandersalbania.com">sandersalbania.com</a></div></div>
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
