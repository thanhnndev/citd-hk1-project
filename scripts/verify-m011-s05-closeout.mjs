import { access, readFile } from 'node:fs/promises';
import { constants } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const repoRoot = path.resolve(import.meta.dirname, '..');

const files = {
  audit: 'docs/M011-REQUIREMENTS-AUDIT.md',
  reconciliation: 'docs/M011-S04-REQUIREMENT-RECONCILIATION.md',
  s01Verifier: 'scripts/verify-m011-s01-inventory.mjs',
  s02Verifier: 'scripts/verify-m011-s02-audit.mjs',
  s03Verifier: 'scripts/verify-m011-s03-bounded-fixes.mjs',
  s04Verifier: 'scripts/verify-m011-s04-reconciliation.mjs',
};

const boundedResults = [
  'passed',
  'failed',
  'partial',
  'credential_blocked',
  'environment_blocked',
  'not_run',
  'durable_verified',
];

const requiredEvidenceSurfaces = [
  'static',
  'backend',
  'frontend',
  'provider',
  'runtime',
];

const requiredProviderCaveats = [
  'OpenAI',
  'Qdrant',
  'Google Places',
  'Google Routes',
  'Langfuse',
];

const requiredDeferredCaveats = [
  'frontend performance/accessibility',
  'production fairness history',
  'RAGAS CI/CD',
  'semantic cache',
  'session durability',
  'infra/runtime checks',
];

const liveProofGuardrails = [
  {
    surface: 'OpenAI/Qdrant',
    blockedPattern: /(?:OpenAI|Qdrant)[\s\S]{0,220}credential_blocked/i,
    passClaimPattern: /(?:OpenAI|Qdrant)[\s\S]{0,220}\b(?:live[_ -]?pass|live proof|verified live|passed)\b/i,
    resultPattern: /RESULT=(?:passed|durable_verified)/,
  },
  {
    surface: 'Google Places/Routes',
    blockedPattern: /(?:Google Places|Google Routes|Places\/Routes)[\s\S]{0,220}credential_blocked/i,
    passClaimPattern: /(?:Google Places|Google Routes|Places\/Routes)[\s\S]{0,220}\b(?:live[_ -]?pass|live proof|verified live|passed)\b/i,
    resultPattern: /RESULT=(?:passed|durable_verified)/,
  },
  {
    surface: 'Langfuse',
    blockedPattern: /Langfuse[\s\S]{0,220}credential_blocked/i,
    passClaimPattern: /Langfuse[\s\S]{0,220}\b(?:live[_ -]?pass|live proof|verified live|passed)\b/i,
    resultPattern: /RESULT=(?:passed|durable_verified)/,
  },
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
    .replace(/[^\p{L}\p{N}/_.:=+-]+/gu, ' ')
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

function s05Section(audit) {
  const match = audit.match(/^##\s+S05\b[^\n]*\n[\s\S]*?(?=^##\s+|(?![\s\S]))/m);
  assert.ok(
    match,
    'Audit report is missing an S05 final verification closeout section.',
  );
  return match[0];
}

function tableRows(markdown) {
  return markdown
    .split('\n')
    .filter((line) => /^\|.+\|$/.test(line) && !/^\|\s*-+/.test(line));
}

function assertNoBlockedSurfacePromotedToLivePass(section) {
  for (const guardrail of liveProofGuardrails) {
    const hasBlockedSurface = guardrail.blockedPattern.test(section);
    const hasPassClaim = guardrail.passClaimPattern.test(section);
    const hasExplicitLiveResult = guardrail.resultPattern.test(section);

    assert.ok(
      !hasBlockedSurface || !hasPassClaim || hasExplicitLiveResult,
      `${guardrail.surface} is credential_blocked but appears to be represented as live pass without RESULT=passed or RESULT=durable_verified.`,
    );
  }
}

test('M011/S05 closeout section exists and uses bounded result vocabulary', async () => {
  const section = s05Section(await read(files.audit));

  assertContainsAll(section, ['Final Verification', 'Closeout', 'Result', 'Evidence'], 'S05 closeout section');

  for (const result of boundedResults) {
    assertContainsAll(section, [result], 'S05 bounded result vocabulary');
  }

  const unknownResultPattern = /\bRESULT=(?!passed\b|failed\b|partial\b|credential_blocked\b|environment_blocked\b|not_run\b|durable_verified\b)[A-Za-z_]+/g;
  assert.doesNotMatch(
    section,
    unknownResultPattern,
    'S05 closeout section contains an unbounded RESULT token; use the documented result vocabulary.',
  );
});

test('M011/S05 closeout records static/backend/frontend/provider/runtime evidence surfaces', async () => {
  const section = s05Section(await read(files.audit));

  assertContainsAll(section, requiredEvidenceSurfaces, 'S05 evidence surface coverage');
  assertContainsAll(
    section,
    [
      'node --test',
      'pytest',
      'frontend',
      'provider',
      'runtime',
      'gsd_exec',
    ],
    'S05 reproducible command evidence',
  );

  const rows = tableRows(section);
  assert.ok(
    rows.length >= requiredEvidenceSurfaces.length,
    'S05 closeout should include a durable evidence table with at least one row per surface.',
  );
});

test('M011/S05 closeout includes evidence IDs or timestamps for noisy/non-static diagnostics', async () => {
  const section = s05Section(await read(files.audit));

  assert.match(
    section,
    /\b(?:gsd_exec|run id|evidence id)\b/i,
    'S05 closeout must cite gsd_exec run IDs or evidence IDs for diagnostics.',
  );
  assert.match(
    section,
    /\b\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+-Z]+)?\b/,
    'S05 closeout must include timestamps or dated evidence for final verification.',
  );
});

test('M011/S05 closeout preserves live-provider and deferred-scope caveats', async () => {
  const section = s05Section(await read(files.audit));

  assertContainsAll(section, ['credential_blocked', 'deferred', 'unblock condition'], 'S05 caveat framing');
  assertContainsAll(section, requiredProviderCaveats, 'S05 provider caveats');
  assertContainsAll(section, requiredDeferredCaveats, 'S05 deferred and environment caveats');
  assertNoBlockedSurfacePromotedToLivePass(section);
});

test('M011/S05 closeout keeps S04 reconciliation caveats aligned', async () => {
  const [section, reconciliation] = await Promise.all([
    read(files.audit).then(s05Section),
    read(files.reconciliation),
  ]);

  const requiredSharedCaveats = [
    'credential_blocked',
    'deferred_major_scope',
    'missing_operational_metrics',
    'frontend_nonfunctional_pending',
    'endpoint_naming_drift',
  ];

  assertContainsAll(reconciliation, requiredSharedCaveats, 'S04 reconciliation caveats');
  assertContainsAll(section, requiredSharedCaveats, 'S05 closeout caveats');
});

test('M011/S05 aggregate static gate references S01-S04 and S05 verifier scripts', async () => {
  await Promise.all(Object.values(files).map((relativePath) => read(relativePath)));
  const section = s05Section(await read(files.audit));

  assertContainsAll(
    section,
    [
      files.s01Verifier,
      files.s02Verifier,
      files.s03Verifier,
      files.s04Verifier,
      'scripts/verify-m011-s05-closeout.mjs',
    ],
    'S05 aggregate static gate references',
  );
});
