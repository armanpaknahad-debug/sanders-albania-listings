#!/usr/bin/env python3
"""
add_to_gallery.py — add (or update) a unit in the collection gallery.

- Inserts the unit's card into its development section of index.html (creating the
  section if the development is new), and keeps that section's residence count right.
- Adds/updates the unit in units.json.
Idempotent: re-running for the same slug updates in place, never duplicates.

Usage:
    python3 add_to_gallery.py path/to/config.json   [--index index.html] [--manifest units.json]
"""
import json, sys, re, argparse
from pathlib import Path

def esc(s): return (s or "").replace("&","&amp;")

def card_html(cfg):
    meta = cfg.get("card_meta") or " · ".join(filter(None,[
        f'{cfg.get("beds")} bed' if cfg.get("beds") else "",
        cfg.get("area",""), cfg.get("tag","")]))
    return (
f'<a class="card" href="{cfg["slug"]}/">\n'
f'      <div class="thumb" style="background-image:url(\'{cfg["slug"]}/thumb.jpg\')"><span class="badge">AVAILABLE</span></div>\n'
f'      <div class="cbody">\n'
f'        <div class="cname">{esc(cfg["name"])}</div>\n'
f'        <div class="cloc">{esc(cfg.get("location",""))}</div>\n'
f'        <div class="cmeta">{esc(meta)}</div>\n'
f'        <div class="cprice">{esc(cfg.get("price",""))}</div>\n'
f'      </div>\n    </a>')

def section_html(cfg, card):
    return (
f'<div class="wrap devsec">\n'
f'  <div class="dev-eyebrow">{esc(cfg.get("dev_eyebrow","").upper())}</div>\n'
f'  <div class="devrow"><h2 class="devname">{esc(cfg["development"])}</h2><span class="devcount">1 residence</span></div>\n'
f'  <div class="devstrap">{esc(cfg.get("dev_strap",""))}</div>\n'
f'  <div class="grid">{card}</div>\n'
f'</div>\n')

def split_sections(h):
    parts = h.split('<div class="wrap devsec">')
    return parts[0], ['<div class="wrap devsec">'+p for p in parts[1:]]

def count_and_fix_devcount(section):
    n = section.count('<a class="card"')
    label = f'{n} residence' if n == 1 else f'{n} residences'
    return re.sub(r'<span class="devcount">[^<]*</span>',
                  f'<span class="devcount">{label}</span>', section, count=1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--index", default="index.html")
    ap.add_argument("--manifest", default="units.json")
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    slug = cfg["slug"]

    # ---- gallery index.html ----
    h = Path(args.index).read_text(encoding="utf-8")
    card = card_html(cfg)
    if f'href="{slug}/"' in h:
        # already present -> replace the existing card in place
        h = re.sub(r'<a class="card" href="'+re.escape(slug)+r'/">.*?</a>', card, h, count=1, flags=re.S)
        print(f"updated existing card for {slug}")
    else:
        head, secs = split_sections(h)
        placed = False
        for i, sec in enumerate(secs):
            m = re.search(r'devname">([^<]+)</h2>', sec)
            if m and m.group(1).strip() == cfg["development"].strip():
                # append card after the last card in this section's grid
                idx = sec.rfind('</a>')
                sec = sec[:idx+4] + card + sec[idx+4:]
                secs[i] = count_and_fix_devcount(sec)
                placed = True
                print(f"added {slug} to existing section '{cfg['development']}'")
                break
        if not placed:
            # new development section: insert before footer (or </body>)
            new_sec = section_html(cfg, card)
            body = head + "".join(secs)
            anchor = -1
            for a in ('<footer', '<div class="foot"', '</main>', '</body>'):
                anchor = body.find(a)
                if anchor >= 0: break
            h = body[:anchor] + new_sec + body[anchor:]
            print(f"created new section '{cfg['development']}' for {slug}")
            head = None
        if placed:
            h = head + "".join(secs)
    Path(args.index).write_text(h, encoding="utf-8")

    # ---- units.json ----
    man = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    entry = {"slug":slug,"name":cfg["name"],"development":cfg.get("development",""),
             "location":cfg.get("location",""),"price":cfg.get("price",""),
             "beds":cfg.get("beds"),"area":cfg.get("area",""),"tag":cfg.get("tag",""),
             "status":"available","thumb":f"{slug}/thumb.jpg","href":f"{slug}/"}
    units = man["units"] if isinstance(man, dict) and "units" in man else man
    for i,u in enumerate(units):
        if u.get("slug")==slug: units[i]=entry; break
    else: units.append(entry)
    if isinstance(man, dict):
        man["units"]=units
        if isinstance(man.get("collection"),dict) and isinstance(man["collection"].get("count"),int):
            man["collection"]["count"]=len(units)
        out=man
    else:
        out=units
    Path(args.manifest).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest now {len(units)} units")

if __name__ == "__main__":
    main()
