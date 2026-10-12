/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import babel from "@rolldown/plugin-babel";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";

export default defineConfig({
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    // plugin-react v6 no longer runs Babel itself: the React Compiler is a
    // separate Babel pass. The Rust (`compiler: true`) path is experimental,
    // so we stay on Babel.
    babel({ presets: [reactCompilerPreset()] }),
    tailwindcss(),
  ],
  // Vite resolves tsconfig `paths` (the `@/` alias) itself.
  resolve: { tsconfigPaths: true },
  test: {
    globals: true,
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}", "eslint-rules/**/*.test.ts"],
  },
});
