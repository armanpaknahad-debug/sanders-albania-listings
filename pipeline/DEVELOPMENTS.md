# Development registry

Permanent, per-development standing rules. A row here overrides any default in
the standardiser. Read it before building a unit; add to it, never quietly
change it.

---

## Marina Orikum · Orikum, Vlorë · Sanders Albania

**Brand** — "Marina Orikum" is **retained**. It is the development's own name and
carries the "Albania's first marina" story. Do not white-label it.

**Credits** — developer **Concord Investment Group** and architect **Chris Precht**
are **both credited**, not stripped. Precht is a genuine selling point at this
price level.

**Strip** — from every plan sheet: the `sh.p.k.` legal entity line, the
`ALBUM SHITJESH` sheet header, apartment and section codes
(`OBJEKTI x / KATI n / APART.NR. n`, `AP.n(x+1)`, `SEKSIONI x`), and the FAZA 1
construction description. Keep the drawing and the position insets.
Implemented in `lib/orikum.py` → `STRIP_PATTERNS`.

**Status** — off-plan. Permit obtained; construction begins within 30 days of the
developer's rate card. Completion approximately three years.

**PRICING — STANDING RULE.** Never publish a total unit price for this
development. Publish the indicative €/m² band only:

| Floor | Back view | Side view | Full sea view |
|---|---|---|---|
| 1–5 | €3,200/m² | €3,300/m² | €3,500/m² |
| Above 5 | €3,300/m² | €3,400/m² | €3,600/m² |

Each unit page shows the rate applying to that unit plus the overall band
**€3,200–3,600/m², varying by floor and position**. Do **not** multiply rate by
area anywhere — page, card, manifest or JSON-LD. Where a schema wants a price,
omit the offer rather than invent a figure. Enforced by `lib/orikum.RATE_ONLY`;
no function in the pipeline returns a unit total.

**Payment schedule** (as supplied): 30% on signing · 35% on completion of the
structural framework · 30% on completion of plastering and gypsum works
including first-fix electrical, plumbing and mechanical · 5% on handover of keys.

**Address** — Marina e Orikumit, Orikum 9400. No coordinates supplied; the map is
built from the address.

**Areas** — the sheets measure externally and to the centreline of party and
stair walls. Carry that qualification onto every page; never present these as
internal areas. `Sip.TOTALE` = net + common + balcony; the **veranda is excluded**
from that total and must be stated separately.

**Imagery** — as of the 2026-08 drop, *every* supplied image is a
computer-generated visualisation, including the seven files named
`2024121*_iOS.jpeg`, which are renders exported through Photoshop and carry no
camera EXIF. All Marina Orikum imagery is labelled ARTIST'S IMPRESSION until
genuine photography of the built development is supplied.

**Copy** — the brochure is bilingual and the Albanian is developer-written; use it
as the source for development-level Albanian rather than translating the English
back. Unit-level Albanian follows house style.

**Onboarding** — 70 plan sheets, all parsing cleanly:

    python3 pipeline/build_orikum.py _work/orikum/<slug>/config.json
    python3 pipeline/build_orikum_collection.py

`lib/orikum.parse_sheet()` reads building, floor, apartment number, type and all
five areas off any sheet. Figures are never retyped into a config.
