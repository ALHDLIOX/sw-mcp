# 治理规则集证明：离线采集、签名与只读校验

本文说明 `main` 分支 ruleset 的 `bypass_actors` 如何在**CI 不具备写权限**的前提下被证明为空，
以及该证明的信任边界、生成流程、密钥轮换与失效规则。

## 1. 为什么需要离线证明

GitHub 的规则集详情端点只需要 `Metadata: read` 即可访问，但 `bypass_actors` 被单独门控：

> **Note:** To prevent leaking sensitive information, the `bypass_actors` property is only returned
> if the user making the API request has **write access** to the ruleset.
> —— GitHub REST API, "Get a repository ruleset"

实测（2026-10-27，本仓库为 public，可用匿名请求精确模拟"无写权限调用者"）：

| 字段 | 管理员授权 | 无写权限（匿名等价） |
| --- | --- | --- |
| `bypass_actors` | 可见 | **字段整体缺失**（不是 `null`） |
| `current_user_can_bypass` | `"always"` | **同样缺失** |
| `updated_at` | 可见 | **可见** |

后果：只读审计凭据既读不到 `bypass_actors`，也无法用 `current_user_can_bypass` 兜底。
若把"字段缺失"当成"没有绕过者"，就是**假通过**；若按未知阻断，则规则集合规时也永远无法准入。

三条路径的取舍：

| 方案 | CI 侧最高权限 | 单人可运行 | 结论 |
| --- | --- | --- | --- |
| A 写权限凭据进 CI | `Administration: write`（附带仓库设置、协作者、Webhook 权限） | 是 | 否决：等于仓库治理接管 |
| B 独立审计工作流 | 同上 | 否（Environment `prevent_self_review` 需第二人审批） | 暂不采用 |
| **C 离线采集 + 签名证明** | 全部 `read` | 是 | **采用** |

## 2. 信任边界（必须如实披露）

- 证明由**维护者本人**用本机管理员授权采集并签发，不是第三方审计结论
- 验签公钥（信任根）存放在**本仓库内**，因此能合并到 `main` 的人可以同时替换公钥与证明
- 该机制提供的是**防篡改留痕**与**配置漂移检测**，不是**独立可信根**
- 任何文档、发布说明或验收报告**不得**据此声称具备独立审批、独立审计或双人复核能力

代码与报告中对应字段：`governance.independent_audit = false`、`governance.bypass_proof = "offline_signed_attestation"`、
`remaining_risks` 恒含 `attestation_self_issued_by_maintainer` 与 `trust_root_stored_in_repository`。

## 3. 生成流程（维护者本机）

```bash
# 一次性：生成签名密钥对。私钥留在本机，公钥由 governance_trust_root.cjs 固定
node -e "const c=require('node:crypto'),f=require('node:fs'),h=require('node:os').homedir()+'/.cad-governance/';f.mkdirSync(h,{recursive:true});const{publicKey,privateKey}=c.generateKeyPairSync('ed25519');f.writeFileSync(h+'ed25519-private.pem',privateKey.export({type:'pkcs8',format:'pem'}),{mode:0o600});f.writeFileSync(h+'ed25519-public.pem',publicKey.export({type:'spki',format:'pem'}))"

# 每次规则集变更后：采集并签名（凭据仅用于读取，不出现在任何输出中）
GH_TOKEN=... node scripts/ci/capture_governance_attestation.cjs

# 只打印不入库
GH_TOKEN=... node scripts/ci/capture_governance_attestation.cjs --print-only
```

默认输出：`docs/architecture/evidence/governance-ruleset-attestation.json`
默认有效期：30 天（上限 `MAX_TTL_DAYS = 30`，超出视为无效）

采集工具的硬约束：

- 仓库 ID 与全名必须与固定值一致，否则拒绝生成
- **读不到 `bypass_actors` 时拒绝生成**——那种情况下任何"为空"的结论都是伪造断言
- 私钥只从 `~/.cad-governance/` 或 `GOVERNANCE_SIGNING_KEY` 读取，绝不写入证明、日志或仓库

## 4. 证明结构

```jsonc
{
  "schema": "cad-governance-attestation/v1",
  "repository": { "id": "1184045765", "full_name": "wzyn20051216/solidworks-automation-skill" },
  "ruleset": {
    "id": 25631760, "name": "protect-main", "target": "branch", "enforcement": "active",
    "ref_name_include": ["refs/heads/main"], "ref_name_exclude": [],
    "updated_at": "…", "created_at": "…",
    "rules": [ … ],            // 完整规则，逐条参与摘要
    "bypass_actors": [ … ]     // 必须为空数组
  },
  "config_digest_sha256": "…", // 对 id/name/target/enforcement/ref_name/rules 的规范化摘要
  "governance": { "mode": "single_maintainer", "independent_audit": false,
                  "bypass_requirement": "empty", "trust_boundary": "…" },
  "captured_at": "…", "expires_at": "…",
  "generator": { "tool": "…", "node": "v22.x" },
  "signer": { "key_id": "ed25519:<spki-sha256>", "key_type": "ed25519", "signed_at": "…" },
  "signature": "<base64 ed25519>"
}
```

**摘要刻意不含 `bypass_actors`**：只读凭据读不到该字段，若纳入摘要则永远无法与线上比对。
"bypass 为空"由签名证明独立承担；"配置是否变化"由 `updated_at` 与摘要共同覆盖。

签名覆盖除 `signature` 外的全部字段，使用稳定序列化（键排序、丢弃 `undefined`）。

## 5. CI 只读校验项

`scripts/ci/cad_ci_guard.cjs` 在原有准入条件之上新增/替换以下检查，任何一项不满足即 `blocked`：

| 检查键 | 含义 |
| --- | --- |
| `protected_ref_is_main` | 所选 ref 必须是 `refs/heads/main`（`ref_protected` 不保证这一点） |
| `trust_root_intact` | 轮换日志引用的每个 key 都必须仍在册 |
| `attestation_present` | 证明文件存在且可解析 |
| `attestation_schema` | schema 版本受支持 |
| `attestation_declaration` | 必须如实声明单人维护 + 非独立审计 + 有信任边界说明 |
| `attestation_signature` | 用**固定信任根**验签通过，key 未吊销且在有效期内 |
| `attestation_repository` | 仓库 id 与全名匹配 |
| `attestation_ruleset_identity` | ruleset id/name/target/enforcement 匹配且线上为 active |
| `attestation_main_scope` | 证明侧与线上侧的 `ref_name` 都必须是仅 `refs/heads/main`、无 exclude |
| `attestation_fresh` | 未过期、未超长 TTL、未出现未来时间（容忍 5 分钟偏移） |
| `attestation_digest` | 摘要自洽且与线上配置一致 |
| `attestation_updated_at` | 证明记录的 `updated_at` 与线上一致 |
| `no_bypass_actors` | 证明中的 `bypass_actors` 必须存在且为空数组 |
| `live_bypass_consistent` | 纵深检查：若凭据本就能看见 bypass，则线上必须为空 |

失败原因汇总在报告的 `attestation_reasons` 字段，便于定位。

## 6. 失效规则

| 触发 | 结果 |
| --- | --- |
| 修改 ruleset 任一配置 | `updated_at` 变化 → `attestation_updated_at_mismatch` |
| 修改 rules/ruleset 名称/范围 | 摘要变化 → `attestation_digest_mismatch` |
| 证明超过 30 天或超长 TTL | `attestation_expired_or_invalid_window` |
| 证明缺失 / JSON 损坏 | `attestation_present = false`，其余证明项同时不成立 |
| 证明被手改而未重签 | `attestation_signature_invalid` |

**任何配置变更都必须导致旧证明失效**——这是设计目标，不是缺陷。变更后重新采集即可。

## 7. 密钥固定与轮换

信任根定义在 `scripts/ci/governance_trust_root.cjs`：

- `KEYS`：key_id → 公钥 PEM + `not_before` + `revoked_at`
- `ROTATION_LOG`：只追加的 key_id 列表

轮换步骤：

1. 本机生成新密钥对，私钥留在本机
2. 在 `KEYS` 中**新增**条目（不得删除旧条目），并把新 key_id **追加**到 `ROTATION_LOG`
3. 需要废止旧 key 时，仅设置其 `revoked_at`，条目本身保留
4. 用新私钥重新采集证明并随 PR 提交

安全性质：`KEYS` 中仍被 `ROTATION_LOG` 引用的条目若被删除，`trust_root_intact` 失败 → 全员阻断。
因此**静默移除信任根会立刻暴露**，轮换必须表现为一次可见的代码变更。

## 8. 自检

```bash
# 策略与证明的故障注入（含签名、过期、绑定、轮换、采集工具）
node --test tests/test_cad_ci_guard.cjs

# 仅验证离线证明与线上配置是否仍然一致（不启动 CI、不启动 CAD）
node scripts/ci/capture_governance_attestation.cjs --print-only > /dev/null   # 凭据不足会直接报错
```

## 9. 未解决与未验证

- **当前真实配置仍不达标**：`bypass_actors` 含 owner（`always`），证明会如实记录，CI 判定 `blocked`。策略要求为空，清空动作尚未执行
- `updated_at` 是否在**任何**配置变更时都会更新：依据 GitHub 语义推断，尚未在真实变更中实测
- 匿名请求下 `bypass_actors` 缺失已实测；持认证的只读令牌是否完全相同，因仓库暂无该令牌而未直接实测
- 本机制不提供独立审计能力，属**永久披露**项，不随配置改善而消除
