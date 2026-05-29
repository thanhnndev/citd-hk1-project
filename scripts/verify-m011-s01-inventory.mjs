import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const repoRoot = path.resolve(import.meta.dirname, '..');
const requirementsPath = path.join(repoRoot, 'docs', 'REQUIREMENTS.md');
const inventoryPath = path.join(repoRoot, 'docs', 'M011-S01-REQUIREMENTS-EVIDENCE-INVENTORY.md');

const expectedCoveredSections = Array.from({ length: 13 }, (_, index) => index + 1);
const requiredCaveatMarkers = [
  'credential_blocked',
  'admin/embed',
  'admin/ingest',
  'version drift',
  'needs current test run',
];

function normalizeText(value) {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[đĐ]/g, 'd')
    .replace(/[^\p{L}\p{N}/]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .toLowerCase()
    .trim();
}

function extractMajorRequirementSections(markdown) {
  const sections = new Map();
  const headingPattern = /^##\s+(\d+)\.\s+(.+)$/gm;

  for (const match of markdown.matchAll(headingPattern)) {
    const sectionNumber = Number.parseInt(match[1], 10);
    sections.set(sectionNumber, match[2].trim());
  }

  return sections;
}

function inventoryCoversSection(inventory, sectionNumber, sectionTitle) {
  const normalizedInventory = normalizeText(inventory);
  const titleTokens = normalizeText(sectionTitle).split(' ').filter(Boolean);
  const auditId = `req ${String(sectionNumber).padStart(2, '0')}`;

  return normalizedInventory.includes(auditId)
    && titleTokens.every((token) => normalizedInventory.includes(token));
}

test('M011/S01 inventory covers canonical requirement sections 1 through 13', async () => {
  const [requirements, inventory] = await Promise.all([
    readFile(requirementsPath, 'utf8'),
    readFile(inventoryPath, 'utf8'),
  ]);
  const sections = extractMajorRequirementSections(requirements);

  for (const sectionNumber of expectedCoveredSections) {
    const sectionTitle = sections.get(sectionNumber);
    assert.ok(
      sectionTitle,
      `docs/REQUIREMENTS.md is missing major section ${sectionNumber}; update verifier expectations if requirements changed.`,
    );
    assert.ok(
      inventoryCoversSection(inventory, sectionNumber, sectionTitle),
      `Inventory is missing coverage for requirement section ${sectionNumber}: ${sectionTitle}`,
    );
  }
});

test('M011/S01 inventory preserves key caveat vocabulary for honest S02 verdicting', async () => {
  const inventory = await readFile(inventoryPath, 'utf8');
  const normalizedInventory = normalizeText(inventory);

  for (const marker of requiredCaveatMarkers) {
    assert.ok(
      normalizedInventory.includes(normalizeText(marker)),
      `Inventory is missing required caveat marker: ${marker}`,
    );
  }
});
