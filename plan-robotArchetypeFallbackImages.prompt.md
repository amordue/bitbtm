## Plan: Robot Archetype Fallback Images

Add a static fallback-image system for robots without uploaded photos by committing a small library of blueprint-style archetype images, normalizing free-text `weapon_type` values to those archetypes, and routing all public thumbnail/detail rendering through one shared helper. This keeps image behavior consistent across pages, preserves uploaded/sheet images as the highest priority, and gives unknown labels a generic robot blueprint fallback.

**Steps**
1. Phase 1: Inventory and asset contract
   - Create a fixed fallback asset set under `/home/alexmordue/homeprojects/bitbt/static/robot-archetypes/` with one image per requested archetype: `flipper`, `vertical-spinner`, `horizontal-spinner`, `hammer`, `saw`, `lifter`, `grabber`, `cluster`, `rammer`, plus `generic`.
   - Add an organiser-requested extension asset, `drum-spinner`, as a dedicated blueprint fallback rather than folding all drum imagery into `vertical-spinner`.
   - Standardize one aspect ratio and file format for all committed assets so every existing `Img(...)` slot can reuse them without layout churn. Selected implementation: landscape `4:3` `svg` assets at `1200x900`.
   - Define a reusable image-generation prompt/style sheet so all art is visually consistent: hybrid blueprint/sketch aesthetic, sparse technical linework, readable silhouette, pale cyan/white strokes on deep navy paper, a few drafting callouts, no text labels, no photorealism, minimal background clutter.
   - Document the agreed art direction: mix side and top views when that improves readability, show wheels/running gear clearly, and prefer believable weapon proportions over exaggerated iconography.
   - Map the user-provided archetype list to filenames and document that these are organizer-supplied fallback assets, not replacements for real robot photos.
   - Capture per-archetype silhouette guidance for the committed art set:
     - `flipper`: low wedge flipper
     - `vertical-spinner`: side view with a large exposed disc
     - `horizontal-spinner`: mostly top-down with a long, dominant bar
     - `drum-spinner`: top view with a compact rectangular chassis around the drum
     - `hammer`: long overhead striker on a low compact wedge body
     - `saw`: forward-reaching surgical armature
     - `lifter`: long front forks
     - `grabber`: crusher-like profile
     - `cluster`: three nearly equal bots, visibly separated
     - `rammer`: aggressive wedge/plough silhouette
     - `generic`: balanced all-rounder that still feels battle-ready
2. Phase 2: Weapon-type normalization and fallback selection
   - Add a helper in `/home/alexmordue/homeprojects/bitbt/routes/public.py` or a small shared utility module if reuse across admin/public becomes large enough. The helper should normalize `robot.weapon_type` by lowercasing, trimming, collapsing punctuation, and matching aliases.
   - Build a synonym table that maps common sheet/free-text values to the archetypes. Include values already seen in tests/data such as `Vertical spinner`, `Spinner`, `Drum`, and `Hammer-Saw`.
   - Update explicit alias behavior for the expanded asset set: `drum` should map to `drum-spinner`; generic `spinner` can continue to map to `vertical-spinner`; `hammer-saw` can map to `saw` or `hammer` based on preferred visual emphasis, but this should be chosen once and used consistently.
   - Expose one function that returns the effective display image URL in priority order: uploaded/sheet `robot.image_url` first, mapped archetype image second, `generic` fallback last.
3. Phase 3: Public rendering integration
   - Update all public render sites that currently branch directly on `robot.image_url` to call the shared helper instead.
   - Cover at minimum these locations in `/home/alexmordue/homeprojects/bitbt/routes/public.py`: robot detail hero/lightbox area, leaderboard thumbnails, live display cards, robot lookup results, and sub-event team roster thumbnails.
   - Preserve current behavior where missing robots or `TBD/BYE` slots should not incorrectly show archetype art unless backed by a real `Robot` record.
   - Keep `alt` text tied to the robot name, and only enable the detail-page lightbox if the UX still makes sense for fallback art. Recommended: allow the detail hero image to render with fallback art, but skip the lightbox treatment for generated archetype placeholders to avoid presenting them as full robot photography.
4. Phase 4: Optional admin consistency pass
   - If the chosen scope includes admin thumbnails, reuse the same helper or a small shared helper in `/home/alexmordue/homeprojects/bitbt/routes/admin.py` for roster/list thumbnails without changing upload behavior.
   - Do not alter upload/import persistence rules in `/home/alexmordue/homeprojects/bitbt/routes/admin.py` or `/home/alexmordue/homeprojects/bitbt/event_imports.py`; this feature is display fallback only.
5. Phase 5: Tests and verification
   - Extend `/home/alexmordue/homeprojects/bitbt/tests/test_phase6_public.py` with coverage for robots that have no `image_url` but do have `weapon_type`, asserting that public views render the fallback asset path instead of blank/thumb placeholder markup.
   - Add coverage for alias normalization using representative values already in fixtures or imports, especially `Vertical spinner`, `Hammer`, `Lifter`, `Drum`, and an unknown label that should hit the generic asset.
   - If admin views are included, add or extend the most relevant admin test file to assert roster thumbnails show fallback images without affecting the upload button flow.
   - Run the public-view test target from repo memory: `/home/alexmordue/homeprojects/bitbt/.venv/bin/python -m unittest tests.test_phase6_public`.

**Relevant files**
- `/home/alexmordue/homeprojects/bitbt/routes/public.py` — primary integration points for live cards, robot detail, leaderboard, lookup, and team thumbnails; best place to introduce a shared display-image helper if kept public-only.
- `/home/alexmordue/homeprojects/bitbt/routes/admin.py` — optional admin thumbnail consistency if organizer wants fallback images in roster/list screens too.
- `/home/alexmordue/homeprojects/bitbt/models.py` — confirms `weapon_type` is free-text and `image_url` remains the persisted high-priority image source.
- `/home/alexmordue/homeprojects/bitbt/tests/test_phase6_public.py` — main verification target for public fallback rendering and alias handling.
- `/home/alexmordue/homeprojects/bitbt/static/uploads/` — existing uploaded-image area; should remain separate from committed archetype assets.
- `/home/alexmordue/homeprojects/bitbt/static/robot-archetypes/` — new committed asset directory for the fallback image library.

**Verification**
1. Generate or place the committed archetype assets and confirm they are served correctly from `/static/robot-archetypes/...`.
2. Run `/home/alexmordue/homeprojects/bitbt/.venv/bin/python -m unittest tests.test_phase6_public` and any admin test file touched by the change.
3. Manually load an event with robots lacking `image_url` and confirm fallback images appear in live display, robot detail, leaderboard, lookup results, and team rosters.
4. Manually confirm robots with real uploaded/sheet images still show those originals everywhere, and `TBD/BYE` cards do not inherit archetype art.
5. Verify an unknown or messy `weapon_type` string resolves to the generic blueprint image rather than a broken path.

**Decisions**
- Included scope: all public views that currently render robot images conditionally.
- Selected delivery model: committed static assets rather than runtime generation.
- Selected unknown handling: alias mapping first, generic blueprint fallback second.
- Selected art direction: hybrid blueprint illustrations, sparse linework, mixed viewpoint per archetype, visible wheels, believable weapon proportions, and light drafting callouts.
- Selected scope extension: add a dedicated `drum-spinner` fallback asset.
- Deliberately excluded: database schema changes, Google Sheets import changes, and replacing uploaded real robot images.

**Further Considerations**
1. Alias choice for hybrid types should be documented once during implementation. Recommendation: choose the visually dominant weapon silhouette rather than introducing many extra categories.
2. If the blueprint art is AI-generated outside the repo, keep a short note of prompt/settings/source so future additions match the established style.
3. If the detail-page lightbox is retained for fallback assets, label or visually distinguish them so users do not mistake them for actual uploaded robot photos.
