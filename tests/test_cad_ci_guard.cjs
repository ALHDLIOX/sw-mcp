/** @file CI 授权策略与离线证明的故障注入；只使用合成快照与临时密钥，不启动 Runner。 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const lib = require('../scripts/ci/governance_attestation.cjs');
const captureTool = require('../scripts/ci/capture_governance_attestation.cjs');
const { evaluatePolicy, readSnapshot, readAttestation, TRUSTED_REPOSITORY, TRUSTED_REPOSITORY_ID } = require('../scripts/ci/cad_ci_guard.cjs');

const NOW = new Date('2026-10-27T06:00:00.000Z');
const UPDATED_AT = '2026-10-22T10:42:30.335Z';
const DAY_MS = 24 * 60 * 60 * 1000;
const RULESET_ID = 25631760;

/** @brief 每个测试文件用一次性密钥，避免测试依赖仓库内生产公钥。 */
function newKey() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519');
  return { privatePem: privateKey.export({ type: 'pkcs8', format: 'pem' }), publicPem: publicKey.export({ type: 'spki', format: 'pem' }) };
}
const KEY = newKey();
const KEY_ID = lib.keyIdOf(KEY.publicPem);
function trustRoot(entry = {}) {
  return { keys: { [KEY_ID]: { pem: KEY.publicPem, not_before: '2026-01-01T00:00:00Z', revoked_at: null, ...entry } }, log: [KEY_ID] };
}

/** @brief 线上规则集详情形态（管理员视角，含可见的 bypass）。 */
function liveRuleset() {
  return {
    id: RULESET_ID, name: 'protect-main', target: 'branch', enforcement: 'active',
    conditions: { ref_name: { include: ['refs/heads/main'], exclude: [] } },
    updated_at: UPDATED_AT, created_at: '2026-10-22T10:39:08.016Z',
    rules: [
      { type: 'deletion' },
      { type: 'non_fast_forward' },
      { type: 'pull_request', parameters: { required_approving_review_count: 0, dismiss_stale_reviews_on_push: true, required_reviewers: [] } },
      { type: 'required_status_checks', parameters: { strict_required_status_checks_policy: false, required_status_checks: [{ context: 'test-and-build', integration_id: 15368 }] } },
    ],
    bypass_actors: [],
  };
}

/** @brief 构造并签名证明；digest 在签名前按最终内容计算。 */
function attestationFor(live = liveRuleset(), options = {}) {
  const { now = NOW, ttlDays = 30, key = KEY, rulesetOverrides = {}, overrides = {}, omitBypass = false } = options;
  const ruleset = {
    id: live.id, name: live.name, target: live.target, enforcement: live.enforcement,
    ref_name_include: [...(live.conditions?.ref_name?.include || [])],
    ref_name_exclude: [...(live.conditions?.ref_name?.exclude || [])],
    updated_at: live.updated_at, created_at: live.created_at,
    rules: structuredClone(live.rules), bypass_actors: [],
  };
  if (omitBypass) delete ruleset.bypass_actors;
  Object.assign(ruleset, rulesetOverrides);
  const unsigned = {
    schema: lib.SCHEMA,
    repository: { id: TRUSTED_REPOSITORY_ID, full_name: TRUSTED_REPOSITORY },
    ruleset,
    governance: { mode: 'single_maintainer', independent_audit: false, bypass_requirement: 'empty',
      trust_boundary: '维护者自签；信任根在仓库内，不构成独立审计' },
    captured_at: now.toISOString(), expires_at: new Date(now.getTime() + ttlDays * DAY_MS).toISOString(),
    signer: { key_id: lib.keyIdOf(key.publicPem), key_type: 'ed25519', signed_at: now.toISOString() },
    ...overrides,
  };
  unsigned.config_digest_sha256 = lib.configDigest(unsigned.ruleset);
  return { ...unsigned, signature: lib.signAttestation(unsigned, key.privatePem) };
}

/** @brief 修改内容后重新签名，用于把故障隔离到单一语义检查而非签名本身。 */
function resign(attestation, key = KEY) {
  const { signature, ...unsigned } = attestation;
  return { ...unsigned, signature: lib.signAttestation(unsigned, key.privatePem) };
}

/** @brief 单人维护模式下的合规输入：只看得到读权限字段，bypass 由证明承担。 */
function valid(options = {}) {
  const live = options.live || liveRuleset();
  return {
    context: { repository: TRUSTED_REPOSITORY, repository_id: TRUSTED_REPOSITORY_ID, event_name: 'workflow_dispatch', ref_type: 'branch',
      ref: 'refs/heads/main', ref_protected: true, sha: 'a'.repeat(40), actor: 'owner', triggering_actor: 'owner-2' },
    branch: { protected: true, commit: { sha: 'a'.repeat(40) } },
    rules: structuredClone(live.rules),
    rulesets: [live],
    permissions: { owner: 'admin', 'owner-2': 'maintain' },
    environment: { id: 1, name: 'cad-validation', protection_rules: [],
      deployment_branch_policy: { protected_branches: true, custom_branch_policies: false } },
    runners: [{ status: 'online', busy: false, labels: ['self-hosted', 'Windows', 'CAD'].map(name => ({ name })) }],
    attestation: options.attestation === undefined ? attestationFor(live) : options.attestation,
    trustRoot: options.trustRoot || trustRoot(),
    now: options.now || NOW,
  };
}

/** @brief 只读凭据视角：线上响应里没有 bypass_actors 字段。 */
function readOnlyView() {
  const snapshot = valid();
  delete snapshot.rulesets[0].bypass_actors;
  return snapshot;
}

// ---------------------------------------------------------------- 基本准入

test('只读凭据读不到 bypass 时，配置合规且证明有效即可准入', () => {
  const snapshot = readOnlyView();
  assert.equal('bypass_actors' in snapshot.rulesets[0], false);
  const report = evaluatePolicy(snapshot);
  assert.equal(report.status, 'authorized');
  assert.equal(report.checks.no_bypass_actors, true);
  assert.equal(report.governance.bypass_visible, false);
  assert.equal(report.governance.bypass_proof, 'offline_signed_attestation');
  assert.deepEqual(report.governance.bypass_actors, []);
});

test('单人维护配置可准入，但不谎称完成整体安全验收', () => {
  const report = evaluatePolicy(valid());
  assert.equal(report.status, 'authorized');
  assert.equal(report.safety_acceptance_complete, false);
  assert.equal(report.governance.mode, 'single_maintainer');
  assert.equal(report.governance.independent_audit, false);
});

test('审批数为 0 不构成治理失败，且不因缺少独立审查人误报', () => {
  const report = evaluatePolicy(valid());
  assert.equal(report.checks.pull_request_required, true);
  assert.equal(report.checks.required_status_checks_present, true);
  assert.equal(report.status, 'authorized');
  assert.equal(report.governance.independent_human_review, false);
  assert.ok(report.governance.remaining_risks.includes('no_independent_human_reviewer'));
});

test('单人维护不得被表述为独立审批或独立审计', () => {
  const report = evaluatePolicy(valid());
  assert.match(report.governance.note, /未提供独立审批、独立审计或双人复核能力/);
  assert.ok(report.manual_conditions.some(item => item.includes('不得把本报告当作独立审批已通过的证据')));
  assert.ok(report.governance.remaining_risks.includes('attestation_self_issued_by_maintainer'));
  assert.ok(report.governance.remaining_risks.includes('trust_root_stored_in_repository'));
});

test('存在独立审查人时同样可准入，是否具备只作风险披露', () => {
  const snapshot = valid();
  snapshot.environment.protection_rules = [{ type: 'required_reviewers', prevent_self_review: true, reviewers: [{ type: 'User', reviewer: { id: 2 } }] }];
  const report = evaluatePolicy(snapshot);
  assert.equal(report.status, 'authorized');
  assert.equal(report.governance.independent_human_review, true);
  assert.ok(!report.governance.remaining_risks.includes('no_independent_human_reviewer'));
});

test('Environment 配置了审查人却允许自审时记录风险', () => {
  const snapshot = valid();
  snapshot.environment.protection_rules = [{ type: 'required_reviewers', prevent_self_review: false, reviewers: [{ type: 'User', reviewer: { id: 2 } }] }];
  assert.ok(evaluatePolicy(snapshot).governance.remaining_risks.includes('environment_allows_self_review'));
});

test('非 main 的受保护分支不得通过：凭据链路只允许 main', () => {
  const snapshot = valid();
  snapshot.context.ref = 'refs/heads/release/approved-cad';
  const report = evaluatePolicy(snapshot);
  assert.equal(report.status, 'blocked');
  assert.ok(report.blocking_reasons.includes('protected_ref_is_main'));
});

// ---------------------------------------------------------------- 证明缺失与无效

test('证明缺失时阻断，且不把缺失当成空 bypass', () => {
  const report = evaluatePolicy(valid({ attestation: null }));
  assert.equal(report.status, 'blocked');
  assert.equal(report.checks.attestation_present, false);
  assert.equal(report.checks.no_bypass_actors, false);
  assert.equal(report.governance.attestation.present, false);
  assert.equal(report.governance.bypass_actors, null);
});

test('证明结构不可解析或不可读时阻断', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gov-att-'));
  const missing = readAttestation({ GOVERNANCE_ATTESTATION_PATH: path.join(dir, 'absent.json') });
  assert.equal(missing.attestation, null);
  assert.match(missing.error, /missing/);
  const broken = path.join(dir, 'broken.json');
  fs.writeFileSync(broken, '{ not json');
  const unreadable = readAttestation({ GOVERNANCE_ATTESTATION_PATH: broken });
  assert.equal(unreadable.attestation, null);
  assert.match(unreadable.error, /unreadable/);
});

test('签名被篡改时阻断', () => {
  const attestation = { ...attestationFor(), signature: Buffer.from('forged').toString('base64') };
  const report = evaluatePolicy(valid({ attestation }));
  assert.equal(report.status, 'blocked');
  assert.equal(report.checks.attestation_signature, false);
  assert.ok(report.attestation_reasons.includes('attestation_signature_invalid'));
});

test('内容被改动而签名未更新时阻断', () => {
  const attestation = attestationFor();
  attestation.ruleset.updated_at = UPDATED_AT; // 保持合法值但仍触发"签名与内容不符"
  attestation.ruleset.bypass_actors = [{ actor_id: 1, actor_type: 'User', bypass_mode: 'always' }];
  const report = evaluatePolicy(valid({ attestation }));
  assert.equal(report.status, 'blocked');
  assert.equal(report.checks.attestation_signature, false);
});

test('证明过期或被超长 TTL 签发时阻断', () => {
  const expired = attestationFor(liveRuleset(), { now: new Date(NOW.getTime() - 40 * DAY_MS) });
  const expiredReport = evaluatePolicy(valid({ attestation: expired }));
  assert.equal(expiredReport.checks.attestation_fresh, false);
  assert.ok(expiredReport.attestation_reasons.includes('attestation_expired_or_invalid_window'));

  const longTtl = attestationFor(liveRuleset(), { ttlDays: lib.MAX_TTL_DAYS + 10 });
  assert.equal(evaluatePolicy(valid({ attestation: longTtl })).checks.attestation_fresh, false);
});

test('证明时间在未来（超出时钟偏移）时阻断', () => {
  const future = attestationFor(liveRuleset(), { now: new Date(NOW.getTime() + 10 * 60 * 1000) });
  assert.equal(evaluatePolicy(valid({ attestation: future })).checks.attestation_fresh, false);
});

test('仓库 ID 或全名不匹配时阻断', () => {
  for (const repository of [{ id: '999999', full_name: TRUSTED_REPOSITORY }, { id: TRUSTED_REPOSITORY_ID, full_name: 'outsider/fork' }]) {
    const attestation = resign({ ...attestationFor(), repository });
    const report = evaluatePolicy(valid({ attestation }));
    assert.equal(report.status, 'blocked');
    assert.equal(report.checks.attestation_repository, false);
  }
});

test('规则集 ID 不匹配时阻断', () => {
  const attestation = resign({ ...attestationFor(), ruleset: { ...attestationFor().ruleset, id: 1 } });
  const report = evaluatePolicy(valid({ attestation }));
  assert.equal(report.status, 'blocked');
  assert.equal(report.checks.attestation_ruleset_identity, false);
});

test('main 分支适用范围不匹配时阻断（证明侧与线上侧都要查）', () => {
  const attestedWrong = attestationFor(liveRuleset(), { rulesetOverrides: { ref_name_include: ['refs/heads/*'] } });
  assert.equal(evaluatePolicy(valid({ attestation: attestedWrong })).checks.attestation_main_scope, false);

  const live = liveRuleset();
  live.conditions.ref_name.include = ['refs/heads/release/*'];
  const liveWrong = attestationFor(live);
  const report = evaluatePolicy(valid({ live, attestation: liveWrong }));
  assert.equal(report.checks.attestation_main_scope, false);

  const excluded = liveRuleset();
  excluded.conditions.ref_name.exclude = ['refs/heads/main'];
  assert.equal(evaluatePolicy(valid({ live: excluded, attestation: attestationFor(excluded) })).checks.attestation_main_scope, false);
});

test('配置摘要不匹配时阻断：规则变化使旧证明失效', () => {
  const attestation = attestationFor();
  const live = liveRuleset();
  live.rules[2].parameters.required_approving_review_count = 1; // 不改 updated_at，只改内容
  const report = evaluatePolicy(valid({ live, attestation }));
  assert.equal(report.status, 'blocked');
  assert.equal(report.checks.attestation_digest, false);
  assert.ok(report.attestation_reasons.includes('attestation_digest_mismatch'));
});

test('updated_at 变化时阻断：任何配置变更都使旧证明失效', () => {
  const attestation = attestationFor();  // 绑定旧 updated_at
  const live = liveRuleset();
  live.updated_at = '2026-10-26T00:00:00.000Z';  // 只 bump 时间，不改规则内容
  const report = evaluatePolicy(valid({ live, attestation }));
  assert.equal(report.status, 'blocked');
  assert.equal(report.checks.attestation_digest, true, '规则内容未变，摘要应当仍然一致');
  assert.equal(report.checks.attestation_updated_at, false);
  assert.ok(report.attestation_reasons.includes('attestation_updated_at_mismatch'));
});

test('bypass 非空时阻断', () => {
  const attestation = attestationFor(liveRuleset(), { rulesetOverrides: { bypass_actors: [{ actor_id: 199356225, actor_type: 'User', bypass_mode: 'always' }] } });
  const report = evaluatePolicy(valid({ attestation }));
  assert.equal(report.status, 'blocked');
  assert.equal(report.checks.no_bypass_actors, false);
  assert.equal(report.governance.bypass_actors.length, 1);
});

test('证明缺少 bypass_actors 字段时阻断，不得解释为空', () => {
  const attestation = attestationFor(liveRuleset(), { omitBypass: true });
  const report = evaluatePolicy(valid({ attestation }));
  assert.equal(report.status, 'blocked');
  assert.equal(report.checks.no_bypass_actors, false);
  assert.equal(report.governance.bypass_actors, null);
});

test('线上能看见 bypass 且非空时阻断（纵深检查）', () => {
  const snapshot = valid();
  snapshot.rulesets[0].bypass_actors = [{ actor_id: 199356225, actor_type: 'User', bypass_mode: 'always' }];
  const report = evaluatePolicy(snapshot);
  assert.equal(report.status, 'blocked');
  assert.equal(report.checks.live_bypass_consistent, false);
});

test('声明不得声称独立审计或非单人维护', () => {
  for (const governance of [
    { ...attestationFor().governance, independent_audit: true },
    { ...attestationFor().governance, mode: 'dual_review' },
    { ...attestationFor().governance, trust_boundary: '' },
  ]) {
    const attestation = resign({ ...attestationFor(), governance });
    const report = evaluatePolicy(valid({ attestation }));
    assert.equal(report.status, 'blocked');
    assert.equal(report.checks.attestation_declaration, false);
  }
});

// ---------------------------------------------------------------- 信任根与轮换

test('未固定或已吊销的签名密钥被拒绝', () => {
  const unknown = resign({ ...attestationFor(), signer: { ...attestationFor().signer, key_id: 'ed25519:deadbeef' } });
  const unknownReport = evaluatePolicy(valid({ attestation: unknown }));
  assert.equal(unknownReport.checks.attestation_signature, false);
  assert.ok(unknownReport.attestation_reasons.includes('attestation_key_unknown'));

  const revoked = evaluatePolicy(valid({ trustRoot: trustRoot({ revoked_at: '2026-01-01T00:00:00Z' }) }));
  assert.equal(revoked.checks.attestation_signature, false);
  assert.ok(revoked.attestation_reasons.includes('attestation_key_revoked'));
});

test('信任根被静默删除时阻断：轮换日志仍引用该 key', () => {
  const report = evaluatePolicy(valid({ trustRoot: { keys: {}, log: [KEY_ID] } }));
  assert.equal(report.status, 'blocked');
  assert.equal(report.checks.trust_root_intact, false);
  assert.ok(report.attestation_reasons.includes('trust_root_intact'));
});

test('密钥轮换：新 key 生效、旧 key 吊销后旧证明失效', () => {
  const next = newKey();
  const nextId = lib.keyIdOf(next.publicPem);
  const rotated = { keys: { ...trustRoot().keys, [nextId]: { pem: next.publicPem, not_before: '2026-01-01T00:00:00Z', revoked_at: null } }, log: [KEY_ID, nextId] };

  const byNext = attestationFor(liveRuleset(), { key: next });
  assert.equal(evaluatePolicy(valid({ attestation: byNext, trustRoot: rotated })).status, 'authorized');

  const revokeOld = { keys: { ...rotated.keys, [KEY_ID]: { ...rotated.keys[KEY_ID], revoked_at: '2026-10-01T00:00:00Z' } }, log: rotated.log };
  assert.equal(evaluatePolicy(valid({ attestation: attestationFor(), trustRoot: revokeOld })).checks.attestation_signature, false);
});

// ---------------------------------------------------------------- 离线采集工具

const SECRET = 'ghp_thisMustNeverAppearInAnyOutput0123456789';

function fakeApi(detail) {
  return async (token, route) => {
    if (token !== SECRET) throw new Error('unexpected token');
    if (route === `/repos/${TRUSTED_REPOSITORY}`) return { id: Number(TRUSTED_REPOSITORY_ID), full_name: TRUSTED_REPOSITORY };
    if (route === `/repos/${TRUSTED_REPOSITORY}/rulesets?per_page=100`) return [{ id: RULESET_ID, name: 'protect-main' }];
    if (route === `/repos/${TRUSTED_REPOSITORY}/rulesets/${RULESET_ID}`) return detail;
    throw new Error(`unexpected route ${route}`);
  };
}

test('采集工具在看不到 bypass_actors 时拒绝生成证明', async () => {
  const detail = liveRuleset();
  delete detail.bypass_actors;
  await assert.rejects(() => captureTool.capture({ token: SECRET, privateKeyPem: KEY.privatePem, fetchJson: fakeApi(detail) }), /看不到 bypass_actors/);
});

test('采集工具拒绝与固定仓库身份不符的响应', async () => {
  const fetchJson = async () => ({ id: 42, full_name: 'outsider/fork' });
  await assert.rejects(() => captureTool.capture({ token: SECRET, privateKeyPem: KEY.privatePem, fetchJson }), /仓库身份不符/);
});

test('采集产物不含凭据，且能通过只读校验', async () => {
  const live = liveRuleset();
  const { attestation, warnings } = await captureTool.capture({ token: SECRET, privateKeyPem: KEY.privatePem, fetchJson: fakeApi(live), now: NOW });
  assert.deepEqual(warnings, []);
  const serialized = JSON.stringify(attestation);
  assert.ok(!serialized.includes(SECRET), '证明中不得出现凭据');
  assert.equal(attestation.signer.key_id, KEY_ID);
  assert.equal(attestation.config_digest_sha256, lib.configDigest(attestation.ruleset));

  const report = evaluatePolicy(valid({ live, attestation }));
  assert.equal(report.status, 'authorized');
  assert.equal(report.governance.attestation.verified, true);
});

test('采集工具如实记录非空 bypass 并给出告警', async () => {
  const live = liveRuleset();
  live.bypass_actors = [{ actor_id: 199356225, actor_type: 'User', bypass_mode: 'always' }];
  const { attestation, warnings } = await captureTool.capture({ token: SECRET, privateKeyPem: KEY.privatePem, fetchJson: fakeApi(live), now: NOW });
  assert.equal(warnings.length, 1);
  assert.equal(attestation.ruleset.bypass_actors.length, 1);
  assert.equal(evaluatePolicy(valid({ live, attestation })).checks.no_bypass_actors, false);
});

// ---------------------------------------------------------------- 既有准入条件

const faults = {
  fork: s => { s.context.repository = 'outsider/fork'; },
  replaced_repository: s => { s.context.repository_id = 'unknown'; },
  malformed_sha: s => { s.context.sha = s.branch.commit.sha = 'unknown'; },
  pull_request_event: s => { s.context.event_name = 'pull_request'; },
  pull_request_target: s => { s.context.event_name = 'pull_request_target'; },
  tag: s => { s.context.ref_type = 'tag'; },
  unprotected: s => { s.context.ref_protected = false; },
  api_unprotected: s => { s.branch.protected = false; },
  moved_branch: s => { s.branch.commit.sha = 'b'.repeat(40); },
  inactive_ruleset: s => { s.rulesets[0].enforcement = 'disabled'; },
  missing_ruleset: s => { s.rulesets = []; },
  live_bypass_always: s => { s.rulesets[0].bypass_actors = [{ actor_id: 199356225, actor_type: 'User', bypass_mode: 'always' }]; },
  live_bypass_pull_request: s => { s.rulesets[0].bypass_actors = [{ actor_id: 199356225, actor_type: 'User', bypass_mode: 'pull_request' }]; },
  live_bypass_exempt: s => { s.rulesets[0].bypass_actors = [{ actor_id: 199356225, actor_type: 'User', bypass_mode: 'exempt' }]; },
  missing_pull_request_rule: s => { s.rules = s.rules.filter(r => r.type !== 'pull_request'); },
  missing_checks: s => { s.rules = s.rules.filter(r => r.type !== 'required_status_checks'); },
  wrong_required_check: s => { s.rules = s.rules.map(r => (r.type === 'required_status_checks'
    ? { type: r.type, parameters: { required_status_checks: [{ context: 'lint-only' }] } } : r)); },
  unauthorized_actor: s => { s.permissions.owner = 'write'; },
  unauthorized_rerunner: s => { s.permissions['owner-2'] = 'read'; },
  unknown_actor: s => { delete s.context.actor; },
  missing_environment: s => { s.environment = null; },
  any_branch: s => { s.environment.deployment_branch_policy = null; },
  custom_branch_policy: s => { s.environment.deployment_branch_policy.custom_branch_policies = true; },
  no_runner: s => { s.runners = []; },
  offline_runner: s => { s.runners[0].status = 'offline'; },
  busy_runner: s => { s.runners[0].busy = true; },
  wrong_runner: s => { s.runners[0].labels.pop(); },
};
for (const [name, mutate] of Object.entries(faults)) test(`拒绝 ${name}`, () => {
  const snapshot = valid(); mutate(snapshot);
  assert.equal(evaluatePolicy(snapshot).status, 'blocked');
});

test('缺少 PR 保护或必需状态检查时分别给出明确阻断原因', () => {
  const noPullRequest = valid(); noPullRequest.rules = noPullRequest.rules.filter(r => r.type !== 'pull_request');
  const noPullRequestReport = evaluatePolicy(noPullRequest);
  assert.equal(noPullRequestReport.status, 'blocked');
  assert.ok(noPullRequestReport.blocking_reasons.includes('pull_request_required'));

  const noChecks = valid(); noChecks.rules = noChecks.rules.filter(r => r.type !== 'required_status_checks');
  const noChecksReport = evaluatePolicy(noChecks);
  assert.equal(noChecksReport.status, 'blocked');
  assert.ok(noChecksReport.blocking_reasons.includes('required_status_checks_present'));
});

test('B-01 前提缺失时仍阻断：Runner 与 Environment 未配置', () => {
  const noRunner = valid(); noRunner.runners = [];
  const noRunnerReport = evaluatePolicy(noRunner);
  assert.equal(noRunnerReport.status, 'blocked');
  assert.deepEqual(noRunnerReport.blocking_reasons, ['idle_windows_cad_runner']);

  const noEnvironment = valid(); noEnvironment.environment = null;
  const noEnvironmentReport = evaluatePolicy(noEnvironment);
  assert.equal(noEnvironmentReport.status, 'blocked');
  assert.ok(noEnvironmentReport.blocking_reasons.includes('protected_environment_exists'));
});

test('不可信上下文不发 API 请求', async () => {
  const snapshot = await readSnapshot({ GITHUB_REPOSITORY: 'outsider/fork' });
  assert.equal(evaluatePolicy(snapshot).status, 'blocked');
});

test('缺少只读审计凭据时阻断，不以 GITHUB_TOKEN 假定具备 Runner 管理读取权限', async () => {
  await assert.rejects(() => readSnapshot({ GITHUB_REPOSITORY: TRUSTED_REPOSITORY,
    GITHUB_REPOSITORY_ID: TRUSTED_REPOSITORY_ID, GITHUB_EVENT_NAME: 'workflow_dispatch',
    GITHUB_REF_TYPE: 'branch', GITHUB_REF_PROTECTED: 'true' }), /CAD_CI_AUDIT_TOKEN missing/);
});
