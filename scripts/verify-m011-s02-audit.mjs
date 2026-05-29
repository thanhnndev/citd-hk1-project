import { access, readFile } from 'node:fs/promises';
import path from 'node:path';
import { constants } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const repoRoot = path.resolve(import.meta.dirname, '..');
const auditPath = path.join(repoRoot, 'docs', 'M011-REQUIREMENTS-AUDIT.md');

const canonicalAuditIds = [
  ...Array.from({ length: 8 }, (_, index) => `REQ-${String(index + 1).padStart(2, '0')}`),
  'REQ-09A',
  'REQ-09B',
  'REQ-09C',
  'REQ-09D',
  ...Array.from({ length: 5 }, (_, index) => `REQ-${String(index + 10).padStart(2, '0')}`),
];

const requiredVerdicts = [
  'pass',
  'partial',
  'fail',
  'credential_blocked',
  'out-of-scope',
];

const requiredCaveatLabels = [
  'credential_blocked',
  'endpoint_naming_drift',
  'version_drift',
  'missing_operational_metrics',
  'prior_evidence_may_drift',
];

function normalizeText(value) {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[đĐ]/g, 'd')
    .replace(/[^\p{L}\p{N}_-]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .toLowerCase()
    .trim();
}

async function readAuditReport() {
  await access(auditPath, constants.R_OK);
  return readFile(auditPath, 'utf8');
}

test('M011/S02 audit report exists in committed docs surface', async () => {
  const audit = await readAuditReport();

  assert.ok(
    audit.trim().length > 0,
    'docs/M011-REQUIREMENTS-AUDIT.md exists but is empty.',
  );
});

test('M011/S02 audit report covers every canonical S01 audit ID', async () => {
  const audit = await readAuditReport();

  for (const auditId of canonicalAuditIds) {
    assert.match(
      audit,
      new RegExp(`\\b${auditId}\\b`),
      `Audit verdict report is missing canonical S01 audit ID: ${auditId}`,
    );
  }
});

test('M011/S02 audit report preserves required verdict vocabulary', async () => {
  const normalizedAudit = normalizeText(await readAuditReport());

  for (const verdict of requiredVerdicts) {
    assert.ok(
      normalizedAudit.includes(normalizeText(verdict)),
      `Audit verdict report is missing required verdict token: ${verdict}`,
    );
  }
});

test('M011/S02 audit report preserves required caveat labels', async () => {
  const normalizedAudit = normalizeText(await readAuditReport());

  for (const caveatLabel of requiredCaveatLabels) {
    assert.ok(
      normalizedAudit.includes(normalizeText(caveatLabel)),
      `Audit verdict report is missing required caveat label: ${caveatLabel}`,
    );
  }
});

test('M011/S02 audit report includes downstream S03 and verification sections', async () => {
  const audit = await readAuditReport();

  assert.match(
    audit,
    /^##\s+S03 Candidates\s*$/m,
    'Audit verdict report is missing the S03 bounded fix/defer candidates section.',
  );
  assert.match(
    audit,
    /^##\s+Verification Appendix\s*$/m,
    'Audit verdict report is missing the verification appendix section.',
  );
});
