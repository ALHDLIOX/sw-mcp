"""Validate declarative, geometry-associated drawing recipes without loading COM."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (
    ROOT
    / "subskills/solidworks-engineering-drawing/schemas/native_drawing_recipe.schema.json"
)
SIMPLE_TITLE_BOX = {"left": 0.255, "bottom": 0.010, "right": 0.410, "top": 0.040}


def load_recipe(source):
    """Return validated data; paths are resolved by the executor, not the schema."""
    recipe = (
        copy.deepcopy(source)
        if isinstance(source, dict)
        else json.loads(Path(source).read_text(encoding="utf-8"))
    )
    try:
        Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(
            recipe
        )
    except ValidationError as exc:
        raise ValueError("Invalid drawing recipe: " + exc.message) from exc

    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Recipe numbers must be finite")
        if isinstance(value, dict):
            for item in value.values():
                finite(item)
        if isinstance(value, list):
            for item in value:
                finite(item)

    finite(recipe)
    names = [v["name"] for v in recipe["views"]]
    if len(names) != len(set(names)) or not {"Front", "Top", "Right"} <= set(names):
        raise ValueError("Exactly one Front, Top and Right view is required")
    view_points = {v["name"]: v["positionMm"] for v in recipe["views"]}
    front, top, right = (view_points[n] for n in ("Front", "Top", "Right"))
    if not (
        abs(front[0] - top[0]) <= 0.001
        and top[1] < front[1]
        and abs(front[1] - right[1]) <= 0.001
        and right[0] < front[0]
    ):
        raise ValueError(
            "First-angle views must be aligned: Top below Front, Right to its left"
        )
    if any(not (10 < p[0] < 410 and 10 < p[1] < 287) for p in view_points.values()):
        raise ValueError("View anchor must be inside the A3 frame")
    ids = [d["id"] for d in recipe["dimensions"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Dimension IDs must be unique")
    for item in [*recipe["dimensions"], *recipe.get("notes", [])]:
        if item.get("view") and item["view"] not in names:
            raise ValueError("Annotation references an absent view")
        if item.get("entity") and not item.get("view"):
            raise ValueError("Attached notes require a view")
        x, y = item["positionMm"]
        if not (10 < x < 410 and 10 < y < 287):
            raise ValueError("Annotation anchor must be inside the A3 frame")
    return recipe


def same_point(a, b, tolerance_mm=0.001):
    return len(a) == len(b) and max(abs(x - y) for x, y in zip(a, b)) <= tolerance_mm


def resolve_entity(descriptor, catalog):
    """Select by exact model geometry, never by screen pixels or Edge1 indexes."""
    for item in catalog:
        if descriptor["type"] != item["type"]:
            continue
        kind = descriptor["type"]
        if kind == "vertex" and same_point(descriptor["pointMm"], item["pointMm"]):
            return item["object"]
        if (
            kind == "circle"
            and same_point(descriptor["centerMm"], item["centerMm"])
            and abs(descriptor["radiusMm"] - item["radiusMm"]) <= 0.001
        ):
            return item["object"]
        if kind == "line" and any(
            same_point(descriptor["startMm"], a) and same_point(descriptor["endMm"], b)
            for a, b in [
                (item["startMm"], item["endMm"]),
                (item["endMm"], item["startMm"]),
            ]
        ):
            return item["object"]
    raise ValueError(f"No model entity matches {descriptor}")


def drawing_spec(recipe, source_model):
    return {
        "schemaVersion": "1.0",
        "sourceModel": str(source_model),
        "documentType": "part",
        "standard": recipe.get("standard", "ISO"),
        "projection": "first_angle",
        "paperSize": "A3",
        "modelSizeMm": recipe["modelSizeMm"],
        "scale": recipe.get("scale", 2),
        "views": {v["name"].lower(): {} for v in recipe["views"]},
        "insertModelDimensions": False,
        "requiredDimensions": [
            {
                "id": d["id"],
                "view": d["view"],
                "kind": "diameter" if d["kind"] == "diameter" else "linear",
                "valueMm": d["expectedMm"],
            }
            for d in recipe["dimensions"]
        ],
        "notes": [n["text"] for n in recipe.get("notes", []) if n.get("entity")],
        "outputs": {"slddrw": True, "pdf": True, "png": True, "report": True},
    }
