"""@brief 离线验收器契约测试；合成测量记录不代表真实 CAD 结果。"""
from copy import deepcopy
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from solidworks_golden_mounting_bracket_2026 import completion_gate, expected_volume, load_case, validate_snapshot


def valid_measurements():
    """@brief 构造验收器输入夹具；不启动、模拟或声称已执行 SolidWorks。"""
    _, spec = load_case()
    holes = [{"diameter_mm": 7, "position_mm": [x, y, 0], "axis": [0, 0, 1], "axial_length_mm": 10}
             for x, y in spec["hole_centers_mm"]]
    return {"body_count": 1, "geometry": {"envelope_mm": {"length": 120, "width": 80, "height": 10}, "holes": holes},
            "mass": {"volume_mm3": expected_volume(spec), "density_kg_m3": 2700},
            "planes": [{"axis": a, "coordinate_mm": v} for a, v in ((0, -60), (0, 60), (1, -40), (1, 40), (2, 0), (2, 10))],
            "circular_edges": [[x, y, z, 3.5, True, math.pi * 7] for x, y in spec["hole_centers_mm"] for z in (0, 10)],
            "features": {"features": [{"type": "Boss"}, {"type": "Cut"}]},
            "sketch_quality": {"status": "pass", "sketches": [{}, {}]},
            "material": {"name": "6061-T6 (SS)", "database": "fixture.sldmat"}, "thickness_mm": 10}


def test_analytic_volume_and_definition():
    """@brief 固定 P0 规格及解析体积，防止误改夹具后假成功。"""
    workflow, spec = load_case()
    assert workflow["id"] == "mounting_bracket"
    assert math.isclose(expected_volume(spec), 94460.619599741, abs_tol=1e-6)
    assert validate_snapshot(valid_measurements(), spec)["status"] == "pass"


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(body_count=2),
    lambda s: s["mass"].update(volume_mm3=96000),
    lambda s: s["mass"].update(volume_mm3=float("nan")),
    lambda s: s["geometry"]["holes"][0].update(diameter_mm=6),
    lambda s: s["geometry"]["holes"][0].update(position_mm=[-47, -28, 0]),
    lambda s: s["geometry"]["holes"][0].update(axial_length_mm=9),
    lambda s: s["geometry"]["holes"][0].update(axis=[1, 0, 0]),
    lambda s: s["geometry"]["holes"].pop(),
    lambda s: s["geometry"].update(errors=["unknown"]),
    lambda s: s["geometry"]["envelope_mm"].update(length=119),
    lambda s: s["planes"].pop(),
    lambda s: s["circular_edges"].pop(),
    lambda s: s["circular_edges"][0].__setitem__(4, False),
    lambda s: s["sketch_quality"].update(status="review_required"),
    lambda s: s["features"].update(unknown_feature_health=[{"name": "unknown"}]),
    lambda s: s["features"].update(features=[{"type": "Imported"}]),
    lambda s: s["material"].update(name="6061"),
    lambda s: s["material"].update(database=""),
    lambda s: s["mass"].update(density_kg_m3=1000),
    lambda s: s.update(thickness_mm=9),
])
def test_geometric_or_unknown_evidence_never_passes(mutation):
    """@brief 孔位、孔径、盲孔、约束、未知状态等故障必须被验收拒绝。"""
    snapshot = valid_measurements()
    mutation(snapshot)
    assert validate_snapshot(snapshot, load_case()[1])["status"] == "fail"


def complete_report():
    """@brief 仅用于纯终态函数的输入夹具。"""
    return {"cleanup": {"status": "pass"},
            **{stage: {"validation": {"status": "pass"}} for stage in ("built", "reopened", "step_reopened")},
            "review": {"evaluation": {"status": "pass", "manual_review_required": False}, "previews": [{}, {}, {}, {}]}}


@pytest.mark.parametrize("status,manual", [("pass", True), ("warn", False), ("fail", False), ("unknown", False), ("pass", None)])
def test_review_never_becomes_false_completion(status, manual):
    """@brief 即使建模成功，WARN/FAIL/未知/人工标志也必须阻断。"""
    report = complete_report()
    report["review"]["evaluation"].update(status=status, manual_review_required=manual)
    assert completion_gate(report) == "blocked"


def test_cleanup_and_step_reopen_required():
    """@brief 清理失败、缺少交付重开和预览均不能完成。"""
    report = complete_report()
    assert completion_gate(report) == "completed"
    for field in ("cleanup", "step_reopened"):
        changed = deepcopy(report)
        changed.pop(field)
        assert completion_gate(changed) == "failed"
    report["review"]["previews"].pop()
    assert completion_gate(report) == "blocked"


def test_instant3d_underlying_type_must_be_read():
    """@brief 接受已回读的 Cut 底层类型；未知 ICE 不可直接视为切除。"""
    snapshot = valid_measurements()
    snapshot["features"]["features"] = [{"type": "Extrusion"}, {"type": "ICE", "underlying_type": "Cut"}]
    assert validate_snapshot(snapshot, load_case()[1])["status"] == "pass"
    snapshot["features"]["features"][1].pop("underlying_type")
    assert validate_snapshot(snapshot, load_case()[1])["status"] == "fail"


def test_step_split_faces_require_full_area_and_full_circles():
    """@brief STEP 半圆接缝不得被误判为槽；缺面或缺弧仍不能通过。"""
    snapshot = valid_measurements()
    snapshot["geometry"]["holes"] = []
    snapshot["geometry"]["cylindrical_faces"] = [
        {"diameter_mm": 7, "origin_mm": [x, y, 10], "axis": [0, 0, -1],
         "internal": True, "area_mm2": math.pi * 7 * 10 / 2}
        for x, y in load_case()[1]["hole_centers_mm"] for _ in range(2)]
    snapshot["circular_edges"] = [[*edge[:5], edge[5] / 2] for edge in snapshot["circular_edges"] for _ in range(2)]
    assert validate_snapshot(snapshot, load_case()[1], native=False)["status"] == "pass"
    broken = deepcopy(snapshot)
    broken["geometry"]["cylindrical_faces"].pop()
    assert validate_snapshot(broken, load_case()[1], native=False)["status"] == "fail"
    snapshot["circular_edges"].pop()
    assert validate_snapshot(snapshot, load_case()[1], native=False)["status"] == "fail"
