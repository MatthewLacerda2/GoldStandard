// @vitest-environment node
import { existsSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  generateRouteTree,
  mergeRouteSets,
  routeFilesOf,
} from "./merge-route-tree";

const FRONTEND = join(import.meta.dirname, "..");
const TREE = readFileSync(join(FRONTEND, "src", "routeTree.gen.ts"), "utf8");

describe("routeFilesOf", () => {
  it("reads one entry per route file the tree imports", () => {
    const files = routeFilesOf(TREE);
    expect(files.has("__root")).toBe(true);
    expect(files.size).toBe(TREE.match(/from '\.\/routes\//g)?.length);
  });
});

describe("mergeRouteSets", () => {
  const set = (...files: string[]) => new Set(files);

  it("keeps a file either side added and drops one either side deleted", () => {
    expect(
      mergeRouteSets(
        set("__root", "a", "b"),
        set("__root", "a", "ours"),
        set("__root", "b", "theirs"),
      ),
    ).toEqual(set("__root", "ours", "theirs"));
  });
});

describe("generateRouteTree", () => {
  // The premise of the driver: the tree is a function of the route paths
  // alone. If the generator ever reads more than that, or vite.config.ts's
  // router options drift from the driver's, this is what goes red.
  // 30 s: the full generator runs here, and the 5 s default timed out under load.
  it("rebuilds the committed tree from its own route set, byte for byte", async () => {
    expect(await generateRouteTree(routeFilesOf(TREE))).toBe(TREE);
  }, 30_000);

  // The generator renames each file from its tmpDir into place; left at its
  // default (<cwd>/.tanstack/tmp) that rename crosses filesystems whenever the
  // scratch directory is on another one (EXDEV on a tmpfs /tmp) and litters cwd.
  it("keeps the generator's temp files out of the working directory", async () => {
    const tmp = join(process.cwd(), ".tanstack", "tmp");
    const before = existsSync(tmp) ? statSync(tmp).mtimeMs : null;
    await generateRouteTree(["__root"]);
    expect(existsSync(tmp) ? statSync(tmp).mtimeMs : null).toBe(before);
  }, 30_000);
});
