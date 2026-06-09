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
  'src/components/landing/section-shell.tsx',
  'src/components/landing/hero-section.tsx',
  'src/components/landing/problem-section.tsx',
  'src/components/landing/solution-section.tsx',
  'src/components/landing/tech-stack-section.tsx',
  'src/components/landing/demo-cta-section.tsx',
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
assert.match(localeLayout, /<main\b/, 'Locale layout must expose one main landmark');
assert.equal((localeLayout.match(/<main\b/g) ?? []).length, 1, 'Locale layout must render exactly one main landmark');

const expectedLandingComponents = [
  'HeroSection',
  'ProblemSection',
  'SolutionSection',
  'TechStackSection',
  'DemoCtaSection'
];

for (const component of expectedLandingComponents) {
  assert.match(localePage, new RegExp(`import \\{ ${component} \\}`), `Locale page must import ${component}`);
  assert.match(localePage, new RegExp(`<${component}\\b`), `Locale page must render ${component}`);
}

const expectedSectionIds = [
  'hero',
  'problem',
  'solution',
  'tech-stack',
  'demo'
];

const landingComponentSource = [
  'src/components/landing/section-shell.tsx',
  'src/components/landing/hero-section.tsx',
  'src/components/landing/problem-section.tsx',
  'src/components/landing/solution-section.tsx',
  'src/components/landing/tech-stack-section.tsx',
  'src/components/landing/demo-cta-section.tsx'
]
  .map((file) => readFileSync(path.join(projectRoot, file), 'utf8'))
  .join('\n');

for (const id of expectedSectionIds) {
  assert.match(landingComponentSource, new RegExp(`id=[{]?['"]${id}['"]`), `Landing components must expose section id: ${id}`);
}

assert.doesNotMatch(localePage, /\.module\.css/, 'Locale page must not import CSS Modules');
assert.doesNotMatch(landingComponentSource, /\.module\.css/, 'Landing components must not import CSS Modules');
assert.doesNotMatch(landingComponentSource, /dangerouslySetInnerHTML/, 'Landing components must not use dangerouslySetInnerHTML');

const requiredLandingSections = [
  'hero',
  'problem',
  'solution',
  'techStack',
  'demo'
];

function describeShape(value) {
  if (Array.isArray(value)) {
    return value.map((item) => describeShape(item));
  }

  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, describeShape(value[key])])
    );
  }

  return typeof value;
}

function getPath(value, keyPath) {
  return keyPath.split('.').reduce((current, segment) => current?.[segment], value);
}

const landingMessages = Object.fromEntries(
  ['vi', 'en'].map((locale) => [
    locale,
    JSON.parse(readFileSync(path.join(projectRoot, `messages/${locale}.json`), 'utf8')).Landing
  ])
);

for (const [locale, landing] of Object.entries(landingMessages)) {
  assert.ok(landing && typeof landing === 'object' && !Array.isArray(landing), `${locale} Landing must be an object`);
  assert.deepEqual(Object.keys(landing).sort(), requiredLandingSections.toSorted(), `${locale} Landing must expose exactly the required user-facing sections`);

  for (const key of ['hero.title', 'hero.description', 'hero.ctaExplore', 'hero.ctaArchitecture']) {
    const value = getPath(landing, key);
    assert.equal(typeof value, 'string', `${locale} Landing.${key} must be a string`);
    assert.ok(value.length > 0, `${locale} Landing.${key} must not be empty`);
  }

}

assert.deepEqual(
  describeShape(landingMessages.vi),
  describeShape(landingMessages.en),
  'Vietnamese and English Landing catalogs must have matching recursive structure'
);

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
