import assert from 'node:assert/strict';
import { execSync, execFileSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';

const projectRoot = path.resolve(import.meta.dirname, '..');
const buildDir = path.join(projectRoot, '.next');
const appDir = path.join(buildDir, 'server', 'app');

const locales = ['vi', 'en'];

// ── Helpers ──────────────────────────────────────────────────────────────────

const frontendDir = path.resolve(import.meta.dirname, '..');

function runBuild() {
  execFileSync('bun', ['run', 'build'], {
    stdio: 'inherit',
    cwd: frontendDir,
  });
}

function runTypeCheck() {
  execFileSync('bun', ['run', 'type-check'], {
    stdio: 'inherit',
    cwd: frontendDir,
  });
}

function readBuildHtml(locale) {
  const htmlPath = path.join(appDir, `${locale}.html`);
  assert.ok(existsSync(htmlPath), `Production build HTML for /${locale} must exist at ${htmlPath}. Run "bun --cwd=frontend run build" first.`);
  return readFileSync(htmlPath, 'utf8');
}

// ── Build & Type-Check ───────────────────────────────────────────────────────

test('production build exits 0', () => {
  runBuild();
});

test('type-check exits 0', () => {
  runTypeCheck();
});

// ── Navigation Landmarks (per locale) ────────────────────────────────────────

for (const locale of locales) {
  test(`/${locale} production HTML contains <header> landmark`, () => {
    const html = readBuildHtml(locale);
    assert.ok(
      /<header[\s>]/.test(html),
      `/${locale} HTML must contain a <header> element`
    );
  });

  test(`/${locale} production HTML contains <nav> landmark`, () => {
    const html = readBuildHtml(locale);
    assert.ok(
      /<nav[\s>]/.test(html),
      `/${locale} HTML must contain a <nav> element`
    );
  });

  test(`/${locale} production HTML contains <footer> landmark`, () => {
    const html = readBuildHtml(locale);
    assert.ok(
      /<footer[\s>]/.test(html),
      `/${locale} HTML must contain a <footer> element`
    );
  });
}

// ── Locale Switcher ──────────────────────────────────────────────────────────

test('production HTML contains LocaleSwitcher component', () => {
  const html = readBuildHtml('vi');
  // LocaleSwitcher is a client component ("use client") so its <select> is not
  // rendered in server HTML.  Instead verify the RSC payload includes the
  // LocaleSwitcher component reference, which proves it is wired into the build.
  assert.ok(
    /LocaleSwitcher/.test(html),
    'Production HTML must reference the LocaleSwitcher component in the RSC payload'
  );
});

// ── Navigation Links ─────────────────────────────────────────────────────────

const navKeys = ['home', 'chat', 'map', 'architecture'];

const expectedLabels = {
  vi: { home: 'Trang chủ', chat: 'Trò chuyện', map: 'Bản đồ', architecture: 'Kiến trúc' },
  en: { home: 'Home', chat: 'Chat', map: 'Map', architecture: 'Architecture' },
};

for (const locale of locales) {
  for (const key of navKeys) {
    test(`/${locale} nav link "${key}" is present in production HTML`, () => {
      const html = readBuildHtml(locale);
      const label = expectedLabels[locale][key];
      assert.ok(
        html.includes(label),
        `/${locale} HTML must contain nav link "${key}" with label "${label}"`
      );
    });
  }
}

// ── Footer copyright and tagline (vi locale, spot check) ─────────────────────

test('/vi footer contains copyright text', () => {
  const html = readBuildHtml('vi');
  assert.ok(
    /Hàm Ninh AI Guide/.test(html),
    '/vi HTML must contain "Hàm Ninh AI Guide" in footer copyright'
  );
});

test('/vi footer contains responsible AI tagline', () => {
  const html = readBuildHtml('vi');
  assert.ok(
    /AI có trách nhiệm/.test(html),
    '/vi HTML must contain responsible AI tagline "AI có trách nhiệm"'
  );
});

console.log('S02 Navigation contract test loaded — %d tests defined', 2 + 8 + 1 + 8 + 2);
