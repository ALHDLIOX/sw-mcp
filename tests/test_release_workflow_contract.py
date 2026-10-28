"""@brief 发布工作流的合同测试：锁定合并门禁与 merge queue 依赖的结构性不变量。

这些不变量一旦被无意改掉，后果都是"静默失效"而不是显式报错：
- 缺少 `merge_group` 触发器 → merge queue 条目等不到必需检查，队列超时；
- `test-and-build` 作业被改名或删除 → ruleset 要求的必需检查上下文消失，门禁失效；
- `test-and-build` 不再 `needs` 全部作业 → 某个子作业失败也能拿到绿灯；
- 作业缺少 `timeout-minutes` → 悬挂运行占用额度直到 6 小时默认上限。

因此这里用结构化断言把它们固定下来，而不是靠评审时的记忆。
为避免引入新依赖（仓库未声明 PyYAML），本文件只做缩进感知的行级解析，不做通用 YAML 解析。
"""
from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "windows-release.yml"
JOB_LINE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
REQUIRED_CHECK = "test-and-build"


def _lines() -> list[str]:
    return WORKFLOW.read_text(encoding="utf-8").splitlines()


def _block(lines: list[str], start: int) -> list[str]:
    """@brief 取从 start 开始、到下一个同级或更高层级键之前的所有行。"""
    indent = len(lines[start]) - len(lines[start].lstrip())
    block = [lines[start]]
    for line in lines[start + 1:]:
        if not line.strip():
            block.append(line)
            continue
        current = len(line) - len(line.lstrip())
        if current <= indent and re.match(r"^[^\s#]", line.lstrip()) is None:
            break
        if current <= indent and line.strip() and not line.startswith(" " * (indent + 1)):
            break
        block.append(line)
    return block


def _top_level_block(lines: list[str], key: str) -> list[str]:
    for index, line in enumerate(lines):
        if line.rstrip() == f"{key}:":
            return _block(lines, index)
    raise AssertionError(f"工作流缺少顶层键 {key}:")


def _jobs(lines: list[str]) -> dict[str, list[str]]:
    for index, line in enumerate(lines):
        if line.rstrip() != "jobs:":
            continue
        jobs: dict[str, list[str]] = {}
        for offset in range(index + 1, len(lines)):
            match = JOB_LINE.match(lines[offset])
            if match:
                jobs[match.group(1)] = _block(lines, offset)
            elif lines[offset].strip() and not lines[offset].startswith(" "):
                break
        return jobs
    raise AssertionError("工作流缺少顶层键 jobs:")


def _joined(block: list[str]) -> str:
    return "\n".join(block)


def test_workflow_declares_merge_group_trigger():
    """merge queue 依赖 merge_group 事件；缺失会让队列条目永远等不到必需检查。"""
    block = _joined(_top_level_block(_lines(), "on"))
    assert "merge_group:" in block, "缺少 merge_group 触发器，merge queue 将无法获得必需检查"


def test_required_check_job_exists_with_expected_name():
    """ruleset 要求的上下文是 test-and-build；作业名或键名变化都会让门禁静默失效。"""
    jobs = _jobs(_lines())
    assert REQUIRED_CHECK in jobs, f"缺少作业 {REQUIRED_CHECK}"
    assert f"name: {REQUIRED_CHECK}" in _joined(jobs[REQUIRED_CHECK]), (
        "作业显示名必须与 ruleset 要求的上下文一致"
    )


def test_required_check_job_depends_on_every_other_job():
    """任一子作业失败时，必需检查必须随之失败，而不是拿到独立绿灯。"""
    jobs = _jobs(_lines())
    block = _joined(jobs[REQUIRED_CHECK])
    needs_match = re.search(r"needs:\s*\[([^\]]*)\]", block)
    assert needs_match, "test-and-build 必须以行内列表声明 needs"
    needs = {item.strip() for item in needs_match.group(1).split(",") if item.strip()}
    expected = set(jobs) - {REQUIRED_CHECK}
    assert needs == expected, f"needs 与作业集合不一致：缺少 {expected - needs}，多出 {needs - expected}"


def test_required_check_job_reports_failure_instead_of_being_skipped():
    """上游失败时若本作业被 skipped，会被误读为"未运行"；必须显式判定并报 failure。"""
    block = _joined(_jobs(_lines())[REQUIRED_CHECK])
    assert "if: always()" in block, "必需检查作业必须使用 if: always() 保证始终给出结论"
    for job in ("governance", "python-tests", "frontend-tests", "rust-tests", "package-build"):
        assert f"needs.{job}.result" in block, f"必需检查未读取 {job} 的结论"


def test_every_job_has_timeout():
    """缺少 timeout 会让悬挂运行占满默认 6 小时上限。"""
    jobs = _jobs(_lines())
    missing = [name for name, block in jobs.items() if "timeout-minutes:" not in _joined(block)]
    assert not missing, f"以下作业缺少 timeout-minutes: {missing}"


def test_end_to_end_steps_retry_once_and_keep_first_diagnostics():
    """端到端允许重试 1 次以吸收启动竞态，但必须保留第 1 次诊断，不能掩盖稳定失败。"""
    jobs = _jobs(_lines())
    package = _joined(jobs["package-build"])
    assert "e2e-diagnostics.attempt1" in package, "重试前必须保留第 1 次诊断文件"
    assert "重试 1 次" in package, "重试行为必须在日志中显式说明"
    # 重试后仍失败必须抛错，不允许仅打印警告就通过
    assert "throw" in package, "重试后仍失败必须抛出错误"


def test_package_diagnostics_upload_is_unconditional():
    """失败时恰好最需要现场：诊断上传不能只在成功路径执行。"""
    package = _joined(_jobs(_lines())["package-build"])
    assert "Upload package startup diagnostics" in package
    assert "if: always()" in package


def test_pull_request_runs_cancel_superseded_commits():
    """同一 PR 的旧运行应被取消，避免排队等待已过期提交。"""
    block = _joined(_top_level_block(_lines(), "concurrency"))
    assert "cancel-in-progress:" in block
    assert "pull_request" in block
