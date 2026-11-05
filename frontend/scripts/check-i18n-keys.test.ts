// @vitest-environment node
// `check-i18n-keys.ts` itself, run over a small project: a copy of the script
// and its helpers beside a fixture `src/`, as the script finds its tree from
// where it lives. This pins that the gate reads both directions and exits red.
import { spawnSync } from "node:child_process";
import {
  cpSync,
  mkdirSync,
  mkdtempSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterAll, describe, expect, it } from "vitest";

const FRONTEND = join(import.meta.dirname, "..");
const made: string[] = [];
afterAll(() => {
  for (const dir of made) rmSync(dir, { recursive: true, force: true });
});

/** Runs the gate over a project holding `files`, as `make front-deadcode` would. */
function gate(files: Record<string, string>) {
  const project = realpathSync(mkdtempSync(join(tmpdir(), "i18n-keys-")));
  made.push(project);
  const scripts = join(project, "scripts");
  mkdirSync(scripts);
  cpSync(
    join(FRONTEND, "scripts", "check-i18n-keys.ts"),
    join(scripts, "check-i18n-keys.ts"),
  );
  cpSync(join(FRONTEND, "scripts", "i18n-keys"), join(scripts, "i18n-keys"), {
    recursive: true,
  });
  symlinkSync(join(FRONTEND, "node_modules"), join(project, "node_modules"));
  for (const [path, text] of Object.entries(files)) {
    mkdirSync(dirname(join(project, path)), { recursive: true });
    writeFileSync(join(project, path), text);
  }
  const run = spawnSync("bun", [join(scripts, "check-i18n-keys.ts")], {
    cwd: project,
    encoding: "utf8",
  });
  return { status: run.status, stderr: run.stderr };
}

const locale = (tree: unknown) => JSON.stringify(tree);

describe("check-i18n-keys.ts", () => {
  it("fails a key the code asks for that one locale lacks, naming key, file and locale", () => {
    const { status, stderr } = gate({
      "src/i18n/locales/en.json": locale({ page: { title: "T", added: "A" } }),
      "src/i18n/locales/pt.json": locale({ page: { title: "T" } }),
      "src/page.tsx": `t("page.title"); t("page.added");`,
    });
    expect(status).toBe(1);
    expect(stderr).toContain(
      "page.added (asked for in page.tsx) is missing from pt.json",
    );
    expect(stderr).not.toContain("en.json");
  });

  it("passes when every locale has every key asked for, and each is read", () => {
    const tree = { page: { title: "T", count_one: "1", count_other: "n" } };
    const { status, stderr } = gate({
      "src/i18n/locales/en.json": locale(tree),
      "src/i18n/locales/pt.json": locale(tree),
      "src/page.tsx": `t("page.title"); t("page.count", { count });`,
    });
    expect(stderr).toBe("");
    expect(status).toBe(0);
  });
});
