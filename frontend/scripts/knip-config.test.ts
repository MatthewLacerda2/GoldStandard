// @vitest-environment node
// `knip.ts` run on a small project: what it must flag and what it must pass.
// Knip's own analysis is knip's to test; this pins the policy the config
// adds, and that the gate finds anything at all (an empty scan stays green).
import { execFileSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterAll, describe, expect, it } from "vitest";

const FRONTEND = join(import.meta.dirname, "..");
const KNIP = join(FRONTEND, "node_modules", ".bin", "knip");

// The real path: knip loses imports under a symlinked temp dir (macOS /var).
const project = realpathSync(mkdtempSync(join(tmpdir(), "knip-config-")));
afterAll(() => rmSync(project, { recursive: true, force: true }));

const files: Record<string, string> = {
  "package.json": `{ "name": "fixture", "type": "module" }`,
  "scripts/run.ts": `import { used } from "./lib/used";\nused();\n`,
  "scripts/lib/used.ts": [
    "export function used() { return inFile(); }",
    "export function inFile() { return 1; }",
    "export function dead() {}",
    "/** @keep a reason */",
    "export function kept() {}",
  ].join("\n"),
  "scripts/lib/orphan.ts": "export const orphan = 1;\n",
  "src/components/ui/primitive.tsx": "export const Part = 1;\n",
};
for (const [path, text] of Object.entries(files)) {
  mkdirSync(dirname(join(project, path)), { recursive: true });
  writeFileSync(join(project, path), text);
}

interface Report {
  issues: { file: string; files: unknown[]; exports: { name: string }[] }[];
}
const report = JSON.parse(
  execFileSync(KNIP, [
    ...["--directory", project, "--config", join(FRONTEND, "knip.ts")],
    ...["--no-config-hints", "--no-exit-code", "--reporter", "json"],
  ]).toString(),
) as Report;
const unusedFiles = report.issues
  .filter((issue) => issue.files.length > 0)
  .map((issue) => issue.file);
const unusedExports = report.issues.flatMap((issue) =>
  issue.exports.map((e) => `${issue.file}#${e.name}`),
);

describe("knip.ts", () => {
  it("flags a file nothing imports and an export nothing imports", () => {
    expect(unusedFiles).toEqual(["scripts/lib/orphan.ts"]);
    expect(unusedExports).toEqual(["scripts/lib/used.ts#dead"]);
  });

  it("passes a script, a ui primitive, an export used in its file and a @keep", () => {
    expect(unusedFiles).not.toContain("scripts/run.ts");
    expect(unusedFiles).not.toContain("src/components/ui/primitive.tsx");
    expect(unusedExports).not.toContain("scripts/lib/used.ts#inFile");
    expect(unusedExports).not.toContain("scripts/lib/used.ts#kept");
  });
});
