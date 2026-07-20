#!/usr/bin/env python3
"""
onboard.py — the Sanders unit onboarding pipeline (run from the repo root).

Two phases, because placing clickable rooms on a plan needs Claude's eyes:

  1) python3 pipeline/onboard.py extract <brochure.pdf> --price "€ 1,250,000"
        Pulls photos + plan drawings + spec out of the PDF into _work/<slug>/,
        writes a DRAFT config.json and a rooms.template.json. Then STOP — Claude
        views the plan drawings and writes _work/<slug>/rooms.json (image mode:
        real drawing + clickable room hotspots), and tidies config.json.

  2) python3 pipeline/onboard.py build <slug>
        Builds <slug>/plan.html (from rooms.json), <slug>/index.html (from
        config.json), <slug>/thumb.jpg, and adds the card to index.html + units.json.
        Then: git add -A && git commit -m "Add <name>" && git push origin main

Idempotent: re-running build refreshes the unit in place.
"""
import sys, os, re, io, json, base64, subprocess, argparse
from pathlib import Path
import fitz  # PyMuPDF
from PIL import Image, ImageStat, ImageChops, ImageOps

HERE = Path(__file__).resolve().parent
LIB  = HERE / "lib"

def slugify(s):
    s = re.sub(r"[^\w\s-]", "", (s or "").lower()).strip()
    return re.sub(r"[\s_]+", "-", s) or "unit"

def is_plan(im):
    hsv = im.convert("HSV").resize((160,160)); st = ImageStat.Stat(hsv)
    return st.mean[1] < 35 and st.mean[2] > 165   # low saturation, bright = line drawing

def is_logo(im):
    return im.width < 520 and im.height < 560 and is_plan(im)

# ---------------- EXTRACT ----------------
def extract(args):
    doc = fitz.open(args.pdf)
    text = "\n".join(p.get_text() for p in doc)
    # name: first non-empty Cormorant-ish title line (heuristic: a short line before a price/spec)
    name = args.name
    if not name:
        for ln in [l.strip() for l in text.splitlines() if l.strip()]:
            if 2 <= len(ln) <= 22 and ln[0].isupper() and " " not in ln.strip() and ln.isalpha():
                name = ln; break
        name = name or "Unit"
    slug = args.slug or slugify(name)
    work = Path(args.out) / slug
    (work/"assets").mkdir(parents=True, exist_ok=True)
    (work/"plans").mkdir(parents=True, exist_ok=True)

    # images: classify + save
    photos, plans = [], []
    seen=set(); idx=0
    for pi in range(doc.page_count):
        for img in doc[pi].get_images(full=True):
            xref=img[0]
            if xref in seen: continue
            seen.add(xref)
            try: raw=doc.extract_image(xref)
            except Exception: continue
            data=raw["image"]
            try: im=Image.open(io.BytesIO(data)).convert("RGB")
            except Exception: continue
            if im.width<200 or im.height<200: continue
            if is_logo(im): continue
            (plans if is_plan(im) else photos).append((im.width*im.height, im, pi, idx)); idx+=1

    photos.sort(key=lambda t: t[0], reverse=True)
    for i,(_,im,_,_) in enumerate(photos[:6]):
        im.save(work/"assets"/(f"hero.jpg" if i==0 else f"g{i}.jpg"), "JPEG", quality=86)
    # render any page that looks like a floor-plan page (full render, Claude will crop per level)
    for pi in range(doc.page_count):
        t=doc[pi].get_text().upper()
        if "FLOOR PLAN" in t or ("GROUND FLOOR" in t) or ("BASEMENT" in t and "M" in t):
            pix=doc[pi].get_pixmap(matrix=fitz.Matrix(4,4))
            pix.save(str(work/"plans"/f"page{pi}.png"))
    for i,(_,im,_,_) in enumerate(plans):
        im.save(work/"plans"/f"plan_raw_{i}.png")

    # spec rows + price + beds + levels (best-effort)
    price = args.price or (re.search(r"€\s?[\d.,]+", text).group(0) if re.search(r"€\s?[\d.,]+", text) else "")
    spec=[]
    for label in ["Internal area","Internal","Lower level","Total living area","Loggia","Veranda",
                  "Balcony","Garden","Plot","Common area","Built","Bedrooms","Bathrooms","Levels"]:
        m=re.search(re.escape(label)+r"[^0-9A-Za-z]{0,4}([\d.,]+\s*m²|[\d.,]+|Basement[^\n]*|\d)", text, re.I)
        if m: spec.append([label, m.group(1).strip()])
    beds=None
    mb=re.search(r"(\d)\s*Bed", text) or re.search(r"Bedrooms[^\d]*(\d)", text)
    if mb: beds=int(mb.group(1))

    cfg={"name":name,"slug":slug,"development":args.dev or "",
         "dev_eyebrow":"","dev_strap":"","location":args.location or "",
         "price":price,"tag":args.tag or "","beds":beds,
         "area":next((v for k,v in spec if k.lower().startswith("internal")), ""),
         "eyebrow":"","sub":"","description":"",
         "spec":spec[:5] if spec else [["Internal",""]],
         "highlights":[],"location_h2":"","location_body":"",
         "hero":"assets/hero.jpg",
         "gallery":[[f"assets/g{i}.jpg",""] for i in range(1,min(5,len(photos)))]}
    (work/"config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    # rooms template — one level per detected level word, image-mode stub
    levels=[l for l in ["Basement","Ground floor","First floor","Second floor","Roof terrace"]
            if l.split()[0].upper() in text.upper()] or ["Ground floor"]
    tmpl={"name":name,"development":"","tagline":"Tap any room on the plan to see its size.",
          "totals":[[k,v] for k,v in spec[:4]],
          "levels":[{"name":l,"image":"plans/<cropped_level>.png (base64 or path)",
                     "viewbox":"0 0 <imgW> <imgH>",
                     "rooms":[{"name":"<Room>","area":"<m²>","points":"x1,y1 x2,y2 ..."}]} for l in levels]}
    (work/"rooms.template.json").write_text(json.dumps(tmpl, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nEXTRACTED → {work}")
    print(f"  name={name}  slug={slug}  price={price or '(missing, pass --price)'}  beds={beds}")
    print(f"  photos: {min(6,len(photos))}  plan drawings: {len(plans)}  plan pages rendered: {len(list((work/'plans').glob('page*.png')))}")
    print("\nNEXT (Claude): open _work/%s/plans/*, crop each level's drawing, and write" % slug)
    print("  _work/%s/rooms.json  (image mode: real drawing + clickable room hotspots)." % slug)
    print("  Read room names off the drawing; reconcile each level's room m² to the certified level total.")
    print("  Tidy _work/%s/config.json (dev_eyebrow, dev_strap, sub, description, captions)." % slug)
    print("  Then:  python3 pipeline/onboard.py build %s" % slug)

# ---------------- BUILD ----------------
def build(args):
    work = Path(args.out) / args.slug
    cfg  = json.loads((work/"config.json").read_text(encoding="utf-8"))
    slug = cfg["slug"]
    # 1) interactive plan
    subprocess.run([sys.executable, str(LIB/"build_plan.py"), str(work/"rooms.json"),
                    "--out", f"{slug}/plan.html", "--slug", slug], check=True)
    # 2) listing page
    subprocess.run([sys.executable, str(HERE/"build_listing.py"), str(work/"config.json")], check=True)
    # 3) thumbnail
    hero = work/cfg["hero"]
    im = Image.open(hero).convert("RGB").resize((900,675))
    im.save(f"{slug}/thumb.jpg","JPEG",quality=86)
    # 4) gallery + manifest
    subprocess.run([sys.executable, str(HERE/"add_to_gallery.py"), str(work/"config.json")], check=True)
    print(f"\nBUILT {slug}: plan.html + index.html + thumb.jpg + gallery card.")
    print(f'Now:  git add -A && git commit -m "Add {cfg["name"]}" && git push origin main')

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd", required=True)
    e=sub.add_parser("extract"); e.add_argument("pdf")
    for f in ["slug","price","name","dev","location","tag"]: e.add_argument("--"+f)
    e.add_argument("--out", default="_work"); e.set_defaults(func=extract)
    b=sub.add_parser("build"); b.add_argument("slug"); b.add_argument("--out", default="_work"); b.set_defaults(func=build)
    args=ap.parse_args(); args.func(args)

if __name__ == "__main__":
    main()
