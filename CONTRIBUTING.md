# 贡献指南 / Contributing Guide

感谢你对 SolidWorks Automation Skill 项目的关注!

## 治理与维护模式

本仓库采用**单人核心维护 + 开放社区贡献**模式。任何外部开发者都可以通过 Fork + Pull Request 提交代码，由仓库 owner 评估代码质量、测试证据和实际价值后决定是否合并。

- **维护者**：[@wzyn20051216](https://github.com/wzyn20051216)（当前唯一具有写权限的账号）
- **不设置固定的独立审查人**，也不要求 PR 必须获得他人 approve
- **所有合并决策由 owner 一人作出**。本项目不提供独立复核能力，也不对外声称具备该能力
- 外部贡献者不持有写权限，无法直接推送任何受保护分支；一切外部变更只能经 PR 由 owner 合并

**该模式的已知边界**：合并质量依赖 owner 个人判断，不存在第二人交叉验证。这适用于工具型开源项目的社区协作，不适用于需要合规审计或第三方签核的场景。

### 当前治理限制（如实记录，截至 2026-10-27）

- `main` 的 ruleset 当前 `required_approving_review_count = 0`（单人维护模式的既定取值，不因此判定为治理失败）
- owner 仍位于 ruleset `bypass_actors` 中且 `bypass_mode = always`。**这是当前未解除的阻断项**：策略要求 bypass 列表为空，
  代码、文档与测试均按"任何 bypass 都视为不达标"执行
- 远程 CAD 准入的 `bypass_actors` 证据**不来自 CI 实时读取**——GitHub 仅在对该 ruleset 有写权限时才返回该字段，
  只读审计凭据读不到。因此改由**离线采集 + 签名证明**承担，CI 只做只读校验，详见
  [`docs/architecture/governance-attestation.md`](docs/architecture/governance-attestation.md)
- **该证明由维护者自行签发，公钥信任根存放于本仓库**，只提供防篡改留痕，**不构成独立审计、独立审批或双人复核**
- **在上述调整完成并实际验证之前，不得对外声称本仓库具备独立审批能力或强制 CI 门禁**

上述限制的跟踪条目见发布阻断清单 B-02。

### 维护者：规则集变更后必须重新采集证明

任何 ruleset 修改（含清空 `bypass_actors`）都会让 `updated_at` 变化，**旧证明立即失效**，远程 CAD 准入随之阻断。
变更后需在本机执行一次采集并随 PR 提交新证明：

```bash
GH_TOKEN=... node scripts/ci/capture_governance_attestation.cjs
```

私钥仅存于本机 `~/.cad-governance/`，不得入库、不得写入 CI。完整流程与密钥轮换步骤见上述文档。

## 如何贡献

### 报告 Bug

如果你发现了 Bug,请创建一个 Issue 并包含以下信息:

- SolidWorks 版本
- Python 版本
- 操作系统版本
- 详细的错误信息和堆栈跟踪
- 重现步骤

### 提交功能请求

如果你有新功能的想法:

1. 先检查 Issues 中是否已有类似请求
2. 创建新 Issue 描述你的想法
3. 说明使用场景和预期效果

### 提交代码

1. **Fork 仓库**
   ```bash
   git clone https://github.com/yourusername/solidworks-automation-skill.git
   cd solidworks-automation-skill
   ```

2. **创建分支**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **编写代码**
   - 遵循现有代码风格
   - 添加必要的注释(中文)
   - 确保代码在 SolidWorks 2020 及以上版本可运行；当前真机验收基线为 **2026**，CAD 相关改动另见下文「CAD 相关修改的额外要求」

4. **测试**
   - 在 SolidWorks 中测试你的代码
   - 确保没有破坏现有功能

5. **提交**
   ```bash
   git add .
   git commit -m "添加: 你的功能描述"
   ```

6. **推送并创建 PR**
   ```bash
   git push origin feature/your-feature-name
   ```
   然后在 GitHub 上创建 Pull Request

## PR 审查与合并标准

外部 PR 由 owner 审查后决定合并或关闭。以下标准对内部与外部 PR 同等适用。

### 1. 提交前要求

- 分支基于**最新 `main`** 创建，避免"旧分支过 CI"式的假通过
- **一个 PR 只解决一个问题**。功能、修复、重构、格式化不要混在同一个 PR 里
- 不要夹带与 PR 目标无关的格式化或重排改动，这类改动会增加审查成本
- 破坏性变更（修改公开函数签名、改变默认行为、删除能力）必须在标题与描述中显式标注 `BREAKING`

### 2. PR 描述必须包含的六项

| 项 | 要求 |
| --- | --- |
| 问题 / 动机 | 要解决什么问题，复现条件；关联 Issue 编号 |
| 方案概述 | 改了什么、为什么这样改，替代方案为何不选 |
| 影响范围 | 是否触及生产门禁（Review / Verification / Execution Core）、依赖、导出格式、配置文件 |
| 向后兼容性 | 既有调用是否受影响；默认参数下行为是否保持不变 |
| 回滚方式 | 出问题时如何撤回，是否需要数据迁移 |
| 测试证据位置 | 离线测试与真机证据的实际路径 |

缺失上述任一项的 PR，owner 可以直接要求补齐而不进入代码审查。

### 3. 测试证据要求

**离线测试（必需）**

- 提交前本地执行 `python -m pytest -q`，必须全部通过
- 新增或修改功能必须附带测试；仅改文档或注释可豁免，但需在描述中说明
- 故障注入类测试不得删除，也不得为了通过而放宽断言

**真机测试（涉及 CAD 行为时必需）**

- 明确标注 SolidWorks 版本；本仓库当前真机验收基线为 **SolidWorks 2026**
- 明确区分"真实执行"与"合成 / mock"。mock 结果**不计入**真机统计，也不得用于宣称能力已验证
- 证据写入**新的独立目录**，不得覆盖或改写既有输出目录与历史证据

### 4. CI 检查

- PR 必须通过 `test-and-build` 状态检查
- **本地通过不能替代 CI 通过**。两者结论不一致时，以 CI 为准并排查差异
- 注意：当前 owner 具备绕过 CI 的能力（见「当前治理限制」），这是已记录的治理缺口，不代表 CI 检查可被忽视

### 5. 代码审查维度

owner 按以下维度判断是否合并：

1. **正确性**：逻辑是否成立，边界条件（空值、越界、并发、COM 断开）是否处理
2. **兼容性**：是否向后兼容；默认参数下既有行为是否逐位不变
3. **安全边界**：是否放宽了校验、是否可能把失败伪装成成功、是否引入自动审批或跳过审查的路径
4. **可维护性**：是否符合现有代码风格，是否有必要的文档字符串
5. **证据质量**：测试是否覆盖改动点，真机证据是否可复核，数值是否可追溯到原始产物
6. **实际价值**：是否解决真实问题，是否与项目方向一致

### 6. 拒绝或要求修改的条件

满足任一条即**不予合并**：

- 未通过 `test-and-build`，或提交了会破坏 CI 的改动
- 把工具调用成功当作任务完成，或在未验证时声称能力已通过
- 删除、注释掉或放宽既有测试与故障注入以"让测试变绿"
- 放宽生产门禁（`scripts/sw_review.py`、`scripts/core/verification.py`、`scripts/core/execution.py`）
- 引入绕过人工审查、自动审批或可配置跳过检查的路径
- 覆盖、改写或删除历史证据目录
- 一个 PR 混杂多个无关目标，且拒绝拆分
- 描述缺失关键信息，且在提醒后仍未补充

可以合并但需**要求修改**的情形：命名或注释不规范、缺少边界处理、测试覆盖面不足、文档未同步更新。

### 7. CAD 相关修改的额外要求

涉及建模、装配、配合、导出、干涉检测、行程验证的改动，还必须提供：

- **版本与后端**：实际 SolidWorks 版本、后端标识（如 `SldWorks.Application.34`），以及是否为自建独占实例
- **原生几何证据**：以原生 B-Rep / 特征树 / 配合回读为准，**不接受包围盒代替几何结论**
- **干涉与接触**：真实调用干涉检测 API；有意的零体积共边接触与体积穿透必须分开判定，不得把"非零接触条目"一律当作穿透
- **终态与清理**：说明文档保存、关闭、重开后的回读结果，以及是否残留 CAD 进程或文档
- **未验证范围声明**：明确写出本次**没有**验证的内容（例如：自由拖动、连续扫掠、接触动力学、载荷、Motion Study、制造放行）
- **不得外推**：静态工况的通过不能表述为"运动能力已验证"；本机验收不能表述为远程 CI 验收

## 代码规范

### Python 代码风格

- 使用 4 个空格缩进
- 函数和变量使用 snake_case
- 类名使用 PascalCase
- 常量使用 UPPER_CASE
- 中文注释和文档字符串

### 文档规范

- 所有公共函数必须有文档字符串
- 文档字符串使用中文
- 包含参数说明和返回值说明

示例:
```python
def extrude_boss(model, sketch_name, depth, direction=True, merge=True):
    """
    凸台拉伸

    参数:
        model: IModelDoc2
        sketch_name: 草图名称(如 "Sketch1")
        depth: 拉伸深度(米)
        direction: True=正方向
        merge: True=合并结果

    返回:
        IFeature 对象
    """
    # 实现代码...
```

### 提交信息规范

使用中文,格式如下:

- `添加: 新功能描述`
- `修复: Bug 描述`
- `更新: 更新内容描述`
- `文档: 文档更新描述`
- `重构: 重构内容描述`

## 项目结构

```
solidworks-automation-skill/
├── scripts/              # 核心 Python 模块
│   ├── sw_connect.py    # 连接和文档管理
│   ├── sw_part.py       # 零件建模 API
│   ├── sw_assembly.py   # 装配体 API
│   ├── sw_drawing.py    # 工程图 API
│   └── sw_export.py     # 文件导出 API
├── references/          # API 参考文档
├── examples/            # 示例代码
├── README.md            # 项目说明
└── CONTRIBUTING.md      # 本文件
```

## 添加新功能

如果你想添加新的 API 封装:

1. 在对应的 `scripts/sw_*.py` 文件中添加函数
2. 在 `references/` 中更新相关文档
3. 在 `examples/` 中添加使用示例
4. 更新 README.md

## 需要帮助?

- 查看 [references/](./references/) 目录下的文档
- 查看 [examples/](./examples/) 目录下的示例
- 在 Issues 中提问
- 参考 [SolidWorks API 官方文档](https://help.solidworks.com/2024/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks_namespace.html)

## 行为准则

- 尊重所有贡献者
- 保持友好和专业
- 接受建设性的批评
- 关注对项目最有利的事情

感谢你的贡献! 🎉
