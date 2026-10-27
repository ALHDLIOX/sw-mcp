/** @file 离线规则集证明的规范化、摘要与签名校验；纯函数，不发网络请求、不读凭据。 */
const crypto = require('node:crypto');

const SCHEMA = 'cad-governance-attestation/v1';
/** 证明最长有效期；超过即视为过期，避免长期沿用旧证明。 */
const MAX_TTL_DAYS = 30;
/** 允许的时钟偏移，防止本机与 CI 时钟轻微不一致导致误判。 */
const CLOCK_SKEW_MS = 5 * 60 * 1000;
/** 被审计的分支范围；单人维护模式下只有 main 允许运行真机 CAD。 */
const GOVERNED_REF = 'refs/heads/main';

/** @brief 稳定序列化：键排序、丢弃 undefined，确保同一配置在任何机器上摘要一致。 */
function canonical(value) {
  if (value === null || value === undefined) return 'null';
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  const keys = Object.keys(value).filter(key => value[key] !== undefined).sort();
  return `{${keys.map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
}

function sha256Hex(text) { return crypto.createHash('sha256').update(text, 'utf8').digest('hex'); }

/** @brief 只保留 type 与 parameters；剔除随端点变化的来源字段，避免无意义摘要漂移。 */
function normalizeRule(rule) {
  if (!rule || !rule.type) return null;
  return rule.parameters === undefined ? { type: rule.type } : { type: rule.type, parameters: rule.parameters };
}

/**
 * @brief 摘要覆盖的配置视图。
 * @note 刻意**不含 bypass_actors**：只读凭据读不到该字段，若纳入摘要则永远无法与线上比对。
 *       bypass 为空的证明责任由签名证明独立承担，配置变更由 updated_at 与摘要共同覆盖。
 */
function configView(ruleset) {
  if (!ruleset || !Array.isArray(ruleset.rules)) return null;
  // 兼容两种形态：线上 API 返回 conditions.ref_name，证明文件使用扁平 ref_name_include/exclude。
  const refName = ruleset.conditions?.ref_name || { include: ruleset.ref_name_include, exclude: ruleset.ref_name_exclude };
  const rules = ruleset.rules.map(normalizeRule).filter(Boolean)
    .sort((left, right) => (left.type < right.type ? -1 : left.type > right.type ? 1 : 0));
  return {
    id: ruleset.id, name: ruleset.name, target: ruleset.target, enforcement: ruleset.enforcement,
    include: [...(refName.include || [])].sort(), exclude: [...(refName.exclude || [])].sort(), rules,
  };
}

/** @brief 配置摘要；无法构造视图时返回 null（由调用方按未知阻断）。 */
function configDigest(ruleset) {
  const view = configView(ruleset);
  return view ? sha256Hex(canonical(view)) : null;
}

/** @brief SPKI DER 的 sha256，作为公钥指纹（key id）的稳定来源。 */
function publicKeyFingerprint(publicKeyPem) {
  const der = crypto.createPublicKey(publicKeyPem).export({ type: 'spki', format: 'der' });
  return sha256Hex(der.toString('hex'));
}

function keyIdOf(publicKeyPem) { return `ed25519:${publicKeyFingerprint(publicKeyPem)}`; }

/** @brief 被签名的字节：除 signature 外的全部字段的规范形式。 */
function signingPayload(attestation) {
  const { signature, ...rest } = attestation || {};
  return Buffer.from(canonical(rest), 'utf8');
}

/** @brief 仅离线采集工具使用；私钥不得进入 CI。 */
function signAttestation(attestation, privateKeyPem) {
  const key = crypto.createPrivateKey(privateKeyPem);
  return crypto.sign(null, signingPayload(attestation), key).toString('base64');
}

function verifySignature(attestation, publicKeyPem) {
  try {
    const signature = Buffer.from(String(attestation?.signature || ''), 'base64');
    if (signature.length === 0) return false;
    return crypto.verify(null, signingPayload(attestation), crypto.createPublicKey(publicKeyPem), signature);
  } catch { return false; }
}

function parseTime(value) {
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : null;
}

/** @brief 信任根完整性：轮换日志中记录的每个 key 必须仍在册，删除旧 key 会使校验失败。 */
function trustRootIntact(trustRoot) {
  const keys = trustRoot?.keys;
  const log = trustRoot?.log;
  if (!keys || typeof keys !== 'object' || !Array.isArray(log)) return false;
  return log.every(id => Object.prototype.hasOwnProperty.call(keys, id));
}

/** @brief 选出对 signed_at 有效的 key；已吊销或未生效的 key 不参与验签。 */
function resolveKey(trustRoot, keyId, signedAtMs) {
  const entry = trustRoot?.keys?.[keyId];
  if (!entry || typeof entry.pem !== 'string') return { ok: false, reason: 'attestation_key_unknown' };
  if (keyIdOf(entry.pem) !== keyId) return { ok: false, reason: 'attestation_key_fingerprint_mismatch' };
  const revokedAt = entry.revoked_at ? parseTime(entry.revoked_at) : null;
  if (revokedAt !== null && signedAtMs !== null && signedAtMs >= revokedAt) return { ok: false, reason: 'attestation_key_revoked' };
  const notBefore = entry.not_before ? parseTime(entry.not_before) : null;
  if (notBefore !== null && signedAtMs !== null && signedAtMs < notBefore) return { ok: false, reason: 'attestation_key_not_yet_valid' };
  return { ok: true, pem: entry.pem };
}

const CHECK_KEYS = ['schema_supported', 'declaration_valid', 'repository_matches', 'ruleset_identity_matches',
  'main_scope_matches', 'not_expired', 'signature_valid', 'digest_matches', 'updated_at_matches',
  'bypass_empty', 'trust_root_intact'];

/**
 * @brief 校验离线证明是否可用于准入。
 * @param attestation 证明对象（缺失传 null）
 * @param trustRoot 固定信任根；默认由调用方注入，不得取自证明自身
 * @param live 线上只读读取到的规则集（含 rules / conditions / updated_at）
 * @param repository { id, full_name }
 * @note 任何无法判定、字段缺失、类型不符的情况一律记入 reasons，由调用方阻断。
 */
function verifyAttestation({ attestation, trustRoot, live, repository = {}, now = new Date(), maxTtlDays = MAX_TTL_DAYS } = {}) {
  const checks = Object.fromEntries(CHECK_KEYS.map(key => [key, false]));
  const reasons = [];
  const nowMs = now instanceof Date ? now.getTime() : parseTime(now);
  if (!attestation || typeof attestation !== 'object' || Array.isArray(attestation)) {
    // 证明缺失时 facts 也要给出显式的 null，避免调用方把 undefined 误当成"空"。
    return { ok: false, checks, reasons: ['attestation_missing'],
      facts: { key_id: null, captured_at: null, expires_at: null, updated_at: null, config_digest_sha256: null, bypass_actors: null } };
  }
  const fail = reason => { reasons.push(reason); };

  checks.trust_root_intact = trustRootIntact(trustRoot);
  if (!checks.trust_root_intact) fail('trust_root_intact');

  checks.schema_supported = attestation.schema === SCHEMA;
  if (!checks.schema_supported) fail('attestation_schema_unsupported');

  // 声明必须诚实：单人维护、非独立审计。任何试图声称独立审计的证明都不接受。
  const declaration = attestation.governance || {};
  checks.declaration_valid = declaration.mode === 'single_maintainer' && declaration.independent_audit === false
    && typeof declaration.trust_boundary === 'string' && declaration.trust_boundary.length > 0;
  if (!checks.declaration_valid) fail('attestation_declaration_invalid');

  const attestedRepo = attestation.repository || {};
  checks.repository_matches = String(attestedRepo.id) === String(repository.id)
    && typeof attestedRepo.full_name === 'string' && attestedRepo.full_name === repository.full_name;
  if (!checks.repository_matches) fail('attestation_repository_mismatch');

  const attested = attestation.ruleset || {};
  checks.ruleset_identity_matches = live && attested.id === live.id && attested.name === live.name
    && attested.target === live.target && attested.enforcement === live.enforcement
    && live.target === 'branch' && live.enforcement === 'active';
  if (!checks.ruleset_identity_matches) fail('attestation_ruleset_identity_mismatch');

  const attestedInclude = [...(attested.ref_name_include || [])];
  const liveInclude = [...(live?.conditions?.ref_name?.include || [])];
  const attestedExclude = [...(attested.ref_name_exclude || [])];
  const liveExclude = [...(live?.conditions?.ref_name?.exclude || [])];
  checks.main_scope_matches = attestedInclude.length === 1 && attestedInclude[0] === GOVERNED_REF
    && attestedExclude.length === 0 && liveInclude.length === 1 && liveInclude[0] === GOVERNED_REF
    && liveExclude.length === 0;
  if (!checks.main_scope_matches) fail('attestation_main_scope_mismatch');

  const capturedMs = parseTime(attestation.captured_at);
  const expiresMs = parseTime(attestation.expires_at);
  const ttlMs = capturedMs !== null && expiresMs !== null ? expiresMs - capturedMs : null;
  const ttlWithinLimit = ttlMs !== null && ttlMs > 0 && ttlMs <= maxTtlDays * 24 * 60 * 60 * 1000;
  checks.not_expired = capturedMs !== null && expiresMs !== null && ttlWithinLimit
    && nowMs !== null && nowMs <= expiresMs && nowMs >= capturedMs - CLOCK_SKEW_MS;
  if (!checks.not_expired) fail('attestation_expired_or_invalid_window');

  const signer = attestation.signer || {};
  const signedMs = parseTime(signer.signed_at);
  const resolved = resolveKey(trustRoot, signer.key_id, signedMs);
  if (!resolved.ok) fail(resolved.reason);
  checks.signature_valid = resolved.ok && verifySignature(attestation, resolved.pem);
  if (!checks.signature_valid && resolved.ok) fail('attestation_signature_invalid');

  // 摘要双绑定：证明自身一致 + 与线上配置一致，二者缺一不可。
  const attestedDigest = configDigest(attested);
  const liveDigest = configDigest(live);
  checks.digest_matches = attestedDigest !== null && liveDigest !== null
    && attestation.config_digest_sha256 === attestedDigest && attestedDigest === liveDigest;
  if (!checks.digest_matches) fail('attestation_digest_mismatch');

  checks.updated_at_matches = typeof attested.updated_at === 'string' && typeof live?.updated_at === 'string'
    && attested.updated_at === live.updated_at;
  if (!checks.updated_at_matches) fail('attestation_updated_at_mismatch');

  // 字段缺失 ≠ 为空：必须显式是空数组才算"无绕过者"。
  checks.bypass_empty = Array.isArray(attested.bypass_actors) && attested.bypass_actors.length === 0;
  if (!checks.bypass_empty) fail('attestation_bypass_not_empty');

  const facts = {
    key_id: signer.key_id || null, captured_at: attestation.captured_at || null,
    expires_at: attestation.expires_at || null, updated_at: attested.updated_at || null,
    config_digest_sha256: attestation.config_digest_sha256 || null, bypass_actors: Array.isArray(attested.bypass_actors) ? attested.bypass_actors : null,
  };
  return { ok: reasons.length === 0, checks, reasons: [...new Set(reasons)], facts };
}

module.exports = { SCHEMA, MAX_TTL_DAYS, CLOCK_SKEW_MS, GOVERNED_REF, CHECK_KEYS, canonical, sha256Hex,
  normalizeRule, configView, configDigest, publicKeyFingerprint, keyIdOf, signAttestation, verifySignature,
  trustRootIntact, verifyAttestation };
