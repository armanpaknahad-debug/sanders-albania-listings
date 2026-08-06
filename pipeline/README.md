# Sanders listings — onboarding pipeline

Source of truth is this repo (self-contained HTML, no build generator). To add a unit:

    python3 pipeline/onboard.py extract <brochure.pdf> --price "€ X" --dev "Development" --location "Area, Albania"
    # → Claude: open _work/<slug>/plans/*, write _work/<slug>/rooms.json (real drawing + clickable rooms),
    #   tidy _work/<slug>/config.json
    python3 pipeline/onboard.py build <slug>
    git add -A && git commit -m "Add <Name>" && git push origin main

Scripts: onboard.py (orchestrator) · build_listing.py (config→listing) · add_to_gallery.py (card+manifest).
Engine: lib/build_plan.py + lib/plan_interactive.html (image + vector modes). Logo: lib/logo.png.
Requires: Python 3, PyMuPDF (fitz), Pillow.  `pip install pymupdf pillow`

Rules: real plan drawings as the base (never redrawn boxes); real Sanders logo; mobile-safe clamp() CSS;
interactive plan embedded via iframe. Séraphine keeps its inline-SVG plan — do not touch it.

## English only — do not reintroduce Albanian

`listings.sandersalbania.com` is an **English-only site**. No page on it carries
Albanian, and none should: bilingual output is a **Tirana-site feature** and lives
in that repo, along with its `_albanian-reference/` style guide. A copy of that
folder does not belong here — if one appears, delete it.

Albanian source material is still *read* — the Marina Orikum brochure is bilingual
and its Albanian is developer-written, so it is the better source for facts about
the development. Reading it is fine. Publishing it on this site is not.

There are deliberately no Albanian constants in `lib/orikum.py` and no Albanian
section in `build_orikum.py`. Both were built once and removed on request; don't
add them back.
