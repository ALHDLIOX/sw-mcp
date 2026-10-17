"""@brief 原生路径工具的宿主启动、延迟连接和执行结果回归。"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server"))
import server
from scripts import sw_native_wire as native

NATIVE_TOOLS = {
    "solidworks_inspect_native_geometry",
    "solidworks_build_round_sweeps",
    "solidworks_import_step_part",
    "solidworks_replace_component_preserving_transform",
    "solidworks_exclude_reviewed_bodies",
}


def test_server_registers_native_tools_without_com_imports():
    """@brief 禁止 CAD COM 自动化导入时仍可启动；SDK 自身可使用 Windows 基础类型。"""
    code = '''
import importlib.abc, json, sys
class NoCom(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pythoncom', 'win32com', 'comtypes'}:
            raise ImportError('COM import is forbidden during MCP startup: ' + fullname)
sys.meta_path.insert(0, NoCom())
sys.path.insert(0, sys.argv[1])
import server
assert not server._automation_loaded
assert server.pythoncom is None
print(json.dumps(sorted(server.mcp._tool_manager._tools)))
'''
    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "mcp-server")],
        cwd=ROOT, capture_output=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert NATIVE_TOOLS <= set(json.loads(result.stdout))


def test_connection_is_resolved_after_loader_under_host_lock(monkeypatch, tmp_path):
    """@brief 工具注册后仍能取得宿主新加载的连接函数，并且连接发生在锁内。"""
    calls = []
    sw = object()

    def connect(**kwargs):
        assert server._sw_lock._is_owned()
        assert kwargs == {"wait_seconds": 1}
        calls.append("connect")
        return sw, None

    def load():
        calls.append("load")
        monkeypatch.setattr(server, "connect_solidworks", connect, raising=False)

    def inspect(actual_sw, target, action, **values):
        assert actual_sw is sw and action == "inspect"
        calls.append("inspect")
        return {"status": "ok", "bodies": []}

    monkeypatch.delattr(server, "connect_solidworks", raising=False)
    monkeypatch.setattr(server, "_load_automation_modules", load)
    monkeypatch.setattr(server, "pythoncom", None)
    monkeypatch.setattr(server, "_artifact_access", lambda: type("Artifacts", (), {"publish": lambda self, payload: []})())
    monkeypatch.setattr(native, "invoke_native", inspect)
    params = native.Target(expected_document_path=str(tmp_path / "target.sldprt"))
    result = json.loads(server.mcp._tool_manager._tools["solidworks_inspect_native_geometry"].fn(params))
    assert result["status"] == "ok"
    assert calls == ["load", "connect", "inspect"]
