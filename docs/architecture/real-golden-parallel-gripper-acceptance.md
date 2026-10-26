# P0-2：双指平行夹爪原生装配 Golden

本用例只验证结构、原生装配与交付一致性。没有电机、丝杠、同步带、联动驱动、载荷能力或制造放行结论。
P0-1.2 的安装板验收范围、生产 Review 和 Execution Core 安全门禁均不扩大。

## 分支与执行边界

- 工作分支：`test/p0-real-assembly-gripper-2026`。
- 堆叠 Base：`818087a366efdd830d85b37d0705dd2d873464eb`，来自最新 P0-1.2 开发分支。
- Draft PR 目标为 `test/p0-real-golden-mounting-bracket-2026`；不合并 #39，不修改 main 或 GitHub 设置。
- COM 写操作串行；原始工程 DAG 保存在每轮 engineering_plan.json，排除 Motion、制造工程图和驱动传递。
- Core 仅执行 CAD 和安全清理后的终态适配，`core_scope=terminal_adaptation_only`。

## 统一规格（mm）

规格唯一来源为 golden-workflows.yaml 的 parallel_gripper_assembly，不接受运行时改变尺寸、容差、版本或审批要求。

| 零件文件 | 数量 | 原生几何与定位 |
| --- | --- | --- |
| base.SLDPRT | 1 | 60×12×140；局部截面中心 (0,-32)，底面 z=0；实例原点 z=-70 |
| rod.SLDPRT | 2 | Ø8×140 圆柱，轴线沿 Z；实例 X=-18/+18、Y=0、Z=-70 |
| support.SLDPRT | 2 | 60×34×12，截面中心 (0,-9)；两个 Ø8.02 贯穿孔，X=-18/+18、Y=0；实例 Z=-70/+58 |
| slider.SLDPRT | 2 | 52×20×18，截面中心 (0,0)；两个 Ø8.1 贯穿孔，X=-18/+18、Y=0；实例 Z=-43/+25 |
| finger.SLDPRT | 2 | 12×30×18，截面中心 (0,25)；分别随对应滑块，原点 Z=-43/+25 |

五种零件均为参数化凸台；支撑与滑块另有孔草图和贯穿切除。草图完全定义、可编辑深度参数、材料库条目
6061-T6 (SS)、密度及 B-Rep 回读均参与验收。这里的材料和间隙只是结构 Golden 名义参数，
不替代材料认证、导杆硬度/耐磨要求、轴承选型、公差链或紧固件设计。

两导杆中心距 36；初始夹持间距沿 Z 为 50。支撑底面与底座 y=-26 贴合，手指与滑块在 y=10 接合。
可制造性仍需补充安装/夹紧紧固件、行程限位、轴向保持、润滑、驱动和载荷设计。

## 原生配合与自由度

底座固定，其它组件不使用 Fixed 属性代替 Mate：

- 两个支撑各 3 个基准面 Mate；右端轴向距离为 128，其余对应基准重合。
- 两根导杆各 1 个锁旋转的同心 Mate（对应左支撑孔）及 1 个轴向基准重合 Mate。
- 两个滑块各 1 个锁旋转同心 Mate，保留沿 Z 的轴向移动；第二导杆穿过第二孔，真实 B-Rep 检查其位置和间隙。
- 每个手指与对应滑块建立 3 个基准面重合 Mate。

共 18 个真实 Mate。初始变换只用于插入定位；验收回读 MateGroup、Mate2 类型、抑制/健康、MateEntity2
关联组件 ID 和实体参数，并回读组件变换、固定状态、约束状态和实例唯一 ID。

GetConstrainedStatus 只能证明整体约束状态，不能单独证明自由度数。额外回读 SW2026 原厂 SDK 中
IComponent2.GetRemainingDOFs 的原始计数、旋转/平移状态和向量：目标为每组滑块/手指仅有一条 Z 平移，
静态件无自由度。再用 SetTransformAndSolve2 各自正负移动 2 mm，检查对应手指跟随、其它组不动、恢复准确。
测试运动不会退回直接 Transform2 赋值；无法读取或证明时验收失败，不以视觉代替证明。

GetRemainingDOFs 网页说明不完整，本阶段只使用本机 2026 SDK 交叉验证，不能宣称其它版本支持。
12 个 out 参数及枚举在原厂 sldworks.tlb / Interop 中核对，原始签名另存离线证据。

## 装配、干涉与交付验收

每轮创建新目录和新实例，先拒绝已有或状态未知的 SolidWorks 进程。逐件保存、关闭重开，之后创建装配，
保存并关闭装配及本轮加载的引用，再从磁盘重开 SLDASM。检查所有引用位于本轮 parts 目录且哈希一致。

干涉复用 sw_measure.inspect_interference：通过 InterferenceDetectionManager.GetInterferences 实际计算，
读取数量、体积与组件；Done 仅在读取后释放。关闭重合面干涉，但不忽略隐藏体；不以包围盒代替原生干涉。
每轮还在自有装配中制造真实滑块/手指穿透和抑制滑块 Mate，必须检出，恢复后再保存正常交付。

STEP 在真实 SolidWorks 中重新导入，逐体匹配九个实体的体积、世界质心、圆柱面孔径/轴线和面积，
处理导入后拆分的圆柱接缝。BOM CSV 复用 sw_delivery，并与实际组件引用、数量和磁盘内容交叉检查。
原始 Review 使用 sw_review，不修改其人工复核标记。装配体不支持的零件孔测量字段不能宣称已由通用
Review 完成，而由本用例的独立零件与装配 B-Rep 规则承担。

完整产物哈希、Artifact Ledger、原始 Review、快照和唯一 Core trace 在套件结束时再次回读。
只有全部通过且唯一阻塞为人工复核时才允许 acceptance_status=passed / task_status=blocked /
manual_review_required=true。默认 completed 模式仍严格返回非零。

## 运行命令

在仓库根目录执行，输出目录必须不存在：

```powershell
$env:PYTHONUTF8 = '1'
python -m pytest -q -rs
python tests/evals/runner.py --output-dir output/p0-2-eval-unique
python tests/solidworks_golden_workflow.py --case parallel_gripper_assembly --output output/p0-2-real-unique --runs 5 --expected-terminal blocked
```

--runtime-config 沿用模板/材料库/有界超时，另允许本用例专用 assembly_template（.asmdot）；相对路径相对
配置文件解析。缺省模板复用原有发现。安装板不接受 assembly_template，不能以配置扩大其能力范围。

离线故障注入是合成数据；不得计入真机结果。开发失败、未知证据及异常清理均保留。远程 CAD CI 的
P0-1.2 安全配置阻塞保持原状，本阶段没有变更 Runner、Environment、权限或工作流触发机制。

## API 核查依据

- [AddMate5 参数](https://help.solidworks.com/2025/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IAssemblyDoc~AddMate5.html)
- [组件约束状态](https://help.solidworks.com/2022/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IComponent2~GetConstrainedStatus.html)
- [自由度状态枚举](https://help.solidworks.com/2026/English/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDofStatus_e.html)
- [原生干涉计算](https://help.solidworks.com/2026/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IInterferenceDetectionMgr~GetInterferences.html)
- [Body2 质量属性及世界坐标转换](https://help.solidworks.com/2024/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.ibody2~getmassproperties.html)

实际运行结果与失败记录在执行后补入证据索引和本节；本节以上是验收契约，不是已通过声明。
