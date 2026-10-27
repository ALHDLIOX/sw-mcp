# Reusable associative drawing workflow

Use this path for an existing SLDPRT with explicit dimensions, standard views and a simple title block. The generic DrawingSpec path remains available for legacy templates/BOM. Image interpretation and deciding dimension intent remain agent work; execution is declarative and repeatable.

## Run

```powershell
python scripts/draw_from_recipe.py --recipe examples/peek_bracket_drawing.json --validate-only
python scripts/draw_from_recipe.py --recipe examples/peek_bracket_drawing.json --model C:\parts\PEEK_CONNECTING_BRACKET.SLDPRT --out-dir C:\deliveries\bracket-01 --version 2024
```

MCP: `solidworks_generate_drawing_from_recipe(recipe_path, output_dir, source_model?, version?)`. It calls the same runner under the server's CAD lock. Use a fresh output folder; neither entry point overwrites an existing run. Missing source/geometry or mismatched dimensions fail with a report instead of an automatic retry loop.

`examples/peek_bracket_drawing.json` is a portable 12-dimension example. `--model` paths are relative to the calling shell; `sourceModel` inside a recipe is relative to that JSON. Units are mm in model coordinates and sheet coordinates. Change the JSON rather than copying COM code. The formal schema is `schemas/native_drawing_recipe.schema.json`.

## Contract

- `views`: Front, Top, Right, optionally Isometric; explicit sheet positions, shared scale and requested native center-mark counts.
- `dimensions`: stable ID, view, horizontal/vertical/diameter kind, model entity descriptors, position and expected value. Select lines by their two 3D endpoints, vertices by position and circles by center/radius. Missing geometry stops before drawing creation. No `Edge1` indexes or pixel selection.
- `notes`: literal text, sheet anchor and optional view/entity for an attached leader. Explain un-dimensioned modeling allowances as assumptions; do not invent manufacturing tolerances.
- `titleBlock`: literal part name, drawing number, material and date. Scale and sheet number are generated. The native six-field title block has no file-name/property links or signature grid.

The runner holds one owned `SolidWorksSession`: open source read-only, create drawing, add native associative dimensions, save, insert/read center marks, save and reopen drawing, re-read every dimension ID/value, export PDF, check PDF glyph bounds/layout, render PNG. User-owned documents and shared instances remain open. Source model is never edited. Machine `pass` still requires inspecting the final PNG before user delivery.

## SW2024 pitfalls now handled centrally

1. View positions require `VT_ARRAY | VT_R8`, then actual position readback. Use the existing `_set_view_center` helper, not tuple property setters. Ratio/position fields are not interchangeable.
2. Independent standard views are all Type 7. Map by `GetOrientationName`; do not require projected Type 4 views to recognize Top/Right.
3. `swDwgPaperA3size=8`; 6 is A4. An A3 format file used to mask this error. The runner starts without an inherited format and validates actual sheet width/height/projection.
4. Simple titles start from an empty native sheet format and use fixed literal fields. Do not shrink arbitrary linked descriptions to fit a default ISO signature grid.
5. SW2024 center-mark readback needs `GetFirstCenterMark` fallback; save before insertion and count the actual entities after reopening.
6. `INote.GetExtent` can include an attached leader. Keep that native extent, but use matched final-PDF text bounds for text collisions. A leader intentionally ending on a hole is not text overlaid on that view.
7. Use actual Unicode `Ø` in diameter prefixes; never deliver a PDF displaying unresolved `<MOD-DIAM>` tokens.
8. In native threads, set profile/size, then `PitchOverride=True`, then `Pitch`. A setter before enabling override may silently leave a 10-mm default. This is fixed in the threaded-hole subskill; verify pitch/depth again after model save/reopen.

Full geometry API checks remain distinct from layout: a matching number alone cannot validate a hole's thread, through state or manufacturing process. The original bracket is review-only because material, finish, tolerances and the extra 1-mm tap-drill allowance are undefined by its source drawing.

## Native regression

`python tests/solidworks_drawing_recipe_regression.py --model C:\parts\PEEK_CONNECTING_BRACKET.SLDPRT --out-dir C:\deliveries\recipe-regression --version 2024` exercises the real stdio MCP entry, saved native dimension values, PDF text matches, the unchanged source-model hash, and downloading the exported PDF by artifact URI/SHA-256. It is opt-in and excluded from ordinary pytest because it needs licensed SolidWorks and the matching source model. Fake/unit tests do not stand in for this native result.

Native acceptance on 2026-10-27, SW2024 SP05: the bracket recipe passed via both CLI and stdio MCP, with 12 saved/reopened native dimensions, 12 final-PDF text matches, four top and two front center marks, no layout findings, unchanged input model, and a verified PDF artifact round trip. The rendered simple-title drawing was visually inspected. This is one bounded fixture, not a claim that arbitrary drawings or SW versions are fully validated.
