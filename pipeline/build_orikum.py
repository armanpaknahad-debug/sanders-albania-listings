#!/usr/bin/env python3
"""build_orikum.py — build a Marina Orikum listing from its plan sheet + config.

    python3 pipeline/build_orikum.py _work/orikum/sylvaine/config.json

Everything factual about the unit (building, floor, type, all five areas, the
€/m² rate) is read from the developer's plan sheet by lib/orikum.py at build
time. The config carries only editorial: name, copy, imagery, room hotspots.
That is deliberate — with 70 units to onboard, figures must never be retyped.

THE STANDING PRICE RULE: this development publishes an indicative rate per m²
and the €3,200–3,600 band. It never publishes a unit total. There is no code
path here that multiplies rate by area, and the JSON-LD omits `offers` entirely
rather than inventing a figure. See orikum.RATE_ONLY.
"""
import base64, html, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
import imaging
from plansvg import PlanSVG
from orikum import (parse_sheet, sheet_for, sheet_text_filter, RATE_BAND, RATE_BAND_NOTE,
                    PAYMENT_SCHEDULE, PAYMENT_SCHEDULE_AL, VIEW_LABEL, VIEW_LABEL_AL,
                    MEASURED_NOTE_EN, MEASURED_NOTE_AL)

ROOT = HERE.parent
SITE = "https://listings.sandersalbania.com"
SRC = Path.home() / ("Claude-Projects/GoogleDrive/Listings Sales/ORIKUM BAY/_Source/"
                     "Marina Orikum-Vlora (1)")
PHOTOS = SRC / "photo - video"
PLANS = SRC / "Floor plans"

DEV = {
    "name": "Marina Orikum",
    "town": "Orikum",
    "region": "Vlorë",
    "address": "Marina e Orikumit, Orikum 9400",
    "developer": "Concord Investment Group",
    "architect": "Chris Precht",
    "film": "../assets/video/orikum-film.mp4",
    "poster": "../assets/video/orikum-poster.jpg",
}

# Every image in this drop is a render — the towers are unbuilt, none of the
# files carry camera EXIF, and all were exported through Photoshop. Nothing here
# may be presented as a photograph of the place. See the build report.
ARTIST = "Artist's impression"


def esc(s):
    return html.escape(str(s), quote=True)


def fmt_area(v):
    if v is None:
        return None
    return ("%.2f" % v).rstrip("0").rstrip(".") + " m²"


# ---------------------------------------------------------------------- assets
def hero_uri(name, w=1600, q=74):
    return imaging.datauri(PHOTOS / name, w=w, q=q, watermark=True)


def gal_uri(name, w=1100, q=72):
    return imaging.datauri(PHOTOS / name, w=w, q=q, watermark=True)


def plan_svg(sheet, crop_pad=12):
    p = PlanSVG(sheet, text_filter=sheet_text_filter()).parse()
    svg = p.svg(crop=p.drawing_crop(), pad=crop_pad)
    vb = re.search(r'viewBox="([^"]+)"', svg).group(1)
    return svg, vb


def inset_svgs(sheet):
    """The developer's two position insets — building-in-the-masterplan and
    apartment-on-the-floor-plate — cropped out of the sales band whole.

    Cropped, not reassembled: the insets carry a tinted fill marking WHICH
    building and WHICH apartment, and that highlight is the entire point of the
    figure. Lifting the linework out element by element loses it. So we take the
    region as drawn, band colour and all, and simply leave behind the render, the
    sales-album header and the developer's logo lockup.
    """
    # no text in the insets: the sheet's own captions are Albanian, set white on
    # the band at 6pt, and this figure carries its own English captions instead.
    p = PlanSVG(sheet, text_filter=lambda *a: None).parse()
    band = [it for it in p.items
            if it.kind == "path" and 'fill="none"' not in it.svg
            and (it.bbox[2] - it.bbox[0]) * (it.bbox[3] - it.bbox[1]) > p.W * p.H * 0.06
            and it.bbox[2] > p.W - 8]
    if not band:
        return []
    bx0 = min(b.bbox[0] for b in band)
    inner = [it for it in p.items
             if it.bbox[0] > bx0 + 2 and it.kind in ("path", "text")
             and it.bbox[1] > p.H * 0.28 and it.bbox[3] < p.H * 0.88
             and (it.bbox[2] - it.bbox[0]) * (it.bbox[3] - it.bbox[1]) < p.W * p.H * 0.06]
    if not inner:
        return []
    # split the two insets at the largest vertical gap between them
    ys = sorted(inner, key=lambda it: it.bbox[1])
    gap_at, gap = None, 0
    reach = ys[0].bbox[3]
    for it in ys[1:]:
        if it.bbox[1] - reach > gap:
            gap, gap_at = it.bbox[1] - reach, (reach + it.bbox[1]) / 2
        reach = max(reach, it.bbox[3])
    groups = ([[it for it in inner if it.bbox[3] <= gap_at],
               [it for it in inner if it.bbox[3] > gap_at]] if gap > 12 else [inner])
    out = []
    for g in groups:
        if not g:
            continue
        crop = (min(b.bbox[0] for b in g), min(b.bbox[1] for b in g),
                max(b.bbox[2] for b in g), max(b.bbox[3] for b in g))
        out.append(p.svg(crop=crop, pad=10, background=None))
    return out


def svg_uri(svg):
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode()


# ------------------------------------------------------------------- fragments
def specbar(sheet, cfg):
    tiles = [("Type", cfg.get("type_label") or sheet["type"]),
             ("Net area", fmt_area(sheet["net"])),
             ("Total area", fmt_area(sheet["total"]))]
    if sheet.get("veranda"):
        tiles.append(("Veranda", fmt_area(sheet["veranda"])))
    elif sheet.get("balcony"):
        tiles.append(("Balcony", fmt_area(sheet["balcony"])))
    tiles.append(("Indicative rate", "€%s/m²" % format(sheet["rate"], ",")))
    return ('<div class="specbar"><div class="specgrid">' +
            "".join('<div><div class="n">%s</div><div class="k">%s</div></div>'
                    % (esc(v), esc(k)) for k, v in tiles) +
            "</div></div>")


def areas_table(sheet):
    rows = [("Net area (apartment)", sheet["net"]),
            ("Common area", sheet["common"]),
            ("Balcony", sheet["balcony"]),
            ("Veranda", sheet["veranda"]),
            ("Total area", sheet["total"])]
    body = "".join(
        '<tr%s><th>%s</th><td>%s</td></tr>'
        % (' class="tot"' if k == "Total area" else "", esc(k), esc(fmt_area(v) or "—"))
        for k, v in rows)
    return ('<div class="areas"><table><tbody>%s</tbody></table>'
            '<p class="note">%s The developer\'s total covers the apartment, its '
            'share of common area and any balcony; the veranda is stated '
            'separately and is not inside that figure.</p></div>'
            % (body, esc(MEASURED_NOTE_EN)))


def payment_section():
    rows = "".join('<li><b>%s</b><span>%s</span></li>' % (esc(p), esc(t))
                   for p, t in PAYMENT_SCHEDULE)
    return ("""<section class="pay"><div class="wrap">
 <p class="eyebrow">Terms</p><h2>How an off-plan purchase is staged</h2>
 <p class="lead">The developer's payment schedule, as supplied. Instalments follow
 construction, not the calendar — you pay against work completed and inspected.</p>
 <ol class="sched">%s</ol>
 <p class="note">The building permit has been obtained and construction begins within
 30 days of the developer's rate card. Completion is approximately three years.</p>
</div></section>""" % rows)


def rate_section(sheet):
    return ("""<section class="rates" style="padding-top:0"><div class="wrap">
 <p class="eyebrow">Pricing</p><h2>Priced by the metre, not by the unit</h2>
 <p class="lead">Marina Orikum is sold on an indicative rate per m², set by floor and
 by outlook. This residence sits in the %s band on floor %s, which the developer
 rates at <b>€%s/m²</b>. Across the release the band runs <b>%s</b>, %s.</p>
 <div class="ratecard"><table><thead><tr><th>Floor</th><th>Back view</th>
 <th>Side view</th><th>Full sea view</th></tr></thead><tbody>
 <tr%s><th>1–5</th><td>€3,200/m²</td><td>€3,300/m²</td><td>€3,500/m²</td></tr>
 <tr%s><th>Above 5</th><td>€3,300/m²</td><td>€3,400/m²</td><td>€3,600/m²</td></tr>
 </tbody></table></div>
 <p class="note">Rates are indicative and quoted by the developer per m². We do not
 publish a total for this development — ask us for a written quotation against the
 current rate card and the areas above.</p>
</div></section>""" % (esc(VIEW_LABEL[sheet["view"]].lower()), sheet["floor"],
                       format(sheet["rate"], ","), RATE_BAND, RATE_BAND_NOTE,
                       ' class="on"' if sheet["floor"] <= 5 else "",
                       ' class="on"' if sheet["floor"] > 5 else ""))


def gallery(cfg):
    figs = []
    for fn, cap in cfg["gallery"]:
        figs.append('<figure><img src="%s" alt="%s" loading="lazy">'
                    '<figcaption>%s</figcaption><span class="ai">%s</span></figure>'
                    % (gal_uri(fn), esc(cap), esc(cap), esc(ARTIST)))
    return ('<section style="padding-top:0"><div class="wrap"><div class="gal">%s</div>'
            '<p class="note">Every image of Marina Orikum released by the developer is '
            'a computer-generated visualisation — the buildings are not yet built. '
            'None of these is a photograph of the completed development.</p>'
            '</div></section>' % "".join(figs))


def al_section(cfg, sheet):
    rows = "".join('<li><b>%s</b><span>%s</span></li>' % (esc(p), esc(t))
                   for p, t in PAYMENT_SCHEDULE_AL)
    return ("""<section class="al" lang="sq"><div class="wrap">
 <p class="eyebrow">Në shqip</p><h2>%s — %s</h2>
 <p class="lead">%s</p>
 <p class="lead">%s</p>
 <p class="lead"><b>Sipërfaqja neto %s · Sipërfaqja totale %s · %s · Kati %s ·
 çmimi indikativ €%s/m².</b> Çmimi jepet për m², sipas katit dhe pozicionit;
 brezi i çmimeve është %s. %s</p>
 <ol class="sched">%s</ol>
</div></section>""" % (
        esc(cfg["name"]), esc(DEV["name"]),
        esc(cfg["al_lead"]), esc(cfg["al_body"]),
        esc(fmt_area(sheet["net"])), esc(fmt_area(sheet["total"])),
        esc(VIEW_LABEL_AL[sheet["view"]]), sheet["floor"],
        format(sheet["rate"], ","), esc(RATE_BAND.replace("€", "€")),
        esc(MEASURED_NOTE_AL), rows))


def jsonld(cfg, sheet):
    """No `offers`. The development forbids a published unit total and inventing
    one to satisfy the schema would be exactly the failure this rule guards."""
    d = {
        "@context": "https://schema.org", "@type": "Apartment",
        "name": "%s — %s" % (cfg["name"], DEV["name"]),
        "description": cfg["sub"],
        "url": "%s/%s/" % (SITE, cfg["slug"]),
        "image": "%s/%s/thumb.jpg" % (SITE, cfg["slug"]),
        "numberOfBedrooms": cfg["beds"],
        "floorSize": {"@type": "QuantitativeValue", "value": sheet["net"], "unitCode": "MTK"},
        "address": {"@type": "PostalAddress", "streetAddress": DEV["address"],
                    "addressLocality": DEV["town"], "addressRegion": DEV["region"],
                    "postalCode": "9400", "addressCountry": "AL"},
    }
    if cfg.get("baths"):
        d["numberOfBathroomsTotal"] = cfg["baths"]
    return json.dumps(d, ensure_ascii=False)


EXTRA_CSS = """
.areas{margin-top:26px;max-width:560px}
.areas table{width:100%;border-collapse:collapse;font-size:15px}
.areas th{text-align:left;font-weight:400;color:#4c5a52;padding:10px 0;border-bottom:1px solid rgba(28,58,46,.12)}
.areas td{text-align:right;padding:10px 0;border-bottom:1px solid rgba(28,58,46,.12);font-variant-numeric:tabular-nums}
.areas tr.tot th,.areas tr.tot td{font-weight:600;color:var(--green);border-bottom:0}
.note{font-size:12.5px;color:#6b7a71;margin-top:14px;max-width:66ch;line-height:1.55}
.rates .ratecard{margin-top:26px;overflow-x:auto;border:1px solid rgba(28,58,46,.12);border-radius:10px;background:var(--ivory2)}
.ratecard table{width:100%;border-collapse:collapse;font-size:14px;min-width:460px}
.ratecard th,.ratecard td{padding:12px 16px;text-align:right;white-space:nowrap}
.ratecard thead th{font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:#6b7a71;font-weight:600;border-bottom:1px solid rgba(28,58,46,.12)}
.ratecard tbody th{text-align:left;font-weight:500;color:var(--green)}
.ratecard tbody tr.on{background:rgba(192,98,60,.09)}
.ratecard tbody tr.on th{color:var(--terra)}
.pay{background:var(--ivory2);border-top:1px solid rgba(28,58,46,.08);border-bottom:1px solid rgba(28,58,46,.08)}
.sched{list-style:none;margin:26px 0 0;padding:0;display:grid;gap:2px;counter-reset:s}
.sched li{display:grid;grid-template-columns:92px 1fr;gap:18px;align-items:baseline;padding:16px 0;border-top:1px solid rgba(28,58,46,.12)}
.sched li:last-child{border-bottom:1px solid rgba(28,58,46,.12)}
.sched b{font-family:var(--disp);font-style:italic;font-size:30px;color:var(--terra);line-height:1}
.sched span{font-size:15px;color:#4c5a52}
@media(max-width:520px){.sched li{grid-template-columns:70px 1fr;gap:12px}.sched b{font-size:24px}}
.gal figure .ai{position:absolute;right:12px;top:11px;font-size:9.5px;letter-spacing:.18em;text-transform:uppercase;color:#fff;background:rgba(13,26,20,.55);padding:5px 9px;border-radius:2px;backdrop-filter:blur(3px)}
.al{background:var(--green);color:rgba(244,240,230,.9)}
.al h2{color:var(--ivory2)}.al .lead{color:rgba(244,240,230,.86)}
.al .sched li{border-color:rgba(244,240,230,.18)}
.al .sched li:last-child{border-bottom-color:rgba(244,240,230,.18)}
.al .sched span{color:rgba(244,240,230,.86)}
.al .sched b{color:var(--gold)}
.rateline{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:rgba(244,240,230,.66);margin:8px 0 0}
"""


def build(cfg_path):
    cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    sheet = parse_sheet(PLANS / sheet_for(cfg["slug"]))
    slug = cfg["slug"]
    out = ROOT / slug
    out.mkdir(exist_ok=True)

    css = (ROOT / "adelaide" / "index.html").read_text(encoding="utf-8")
    css = re.search(r"<style>(.*?)</style>", css, re.S).group(1) + EXTRA_CSS
    logo = base64.b64encode((HERE / "lib" / "logo.png").read_bytes()).decode()

    svg, vb = plan_svg(PLANS / sheet_for(cfg["slug"]))
    rooms = {"name": cfg["name"], "development": DEV["name"],
             "tagline": cfg["plan_tagline"],
             "totals": [{"label": "Net area", "value": fmt_area(sheet["net"])},
                        {"label": "Total area", "value": fmt_area(sheet["total"])},
                        {"label": "Veranda" if sheet["veranda"] else "Balcony",
                         "value": fmt_area(sheet["veranda"] or sheet["balcony"]) or "—"},
                        {"label": "Type", "value": sheet["type"]}],
             "levels": [{"name": "Floor %s" % sheet["floor"],
                         "image": svg_uri(svg), "viewbox": vb,
                         "rooms": cfg["rooms"]}]}
    work = ROOT / "_work" / "orikum" / slug          # generated, gitignored
    work.mkdir(parents=True, exist_ok=True)
    (work / "rooms.json").write_text(json.dumps(rooms, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    import subprocess
    subprocess.run([sys.executable, str(HERE / "lib" / "build_plan.py"),
                    str(work / "rooms.json"), "--out", str(out / "plan.html"),
                    "--slug", slug], check=True)

    caps = ["The building in the masterplan", "The apartment on the floor plate"]
    ins = inset_svgs(PLANS / sheet_for(cfg["slug"]))
    insets = ""
    if ins:
        insets = '<div class="posimgs">%s</div>' % "".join(
            '<figure><img src="%s" alt="%s"><figcaption>%s</figcaption></figure>'
            % (svg_uri(s), esc(c), esc(c)) for s, c in zip(ins, caps))

    title = "%s — %s %s · Sanders" % (cfg["name"], DEV["name"], cfg["type_label"])
    desc = cfg["sub"]
    thumb_url = "%s/%s/thumb.jpg" % (SITE, slug)
    page_url = "%s/%s/" % (SITE, slug)
    mapq = "Marina+e+Orikumit,+Orikum+9400,+Albania"

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<link rel="icon" href="/favicon.ico" sizes="any"><link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png"><link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{page_url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Sanders Albania">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{page_url}">
<meta property="og:image" content="{thumb_url}">
<meta property="og:image:width" content="900">
<meta property="og:image:height" content="675">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(desc)}">
<meta name="twitter:image" content="{thumb_url}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;1,500;1,600&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>{css}</style>
<script type="application/ld+json">{jsonld(cfg, sheet)}</script></head><body>
<nav><div class="navin">
 <div class="brand"><img src="data:image/png;base64,{logo}" alt="Sanders">SANDERS</div>
 <div class="navmid">{esc(cfg["name"])} · {esc(DEV["name"])}</div>
 <a class="btn btn-out" href="mailto:sales@sandersalbania.com?subject={esc(cfg['name'])}%20enquiry">Enquire</a>
</div></nav>
<header class="hero" style="background-image:url({hero_uri(cfg['hero'])})"><div class="wrap">
 <p class="eyebrow">{esc(cfg["eyebrow"])}</p>
 <h1>{esc(cfg["name"])}</h1>
 <p class="sub">{esc(cfg["sub"])}</p>
 <div class="priceRow"><div><p class="lbl">Indicative rate</p><div class="price">€{format(sheet["rate"], ",")}/m²</div>
 <p class="rateline">{esc(RATE_BAND)} across the release, {esc(RATE_BAND_NOTE)}</p></div>
 <a class="btn btn-terra" href="mailto:sales@sandersalbania.com?subject={esc(cfg['name'])}%20viewing">Request a quotation</a></div>
</div></header>
{specbar(sheet, cfg)}
<section><div class="wrap"><div class="vidrow"><div class="vidwrap"><video src="{DEV['film']}" poster="{DEV['poster']}" controls playsinline preload="none" muted></video></div><div class="vidcopy"><p class="eyebrow">The development on film</p><h2>Marina Orikum, in motion</h2><p class="lead">The developer's film across the marina and the towers above it. Computer-generated throughout — the development is off-plan.</p></div></div></div></section>
<section style="padding-top:0"><div class="wrap">
 <p class="eyebrow">The residence</p><h2>{esc(cfg["name"])}</h2>
 <p class="lead">{esc(cfg["description"])}</p>
 {areas_table(sheet)}
</div></section>
{rate_section(sheet)}
<section style="padding-top:0"><div class="wrap"><p class="eyebrow">Explore the residence</p><h2>Walk it, room by room</h2><p class="lead">{esc(cfg["plan_tagline"])}</p><div class="plancard"><iframe class="plan-embed" src="plan.html" title="Interactive floor plan" loading="lazy"></iframe></div><script>(function(){{window.addEventListener("message",function(e){{var h=e.data&&e.data.sandersPlanHeight;if(!h)return;var f=document.querySelector(".plan-embed");if(!f)return;f.style.minHeight="0";f.style.height=(h+2)+"px";}});}})();</script>{insets}</div></section>
{gallery(cfg)}
{payment_section()}
<section class="loc"><div class="wrap">
 <p class="eyebrow">Location &amp; setting</p><h2>{esc(cfg["loc_h2"])}</h2>
 <p class="lead">{esc(cfg["loc_body"])}</p>
 <p class="lead" style="margin-top:16px">Marina Orikum is designed by architect {esc(DEV["architect"])} and developed by {esc(DEV["developer"])}.</p>
 <div class="hl">{"".join("<div>%s</div>" % esc(h) for h in cfg["highlights"])}</div>
 <a class="back" href="/">← The Collection</a>
</div></section>
<section style="padding-top:0"><div class="wrap"><div class="mapwrap"><iframe src="https://maps.google.com/maps?q={mapq}&amp;z=14&amp;output=embed" loading="lazy" referrerpolicy="strict-origin-when-cross-origin" title="{esc(cfg['name'])} — location map"></iframe></div><p class="note">{esc(DEV['address'])}. Map located from the address; the developer supplied no coordinates.</p></div></section>
{al_section(cfg, sheet)}
<footer><div class="wrap"><div class="fgrid">
 <div><img class="flogo" src="data:image/png;base64,{logo}" alt="Sanders"><p class="b">Sanders International</p><div style="font-size:13px">London — Tirana</div></div>
 <div><p class="k">Enquiries</p><div><a href="mailto:sales@sandersalbania.com">sales@sandersalbania.com</a></div><div><a href="tel:+447414444782">+44 7414 444782</a></div><div><a href="https://sandersalbania.com">sandersalbania.com</a></div>
  <div class="social">
   <a href="https://www.linkedin.com/company/sanders-albania/" target="_blank" rel="noopener" aria-label="Sanders on LinkedIn"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM3 9h4v12H3zM9 9h3.8v1.7h.05c.53-1 1.83-2.05 3.77-2.05C20.6 8.65 22 11 22 14.4V21h-4v-5.9c0-1.4-.03-3.2-1.95-3.2-1.95 0-2.25 1.52-2.25 3.1V21H9z"/></svg></a>
   <a href="https://www.instagram.com/sanders_int/" target="_blank" rel="noopener" aria-label="Sanders on Instagram"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.2c3.2 0 3.58.01 4.85.07 1.17.05 1.8.25 2.23.41.56.22.96.48 1.38.9.42.42.68.82.9 1.38.16.42.36 1.06.41 2.23.06 1.27.07 1.65.07 4.85s-.01 3.58-.07 4.85c-.05 1.17-.25 1.8-.41 2.23-.22.56-.48.96-.9 1.38-.42.42-.82.68-1.38.9-.42.16-1.06.36-2.23.41-1.27.06-1.65.07-4.85.07s-3.58-.01-4.85-.07c-1.17-.05-1.8-.25-2.23-.41-.56-.22-.96-.48-1.38-.9-.42-.42-.68-.82-.9-1.38-.16-.42-.36-1.06-.41-2.23C2.21 15.58 2.2 15.2 2.2 12s.01-3.58.07-4.85c.05-1.17.25-1.8.41-2.23.22-.56.48-.96.9-1.38.42-.42.82-.68 1.38-.9.42-.16 1.06-.36 2.23-.41C8.42 2.21 8.8 2.2 12 2.2zm0 1.8c-3.14 0-3.51.01-4.75.07-.9.04-1.39.19-1.71.32-.43.17-.74.37-1.06.69-.32.32-.52.63-.69 1.06-.13.32-.28.81-.32 1.71C3.41 8.49 3.4 8.86 3.4 12s.01 3.51.07 4.75c.4.9.19 1.39.32 1.71.17.43.37.74.69 1.06.32.32.63.52 1.06.69.32.13.81.28 1.71.32 1.24.06 1.61.07 4.75.07s3.51-.01 4.75-.07c.9-.04 1.39-.19 1.71-.32.43-.17.74-.37 1.06-.69.32-.32.52-.63.69-1.06.13-.32.28-.81.32-1.71.06-1.24.07-1.61.07-4.75s-.01-3.51-.07-4.75c-.04-.9-.19-1.39-.32-1.71a2.85 2.85 0 0 0-.69-1.06 2.85 2.85 0 0 0-1.06-.69c-.32-.13-.81-.28-1.71-.32C15.51 4.01 15.14 4 12 4zm0 3.05a4.95 4.95 0 1 1 0 9.9 4.95 4.95 0 0 1 0-9.9zm0 1.8a3.15 3.15 0 1 0 0 6.3 3.15 3.15 0 0 0 0-6.3zm5.15-3.24a1.16 1.16 0 1 1 0 2.32 1.16 1.16 0 0 1 0-2.32z"/></svg></a>
  </div></div>
 <div><p class="k">Offices</p><div>Fox Court, 14 Gray's Inn Road, London WC1X 8HN</div><div style="margin-top:8px">Rruga Mihal Duri 1001, Tirana, Albania</div></div>
</div><p class="disc">Particulars prepared by Sanders International for guidance only and do not form part of any contract. Marina Orikum is an off-plan development; all imagery is computer-generated. Areas are taken from the developer's plan sheet and are measured externally and to the centreline of party and stair walls. Rates are indicative, quoted per m² by the developer, and subject to change; no unit total is published.</p></div></footer>
</body></html>"""
    (out / "index.html").write_text(doc, encoding="utf-8")

    # OG/card thumbnail — watermarked like every other published photo
    imaging._ffmpeg_render(PHOTOS / cfg["hero"], out / "thumb.jpg", 900, 84, True,
                           cover=(900, 675))   # OG declares these exact dimensions

    print("built %s  index.html %.0f KB  plan.html %.0f KB  thumb %.0f KB"
          % (slug, (out / "index.html").stat().st_size / 1024,
             (out / "plan.html").stat().st_size / 1024,
             (out / "thumb.jpg").stat().st_size / 1024))
    return cfg, sheet


if __name__ == "__main__":
    for a in sys.argv[1:]:
        build(a)
