import type { KnipConfig } from "knip";

// The whole-program half of the dead-code gate (`bun run deadcode`, run by
// `make front-deadcode`): files nothing imports, exports nothing imports, and
// dependencies nothing uses. ESLint and tsc only see one file at a time.
//
// Most entry points come from knip's plugins, which read this repo's own
// config: vite (index.html -> src/main.tsx), TanStack Router (the generated
// src/routeTree.gen.ts, which imports every file route, so a route file it
// does not list is reported), eslint (eslint.config.ts -> eslint-rules/),
// vitest (every *.test.ts) and package.json's scripts. An entry file's own
// exports are never reported; what it imports is followed.
const config: KnipConfig = {
  entry: [
    // Run directly (`bun scripts/<name>.ts`), whether package.json names them
    // or not. Their helper modules in subfolders are judged like any other.
    "scripts/*.ts",
    // Vendored shadcn primitives keep their whole API, the parts nothing uses
    // yet included: they are added with `bunx shadcn add`, never trimmed.
    "src/components/ui/**",
  ],
  // An export used in its own file is alive; whether it needs `export` is a
  // style question, not dead code.
  ignoreExportsUsedInFile: true,
  // The exception, written on the export itself with its reason:
  //   /** @keep <why nothing imports it yet, and why it stays> */
  tags: ["-keep"],
};

export default config;
