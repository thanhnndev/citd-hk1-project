import { access, readFile } from 'node:fs/promises';
import { constants } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const repoRoot = path.resolve(import.meta.dirname, '..');

const files = {
  matrix: 'docs/M011-S04-REQUIREMENT-RECONCILIATION.md',
  requirements: '.gsd/REQUIREMENTS.md',
  audit: 'docs/M011-REQUIREMENTS-AUDIT.md',
  adminRouter: 'backend/app/routers/admin.py',
  adminEvalTests: 'backend/tests/test_admin_eval_endpoint.py',
  adminStatsTests: 'backend/tests/test_admin_stats_endpoint.py',
  adminTracesTests: 'backend/tests/test_admin_traces_endpoint.py',
  adminEmbedTests: 'backend/tests/test_admin_embed_auth.py',
  fairnessTests: 'backend/tests/test_fairness_audit.py',
  frontendAuthE2E: 'frontend/tests/s07-auth-e2e.test.mjs',
  s01Verifier: 'scripts/verify-m011-s01-inventory.mjs',
  s02Verifier: 'scripts/verify-m011-s02-audit.mjs',
  s03Verifier: 'scripts/verify-m011-s03-bounded-fixes.mjs',
};

const requiredRequirementIds = [
  'R007',
  'R008',
  'R010',
  'R011',
  'R013',
  'R015',
  'R026',
  'R028',
  'R029',
  'R031',
  'R032',
  'R033',
  'R034',
];

function repoPath(relativePath) {
  return path.join(repoRoot, relativePath);
}

async function read(relativePath) {
  const absolutePath = repoPath(relativePath);
  await access(absolutePath, constants.R_OK);
  return readFile(absolutePath, 'utf8');
}

function normalizeText(value) {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[đĐ]/g, 'd')
    .replace(/[^\p{L}\p{N}/_.:-]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .toLowerCase()
    .trim();
}

function assertContainsAll(haystack, needles, context) {
  const normalizedHaystack = normalizeText(haystack);
  for (const needle of needles) {
    assert.ok(
      normalizedHaystack.includes(normalizeText(needle)),
      `${context} is missing required token: ${needle}`,
    );
  }
}

function requirementRow(matrix, requirementId) {
  const escapedId = requirementId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = matrix.match(new RegExp(`\\|\\s*${escapedId}\\s*\\|[^\n]+`, 'm'));
  assert.ok(match, `Reconciliation matrix is missing row for ${requirementId}.`);
  return match[0];
}

test('M011/S04 reconciliation matrix exists and covers required active requirement IDs', async () => {
  const [matrix, requirements] = await Promise.all([
    read(files.matrix),
    read(files.requirements),
  ]);

  assert.ok(matrix.trim().length > 0, 'S04 reconciliation matrix exists but is empty.');
  assertContainsAll(matrix, ['Active Requirement Matrix', 'Planned Action', 'Evidence Paths', 'Caveats', 'S05 Implication'], 'S04 matrix table');

  for (const requirementId of requiredRequirementIds) {
    assert.match(requirements, new RegExp(`\\b${requirementId}\\b`), `.gsd/REQUIREMENTS.md is missing expected active requirement ${requirementId}.`);
    requirementRow(matrix, requirementId);
  }
});

test('M011/S04 matrix preserves credential-blocked provider caveats without overclaiming live proof', async () => {
  const matrix = await read(files.matrix);

  assertContainsAll(
    matrix,
    [
      'credential_blocked',
      'OpenAI',
      'Google Places/Routes',
      'Qdrant',
      'Langfuse',
      'valid credentials',
      'running services',
      'Do not cite mocked/static tests as live',
      'must not mark live Places/Routes verified without RESULT=passed',
    ],
    'S04 credential-blocked caveats',
  );

  for (const requirementId of ['R007', 'R008', 'R010', 'R026', 'R033']) {
    assertContainsAll(requirementRow(matrix, requirementId), ['credential_blocked'], `${requirementId} caveats`);
  }
});

test('M011/S04 matrix keeps deferred major capabilities explicit', async () => {
  const matrix = await read(files.matrix);

  assertContainsAll(
    matrix,
    [
      'deferred_major_scope',
      'RAGAS CI/CD',
      'semantic cache',
      'Redis semantic-cache production behavior',
      'monthly production fairness history',
      'production fairness history',
      'frontend performance/accessibility',
      'frontend_nonfunctional_pending',
      'missing_operational_metrics',
    ],
    'S04 deferred caveat language',
  );

  assertContainsAll(requirementRow(matrix, 'R010'), ['semantic cache', 'RAGAS CI/CD', 'monthly production fairness history'], 'R010 deferred scope');
  assertContainsAll(requirementRow(matrix, 'R034'), ['RAGAS CI/CD', 'semantic cache', 'production fairness history', 'frontend nonfunctional proof'], 'R034 deferred scope');
});

test('M011/S04 matrix encodes R033 active and R032/R034 validation dependency on reconciliation evidence', async () => {
  const matrix = await read(files.matrix);

  assertContainsAll(requirementRow(matrix, 'R033'), ['keep_active', 'S05', 'must not pre-validate'], 'R033 S05 active contract');
  assertContainsAll(requirementRow(matrix, 'R032'), ['validate_after_reconciliation_evidence', 'matrix and verifier exist', '.gsd/REQUIREMENTS.md reconciliation'], 'R032 validation dependency');
  assertContainsAll(requirementRow(matrix, 'R034'), ['validate_after_reconciliation_evidence', 'explicit deferrals', 'not silently closing major gaps'], 'R034 validation dependency');
  assertContainsAll(matrix, ['R033 remains active for S05', 'R032 and R034 should not be marked validated until reconciliation evidence exists'], 'S05 readiness notes');
});

test('M011/S04 matrix references only tracked source/documentation evidence, not generated audit paths', async () => {
  const matrix = await read(files.matrix);

  assertContainsAll(
    matrix,
    [
      'docs/M011-REQUIREMENTS-AUDIT.md',
      'scripts/verify-m011-s01-inventory.mjs',
      'scripts/verify-m011-s02-audit.mjs',
      'scripts/verify-m011-s03-bounded-fixes.mjs',
      'scripts/verify-m011-s04-reconciliation.mjs',
      'backend/app/routers/admin.py',
      'backend/tests/test_admin_eval_endpoint.py',
      'backend/tests/test_admin_stats_endpoint.py',
      'backend/tests/test_admin_traces_endpoint.py',
      'backend/tests/test_admin_embed_auth.py',
      'backend/tests/test_fairness_audit.py',
      'frontend/tests/s07-auth-e2e.test.mjs',
    ],
    'S04 evidence paths',
  );

  assert.doesNotMatch(matrix, /\.planning\//, 'Matrix must not cite .planning generated paths.');
  assert.doesNotMatch(matrix, /\.audits\//, 'Matrix must not cite .audits generated paths.');
});

test('M011/S04 verifier cross-checks current admin, audit, and test surfaces for stale status drift', async () => {
  const [matrix, audit, adminRouter, adminTests, fairnessTests, frontendE2E] = await Promise.all([
    read(files.matrix),
    read(files.audit),
    read(files.adminRouter),
    Promise.all([
      read(files.adminEvalTests),
      read(files.adminStatsTests),
      read(files.adminTracesTests),
      read(files.adminEmbedTests),
    ]).then((sources) => sources.join('\n')),
    read(files.fairnessTests),
    read(files.frontendAuthE2E),
  ]);

  assertContainsAll(audit, ['credential_blocked', 'endpoint_naming_drift', 'missing_operational_metrics', 'S03 Remediation Outcomes'], 'M011 audit report');
  assertContainsAll(adminRouter, ['@router.post(\n    "/eval/trigger"', '@router.get("/traces"', '@router.get("/stats"', '@router.get("/fairness"', 'Depends(get_current_user)'], 'admin router source');
  assert.doesNotMatch(adminRouter, /@router\.post\(["']\/eval["']/, 'Admin router must not restore stale POST /admin/eval route naming.');
  assertContainsAll(adminTests, ['/admin/eval/trigger', '/admin/traces', '/admin/stats', '/admin/embed', 'decode_access_token'], 'admin auth tests');
  assertContainsAll(fairnessTests, ['/admin/fairness', 'fairness_audit', 'local_factor_distribution'], 'fairness audit tests');
  assertContainsAll(frontendE2E, ['admin', 'auth'], 'frontend admin/auth E2E surface');
  assertContainsAll(matrix, ['endpoint_naming_drift', 'POST /admin/eval/trigger', 'GET /admin/traces', 'POST /admin/embed'], 'S04 admin route reconciliation');
});

test('M011/S04 prerequisite verifier scripts remain present for S05 aggregate checks', async () => {
  await Promise.all([
    read(files.s01Verifier),
    read(files.s02Verifier),
    read(files.s03Verifier),
  ]);
});
