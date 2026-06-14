import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactCompiler from "eslint-plugin-react-compiler";
import betterTailwind from "eslint-plugin-better-tailwindcss";
import local from "./eslint-rules/index";

// Classes that are legitimately not Tailwind utilities (e.g. structural hooks),
// so the color allowlist rule must not flag them as unregistered.
const NON_TAILWIND_CLASSES = ["^dark$", "^group($|/)", "^peer($|/)"];

export default tseslint.config(
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "src/routeTree.gen.ts",
      "vite.config.ts",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  // App + plugin source.
  {
    files: ["**/*.{ts,tsx}"],
    plugins: {
      local,
      "react-compiler": reactCompiler,
      "better-tailwindcss": betterTailwind,
    },
    settings: {
      "better-tailwindcss": {
        entryPoint: "src/styles.css",
      },
    },
    rules: {
      // --- Local design-system rules: all ERROR. ---
      "local/one-exported-component-per-file": "error",
      "local/no-arbitrary-text": "error",
      "local/no-legacy-text-scale": "error",
      "local/no-color-literal": "error",
      "local/no-hand-rolled-form-control": "error",
      "local/no-redundant-font-utility": "error",

      // --- Color allowlist via the real theme. ---
      "better-tailwindcss/no-unregistered-classes": [
        "error",
        { ignore: NON_TAILWIND_CLASSES },
      ],

      // --- TypeScript hygiene. ---
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-shadow": "error",
      "no-shadow": "off",

      // --- React Compiler. ---
      "react-compiler/react-compiler": "warn",

      // --- File length. ---
      "max-lines": ["error", { max: 550, skipBlankLines: false }],
    },
  },
  // mock-*.ts files are exempt from max-lines.
  {
    files: ["**/mock-*.ts"],
    rules: { "max-lines": "off" },
  },
  // components/ui primitives are vendored shadcn code: exempt from the
  // design-system, one-component, and color-allowlist rules.
  {
    files: ["src/components/ui/**"],
    rules: {
      "local/one-exported-component-per-file": "off",
      "local/no-hand-rolled-form-control": "off",
      "local/no-arbitrary-text": "off",
      "local/no-legacy-text-scale": "off",
      "local/no-color-literal": "off",
      "local/no-redundant-font-utility": "off",
      "better-tailwindcss/no-unregistered-classes": "off",
    },
  },
  // ESLint rule sources and their tests are Node modules, not DOM/Tailwind code.
  {
    files: ["eslint-rules/**"],
    rules: {
      "better-tailwindcss/no-unregistered-classes": "off",
      "local/no-hand-rolled-form-control": "off",
      "local/no-color-literal": "off",
    },
  },
);
