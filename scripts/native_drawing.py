"""One-session native associative drawings from validated, reusable JSON recipes.

No arbitrary code, screen coordinates, template-property links, or retry loops.
The saved drawing is reopened and audited before final PDF/layout review.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import traceback
from pathlib import Path

from .drawing_recipe import SIMPLE_TITLE_BOX, drawing_spec, load_recipe, resolve_entity


def _catalog(model, get):
    records = []
    for body in get(model, "GetBodies2", 0, False) or []:
        for edge in get(body, "GetEdges") or []:
            curve = get(edge, "GetCurve")
            vertices = [
                get(edge, key, default=None)
                for key in ("GetStartVertex", "GetEndVertex")
            ]
            points = [
                [float(x) * 1000 for x in get(v, "GetPoint")] if v is not None else None
                for v in vertices
            ]
            for v, p in zip(vertices, points):
                if p is not None:
                    records.append({"type": "vertex", "pointMm": p, "object": v})
            if get(curve, "IsLine") and all(p is not None for p in points):
                records.append(
                    {
                        "type": "line",
                        "startMm": points[0],
                        "endMm": points[1],
                        "object": edge,
                    }
                )
            elif get(curve, "IsCircle"):
                data = list(get(curve, "CircleParams"))
                records.append(
                    {
                        "type": "circle",
                        "centerMm": [x * 1000 for x in data[:3]],
                        "radiusMm": data[6] * 1000,
                        "object": edge,
                    }
                )
    return records


def _font(annotation, get, height_mm=3.2):
    fmt = get(annotation, "GetTextFormat", 0)
    fmt.TypeFaceName = "Arial"
    fmt.CharHeight = height_mm / 1000
    fmt.Bold = False
    fmt.Italic = False
    if not annotation.SetTextFormat(0, False, fmt):
        raise RuntimeError("Annotation font assignment failed")


def _note(drawing, get, text, position_mm, height_mm=3.0, view=None, entity=None):
    drawing.ClearSelection2(True)
    if view is not None:
        drawing.ActivateView(view.Name)
        if entity is not None and not view.SelectEntity(entity, False):
            raise RuntimeError("Cannot select note attachment")
    note = drawing.InsertNote(text)
    if note is None:
        raise RuntimeError("InsertNote returned None")
    annotation = get(note, "GetAnnotation")
    annotation.SetPosition2(position_mm[0] / 1000, position_mm[1] / 1000, 0)
    annotation.SetLeader3(1 if entity is not None else 0, 0, False, False, False, False)
    _font(annotation, get, height_mm)
    if str(get(note, "GetText")) != text:
        raise RuntimeError("Note text did not persist")
    drawing.ClearSelection2(True)
    return note


def _simple_sheet(drawing, recipe, get):
    """Native linework and literal fields, never linked filenames or author grids."""
    sheet = get(drawing, "GetCurrentSheet")
    scale = recipe.get("scale", 2)
    # swDwgPaperA3size=8, swDwgTemplateNone=13 (SW2024 Interop).
    if not drawing.SetupSheet6(
        get(sheet, "GetName"),
        8,
        13,
        scale,
        1.0,
        True,
        "",
        0.420,
        0.297,
        "",
        True,
        0.0,
        0.0,
        0.0,
        0.0,
        0,
        0,
    ):
        raise RuntimeError("Blank A3 first-angle sheet setup failed")
    drawing.EditTemplate()
    try:
        sm = drawing.SketchManager
        sm.AddToDB = True
        try:
            lines = [
                (10, 10, 410, 10),
                (410, 10, 410, 287),
                (410, 287, 10, 287),
                (10, 287, 10, 10),
                (255, 10, 255, 40),
                (255, 40, 410, 40),
                (255, 25, 410, 25),
                (370, 25, 370, 40),
                (310, 10, 310, 25),
                (360, 10, 360, 25),
                (385, 10, 385, 25),
            ]
            for x1, y1, x2, y2 in lines:
                if (
                    sm.CreateLine(x1 / 1000, y1 / 1000, 0, x2 / 1000, y2 / 1000, 0)
                    is None
                ):
                    raise RuntimeError("Sheet-format line creation failed")
        finally:
            sm.AddToDB = False
        tb = recipe["titleBlock"]
        fields = [
            ("PART NAME", tb["title"], 258, 38, 31, 3.0),
            ("DATE", tb.get("date", "TBD"), 373, 38, 31, 2.8),
            ("DRAWING NO.", tb["drawingNumber"], 258, 23, 16, 3.0),
            ("MATERIAL", tb.get("material", "TBD"), 313, 23, 16, 2.8),
            ("SCALE", f"{scale:g}:1", 363, 23, 16, 2.8),
            ("SHEET", "1 / 1", 388, 23, 16, 2.8),
        ]
        for label, value, x, label_y, value_y, height in fields:
            _note(drawing, get, label, [x, label_y], 1.8)
            _note(drawing, get, value, [x, value_y], height)
    finally:
        drawing.EditSheet()
    drawing.ClearSelection2(True)
    props = list(get(sheet, "GetProperties"))
    if (
        len(props) < 7
        or not bool(props[4])
        or abs(props[5] - 0.42) > 1e-6
        or abs(props[6] - 0.297) > 1e-6
    ):
        raise RuntimeError(f"A3 projection/size readback failed: {props}")
    return {
        "style": "simple",
        "fields": dict(recipe["titleBlock"]),
        "box": dict(SIMPLE_TITLE_BOX),
        "sheet_properties": props,
    }


def _annotate(drawing, views, recipe, catalog, get):
    results = []
    for dim in recipe["dimensions"]:
        drawing.ClearSelection2(True)
        view = views[dim["view"]]
        drawing.ActivateView(view.Name)
        for i, descriptor in enumerate(dim["entities"]):
            if not view.SelectEntity(resolve_entity(descriptor, catalog), i > 0):
                raise RuntimeError("Dimension selection failed: " + dim["id"])
        method = {
            "horizontal": "AddHorizontalDimension2",
            "vertical": "AddVerticalDimension2",
            "diameter": "AddDiameterDimension2",
        }[dim["kind"]]
        x, y = [v / 1000 for v in dim["positionMm"]]
        dd = get(drawing, method, x, y, 0)
        if dd is None:
            raise RuntimeError("Dimension creation failed: " + dim["id"])
        native = get(dd, "GetDimension2", 0)
        actual = float(get(native, "SystemValue")) * 1000
        if not math.isclose(actual, dim["expectedMm"], abs_tol=0.001):
            raise RuntimeError(
                f"Dimension {dim['id']}: expected {dim['expectedMm']}, measured {actual}"
            )
        native.Name = dim["id"]
        # Actual Unicode diameter avoids a literal unresolved <MOD-DIAM> token.
        for key, index in [("prefix", 1), ("suffix", 2)]:
            if key in dim:
                dd.SetText(index, dim[key])
        _font(get(dd, "GetAnnotation"), get)
        results.append({"id": dim["id"], "value_mm": actual})
    for note in recipe.get("notes", []):
        drawing.ActivateView("")
        _note(
            drawing,
            get,
            note["text"],
            note["positionMm"],
            note.get("heightMm", 3),
            views.get(note.get("view")),
            resolve_entity(note["entity"], catalog) if note.get("entity") else None,
        )
    drawing.ActivateView("")
    drawing.ClearSelection2(True)
    return results


def _dimension_readback(drawing, recipe, get):
    expected = {d["id"]: d for d in recipe["dimensions"]}
    values = {}
    for view in get(get(drawing, "GetCurrentSheet"), "GetViews") or []:
        dd = get(view, "GetFirstDisplayDimension5", default=None)
        while dd is not None:
            name = str(get(dd, "GetNameForSelection")).split("@")[0]
            if name in expected:
                actual = float(get(get(dd, "GetDimension2", 0), "SystemValue")) * 1000
                if not math.isclose(
                    actual, expected[name]["expectedMm"], abs_tol=0.001
                ):
                    raise RuntimeError("Reopened dimension value mismatch: " + name)
                values[name] = actual
            dd = get(dd, "GetNext5", default=None)
    if set(values) != set(expected):
        raise RuntimeError(
            f"Saved dimension IDs missing: {set(expected) - set(values)}"
        )
    return values


def render_pdf(pdf, png):
    renderer = shutil.which("pdftoppm")
    if renderer:
        subprocess.run(
            [
                renderer,
                "-scale-to",
                "2200",
                "-png",
                "-singlefile",
                str(pdf),
                str(png.with_suffix("")),
            ],
            check=True,
            timeout=60,
            capture_output=True,
        )
    else:
        import pymupdf

        with pymupdf.open(pdf) as document:
            document[0].get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(png)


def generate_drawing(recipe_source, output_dir, *, source_model=None, version=None):
    """Create a fresh run without overwriting deliverables; COM remains in one session."""
    recipe = load_recipe(recipe_source)
    base = (
        Path(recipe_source).resolve().parent
        if not isinstance(recipe_source, dict)
        else Path.cwd()
    )
    source = Path(source_model or recipe["sourceModel"]).expanduser()
    source = (
        source if source.is_absolute() or source_model is not None else base / source
    ).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    out = Path(output_dir).expanduser().resolve()
    name = recipe.get("basename", "drawing")
    drw, pdf, png, report_path = [
        out / (name + suffix)
        for suffix in (".SLDDRW", ".pdf", "_preview.png", "_report.json")
    ]
    if any(p.exists() for p in (drw, pdf, png, report_path)):
        raise FileExistsError(
            "Choose a new output directory; existing deliverables are protected"
        )
    # Resolve all environment-dependent imports only after recipe validation.
    from . import sw_drawing as drawing_tools
    from .sw_connect import get_com_member as get
    from .sw_drawing_review import review_drawing_artifacts
    from .sw_review import inspect_pdf_text_layout
    from .sw_session import SolidWorksSession

    out.mkdir(parents=True, exist_ok=True)
    spec = drawing_spec(recipe, source)
    result = {
        "status": "running",
        "source_model": str(source),
        "outputs": {
            "slddrw": str(drw),
            "pdf": str(pdf),
            "preview": str(png),
            "report": str(report_path),
        },
    }
    try:
        with SolidWorksSession(
            version=version, wait_seconds=30, visible=True
        ) as session:
            model = session.open(str(source), read_only=True, silent=True)
            catalog = _catalog(model, get)
            # Resolve geometry before creating the drawing; unsupported topology fails once.
            for d in recipe["dimensions"]:
                for entity in d["entities"]:
                    resolve_entity(entity, catalog)
            drawing = session.new_drawing()
            drawing.SetUnits(0, 1, 2, 0, False)
            drawing.SetUserPreferenceIntegerValue(
                13, 7 if recipe.get("standard") == "GB_T" else 2
            )
            drawing.SetUserPreferenceIntegerValue(49, 2)
            result["title_block"] = _simple_sheet(drawing, recipe, get)
            views = {}
            for item in recipe["views"]:
                view = drawing_tools.add_view(
                    drawing, str(source), "*" + item["name"], 0.2, 0.2
                )
                if view is None:
                    raise RuntimeError("View creation failed: " + item["name"])
                view.SetName2(item["name"])
                view.UseSheetScale = 1
                view.PositionLocked = False
                if not view.SetDisplayMode3(False, 2, False, False):
                    raise RuntimeError("Hidden-line removal setup failed")
                # Reuse typed SAFEARRAY setter + position readback. No raw tuple setters.
                drawing_tools.set_view_position(
                    view, [x / 1000 for x in item["positionMm"]]
                )
                views[item["name"]] = view
            result["created_dimensions"] = _annotate(
                drawing, views, recipe, catalog, get
            )
            if not drawing.ForceRebuild3(False) or not session.save(drawing, str(drw)):
                raise RuntimeError("Drawing rebuild/save failed")
            requirements = [
                {
                    "id": "CM_" + v["name"],
                    "view": v["name"],
                    "count": v["centerMarks"],
                    "targets": ["holes"],
                }
                for v in recipe["views"]
                if v.get("centerMarks")
            ]
            if requirements:
                marks = drawing_tools.auto_insert_center_marks(drawing, requirements)
                result["center_marks"] = marks
                if marks["status"] != "pass":
                    raise RuntimeError(f"Center-mark validation failed: {marks}")
            drawing.ActivateView("")
            drawing.ClearSelection2(True)
            if not session.save(drawing, str(drw)):
                raise RuntimeError("Annotated drawing save failed")
            session.close(drawing)
            drawing = session.open(str(drw), silent=True)
            result["reopened_dimension_values_mm"] = _dimension_readback(
                drawing, recipe, get
            )
            drawing.ViewZoomtofit2()
            if not drawing_tools.export_sheet_to_pdf(
                drawing, str(pdf), sw_app=session.sw
            ):
                raise RuntimeError("PDF export failed")
            structure = drawing_tools.inspect_drawing_structure(
                drawing, paper_size_hint="A3", title_block_box=SIMPLE_TITLE_BOX
            )
            definition = {d["id"]: d for d in recipe["dimensions"]}
            for d in structure["dimensions"]:
                key = d["name"].split("@")[0]
                if key in definition:
                    d.update(
                        id=key,
                        kind="diameter"
                        if definition[key]["kind"] == "diameter"
                        else "linear",
                        value_mm=result["reopened_dimension_values_mm"][key],
                        semantic_view=definition[key]["view"],
                    )
            result["structure"] = structure
            result["review"] = review_drawing_artifacts(
                spec, structure=structure, pdf_path=pdf
            )
            result["pdf_text"] = inspect_pdf_text_layout(pdf)
            result["status"] = result["review"]["status"]
            if not drw.stat().st_size or not pdf.stat().st_size:
                raise RuntimeError("Empty deliverable")
        render_pdf(pdf, png)
        result["visual_review_required"] = True
        result["recipe"] = recipe
    except Exception as exc:  # noqa: BLE001 - persist failures at the COM/run boundary
        result.update(status="failed", error=str(exc), traceback=traceback.format_exc())
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return result
