---
name: sanders-unit
description: >
  Sanders' single front door for a new property unit. Trigger whenever Arman
  starts a new unit and drops raw developer materials — phrases like "new unit",
  "new unit — name or development", "onboard this unit", "do the full run",
  "standardise this place", or simply dropping photos, a floor-plan sheet and a price for a
  villa or apartment. This skill turns messy inbound (WhatsApp photos, renders,
  Instagram screenshots, an Albanian/Greek developer plan sheet, a price and unit
  code) into ONE canonical Property Profile, then fans out the full standardized
  bundle: the Cypress brochure PDF, the interactive floor-plan viewer link, the
  web listing, and the staff quote schedule. It owns the intake logic and the
  Property Profile schema; it delegates the actual builds to the existing engines
  (sanders-brochure for the PDF, the sanders-viewer pipeline for the HTML/link,
  GitHub→Netlify for the listing, the xlsx skill for the quote). Do NOT use for
  payment trackers (per-client, separate) or developer-agreement redlines.
---

# Sanders Unit — one drop, the whole standardized experience

## Onboarding pipeline (run from the listings repo in Claude Code)

The listings repo `armanpaknahad-debug/sanders-albania-listings` is the source of
truth — self-contained HTML pages, no build generator. It ships `pipeline/` with the
scripts below. When Arman drops a finished Sanders brochure PDF and a price, run:

```
# 1. extract — pulls photos, the real plan drawings, and spec into _work/<slug>/
python3 pipeline/onboard.py extract <brochure.pdf> --price "€ X" --dev "Development" --location "Area, Albania"

# 2. TRACE (this is the one step that needs Claude's eyes — do not script it blind):
#    - open _work/<slug>/plans/*  (the real drawings)
#    - for each level, crop its drawing and write _work/<slug>/rooms.json in IMAGE MODE:
#         {"levels":[{"name":"Ground floor","image":"data:image/png;base64,...","viewbox":"0 0 W H",
#                     "rooms":[{"name":"Living","area":"44 m²","points":"x1,y1 x2,y2 ..."}, ...]}]}
#      → the real drawing is the base; each room is a transparent clickable polygon in image px.
#      → read room NAMES off the drawing; the drawings rarely stamp per-room m², so reconcile
#        each level's room areas to the certified level total from the spec. Never invent totals.
#    - tidy _work/<slug>/config.json (dev_eyebrow, dev_strap, sub, description, gallery captions)

# 3. build — plan.html + index.html + thumb.jpg + gallery card + units.json, all in place
python3 pipeline/onboard.py build <slug>

# 4. publish
git add -A && git commit -m "Add <Name>" && git push origin main   # Netlify auto-deploys
```

**Non-negotiables baked into the pipeline:** real plan drawings as the base (never
redrawn boxes) with clickable rooms; the real Sanders logo (`pipeline/lib/logo.png`);
mobile-safe Cypress CSS with `clamp()` spacing (no dead space, no edge-crowding); the
listing embeds the interactive plan via `<iframe src="plan.html">` with height-sync.
**Séraphine is the exception** — inline SVG plan, no plan.html, leave untouched.

Pipeline files: `pipeline/onboard.py` (orchestrator), `pipeline/build_listing.py`
(config→listing), `pipeline/add_to_gallery.py` (card+manifest, idempotent, creates a new
development section when needed), `pipeline/lib/build_plan.py` + `plan_interactive.html`
(the interactive-plan engine, image + vector modes), `pipeline/lib/logo.png`.

## Legacy notes

The job: Arman drops everything he has on a single unit in one message. This skill
sorts it, builds one **Property Profile** (the source of truth), and generates all
four client-facing assets from that single record so they can never disagree.

**Golden rule:** every output reads from the Property Profile. Build the profile
once, correctly, then fan out. Never hand-feed raw materials into an engine twice.

## Step 0 — recognise the drop

The trigger is Arman starting a unit: a short sentence ("new unit — Green Coast
F2-4") plus attachments, or just the raw materials. Accept whatever's there:
photos, renders, drone/aerials, IG screenshots, a developer floor-plan PDF, an
area schedule, a developer price, a unit code, a development/location name, and any
special instruction ("keep the marina name", "all codes gone", "you pick the name").

Do NOT demand a tidy set. Sort what's given, flag what's missing, fabricate nothing.

## Step 1 — sort, then confirm THREE things in one round

Silently triage the drop (which image is the hero, which is a render vs the real
unit, which file is the plan sheet, what language the sheet is in). Then ask Arman
in a **single** round — never build before these are answered:

1. **Unit name** — a French female name not used before (track against memory to
   avoid repeats). Arman may say "you pick" → choose one that suits the setting.
2. **Client price** — either the guide price to display, or the developer price
   (then apply the +7% uplift, round to nearest €500). Confirm which.
3. **Market** — Albania or Greece → sets contacts, website, and Golden Visa framing.

Also confirm any edge cases surfaced during triage: keep vs strip the development
name; strip all unit codes; which images are renders needing "ARTIST'S IMPRESSION".

## Step 2 — build the Property Profile (show it, get GO)

Fill one `config.json` per unit and show it to Arman before generating anything.
He gives GO or corrects in one round.

```json
{
  "unit_id": "greencoast-II-F2-4",
  "developer_code": "F2-4",
  "sanders_name": "Séraphine",
  "development": "Green Coast",
  "keep_development_name": true,
  "location": { "town": "Palasë", "region": "Himarë", "country": "Albania" },
  "market": "albania",
  "price_developer": 370000,
  "price_client": 396000,
  "parking": { "included": false, "price": 20000 },
  "spec": {
    "bedrooms": 2,
    "internal_m2": 78, "loggia_m2": 12, "veranda_m2": 0, "common_m2": 9
  },
  "plan": {
    "rooms_file": "src/rooms.json",
    "_note": "Per-room geometry + m² for the interactive plan (see engine/rooms.example.json). Read every room name and size straight off the registered/developer plan — never fabricate. If a plan sheet is present, this MUST be filled; the listing does not ship without it."
  },
  "assets": {
    "hero": "src/hero.jpg",
    "gallery": ["src/g1.jpg", "src/g2.jpg"],
    "renders": ["src/render1.jpg"],
    "plan_sheet": "src/plans.pdf",
    "aerial": "src/aerial.jpg"
  },
  "flags": {
    "strip_all_codes": true,
    "artist_impression": ["render1.jpg"]
  }
}
```

Weighted area for €/m²: internal + loggia (100%) + veranda (50%) + common (50%).

## Step 3 — apply the Standardizer (non-negotiable, every unit)

These are the Sanders defaults — already the house standard:

- **De-brand** — strip developer contacts, unit codes, architect credits.
- **Rename** — use the agreed French female name everywhere, including cover
  reference lines. Original code lives in `developer_code` only, never displayed.
- **Translate** — Albanian/Greek plan labels → English (Tualet→WC, Kuzhine→Kitchen,
  Dhome gjumi→Bedroom; Loggia stays Loggia). Redact + re-insert real text; don't
  paint over line art.
- **Uplift** — developer price +7%, round to €500. Parking is always a separate
  charge, flagged explicitly — never rolled into the unit price.
- **Interactive plan** — the listing plan is always the clickable Cypress plan (tap a
  room → its m²), built via `engine/build_plan.py`. Never a flat brochure image.
- **Honest renders** — anything not the exact unit → captioned "ARTIST'S IMPRESSION".
- **Never fabricate** — blanks stay blank; read bedroom counts off the plan only if
  clearly visible.

## Step 4 — fan out all four (delegate to the existing engines)

Generate from the Property Profile — do not re-ask for materials:

1. **Brochure PDF** → invoke the `sanders-brochure` skill. Feed it the profile's
   name, price, market contacts, image paths, and cleaned plan sheet. Output:
   `<Name>_Sanders.pdf` (3-page landscape Cypress deck).
2. **Interactive floor plan → viewer** (NON-NEGOTIABLE, every unit — the Séraphine
   standard). The listing's plan is ALWAYS the clickable Cypress plan where tapping a
   room reveals its m² — never a flat image lifted from the brochure. Build it with
   the bundled engine:

   ```
   python3 engine/build_plan.py <unit>/rooms.json --out <slug>/plan.html
   ```

   Then embed `plan.html` as the plan section of the listing (inline, or as the
   viewer link). See **Interactive plan engine** below for the room schema and the
   redraw rule. No listing publishes with "Floor plans available on request" while a
   plan sheet exists — if we hold plans, it's a deliberate, flagged exception (raw
   construction-only drawings), not a default.
3. **Web listing** → publish the built page, **routed by `market`** (see routing
   table below). Push via GitHub Contents API (fetch SHA fresh before PUT; Netlify
   auto-deploys). Update both the per-floor row and the "all units" table in
   `apartments/index.html` on the target site.
4. **Quote schedule** → build the staff-facing xlsx via the `xlsx` skill:
   client price only (developer base + margin mechanics stripped), parking listed
   separately, +7% already applied. Run `recalc.py` after build.

### Listing routing — separate by country (non-negotiable)

The `market` field decides where the listing and the viewer link go. Never mix them.

| `market`  | Live URL pattern                          | Host / repo target                     | Status |
|-----------|-------------------------------------------|----------------------------------------|--------|
| `greece`  | `sandersgreece.com/listings/<slug>/`      | Sandersgreece repo → Netlify           | Live now |
| `albania` | `listings.sandersalbania.com/<slug>/`     | Albania listings site → Netlify        | Pending DNS |
| other     | confirm with Arman before publishing      | —                                      | Ask |

Rules:
- **Greek units** → publish to `sandersgreece.com` exactly as today.
- **Albanian units** → target the `listings.sandersalbania.com` subdomain. This is a
  Netlify subdomain that does NOT touch the team's Framer marketing site — never push
  Sanders listings onto the root `sandersalbania.com` (Framer owns it, used for paid
  ads). Only build/link listings under the `listings.` subdomain.
- **If the Albania subdomain isn't live yet** (DNS/Netlify not set up): build the
  page and viewer as normal, but DON'T publish to a dead URL. Tell Arman it's ready
  and held pending the `listings.sandersalbania.com` DNS record, and offer to
  temporarily stage it under `sandersgreece.com` if he wants a working link now.
- The brochure and quote schedule are unaffected by market except for contacts
  (Albania vs Greece) — that's already handled by the `market` field.

Render every visual output to image and **look at it** before presenting — check for
leftover codes/contacts, IG badges, construction signage, washed-out text. Grep the
brochure text layer for the developer name and unit codes to confirm they're gone.

## Step 5 — present + remember

Present all four together in one message (each as a file/link). Save the Property
Profile to memory so any later tweak regenerates fresh — never ask Arman to
re-upload. Log the French name as used.

## Interactive plan engine (`engine/`)

Every unit's plan is the clickable Séraphine-style plan: rooms are SVG polygons,
tapping one reveals its size in the detail panel, level tabs switch floors. Cypress
palette, generous mobile padding (no text near the edges), viewBox cropped tight to
the plan so there's **no dead space** below it.

Files:
- `engine/plan_interactive.html` — the template + engine (data block is the swap point).
- `engine/build_plan.py` — `python3 build_plan.py rooms.json --out <slug>/plan.html`.
- `engine/rooms.example.json` — the schema.

Room schema (per level): `viewbox` (SVG coords for that floor) + `rooms[]`, each with
`name`, `area` (e.g. `"22.8 m²"`), `points` (polygon in that viewBox). `outdoor:true`
= dashed gold styling for veranda/terrace. Top-level `totals[]` fills the summary tiles.

The redraw rule (unchanged from the brochure standard): **redraw the plan geometry per
unit** — trace the real walls off the registered/developer sheet; read every room name
and m² straight off it; fabricate nothing. This tracing is the one genuinely per-unit
step — the engine turns it into "fill the schema", not bespoke code each time. If all
you have is a low-res thumbnail, trace from that and flag it for a clean re-trace.

## Working style (Arman)

Execution-first — make reasonable calls on layout, naming, copy; flag edge cases,
don't gate on every detail. Gather-then-build: reconcile all figures before building.
All feedback in one round, then GO. One clear step at a time. Direct, warm, short
sentences; dashes for lists; no corporate language.
