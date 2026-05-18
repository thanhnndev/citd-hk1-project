import nextPlugin from "@next/eslint-plugin-next";
import eslintJs from "@eslint/js";
import tsParser from "typescript-eslint";
import globals from "globals";

/** @type {import("eslint").Linter.FlatConfig[]} */
export default [
  // Ignore build output and node_modules
  { ignores: ["node_modules/**", ".next/**", "out/**"] },

  // Base JS recommended rules
  eslintJs.configs.recommended,

  // TypeScript support (non-type-checked — fast, avoids blocking on TS errors)
  ...tsParser.configs.recommended,

  // React + Next.js rules
  {
    files: ["**/*.{js,jsx,mjs,ts,tsx}"],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
        ...globals.es2025,
      },
      parser: tsParser.parser,
    },
    plugins: {
      "@next/next": nextPlugin,
    },
    rules: {
      // Next.js recommended + core-web-vitals
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,
      // Allow underscore-prefixed unused vars (e.g. _locale)
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
];
