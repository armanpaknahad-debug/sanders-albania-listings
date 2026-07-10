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
