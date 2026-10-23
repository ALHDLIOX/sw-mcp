# SolidWorks 2026 真实 Golden Workflow 验收

本验收面向自动化维护者与 QA，验证 P0-1 `mounting_bracket`。规格从
`golden-workflows.yaml` 的 `real_acceptance_2026` 读取：120 × 80 × 10 mm，
4 × Ø7 贯穿孔，孔中心 X=±48、Y=±28 mm，原厂材料库 6061-T6。
解析体积为 94460.619599741 mm³；长度容差 0.01 mm，体积容差 0.05 mm³。

## 构建与运行

使用 Windows、Python 3.12、已授权且完成首次启动的 SolidWorks 2026，
安装项目 `requirements.txt` 与 pytest。真机前先执行离线契约测试与既有
deterministic eval；后者使用夹具，不能证明 CAD 能力。

```powershell
python -m pytest tests/test_solidworks_golden_mounting_bracket_2026.py tests/test_core_execution.py tests/test_eval_runner.py -q
python tests/evals/runner.py --output-dir output/p0-offline-eval
python tests/solidworks_golden_mounting_bracket_2026.py --output output/p0-golden-unique --runs 5
```

输出根目录必须不存在；每轮目录独立且拒绝覆盖。每轮先保存 preflight/doctor
诊断，再检查全机 SolidWorks 进程为空。若用户已有实例或进程状态不可知，
记录 BLOCKED，不修改、关闭或杀死已有实例。不自动切换到 Mock/OCCT。

## 验收证据

复用 `sw_connect`、`sw_part`、`sw_sketch_quality`、`sw_measure`、`sw_review`
和 `sw_export`，不重新实现 COM 连接器。完全定义草图保留驱动尺寸并拒绝 Fix；
重建后从 B-Rep 独立读取一个实体、六个板体平面、四个内部圆柱面及八条圆边。
逐孔验证直径、中心、法向、轴向长度及圆边与两个板面的邻接，排除盲孔。
同时验证解析体积、包络、厚度参数、原生 Boss/Cut 特征与草图健康状态。
从原厂材料库分配精确条目 `6061-T6 (SS)`（matid 164），回读材料名/数据库及
实际质量体积反算密度；不把不存在的 `6061-T6` 条目或自定义属性当作材料分配。
SW2026 Instant3D 返回 `ICE` 时按官方规则用 `GetTypeName` 回读底层 Cut 类型，
保留原始类型，不将未知类型直接解释为切除。

保存 SLDPRT 后关闭、重新打开并重新采集完整证据。STEP 必须非空且具有
ISO-10303-21 文件头，再由真实 SolidWorks 导入，复核实体与几何。
审查复用四视角 BMP 和原有规则；不忽略 WARN/FAIL、未知值或人工复核标志。
通过 Execution Core 记录终态与 trace，通过 Artifact Ledger 记录产物与 hash。
`sha256.json` 覆盖本轮日志、诊断、几何证据、原生件、STEP、预览、Review、
报告、trace 和 ledger（清单自身不自哈希）。失败保留已有产物，不删日志。

每轮清理仅关闭本轮创建的未保存文档或路径处于本轮目录内的文档。
只有已确认拥有 PID 且无剩余文档时才请求 ExitApp；等待退出并比对进程快照。
不使用全局 CloseAll、按进程名终止或清理用户文件。清理不通过不得完成。

## 已知限制

当前通用 `sw_review.evaluate_review_report` 固定返回
`manual_review_required=True`。即使所有几何检查和规则评分通过，终态也只能是
`blocked`，退出码非零。该验收不会取消原审查要求以取得绿灯。
需后续经过审查的自动审查能力才能满足无人复核的五轮 `completed` 标准。

本测试不证明其它尺寸、装配、工程图、复杂孔、材料力学性质或多版本兼容性。
STEP 回读验证交付几何，不要求保留原生草图或材料。COM 若永久挂起，需由操作者
核查进程所有权再处理；本脚本不会猜测所有权并强杀进程。

## CI 边界

复用 `windows-cad-regression.yml`，只有仓库内指定
`test/p0-real-golden-mounting-bracket-2026` 分支的 `workflow_dispatch`
可访问自托管 CAD Runner。没有 PR/pull_request_target 触发，checkout 使用
触发分支；只读令牌、串行运行、不取消前一轮清理。证据由既有 always 上传步骤保留。
本地证据与离线结果应分别列出，禁止用 deterministic 37 场景 PASS 替代五轮真机结果。
