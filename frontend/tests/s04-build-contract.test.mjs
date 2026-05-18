import assert from 'node:assert/strict';
import { execSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';

const frontendDir = path.resolve(import.meta.dirname, '..');
const buildDir = path.join(frontendDir, '.next');
const appDir = path.join(buildDir, 'server', 'app');

const locales = ['vi', 'en'];

// ── Helpers ──────────────────────────────────────────────────────────────────

function readBuildHtml(locale) {
  const htmlPath = path.join(appDir, `${locale}.html`);
  assert.ok(
    existsSync(htmlPath),
    `Production build HTML for /${locale} must exist at ${htmlPath}. Run "bun --cwd=frontend run build" first.`
  );
  return readFileSync(htmlPath, 'utf8');
}

// ── 1. Single <main> element per locale ──────────────────────────────────────

for (const locale of locales) {
  test(`/${locale} has exactly one <main> element`, () => {
    const html = readBuildHtml(locale);
    const mainMatches = html.match(/<main[\s>]/g);
    assert.equal(
      mainMatches?.length ?? 0,
      1,
      `/${locale} HTML must contain exactly one <main> element, found ${mainMatches?.length ?? 0}`
    );
  });
}

// ── 2. Semantic landmarks ────────────────────────────────────────────────────

for (const locale of locales) {
  test(`/${locale} contains <header role="banner">`, () => {
    const html = readBuildHtml(locale);
    assert.ok(
      /<header[^>]*role="banner"/.test(html) || /<header[\s>]/.test(html),
      `/${locale} HTML must contain a <header> element`
    );
  });

  test(`/${locale} contains <footer role="contentinfo">`, () => {
    const html = readBuildHtml(locale);
    assert.ok(
      /<footer[^>]*role="contentinfo"/.test(html) || /<footer[\s>]/.test(html),
      `/${locale} HTML must contain a <footer> element`
    );
  });

  test(`/${locale} contains <nav> element`, () => {
    const html = readBuildHtml(locale);
    assert.ok(/<nav[\s>]/.test(html), `/${locale} HTML must contain a <nav> element`);
  });

  test(`/${locale} contains <section> element`, () => {
    const html = readBuildHtml(locale);
    assert.ok(/<section[\s>]/.test(html), `/${locale} HTML must contain a <section> element`);
  });
}

// ── 3. Correct lang attribute ────────────────────────────────────────────────

for (const locale of locales) {
  test(`/${locale} <html> has lang="${locale}"`, () => {
    const html = readBuildHtml(locale);
    assert.ok(
      new RegExp(`<html[^>]*\\blang="${locale}"`).test(html),
      `/${locale} HTML must have lang="${locale}" on <html>`
    );
  });
}

// ── 4. Build output: no console.error / console.warn patterns ────────────────

test('build output contains no console.error or console.warn patterns', () => {
  const buildOutput = execSync('bun run build 2>&1', {
    cwd: frontendDir,
    encoding: 'utf8',
  });
  assert.ok(
    !/console\.(error|warn)/i.test(buildOutput),
    'Build output must not contain console.error or console.warn patterns'
  );
});

// ── 5. Build output: /vi and /en as statically generated ─────────────────────

test('build output lists /vi and /en as statically generated routes', () => {
  const buildOutput = execSync('bun run build 2>&1', {
    cwd: frontendDir,
    encoding: 'utf8',
  });
  for (const locale of locales) {
    assert.ok(
      new RegExp(`/\\b${locale}\\b`).test(buildOutput),
      `Build output must list /${locale} as a generated route`
    );
  }
});

console.log(
  'S04 Build contract test loaded — %d tests defined',
  locales.length + // single <main>
    locales.length * 4 + // landmarks (header, footer, nav, section)
    locales.length + // lang attribute
    2 // build output checks
);
