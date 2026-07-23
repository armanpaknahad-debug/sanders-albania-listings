#!/usr/bin/env python3
"""
Generate the Sanders Unit Name Register from the two files that already exist.

  units.json        -> source of truth for anything client-facing (live status,
                       price, areas). Never edited by hand for the register.
  unit_codes.json   -> internal only: Sanders name -> developer code, plus
                       withdrawn / held / retired names. Lives OUTSIDE this repo
                       (~/Claude-Projects/sanders-internal/, or $SANDERS_CODES).

Output: register.csv, written beside unit_codes.json outside this repo
        (paste straight into the Google Sheet)

The point of this script is the VALIDATION. It fails loudly on the mistakes that
have actually happened: a live unit with no register row, a name reused, a code
assigned twice, a retired name brought back.

    python3 build_register.py                 # validate + write register.csv
    python3 build_register.py --check         # validate only, non-zero exit on error
"""
import json, csv, os, sys, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# unit_codes.json maps Sanders names to developer unit codes. That mapping defeats
# the white-labelling, so it lives OUTSIDE this repo and is never committed here --
# a private repo can be made public by accident, and git history keeps a file forever.
CODES = Path(os.environ.get("SANDERS_CODES",
                            Path.home() / "Claude-Projects/sanders-internal/unit_codes.json"))
UNITS = ROOT.parent / "units.json"
OUT   = CODES.parent / "register.csv"      # written beside the codes, never into the repo

# units.json field names differ between generators; try these in order.
NAME_KEYS  = ("name", "title", "unit", "sanders_name", "displayName")
PRICE_KEYS = ("price", "guide_price", "priceLabel", "price_display")

def norm(s):
    """Compare names accent- and case-insensitively so Éloïse == Eloise."""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()

def pick(d, keys, default=""):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default

def load_units():
    if not UNITS.exists():
        return None
    data = json.loads(UNITS.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for k in ("units", "items", "listings", "data"):
            if isinstance(data.get(k), list):
                data = data[k]; break
    if not isinstance(data, list):
        sys.exit("units.json: could not find a list of units")
    return data

def main(check_only=False):
    if not CODES.exists():
        sys.exit(f"unit_codes.json not found at: {CODES}\n"
                 f"It is internal-only and lives outside this repo by design.\n"
                 f"Set SANDERS_CODES to its path if it has moved.")
    cfg   = json.loads(CODES.read_text(encoding="utf-8"))
    units = load_units()
    errors, warnings = [], []

    reg      = cfg["units"]
    retired  = {norm(r["name"]): r for r in cfg["retired_names"]}
    live_reg = [u for u in reg if u["status"] == "live"]

    # --- 1. no duplicate Sanders names anywhere -------------------------------
    seen = {}
    for u in reg:
        if u["name"].startswith("\u2014"):      # placeholder rows
            continue
        k = norm(u["name"])
        if k in seen:
            errors.append(f"DUPLICATE NAME: '{u['name']}' used by {seen[k]} and {u['code']}")
        seen[k] = u["code"]

    # --- 2. no live/reserved name collides with a retired name ----------------
    for u in reg:
        k = norm(u["name"])
        if k in retired:
            errors.append(f"RETIRED NAME REUSED: '{u['name']}' ({u['code']}) "
                          f"- retired because: {retired[k]['reason']}")

    # --- 3. no developer code assigned to two names --------------------------
    bycode = {}
    for u in reg:
        key = (u["project"], u["band"], u["code"])
        if u["code"].startswith(("\u2014",)):
            continue
        if key in bycode:
            errors.append(f"CODE REUSED: {u['code']} in {u['project']}/{u['band']} "
                          f"-> '{bycode[key]}' and '{u['name']}'")
        bycode[key] = u["name"]

    # --- 4. reconcile against the live site ----------------------------------
    if units is None:
        warnings.append("units.json not found - skipped reconciliation against the live site")
    else:
        site = {}
        for u in units:
            nm = pick(u, NAME_KEYS)
            if nm:
                site[norm(nm)] = u
        reg_live = {norm(u["name"]) for u in live_reg}

        for k, u in site.items():
            if k not in reg_live:
                errors.append(f"ON SITE BUT NOT IN REGISTER: '{pick(u, NAME_KEYS)}' "
                              f"- add it to unit_codes.json with its developer code")
        for u in live_reg:
            if norm(u["name"]) not in site:
                errors.append(f"REGISTER SAYS LIVE BUT NOT ON SITE: '{u['name']}' ({u['code']})")

        if len(site) != len(reg_live):
            warnings.append(f"count mismatch: units.json={len(site)} live-in-register={len(reg_live)}")

    # --- report ---------------------------------------------------------------
    for w in warnings: print("WARN ", w)
    for e in errors:   print("ERROR", e)
    if errors:
        print(f"\n{len(errors)} error(s) - register NOT written.")
        return 1
    print(f"OK - {len(live_reg)} live, "
          f"{sum(1 for u in reg if u['status']=='withdrawn')} withdrawn, "
          f"{sum(1 for u in reg if u['status'] in ('held','unnamed'))} held/unnamed, "
          f"{len(retired)} retired names.")
    if check_only:
        return 0

    # --- write the register ---------------------------------------------------
    price_of = {}
    if units:
        for u in units:
            nm = pick(u, NAME_KEYS)
            if nm:
                price_of[norm(nm)] = str(pick(u, PRICE_KEYS, "")).strip()

    hdr = ["Sanders name","Unit code","Status","Price","Project","Band","Notes"]
    rows = []
    for proj_key, proj in cfg["projects"].items():
        for band_key, band_label in proj["bands"].items():
            members = [u for u in reg if u["project"]==proj_key and u["band"]==band_key]
            if not members:
                continue
            rows.append([band_label,"","","","","",""])
            rows.append(hdr)
            for u in sorted(members, key=lambda x: (x["status"]!="live", x["name"])):
                price = price_of.get(norm(u["name"]), "") if u["status"]=="live" else ""
                rows.append([u["name"], u["code"], u["status"], price,
                             proj["label"], band_key, u.get("note","")])
            rows.append([""]*7)

    rows.append(["RETIRED NAMES - never reuse","","","","","",""])
    rows.append(["Name","Reason","","","","",""])
    for r in cfg["retired_names"]:
        rows.append([r["name"], r["reason"],"","","","",""])
    rows.append([""]*7)
    rows.append(["NOTES","","","","","",""])
    for n in cfg["notes"]:
        rows.append([n,"","","","","",""])

    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)
    print(f"wrote {OUT}  ({len(rows)} rows)")
    return 0

if __name__ == "__main__":
    sys.exit(main(check_only="--check" in sys.argv))
