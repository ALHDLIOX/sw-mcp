"""@brief P0-1 真机验收；显式运行，普通 pytest 不启动 CAD，无替代后端。

@details 每轮独占新目录、新 SolidWorks 2026 进程；未知证据与人工复核均阻止完成。
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import gc
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from evals.runner import load_golden_workflows
from scripts.core.execution import execute_with_core
from apps.desktop.cad_workbench.artifact_ledger import write_artifact_ledger, sha256_file

VIEWS = ("isometric", "front", "top", "right")


def write_json(path, payload):
    """@brief 写入本轮目录内的 JSON 证据。"""
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_case():
    """@brief 复用 deterministic runner 的定义加载器，不执行其 mock 场景。"""
    workflows = load_golden_workflows()["workflows"]
    workflow = next(item for item in workflows if item["id"] == "mounting_bracket")
    spec = workflow["real_acceptance_2026"]
    if spec["size_mm"] != [120, 80, 10] or spec["hole_diameter_mm"] != 7:
        raise ValueError("P0-1 定义与指定验收尺寸不一致")
    if sorted(spec["hole_centers_mm"]) != [[-48, -28], [-48, 28], [48, -28], [48, 28]] or spec["material"] != "6061-T6":
        raise ValueError("P0-1 孔位或材料定义不一致")
    return workflow, spec


def expected_volume(spec):
    """@brief 按板体积减去四个圆柱孔计算解析体积，单位 mm³。"""
    x, y, z = spec["size_mm"]
    return x * y * z - len(spec["hole_centers_mm"]) * math.pi * (spec["hole_diameter_mm"] / 2) ** 2 * z


def close_enough(actual, expected, tolerance):
    """@brief 缺失、非有限或超差数据不能通过。"""
    return isinstance(actual, (int, float)) and math.isfinite(actual) and abs(actual - expected) <= tolerance


def validate_snapshot(snapshot, spec, native=True):
    """@brief 独立核对 B-Rep、解析质量与原生特征证据；不依赖创建 API success。"""
    tol = spec["length_tolerance_mm"]
    checks = {"single_solid": snapshot["body_count"] == 1,
              "measurements_error_free": not snapshot["geometry"].get("errors") and not snapshot["mass"].get("errors"),
              "volume": close_enough(snapshot["mass"].get("volume_mm3"), expected_volume(spec), spec["volume_tolerance_mm3"])}
    envelope = snapshot["geometry"].get("envelope_mm") or {}
    checks["dimensions"] = all(close_enough(envelope.get(k), v, tol) for k, v in zip(("length", "width", "height"), spec["size_mm"]))
    # 六个实际平面的法向坐标证明板体边界；GetPartBox 只是额外交叉检查。
    targets = [(0, -60), (0, 60), (1, -40), (1, 40), (2, 0), (2, 10)]
    planes = snapshot["planes"]
    checks["brep_plate_boundaries"] = len(planes) == 6 and all(
        any(p["axis"] == axis and close_enough(p["coordinate_mm"], value, tol) for p in planes) for axis, value in targets)
    holes = snapshot["geometry"].get("holes") or []
    checks["four_holes"] = len(holes) == 4
    matched = set()
    for i, (x, y) in enumerate(spec["hole_centers_mm"]):
        candidates = [(j, h) for j, h in enumerate(holes) if j not in matched
                      and close_enough(h.get("diameter_mm"), 7, tol)
                      and len(h.get("position_mm", [])) == 3
                      and close_enough(h["position_mm"][0], x, tol) and close_enough(h["position_mm"][1], y, tol)
                      and len(h.get("axis", [])) == 3 and close_enough(abs(h["axis"][2]), 1, 1e-6)
                      and close_enough(h.get("axial_length_mm"), 10, tol)]
        checks[f"hole_{i + 1}_diameter_position_axis_depth"] = len(candidates) == 1
        if len(candidates) == 1:
            matched.add(candidates[0][0])
        # 同一孔的两个圆边须分别邻接 z=0 和 z=10 板面，排除盲孔、内部空腔。
        edges = [e for e in snapshot["circular_edges"] if close_enough(e[0], x, tol)
                 and close_enough(e[1], y, tol) and close_enough(e[3], 3.5, tol)]
        checks[f"hole_{i + 1}_through_boundaries"] = len(edges) == 2 and all(
            any(close_enough(e[2], z, tol) and e[4] for e in edges) for z in (0, 10))
    checks["eight_circular_edges"] = len(snapshot["circular_edges"]) == 8
    if native:
        summary = snapshot["features"]
        checks["healthy_features"] = not any(summary.get(k) for k in ("feature_error", "faulty_features", "warning_features", "unknown_feature_health"))
        types = [f["type"] for f in summary["features"]]
        checks["boss_and_cut"] = types.count("Boss") == 1 and types.count("Cut") == 1
        quality = snapshot["sketch_quality"]
        checks["fully_defined_editable_sketches"] = quality.get("status") == "pass" and len(quality.get("sketches", [])) == 2
        checks["material_readback"] = snapshot["material"]["name"] == spec["material"] and bool(snapshot["material"]["database"])
        checks["material_density"] = close_enough(snapshot["mass"].get("density_kg_m3"), 2700, 1)
        checks["thickness_parameter"] = close_enough(snapshot.get("thickness_mm"), 10, tol)
    return {"status": "pass" if all(checks.values()) else "fail", "checks": checks,
            "failed_checks": [k for k, v in checks.items() if not v]}


def completion_gate(report):
    """@brief 完成条件独立于 API 返回；Review 人工标记不能被规则 PASS 抹去。"""
    if report.get("error") or report.get("cleanup", {}).get("status") != "pass":
        return "failed"
    for stage in ("built", "reopened", "step_reopened"):
        if report.get(stage, {}).get("validation", {}).get("status") != "pass":
            return "failed"
    review = report.get("review", {}).get("evaluation", {})
    if review.get("status") != "pass" or review.get("manual_review_required") is not False:
        return "blocked"
    if len(report.get("review", {}).get("previews", [])) != 4:
        return "blocked"
    return "completed"


def snapshot_model(model, boss_name=None):
    """@brief 调用既有测量/草图/特征接口，补采边界拓扑与材料库回读。"""
    import pythoncom
    from win32com.client import VARIANT
    from scripts.sw_connect import get_com_member as member
    from scripts.sw_measure import collect_mass_properties
    from scripts.sw_review import collect_geometry_measurements, collect_model_summary
    from scripts.sw_sketch_quality import inspect_model_sketches
    bodies = list(member(model, "GetBodies2", 0, False) or [])
    planes, edges = [], []
    for body in bodies:
        for face in member(body, "GetFaces"):
            surface = member(face, "GetSurface")
            if member(surface, "IsPlane"):
                p = list(member(surface, "PlaneParams"))
                axis = max(range(3), key=lambda a: abs(p[a]))
                if close_enough(abs(p[axis]), 1, 1e-6):
                    planes.append({"axis": axis, "coordinate_mm": p[axis + 3] * 1000})
        for edge in member(body, "GetEdges"):
            curve = member(edge, "GetCurve")
            if not member(curve, "IsCircle"):
                continue
            p = list(member(curve, "CircleParams"))
            adjacent = list(member(edge, "GetTwoAdjacentFaces2") or [])
            at_plate = False
            for face in adjacent:
                surface = member(face, "GetSurface")
                if member(surface, "IsPlane"):
                    plane = list(member(surface, "PlaneParams"))
                    at_plate |= close_enough(abs(plane[2]), 1, 1e-6) and close_enough(plane[5] * 1000, p[2] * 1000, .01)
            edges.append([p[0] * 1000, p[1] * 1000, p[2] * 1000, p[6] * 1000, at_plate])
    result = {"body_count": len(bodies), "planes": planes, "circular_edges": edges,
              "geometry": collect_geometry_measurements(model), "mass": collect_mass_properties(model)}
    if boss_name is not None:
        database = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
        name = member(model, "GetMaterialPropertyName2", "", database)
        result.update(features=collect_model_summary(model), sketch_quality=inspect_model_sketches(model),
                      material={"name": name, "database": database.value},
                      thickness_mm=float(member(member(model, "Parameter", "D1@" + boss_name), "SystemValue")) * 1000)
    return result


def run_cad(output, report, spec):
    """@brief 仅在进程状态可证明为空时启动真机；清理只依据实际文档所有权。"""
    import pythoncom
    from scripts.sw_connect import (connect_solidworks, get_com_member as member, get_sw_version,
                                    new_document, save_document, open_document, close_owned_solidworks)
    from scripts.sw_part import sketch, sketch_rectangle, sketch_circle, extrude_boss, extrude_cut, clear_sketch_selection_cache
    from scripts.sw_sketch_quality import fully_define_sketch
    from scripts.sw_export import export_to_step
    from scripts.sw_review import run_review
    from scripts.sw_process import solidworks_processes
    prior = solidworks_processes()
    report["processes_before"] = prior
    if prior is None or prior:
        raise RuntimeError("BLOCKED: SolidWorks 进程状态不为空或不可知；保留已有进程及文档")
    sw, model, pid, owned = None, None, None, False
    owned_titles = set()
    pythoncom.CoInitialize()
    try:
        sw, _, connection = connect_solidworks(version=2026, visible=True, wait_seconds=60, return_metadata=True)
        report.update(connection=connection, version=get_sw_version(sw))
        pid = int(member(sw, "GetProcessID"))
        owned = connection["started_by_cad_studio"] is True and pid not in prior
        if not owned or report["version"]["year"] != 2026 or list(member(sw, "GetDocuments") or []):
            raise RuntimeError("BLOCKED: 无法证明新建空白 SolidWorks 2026 实例的所有权")
        model = new_document(sw, "part")
        owned_titles.add(str(member(model, "GetTitle")))
        with sketch(model, "Front Plane") as ref:
            sketch_rectangle(model, 0, 0, spec["size_mm"][0] / 1000, spec["size_mm"][1] / 1000)
            report["base_constraints"] = fully_define_sketch(model)
        boss = extrude_boss(model, ref, .010, direction=False)
        if boss is None:
            raise RuntimeError("母体拉伸失败")
        boss_name = str(member(boss, "Name"))
        with sketch(model, "Front Plane") as ref:
            for x, y in spec["hole_centers_mm"]:
                if sketch_circle(model, x / 1000, y / 1000, spec["hole_diameter_mm"] / 2000) is None:
                    raise RuntimeError("孔草图创建失败")
            report["hole_constraints"] = fully_define_sketch(model)
        if extrude_cut(model, ref, 0, direction=True) is None:
            raise RuntimeError("贯穿孔切除失败")
        # 使用已安装的原厂材料库，禁止把自定义字符串当作实际材料分配。
        install = Path(report["doctor"]["installations"]["solidworks"]["executable"]).parent
        database = install / "lang" / "english" / "sldmaterials" / "solidworks materials.sldmat"
        if not database.is_file():
            raise RuntimeError("BLOCKED: 未找到原厂材料数据库")
        member(model, "SetMaterialPropertyName2", "", str(database), spec["material"])
        report["material_database_sha256"] = sha256_file(database)
        for stage in ("built", "reopened"):
            if not member(model, "ForceRebuild3", False):
                raise RuntimeError(f"{stage} 重建失败")
            evidence = snapshot_model(model, boss_name)
            evidence["validation"] = validate_snapshot(evidence, spec)
            report[stage] = evidence
            write_json(output / f"{stage}.json", evidence)
            if evidence["validation"]["status"] != "pass":
                raise RuntimeError(f"{stage} 几何验收失败: {evidence['validation']['failed_checks']}")
            if stage == "built":
                native = output / "mounting_bracket.SLDPRT"
                if native.exists() or not save_document(model, str(native)) or native.stat().st_size < 1024:
                    raise RuntimeError("原生保存失败或路径已经存在")
                clear_sketch_selection_cache(model)
                sw.CloseDoc(str(member(model, "GetTitle")))
                if list(member(sw, "GetDocuments") or []):
                    raise RuntimeError("关闭后仍有文档，未执行重开")
                model = open_document(sw, str(native), silent=True, raise_on_error=True)
                owned_titles.add(str(member(model, "GetTitle")))
        step = output / "mounting_bracket.step"
        if step.exists() or not export_to_step(model, str(step)) or step.stat().st_size < 1024:
            raise RuntimeError("STEP 导出失败")
        if not step.read_text(encoding="ascii", errors="replace").lstrip().startswith("ISO-10303-21;"):
            raise RuntimeError("STEP 文件头无效")
        report["review"], report["review_path"] = run_review(model, output / "review", basename="mounting_bracket",
                                                            views=VIEWS, expected_outputs=[str(native), str(step)])
        # 在同一个真实 SolidWorks 内重新导入 STEP，检查实际交付几何。
        clear_sketch_selection_cache(model)
        sw.CloseDoc(str(member(model, "GetTitle")))
        model = open_document(sw, str(step), silent=True, raise_on_error=True)
        owned_titles.add(str(member(model, "GetTitle")))
        evidence = snapshot_model(model)
        evidence["validation"] = validate_snapshot(evidence, spec, native=False)
        report["step_reopened"] = evidence
        write_json(output / "step_reopened.json", evidence)
        if evidence["validation"]["status"] != "pass":
            raise RuntimeError(f"STEP 重开几何不符: {evidence['validation']['failed_checks']}")
    finally:
        cleanup = {"status": "failed", "owned_pid": pid, "errors": []}
        report["cleanup"] = cleanup
        try:
            if sw is not None and owned:
                for doc in list(member(sw, "GetDocuments") or []):
                    path = str(member(doc, "GetPathName") or "")
                    title = str(member(doc, "GetTitle"))
                    if (path and Path(path).resolve().is_relative_to(output)) or (not path and title in owned_titles):
                        clear_sketch_selection_cache(doc)
                        sw.CloseDoc(title)
                remaining = list(member(sw, "GetDocuments") or [])
                cleanup["remaining_documents"] = len(remaining)
                if not remaining:
                    cleanup["exit_requested"] = close_owned_solidworks(sw, True, expected_pid=pid)
        except Exception:
            cleanup["errors"].append(traceback.format_exc())
        model = sw = None
        clear_sketch_selection_cache()
        gc.collect()
        pythoncom.CoUninitialize()
        deadline = time.monotonic() + 30
        while pid and time.monotonic() < deadline:
            current = solidworks_processes()
            if current is None or pid not in current:
                break
            time.sleep(.25)
        cleanup["processes_after"] = solidworks_processes()
        if cleanup.get("remaining_documents") == 0 and cleanup.get("exit_requested") and cleanup["processes_after"] == prior and not cleanup["errors"]:
            cleanup["status"] = "pass"


def run_once(output):
    """@brief 保存所有失败、日志、Execution Core、Artifact Ledger 与文件 SHA-256。"""
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workflow, spec = load_case()
    report = {"schema_version": "1.0", "backend": "real-solidworks-2026", "mock": False,
              "status": "failed", "workflow": workflow, "expected_volume_mm3": expected_volume(spec),
              "generated_at": datetime.now(timezone.utc).isoformat(), "output_dir": str(output),
              "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
    with (output / "run.log").open("w", encoding="utf-8", buffering=1) as log, redirect_stdout(log), redirect_stderr(log):
        try:
            for command, name in ((["scripts/sw_preflight.py"], "preflight"), (["scripts/cad_studio.py", "doctor"], "doctor")):
                result = subprocess.run([sys.executable, "-X", "utf8", *command], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
                (output / f"{name}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
                if result.returncode:
                    raise RuntimeError(f"BLOCKED: {name} 失败: {result.returncode}")
                if name == "doctor":
                    report["doctor"] = json.loads(result.stdout)
            run_cad(output, report, spec)
        except Exception:
            report["error"] = traceback.format_exc()
            print(report["error"], flush=True)
        report["status"] = completion_gate(report)
        if "BLOCKED:" in report.get("error", ""):
            report["status"] = "blocked"
        if report["status"] == "blocked":
            report["blocking_reason"] = report.get("error") or report["review"]["evaluation"]
        raw = {"success": report["status"] != "failed", "status": report["status"],
               "manual_review_required": report.get("review", {}).get("evaluation", {}).get("manual_review_required", True)}
        assessment = execute_with_core(handler=lambda _: raw, run_id=output.name, tool_name="real_golden_mounting_bracket_2026",
                                       capability_id="part_and_features", requires_review=True,
                                       reviewer_result={"status": "pass" if report["status"] == "completed" else report["status"],
                                                        "manual_review_required": raw["manual_review_required"]}, trace_dir=output / "trace")
        report["execution_core"] = assessment.to_dict()
        if report["status"] == "completed" and assessment.run_context.status.value != "completed":
            report["status"] = "blocked"
        print(json.dumps({"status": report["status"], "cleanup": report.get("cleanup")}, ensure_ascii=False), flush=True)
    report["ledger_path"] = str(output / "ledgers" / f"{output.name}.ledger.json")
    write_json(output / "report.json", report)
    files = [p for p in output.rglob("*") if p.is_file()]
    ledger = write_artifact_ledger(output, {"id": output.name, "runId": output.name, "executor": "solidworks-com-pywin32",
                                          "status": report["status"], "cwd": str(output)},
                                  {"artifacts": [{"kind": p.suffix.lstrip("."), "path": str(p)} for p in files],
                                   "artifactBaseline": {}, "verification": [report["execution_core"]]})
    files.append(Path(ledger["ledgerPath"]))
    write_json(output / "sha256.json", [{"path": str(p.relative_to(output)), "size_bytes": p.stat().st_size,
                                        "sha256": sha256_file(p)} for p in sorted(files)])
    print(f"{output.name}: {report['status']} — {output / 'report.json'}", flush=True)
    return report


def main():
    """@brief 每轮独立进程生命周期；任一非 completed 均返回非零。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runs", type=int, choices=range(1, 6), default=1)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    reports = [run_once(args.output / f"run-{i:02d}") for i in range(1, args.runs + 1)]
    summary = {"backend": "real-solidworks-2026", "mock": False,
               "status": "completed" if all(r["status"] == "completed" for r in reports) else "blocked" if any(r["status"] == "blocked" for r in reports) else "failed",
               "runs": [{"status": r["status"], "report": str(Path(r["output_dir"]) / "report.json")} for r in reports]}
    write_json(args.output / "summary.json", summary)
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
