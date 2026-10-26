# P0-2.1：夹爪机械保持、公差及静态全行程验收

本阶段在 P0-2 上新增独立 Golden `parallel_gripper_retention_travel`。原 P0-1、P0-2 用例及其历史证据不改写。
工作分支 `test/p0-real-gripper-retention-travel-2026`，堆叠 Base 为 `e5c242175c0a1d7e0fa4fabc90839f6d9fbc74ac`，
Draft PR 目标为 `test/p0-real-assembly-gripper-2026`。不合并 #39/#42，不修改 main、生产 Review、Verification、
Execution Core 或 GitHub 安全设置。Core 仍只验证终态适配。

## 原结构审计及最小机械改动

P0-2 有双导杆同心配合和两个独立 Z 平移，但 Ø8 导杆、Ø8.1 滑块孔、Ø8.02 支撑孔仅为名义几何，
没有公差带；支撑/底座和手指/滑块仅有 Mate，未建紧固接口；无限行程会越出导杆。

P0-2.1 保留双导杆、两滑块、独立手指、两端支撑的拓扑，新增以下功能实体和接口：

| 部件 | 原生数量 | 改动及功能（mm） |
| --- | --- | --- |
| 底座 | 1 | 60×12×116，Y=-38..-26、Z=-58..58；集成 52×36×8 中央挡块，Y=-26..10、Z=-4..4 |
| 支撑 | 2 | 60×46×12，Y=-38..8；Z=-70..-58 与 58..70，内端面同时为外侧行程止挡 |
| 导杆 | 2 | 建模直径 7.9905，长度 139.8，Z=-69.9..69.9；两根轴 X=±18、Y=0 |
| 滑块 | 2 | 52×20×18；保留双导向孔，补两个沿 Y 的 Ø3.2 连接孔 |
| 手指 | 2 | 12×30×18，Y=10..40；补与对应滑块同轴的两个连接孔 |
| 端部挡板 | 2 | 60×46×4；Z=-74..-70 与 70..74，封住导杆轴向出口 |
| 拉铆杆 | 2 | Ø4×148 杆段，Z=-74..74；两端 Ø8×3 成形头，贯穿端板/支撑/底座的真实接口 |
| 手指铆钉 | 4 | Ø3×50 杆段，Y=-10..40；两端 Ø5.5×3 成形头；同侧头部净距 0.5，每个手指用两根不同轴铆钉保持 |

共八种原生 SLDPRT、十七个实例。铆钉是装配后成形状态的真实双头实体，配有贯穿孔和头部贴合面，
不是螺栓、装饰性几何或已认证标准件。装配顺序需先穿入杆/铆钉再成形末端；成形工艺、可达性、夹紧预载、
头部尺寸和强度必须由工程师审核。本阶段不证明铆接工艺或承载能力，不宣称可直接制造。

导杆与挡板名义轴向间隙各 0.1，总轴向浮动 0.2；止挡面使整个滑块在端点仍位于导杆有效长度内。
轴向叠加公差尚未放行，因此 0.2 是设计间隙，不是制造后保证值。

## 孔与定位明细

下表全部为原生切除，不以标记点代替。位置来自统一 Golden 规格，不允许运行配置更改。

| 零件 / 接口 | 数量 | 轴向、规格及定位基准 |
| --- | --- | --- |
| 底座集成挡块 / 导向 | 2 | 沿 Z，建模 Ø8.0075；X=±18、Y=0，贯穿挡块 8；底座局部 Z=54..62 |
| 支撑 / 导杆 | 每件 2 | 沿 Z，建模 Ø8.0075；X=±18、Y=0，贯穿 12 |
| 滑块 / 导杆 | 每件 2 | 沿 Z，建模 Ø8.0075；X=±18、Y=0，贯穿 18 |
| 底座、支撑、端板 / 拉铆杆 | 每件 2 | 沿 Z，Ø4.1；X=±22、Y=-32，分别贯穿 116 / 12 / 4 |
| 底座 / 外部安装 | 4 | 沿 Y，Ø4.5；X=±12、世界 Z=±40（底座局部 Z=18/98），贯穿底座 12 |
| 滑块及手指 / 铆钉 | 每件 2 | 沿 Y，Ø3.2；X=±3、零件局部 Z=9，贯穿滑块 20 / 手指 30 |

除导向孔/轴配合外，上述安装孔及铆钉尺寸公差为**工程提案、待确认**。外部安装配对设备及其紧固件未建模，
不能宣称已完成整机安装。铆杆穿过底座与支撑的功能连接、双头保持与手指铆钉接触均需原生几何回读。

## 公差依据及适用边界

建议基本尺寸 Ø8 H7/g6。原厂资料：

- [MISUMI 线性轴 g6 推荐表](https://sg.misumi-ec.com/pdf/fa/2013/p226.pdf)：Ø8/10 的 g6 为 -0.005/-0.014 mm。
- [MISUMI H7 轴配件原厂表](https://jp.misumi-ec.com/vona2/detail/110300223240/?HissuCode=ADKR8-10)：Ø8 H7 为 0/+0.015 mm。
- [MISUMI 配合技术资料](https://pt.misumi-ec.com/pdf/fa/2014/P1_2287-2288_F80_EN.pdf)：孔轴公差带与配合分类。

由此得到轴 7.986..7.995、孔 8.000..8.015，直径间隙最小 0.005、最大 0.029 mm。CAD 采用公差带中值
7.9905 / 8.0075，名义建模直径间隙 0.017 mm，便于把间隙与有意端面接触分开；不把中值写成基本标称尺寸。
实际配合尺寸仍需图纸与检测。没有在本阶段声称满足完整 ISO/GB 制造标准。

双导杆孔位置度、平行度、同轴度、粗糙度、润滑/磨损/热膨胀及轴向叠加公差仍待确认；单独的 H7/g6
不能证明双导杆不会卡滞。导杆及铆件的库材料提案为 AISI 1020，其余为
6061-T6 (SS)；这些是 CAD 属性，不是热处理、硬度、材料证书或铆接性能认证。

## 行程与真实计算契约

- 左滑块原点 Z 最小/中间/最大为 -58/-40/-22；右滑块为 4/22/40；每侧独立行程 36。
- 最外侧端点贴合支撑内端面；最内侧端点贴合底座集成中央挡块。没有把必要接触删除或人为留缝以获得零干涉。
- 48 个原生 Mate（含两条真实距离上下限）；读取限位 FeatureData 的 IsAdvancedMate、MinimumDistance、MaximumDistance。
- 对两组三位置执行 3×3 共九工况；每次通过 SetTransformAndSolve2 发送真实编组并回读，重建并检查全部组件、Mate、引用与限位。
- 每工况用 InterferenceDetectionManager.GetInterferences 实际计算一次体积干涉，再以 TreatCoincidenceAsInterference=True
  单独计算有意接触，读取后才 Done。缺失、未知、接口异常或未计算均失败；不使用包围盒作为碰撞结论。
- 静态连接头部接触和端点止挡接触均必须真实检出；体积穿透单独判定，不把所有非零“接触条目”误作穿透。
- 另执行四次实际越界请求、抑制限位 Mate、制造滑块与中央挡块真实穿透，必须检出并恢复。正常文件只在恢复后保存。
- 保存关闭原生装配和引用后重开，回读十七个实例的身份/位置、Mate/上下限/引用、BOM；STEP 在 SW 中重新导入逐体验证。

九静态组合覆盖用户规定的端点和中位组合；不等于连续扫掠碰撞求解或 Motion Study，不宣称同步运动。
无电机、丝杠、同步带、动力传递或载荷结论。

## 运行与双状态

在当前仓库根目录执行，输出目录必须不存在：

```powershell
$env:PYTHONUTF8 = '1'
python -m pytest -q -rs
python tests/evals/runner.py --output-dir output/p0-2-1-eval-unique
node --test tests/test_cad_ci_guard.cjs
python tests/solidworks_golden_workflow.py --case parallel_gripper_retention_travel --output output/p0-2-1-real-unique --runs 5 --expected-terminal blocked --runtime-config output/runtime.json
```

受控 runtime.json 只允许现有模板、材料库路径和有界超时。执行前环境诊断、已有进程拒绝、每轮独立目录/UUID trace、
Session 所有权、PID 与创建时间核验、清理失败即停止后续实例、全文件 SHA-256、Artifact Ledger 和 Core trace 均沿用 P0-2。
仅所有规则通过且唯一阻塞是原始 Review 的人工复核时 acceptance_status=passed、task_status=blocked、
manual_review_required=true。默认 completed 模式仍严格失败。远程 CAD CI 继承前置安全配置 BLOCKED，本阶段不更改或宣称验证。

## API 核查

- [FeatureExtrusion3 的起点偏移](https://help.solidworks.com/2024/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.ifeaturemanager~featureextrusion3.html)：
  T0/StartOffset/FlipStartOffset；本机 SW2026 原厂枚举 swStartOffset=3。
- [FeatureCut4 的双向切除](https://help.solidworks.com/2024/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.ifeaturemanager~featurecut4.html)：
  Sd=False、两方向各用原生 ThroughAll，避免定深孔冒充贯穿。
- [距离 Mate FeatureData](https://help.solidworks.com/2025/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDistanceMateFeatureData_members.html)：
  IsAdvancedMate、MinimumDistance、MaximumDistance 原始回读。
- [原生有意接触开关](https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IInterferenceDetectionMgr~TreatCoincidenceAsInterference.html)：
  开关仅当前管理器有效，每次明确设置，不假设保存后继承。

## 实际执行记录

本节在真实执行后记录结果；上述为验收合同，不是已通过声明。所有失败保留，离线合成与真机统计分开。

1. 首次真机套件 `p0-2-1-real-five-01/run-01`（源码 4aeccde、PID 41276）在导杆材料处失败，退出 1，未启动后续轮次。
   底座和支撑保存重开通过；导杆几何通过但材料为空、密度 1000。全部日志/快照与已生成 CAD 保留，清理通过。
   该轮导杆验证失败发生在保存前，因此没有伪称存在失败导杆原生文件；后续增加失败原生副本保留。
2. 独立真实材料 API 诊断不计 Golden 轮次。1045、1100-O 及 Alloy Steel 名称的应用未成功，可能保留先前材料；
   6061-T6 和 AISI 1020 正确回读。只凭 XML 中有名称不能算材料应用成功。改用可回读 AISI 1020，并按库值检查
   7900 kg/m³；铝件为 2700 kg/m³。材料适用性仍为工程提案，不能把该替代宣称为已认证等效材料。
3. 实施复核同时将同侧铆钉头径由 6 改为 5.5，避免名义相切；头部尺寸及成形工具可达性仍需人工审核。
