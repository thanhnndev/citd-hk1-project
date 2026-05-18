import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const projectRoot = path.resolve(import.meta.dirname, '..');

const navKeys = ['home', 'chat', 'map', 'architecture', 'localeLabel', 'localeSwitcherLabel'];

const viNav = JSON.parse(readFileSync(path.join(projectRoot, 'messages/vi.json'), 'utf8')).Navigation;
const enNav = JSON.parse(readFileSync(path.join(projectRoot, 'messages/en.json'), 'utf8')).Navigation;

// Namespace must exist and be an object
assert.ok(viNav && typeof viNav === 'object' && !Array.isArray(viNav), 'vi Navigation must be an object');
assert.ok(enNav && typeof enNav === 'object' && !Array.isArray(enNav), 'en Navigation must be an object');

// Must expose exactly the required keys
assert.deepEqual(Object.keys(viNav).sort(), navKeys.toSorted(), 'vi Navigation must expose the required keys');
assert.deepEqual(Object.keys(enNav).sort(), navKeys.toSorted(), 'en Navigation must expose the required keys');

// All values must be non-empty strings
for (const [locale, nav] of Object.entries({ vi: viNav, en: enNav })) {
  for (const key of navKeys) {
    const value = nav[key];
    assert.equal(typeof value, 'string', `${locale} Navigation.${key} must be a string`);
    assert.ok(value.length > 0, `${locale} Navigation.${key} must not be empty`);
  }
}

// Verify expected Vietnamese values
const expectedVi = {
  home: 'Trang chủ',
  chat: 'Trò chuyện',
  map: 'Bản đồ',
  architecture: 'Kiến trúc',
  localeLabel: 'Ngôn ngữ',
  localeSwitcherLabel: 'Chọn ngôn ngữ'
};
assert.deepEqual(viNav, expectedVi, 'vi Navigation values must match expected Vietnamese translations');

// Verify expected English values
const expectedEn = {
  home: 'Home',
  chat: 'Chat',
  map: 'Map',
  architecture: 'Architecture',
  localeLabel: 'Language',
  localeSwitcherLabel: 'Select language'
};
assert.deepEqual(enNav, expectedEn, 'en Navigation values must match expected English translations');

console.log('S02 Navigation catalog contract passed');
