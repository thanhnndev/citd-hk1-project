import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';

const projectRoot = path.resolve(import.meta.dirname, '..');
const requiredFiles = [
  'postcss.config.mjs',
  'src/app/globals.css',
  'src/app/layout.tsx',
  'src/app/[locale]/layout.tsx',
  'src/app/[locale]/page.tsx',
  'messages/vi.json',
  'messages/en.json'
];

for (const file of requiredFiles) {
  assert.ok(existsSync(path.join(projectRoot, file)), `Missing required S01 foundation file: ${file}`);
}

const packageJson = JSON.parse(readFileSync(path.join(projectRoot, 'package.json'), 'utf8'));
for (const dependency of [
  '@tailwindcss/postcss',
  '@radix-ui/react-slot',
  'class-variance-authority',
  'clsx',
  'lucide-react',
  'tailwind-merge'
]) {
  assert.ok(packageJson.dependencies?.[dependency], `Missing dependency: ${dependency}`);
}

const postcssConfig = readFileSync(path.join(projectRoot, 'postcss.config.mjs'), 'utf8');
assert.match(postcssConfig, /['"]@tailwindcss\/postcss['"]/, 'PostCSS must use the Tailwind v4 plugin');

const globals = readFileSync(path.join(projectRoot, 'src/app/globals.css'), 'utf8');
assert.match(globals, /@import\s+['"]tailwindcss['"]/, 'globals.css must import Tailwind v4');
assert.match(globals, /@theme\s*{/, 'globals.css must define Tailwind v4 theme tokens');
assert.match(globals, /--color-primary:/, 'globals.css must expose shadcn-compatible color tokens');
assert.match(globals, /--radius-lg:/, 'globals.css must expose shadcn-compatible radius tokens');

const rootLayout = readFileSync(path.join(projectRoot, 'src/app/layout.tsx'), 'utf8');
assert.equal((rootLayout.match(/\.\/globals\.css/g) ?? []).length, 1, 'Root layout must import globals.css exactly once');

const localeLayout = readFileSync(path.join(projectRoot, 'src/app/[locale]/layout.tsx'), 'utf8');
assert.match(localeLayout, /NextIntlClientProvider/, 'Locale layout must provide next-intl context');
assert.match(localeLayout, /notFound\(\)/, 'Locale layout must reject invalid locales with notFound()');
assert.match(localeLayout, /routing\.locales/, 'Locale layout must validate against configured routing locales');

const localePage = readFileSync(path.join(projectRoot, 'src/app/[locale]/page.tsx'), 'utf8');
assert.match(localePage, /getTranslations\(['"]Landing['"]\)/, 'Locale page must load Landing messages');
assert.match(localePage, /notFound\(\)/, 'Locale page must reject invalid locales with notFound()');
assert.match(localePage, /id=['"]hero['"]/, 'Temporary landing page must expose the hero section anchor');

for (const locale of ['vi', 'en']) {
  const messages = JSON.parse(readFileSync(path.join(projectRoot, `messages/${locale}.json`), 'utf8'));
  for (const key of ['hero.title', 'hero.description', 'hero.ctaExplore', 'hero.ctaArchitecture']) {
    const value = key.split('.').reduce((current, segment) => current?.[segment], messages.Landing);
    assert.equal(typeof value, 'string', `${locale} Landing.${key} must be a string`);
    assert.ok(value.length > 0, `${locale} Landing.${key} must not be empty`);
  }
}

function walk(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      if (['node_modules', '.next'].includes(entry.name)) {
        return [];
      }
      return walk(fullPath);
    }
    return fullPath;
  });
}

const cssModules = walk(path.join(projectRoot, 'src')).filter((file) => file.endsWith('.module.css'));
assert.deepEqual(cssModules, [], 'S01 must not introduce CSS Modules');

console.log('S01 landing foundation contract passed');
