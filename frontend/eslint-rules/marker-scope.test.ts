// @vitest-environment node
// `tools/markers.py` leaves the frontend files its `LAYER_LINTED` names to
// this rule, and the root completeness test takes that on trust. This holds
// ESLint to it: a new entry in `ignores`, an override turning the rule off or
// a processor would otherwise drop files from every marker check unseen.
// Files `NOT_READ` names (the generated route tree) are excused here too.
//
// It reads the config ESLint resolves, and the `check` script that runs it.
// An inline `/* eslint ... */` comment is outside both.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

const FRONTEND = join(import.meta.dirname, "..");
const ROOT = join(FRONTEND, "..");
const RULE = "local/no-marker-comment";
// ESLint reports a configured rule's severity as a number.
const SEVERITY: Record<string, string> = { 0: "off", 1: "warn", 2: "error" };

const MARKERS_PY = readFileSync(join(ROOT, "tools/markers.py"), "utf8");

/**
 * The entries of `NAME = (...)` in `tools/markers.py`. They are plain string
 * literals, so anything else in the tuple (an inline comment included) throws
 * rather than being misread; a whole-line comment is skipped.
 */
function tupleOf(name: string): string[] {
  const body = new RegExp(`^${name} = \\(([\\s\\S]*?)\\)$`, "m").exec(
    MARKERS_PY,
  )?.[1];
  const entries = (body ?? "")
    .split("\n")
    .filter((line) => !line.trim().startsWith("#"))
    .join("\n");
  if (body === undefined || !/^(\s*"[^"\\]*"\s*,?)*\s*$/.test(entries)) {
    throw new Error(`tools/markers.py: ${name} is not a tuple of strings`);
  }
  return [...entries.matchAll(/"([^"\\]*)"/g)].map((match) => match[1] ?? "");
}

/** The tracked paths `globs` match. Git matches them in `glob` magic, so
 * `GIT_GLOB_PATHSPECS` cannot change how: like Python's `full_match`, `*`
 * stops at a `/` and `**` does not. (No `exclude` magic: git drops every file
 * for an exclude shorter than the includes' common folder.) */
function trackedBy(globs: string[]): string[] {
  if (globs.length === 0) return [];
  const pathspecs = globs.map((glob) => `:(glob)${glob}`);
  return execFileSync("git", ["ls-files", "-z", "--", ...pathspecs], {
    cwd: ROOT,
    encoding: "utf8",
  })
    .split("\0")
    .filter(Boolean);
}

const claimed = tupleOf("LAYER_LINTED").filter((glob) =>
  glob.startsWith("frontend/"),
);
const excused = new Set(trackedBy(tupleOf("NOT_READ")));
const tracked = trackedBy(claimed).filter((path) => !excused.has(path));

const eslint = new ESLint({ cwd: FRONTEND });

/** What keeps the rule from reading `path` at error, or null if nothing. */
async function gap(path: string): Promise<string | null> {
  // ESLint resolves no config for a file it ignores or no `files` matches.
  const config = (await eslint.calculateConfigForFile(join(ROOT, path))) as
    { rules?: Record<string, unknown>; processor?: unknown } | undefined;
  if (!config) return "not linted: ignored, or no config matches it";
  if (config.processor) return "a processor rewrites it before the rules run";
  const [severity] = [config.rules?.[RULE] ?? "absent"].flat();
  const state = SEVERITY[String(severity)] ?? String(severity);
  return state === "error" ? null : `the rule is ${state}`;
}

const gaps = Object.fromEntries(
  (
    await Promise.all(tracked.map(async (path) => [path, await gap(path)]))
  ).filter(([, found]) => found !== null),
);

describe(`${RULE} scope`, () => {
  it("lists the frontend sources tools/markers.py leaves to ESLint", () => {
    expect(claimed).not.toEqual([]);
    expect(tracked).toContain("frontend/eslint.config.ts");
    expect(tracked).toContain("frontend/src/main.tsx");
    expect(tracked).not.toContain("frontend/src/routeTree.gen.ts");
  });

  it("is an error in each of them, with no processor", () => {
    expect(gaps).toEqual({});
  });

  it("is run over the whole folder, with no rule or ignore flags", () => {
    const { scripts } = JSON.parse(
      readFileSync(join(FRONTEND, "package.json"), "utf8"),
    ) as { scripts: Record<string, string> };
    const runs = (scripts.check ?? "").split("&&").map((step) => step.trim());
    expect(runs.filter((step) => step.startsWith("eslint"))).toEqual([
      "eslint .",
    ]);
  });
});
