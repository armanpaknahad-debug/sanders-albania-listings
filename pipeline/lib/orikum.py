#!/usr/bin/env python3
"""orikum — Marina Orikum (Orikum, Vlorë) source-material parser + standardiser.

Seventy unit plans ship from this developer in one folder tree, all drawn from
the same template, so nothing here should ever be transcribed by hand. Every
sheet carries a clean text layer; `parse_sheet()` pulls building, floor,
apartment number, type and all five areas straight off it, and the view category
comes from the folder path. Onboarding unit 5 or unit 70 is the same call.

Also holds the pieces that are FIXED for this development and must not drift
between units:
  * the rate card (indicative €/m² only — never a computed unit total)
  * the payment schedule
  * the standardiser's text rules for the plan sheets (what to strip, what to
    translate, how the area schedule is retypeset in English)

Standing rule for Marina Orikum: publish the €/m² rate and the €3,200–3,600 band.
Do NOT multiply rate by area. There is deliberately no function here that
returns a unit total — see `RATE_ONLY`.
"""
import json
import os
import re
import unicodedata
from pathlib import Path

# The developer's plan filename IS the unit code (B12 = Sylvaine). That mapping
# defeats the white-labelling the business rests on, so — like unit_codes.json —
# it lives OUTSIDE this public repo. Same $SANDERS_CODES convention as
# internal/build_register.py. Unit configs carry a slug; they never carry a path.
SHEET_MAP = Path(os.environ.get(
    "SANDERS_SHEETS",
    Path.home() / "Claude-Projects/sanders-internal/orikum_sheets.json"))


def sheet_for(slug):
    """Developer plan-sheet path for a Sanders slug. Fails loudly, never guesses."""
    if not SHEET_MAP.exists():
        raise SystemExit(
            "Marina Orikum: the slug -> plan-sheet map is missing at %s.\n"
            "It is internal and deliberately outside this repo; point $SANDERS_SHEETS "
            "at it and rebuild." % SHEET_MAP)
    sheets = json.loads(SHEET_MAP.read_text(encoding="utf-8"))["sheets"]
    if slug not in sheets:
        raise SystemExit("Marina Orikum: no plan sheet registered for %r in %s"
                         % (slug, SHEET_MAP))
    return sheets[slug]

# --------------------------------------------------------------------- pricing
RATE_ONLY = (
    "Marina Orikum publishes an indicative rate per m², never a unit total. "
    "Do not multiply rate by area anywhere: page copy, card, manifest or JSON-LD. "
    "If a schema needs a price, omit the offer instead."
)

# floor band -> view -> €/m², exactly as supplied on the developer rate card
RATE_CARD = {
    "1-5":   {"back": 3200, "side": 3300, "sea": 3500},
    "above": {"back": 3300, "side": 3400, "sea": 3600},
}
RATE_BAND = "€3,200–3,600/m²"
RATE_BAND_NOTE = "varying by floor and position"

PAYMENT_SCHEDULE = [
    ("30%", "on signing the contract"),
    ("35%", "on completion of the structural framework"),
    ("30%", "on completion of plastering and gypsum works, including first-fix "
            "electrical, plumbing and mechanical"),
    ("5%",  "on handover of keys"),
]


VIEW_LABEL = {"back": "Back view", "side": "Side view", "sea": "Full sea view"}

# No Albanian constants live here. listings.sandersalbania.com is an English-only
# site; bilingual output belongs to the Tirana repo. Albanian source material is
# still READ from the developer's brochure to get the facts right — it is just
# never published on this site. See pipeline/README.md.


def rate_for(floor, view):
    """€/m² for a unit. `floor` is the KATI number, `view` one of back/side/sea."""
    band = "1-5" if int(floor) <= 5 else "above"
    return RATE_CARD[band][view]


# ------------------------------------------------------------------- sheet parse
# The sheet's own labels. Tolerant of the stray full stops and the runs of
# padding spaces the CAD export leaves between label and value, and of the "m2"
# being split from its superscript 2 by a separate text run.
_AREA = r"[^0-9\-]{0,12}(-|[\d]+(?:\.[\d]+)?)\s*m?"
PATTERNS = {
    "total":   re.compile(r"Sip\.?\s*TOTALE\.?" + _AREA, re.I),
    "net":     re.compile(r"Sip\.?\s*Apartamenti\.?" + _AREA, re.I),
    "common":  re.compile(r"Sip\.?\s*Perbashket\.?" + _AREA, re.I),
    "balcony": re.compile(r"Sip\.?\s*Ballkoni\.?" + _AREA, re.I),
    "veranda": re.compile(r"Sip\.?\s*Verande\.?" + _AREA, re.I),
}
# the code block is set as three runs on one baseline; other title-block text can
# fall between them once the page is flattened, so bridge with a lazy gap.
RE_CODE = re.compile(
    r"OBJEKTI\s+(\w+)\s*/.{0,80}?KATI\s*(\d+)\s*/\s*APART\.?\s*NR\.?\s*(\d+)", re.I | re.S)
RE_TYPE = re.compile(r"Tipi\s+i\s+apartamentit\s*([\d\+]+)", re.I)
RE_LEVEL = re.compile(r"Kuota\s*([+\-][\d.]+)", re.I)

VIEW_FROM_PATH = [("full sea view", "sea"), ("side view", "side"), ("back view", "back")]


def view_from_path(path):
    p = str(path).lower()
    for needle, key in VIEW_FROM_PATH:
        if needle in p:
            return key
    return None


def _num(v):
    if v in (None, "-", ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_sheet(pdf_path, view=None):
    """Read one plan sheet. Returns a dict of everything the sheet states.

    Areas are as printed on the sheet, which measures EXTERNALLY and to the
    centreline of party and stair walls — carried through as `measured_note` so
    no caller can present them as internal areas by accident.
    """
    from pdfmini import PDF, page_text
    pdf_path = Path(pdf_path)
    doc = PDF(str(pdf_path))
    page = doc.pages()[0]
    text = page_text(doc, page, sep="\n")
    flat = re.sub(r"\s+", " ", text)

    out = {"source": pdf_path.name, "view": view or view_from_path(pdf_path)}
    m = RE_CODE.search(flat)
    if m:
        out["building"] = m.group(1).upper()
        out["floor"] = int(m.group(2))
        out["apartment_no"] = int(m.group(3))     # developer code — never published
    m = RE_TYPE.search(flat)
    if m:
        out["type"] = m.group(1)
    m = RE_LEVEL.search(flat)
    if m:
        out["datum"] = m.group(1)
    for key, rx in PATTERNS.items():
        mm = rx.search(flat)
        out[key] = _num(mm.group(1)) if mm else None
    if out.get("floor") is not None and out.get("view"):
        out["rate"] = rate_for(out["floor"], out["view"])
    out["measured_note"] = MEASURED_NOTE_EN
    return out


MEASURED_NOTE_EN = ("Areas are measured externally and to the centreline of party "
                    "and stair walls, as stated on the developer's plan.")


# --------------------------------------------------------- plan-sheet text rules
# Everything the standardiser removes from a Marina Orikum sheet. Matched on the
# normalised (accent-folded, upper-case) run so the CAD export's inconsistent
# diacritics and padding cannot slip a line through.
STRIP_PATTERNS = [
    r"ALBUM\s+SHITJESH",                       # sales-album sheet header
    r"MARINA\s+ORIKUM\s*-?\s*FAZA",            # FAZA 1 construction description
    r"STRUKTURA\s+HOTELERIE",                  # ditto, continuation line
    r"SH\.?P\.?K\.?",                          # the legal entity line
    r"ME\s+VENDNDODHJE\s+NE\s+ORIKUM",         # ditto, continuation line
    r"OBJEKTI\s+\w+\s*/\s*KATI",               # building / floor / apartment code
    r"^\s*AP\.?\s*\d+\s*\(",                   # apartment code stamped on the drawing
    r"SEKSIONI\s+\w+",                         # section code
    r"^\s*EKSIONI",                            # ditto, split by the drop-cap run
    r"^\s*['\"]+\s*$",                         # orphan quote marks left by the split
]
_STRIP = [re.compile(p) for p in STRIP_PATTERNS]

# Albanian -> English for anything that survives. Longest key first at apply time.
TRANSLATE = {
    "dhome gjumi": "Bedroom", "dhomë gjumi": "Bedroom", "dhoma gjumi": "Bedroom",
    "banjo": "Bathroom", "banje": "Bathroom", "banjë": "Bathroom",
    "kuzhine": "Kitchen", "kuzhinë": "Kitchen",
    "ballkon": "Balcony", "ballkoni": "Balcony",
    "verande": "Veranda", "verandë": "Veranda",
    "korridor": "Hall", "korridori": "Hall",
    "depo": "Store", "garderobe": "Wardrobe", "garderobë": "Wardrobe",
    "shkalle": "Stairs & lift", "shkallë": "Stairs & lift",
    "ashensor": "Stairs & lift", "shkalle/ashensor": "Stairs & lift",
    "shaft teknik": "Service shaft",
    # the export splits this label across two runs on one baseline: translate
    # the first in full and drop the second, so it reads right where it sits
    "shaft": "Service shaft", "teknik": "",
    "ndenje": "Living", "ndenjë": "Living", "ngrenie": "Dining", "ngrënie": "Dining",
    "tualet": "WC", "wc": "WC", "hyrje": "Entrance",
    "pozicioni i seksionit": "Section position",
    "pozicioni i apartamentit ne planimetrine e katit":
        "Apartment position on the floor plate",
    "pozicioni i apartamentit": "Apartment position",
    "kuota": "Level",
}

# The area schedule, retypeset in English. Keys are the sheet's own labels.
SCHEDULE_EN = {
    "tipi i apartamentit": "Type",
    "sip.apartamenti": "Net area",
    "sip.ballkoni": "Balcony",
    "sip.perbashket": "Common area",
    "sip.totale": "Total area",
    "sip.verande": "Veranda",
}


def _fold(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).upper().strip()


def is_stripped(text):
    f = _fold(text)
    return any(rx.search(f) for rx in _STRIP)


def translate_run(text):
    """Translate a text run, or return it unchanged. Numbers pass straight through."""
    key = text.strip().lower().rstrip(".:")
    if key in TRANSLATE:
        return TRANSLATE[key]
    for k in sorted(TRANSLATE, key=len, reverse=True):
        if k in key:
            return re.sub(re.escape(k), TRANSLATE[k], key, flags=re.I).capitalize()
    return text


def sheet_text_filter(drop_schedule=True):
    """Build a text_filter for plansvg.PlanSVG.

    Strips the sales-album header, the FAZA 1 description, the legal entity line
    and all apartment/section codes; drops the Albanian area schedule (the page
    retypesets it in English rather than translating it in place); translates
    whatever remains. Dimension strings are numbers and pass through untouched.
    """
    sched = re.compile(r"^\s*(Sip\.|Tipi i apartamentit)", re.I)
    note = re.compile(r"Siperfaqet jane matur|te perbashketa me fqinjin", re.I)

    def f(text, x, y, size):
        t = text.strip()
        if not t:
            return None
        if is_stripped(t):
            return None
        if drop_schedule and (sched.search(t) or note.search(_fold(t))):
            return None
        if drop_schedule and re.fullmatch(r"[²2]", t) and size < 8:
            return None                      # orphan superscript from the schedule
        if re.fullmatch(r"[\d\s.,+\-]+", t):
            return text                      # dimension string — leave as drawn
        return translate_run(t)
    return f
