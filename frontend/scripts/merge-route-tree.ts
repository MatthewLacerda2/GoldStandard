// The routeTree.gen.ts half of the git merge driver (merge-driver.ts).
//
// The generated route tree is a function of one thing only: the set of route
// files under src/routes. Two branches that each add a page both insert lines
// at the same alphabetical spots of it — imports, constants, the interfaces,
// the children objects — so git reports a conflict a person would never
// resolve by hand: the right answer is to run the generator again.
//
// It cannot run against the working tree, though: git calls a merge driver
// before it writes the merged files, so src/routes on disk is still one side
// (and in `git merge-tree` it is not a side at all). Instead, each side's route
// set is read back from its own routeTree.gen.ts — every route file appears in
// it as an import of './routes/<path>' — the three sets are merged, and the
// generator runs over an empty file per route in a throwaway directory. Empty
// route files are enough: the generator scaffolds them before it reads them,
// and the tree it writes depends on their paths, not their contents
// (merge-route-tree.test.ts proves it on the real tree).

import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
// Type-only: the package is loaded on demand, so a missing node_modules fails one
// route-tree merge (which falls back to a line merge), not the locale driver too.
// merge-driver.sh runs bun with --no-install, so bun cannot fetch a generator
// of its own choosing instead of the one bun.lock pins.
import type { Config } from "@tanstack/router-plugin";

const ROUTE_IMPORT = /['"]\.\/routes\/([^'"]+)['"]/g;

/** The route files a generated tree imports, as paths under src/routes without extension. */
export function routeFilesOf(tree: string): Set<string> {
  return new Set([...tree.matchAll(ROUTE_IMPORT)].map((m) => m[1]));
}

/**
 * The three-way merge of route sets: a file either side added is in, a file
 * either side deleted is out, everything else is as both left it.
 */
export function mergeRouteSets(
  base: Set<string>,
  ours: Set<string>,
  theirs: Set<string>,
): Set<string> {
  const merged = new Set<string>();
  for (const file of new Set([...ours, ...theirs])) {
    const deletedByOne =
      base.has(file) && !(ours.has(file) && theirs.has(file));
    if (!deletedByOne) merged.add(file);
  }
  return merged;
}

/**
 * What this script uses of @tanstack/router-generator. Spelled out because
 * the package is reached through router-plugin's own dependency, not
 * declared in package.json (a second copy could be a second version).
 */
interface GeneratorModule {
  Generator: new (opts: { config: Config; root: string }) => {
    run(): Promise<void>;
  };
}

/**
 * Runs the TanStack Router generator over `files` in a scratch directory and
 * returns the tree it writes. The generator is the one @tanstack/router-plugin
 * itself depends on — the same version `vite build` runs — and the options are
 * vite.config.ts's, minus the code-splitting ones the tree does not depend on.
 */
export async function generateRouteTree(
  files: Iterable<string>,
): Promise<string> {
  const scratch = mkdtempSync(join(tmpdir(), "route-tree-merge-"));
  try {
    const routes = join(scratch, "src", "routes");
    for (const file of files) {
      const path = join(routes, `${file}.tsx`);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, "");
    }
    const output = join(scratch, "src", "routeTree.gen.ts");
    const pluginRequire = createRequire(
      import.meta.resolve("@tanstack/router-plugin"),
    );
    const { getConfig } = await import("@tanstack/router-plugin");
    const generatorUrl = pathToFileURL(
      pluginRequire.resolve("@tanstack/router-generator"),
    ).href;
    const { Generator } = (await import(generatorUrl)) as GeneratorModule;
    const config = getConfig(
      {
        target: "react",
        autoCodeSplitting: true,
        routesDirectory: routes,
        generatedRouteTree: output,
        disableLogging: true,
        // The generator writes each file to tmpDir and renames it into place. Its
        // default (TSR_TMP_DIR, else <cwd>/.tanstack/tmp) can be another filesystem
        // than the scratch directory (EXDEV when /tmp is a tmpfs); this explicit
        // option overrides both.
        tmpDir: join(scratch, ".tmp"),
      },
      scratch,
    );
    await new Generator({ config, root: scratch }).run();
    return readFileSync(output, "utf8");
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
}

/** The merged tree of three sides' trees, or a thrown error when it cannot be made. */
export async function mergeRouteTree(
  base: string,
  ours: string,
  theirs: string,
): Promise<string> {
  const merged = mergeRouteSets(
    routeFilesOf(base),
    routeFilesOf(ours),
    routeFilesOf(theirs),
  );
  if (!merged.has("__root"))
    throw new Error("the merged route set has no __root");
  return generateRouteTree(merged);
}
