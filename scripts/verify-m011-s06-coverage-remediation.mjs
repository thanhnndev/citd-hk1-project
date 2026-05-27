import { access, readFile } from 'node:fs/promises';
import { constants } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const repoRoot = path.resolve(import.meta.dirname, '..');
const auditPath = path.join(repoRoot, 'docs', 'M011-REQUIREMENTS-AUDIT.md');

const r012AbsencePhrases = [
  'absent from active implementation scope',
  'out-of-scope',
  'no current contract',
  'not validated',
];

const r027LifecycleEvidence = [
  'R027',
  'scripts/verify-s07-auth-e2e.sh',
  'register',
  'verify',
  'login',
  'admin dashboard',
];

const requiredCaveatLabels = [
  'credential_blocked',
  'environment_blocked',
  'deferred_major_scope',
  'frontend_nonfunctional_pending',
  'missing_operational_metrics',
  'endpoint_naming_drift',
];

const blockedDeferredGuardrails = [
  'credential_blocked',
  'environment_blocked',
  'deferred_major_scope',
];

async function readAuditReport() {
  await access(auditPath, constants.R_OK);
  return readFile(auditPath, 'utf8');
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

function assertContainsAny(haystack, needles, context) {
  const normalizedHaystack = normalizeText(haystack);
  const matchedNeedle = needles.find((needle) =>
    normalizedHaystack.includes(normalizeText(needle)),
  );

  assert.ok(
    matchedNeedle,
    `${context} is missing one of the required stable concepts: ${needles.join(', ')}`,
  );
}

test('M011/S06 audit addendum preserves R012 absence or out-of-scope coverage', async () => {
  const audit = await readAuditReport();

  assertContainsAll(audit, ['R012'], 'S06 R012 coverage');
  assertContainsAny(audit, r012AbsencePhrases, 'S06 R012 absence framing');
});

test('M011/S06 audit addendum preserves R027 mocked auth lifecycle evidence', async () => {
  const audit = await readAuditReport();

  assertContainsAll(audit, r027LifecycleEvidence, 'S06 R027 auth lifecycle coverage');
});

test('M011/S06 audit addendum preserves blocked and deferred caveat vocabulary', async () => {
  const audit = await readAuditReport();

  assertContainsAll(audit, requiredCaveatLabels, 'S06 caveat vocabulary');
});

test('M011/S06 guardrail keeps live provider and runtime promotion caveats visible', async () => {
  const audit = await readAuditReport();

  assertContainsAll(audit, blockedDeferredGuardrails, 'S06 blocked/deferred guardrails');
  assert.match(
    audit,
    /(?:live provider|provider|runtime)[\s\S]{0,320}(?:credential_blocked|environment_blocked|deferred_major_scope)/i,
    'S06 audit must keep provider/runtime caveats visible instead of promoting blocked or deferred surfaces.',
  );
});
