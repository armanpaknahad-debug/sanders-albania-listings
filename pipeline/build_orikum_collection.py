#!/usr/bin/env python3
"""build_orikum_collection.py — the Marina Orikum band and manifest rows.

    python3 pipeline/build_orikum_collection.py

Writes marina-orikum/index.html (the development page), adds the project card to
the root collection index, and syncs units.json. Idempotent — safe to re-run as
the other 66 units are onboarded.

Cards carry the €/m² rate, never a total. The card grid's `.cprice` slot is the
one place a total would most plausibly creep back in, so it is fed from the same
sheet-derived rate as the listing page.
"""
import html, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
from orikum import parse_sheet, sheet_for, RATE_BAND

ROOT = HERE.parent
SITE = "https://listings.sandersalbania.com"
PLANS = (Path.home() / "Claude-Projects/GoogleDrive/Listings Sales/ORIKUM BAY/_Source/"
         "Marina Orikum-Vlora (1)/Floor plans")
DEV_SLUG = "marina-orikum"
DEV_NAME = "Marina Orikum"
DEV_LOC = "Orikum, Vlorë"
DEV_DESC = ("Albania's first marina, in the Gulf of Vlorë — 800 berths, with residences "
            "by Chris Precht above them. Off-plan, priced by the metre.")
ORDER = ["sylvaine", "bastienne", "aurore", "ghislaine"]


def esc(s):
    return html.escape(str(s), quote=True)


def fmt(v):
    return ("%.2f" % v).rstrip("0").rstrip(".") + " m²" if v is not None else None


def load(slug):
    cfg = json.loads((HERE / "units" / "orikum" / (slug + ".json")).read_text(encoding="utf-8"))
    return cfg, parse_sheet(PLANS / sheet_for(slug))


def card(cfg, sheet):
    outdoor = (("%s veranda" % fmt(sheet["veranda"])) if sheet["veranda"]
               else ("%s balcony" % fmt(sheet["balcony"])) if sheet["balcony"] else None)
    meta = " · ".join(x for x in [cfg["type_label"], "%s net" % fmt(sheet["net"]), outdoor] if x)
    chip = cfg["type_label"]
    return f"""<a class="card" href="/{cfg['slug']}/">
      <div class="thumb" style="background-image:url('/{cfg['slug']}/thumb.jpg')"><span class="badge">OFF-PLAN</span><span class="blockchip">{esc(chip)}</span></div>
      <div class="cbody">
        <div class="cname">{esc(cfg['name'])}</div>
        <div class="cloc">{esc(DEV_NAME)} — {esc(DEV_LOC)}</div>
        <div class="cmeta">{esc(meta)}</div>
        <div class="cprice">€{sheet['rate']:,}/m²</div>
      </div>
    </a>"""


def build_dev_page(units):
    """Clone the SOL Residence development page, swapping band, cards and copy."""
    src = (ROOT / "sol-residence" / "index.html").read_text(encoding="utf-8")
    head_desc = DEV_DESC
    out = src
    for a, b in [
        ("SOL Residence · Sanders", "%s · Sanders" % DEV_NAME),
        ("https://listings.sandersalbania.com/sol-residence/", "%s/%s/" % (SITE, DEV_SLUG)),
        ("https://listings.sandersalbania.com/assets/projects/sol-residence.jpg",
         "%s/assets/projects/%s.jpg" % (SITE, DEV_SLUG)),
        ("Sea-view residences above the bay at Kalaja, Vlorë — built and ready to occupy.",
         head_desc),
    ]:
        out = out.replace(a, b)
    # hero block
    out = re.sub(r'<div class="ey">KALAJA[^<]*</div>',
                 '<div class="ey">ORIKUM &nbsp;·&nbsp; VLORË</div>', out)
    out = out.replace("<h1>SOL Residence</h1>", "<h1>%s</h1>" % DEV_NAME)
    out = re.sub(r'<div class="devcount"[^>]*>3 residences</div>',
                 '<div class="devcount" style="margin-top:8px">%d residences</div>' % len(units), out)
    out = re.sub(r'<p>Sea-view residences set into the hillside[^<]*</p>',
                 "<p>Albania's first marina, in the Gulf of Vlorë between the Adriatic and the "
                 "Ionian — extending to 800 berths, with residences by Chris Precht above them. "
                 "Off-plan: the building permit is granted, construction begins within 30 days "
                 "and completion is about three years out. Priced by the metre, not by the unit "
                 "— %s across the release, varying by floor and position.</p>" % RATE_BAND, out)
    # the card grid
    grid = ('<div class="blockband">%s</div>\n' % esc(DEV_NAME)) + "\n".join(
        card(c, s) for c, s in units)
    out = re.sub(r'<div class="wrap"><div class="grid">.*?</div></div>\n<div class="foot">',
                 lambda _m: '<div class="wrap"><div class="grid">\n%s\n\n</div></div>\n<div class="foot">' % grid,
                 out, count=1, flags=re.S)
    (ROOT / DEV_SLUG).mkdir(exist_ok=True)
    (ROOT / DEV_SLUG / "index.html").write_text(out, encoding="utf-8")
    return out


def add_project_card(n):
    p = ROOT / "index.html"
    h = p.read_text(encoding="utf-8")
    tile = ('<a class="projcard mo" href="/%s/"><div class="ph" style="background-image:'
            "url('/assets/projects/%s.jpg')\"></div><div class=\"scrim\"></div><div class=\"inner\">"
            '<div class="pname">Marina<br>Orikum</div></div><div class="pcount">%d residences</div></a>'
            % (DEV_SLUG, DEV_SLUG, n))
    h = re.sub(r'<a class="projcard mo".*?</a>\n?', "", h, flags=re.S)   # idempotent
    anchor = '<a class="projcard sel"'
    if anchor not in h:
        raise SystemExit("collection index: could not find the Selected card to insert before")
    h = h.replace(anchor, tile + "\n" + anchor, 1)
    p.write_text(h, encoding="utf-8")


def sync_manifest(units):
    p = ROOT / "units.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["units"] = [u for u in d["units"] if u.get("development") != DEV_NAME]
    for cfg, sheet in units:
        d["units"].append({
            "slug": cfg["slug"], "name": cfg["name"], "development": DEV_NAME,
            "location": "%s — %s" % (DEV_NAME, DEV_LOC),
            # rate, never a total: this development does not publish unit prices
            "price": "€%s/m²" % format(sheet["rate"], ","),
            "price_basis": "per_m2_indicative",
            "beds": cfg["beds"],
            "area": fmt(sheet["net"]),
            "tag": "%s %s residence" % (cfg["type_label"],
                                        "sea-view" if sheet["view"] == "sea" else "marina"),
            "status": "off-plan",
            "thumb": "%s/thumb.jpg" % cfg["slug"], "href": "%s/" % cfg["slug"],
        })
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    units = [load(s) for s in ORDER]
    build_dev_page(units)
    add_project_card(len(units))
    sync_manifest(units)
    print("collection: %s/index.html, project card, %d manifest rows"
          % (DEV_SLUG, len(units)))
    for cfg, sheet in units:
        print("   %-10s %-5s %8s net  €%s/m²" % (cfg["name"], cfg["type_label"],
                                                 fmt(sheet["net"]), format(sheet["rate"], ",")))


if __name__ == "__main__":
    main()
