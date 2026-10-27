"""Regression contracts for the SW2024 bracket drawing failures."""

from pathlib import Path

import pytest

from scripts.drawing_recipe import load_recipe, resolve_entity

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/peek_bracket_drawing.json"


def test_checked_in_recipe_is_complete_and_portable():
    recipe = load_recipe(EXAMPLE)
    assert len(recipe["dimensions"]) == 12
    assert not Path(recipe["sourceModel"]).is_absolute()
    assert {v["name"]: v.get("centerMarks") for v in recipe["views"]}["Top"] == 4


@pytest.mark.parametrize(
    "mutation", ["duplicate_id", "absent_view", "nan", "outside_sheet", "third_angle"]
)
def test_invalid_recipe_is_rejected_before_loading_com(mutation):
    recipe = load_recipe(EXAMPLE)
    if mutation == "duplicate_id":
        recipe["dimensions"][1]["id"] = recipe["dimensions"][0]["id"]
    elif mutation == "absent_view":
        recipe["dimensions"][0]["view"] = "Back"
    elif mutation == "nan":
        recipe["dimensions"][0]["entities"][0]["centerMm"][0] = float("nan")
    elif mutation == "third_angle":
        recipe["views"][1]["positionMm"] = [180, 250]
    else:
        recipe["dimensions"][0]["positionMm"] = [500, 100]
    with pytest.raises(ValueError):
        load_recipe(recipe)


def test_line_selection_uses_endpoints_not_enum_order():
    descriptor = {"type": "line", "startMm": [0, 0, 0], "endMm": [40, 0, 0]}
    catalog = [
        {"type": "line", "startMm": [0, 0, 0], "endMm": [4, 0, 0], "object": "wrong"},
        {"type": "line", "startMm": [40, 0, 0], "endMm": [0, 0, 0], "object": "right"},
    ]
    assert resolve_entity(descriptor, catalog) == "right"
    with pytest.raises(ValueError, match="No model entity"):
        resolve_entity({"type": "vertex", "pointMm": [0, 0, 0]}, catalog)


def test_existing_deliverables_are_not_overwritten_before_com(tmp_path):
    from scripts.native_drawing import generate_drawing

    model = tmp_path / "part.SLDPRT"
    model.write_bytes(b"existing")
    recipe = load_recipe(EXAMPLE)
    (tmp_path / (recipe["basename"] + ".pdf")).write_bytes(b"existing PDF")
    with pytest.raises(FileExistsError):
        generate_drawing(recipe, tmp_path, source_model=model)
    assert (tmp_path / (recipe["basename"] + ".pdf")).read_bytes() == b"existing PDF"


def test_model_override_is_relative_to_caller_not_recipe(monkeypatch, tmp_path):
    from scripts.native_drawing import generate_drawing

    monkeypatch.chdir(tmp_path)
    (tmp_path / "part.SLDPRT").write_bytes(b"model")
    (tmp_path / "PEEK_CONNECTING_BRACKET_SIMPLE.pdf").write_bytes(b"protected")
    with pytest.raises(FileExistsError):
        generate_drawing(EXAMPLE, tmp_path, source_model=Path("part.SLDPRT"))
