// @vitest-environment node
// `check-i18n-keys.ts` itself, run over a small project: a copy of the script
// and its helpers beside a fixture `src/`, as the script finds its tree from
// where it lives. This pins that the gate reads both directions, reports both
// when both fail, and exits red.
import { spawnSync } from "node:child_process";
import {
  cpSync,
  mkdirSync,
  mkdtempSync,
  realpathSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  dropScratch,
  FRONTEND,
  GIT_SPAWN_TIMEOUT_MS,
  scratch,
} from "./merge-driver-fixture";

afterEach(dropScratch);

/** Runs the gate over a project holding `files`, as `make front-deadcode` would. */
function gate(files: Record<string, string>) {
  const project = realpathSync(mkdtempSync(join(tmpdir(), "i18n-keys-")));
  scratch.push(project);
  const scripts = join(project, "scripts");
  mkdirSync(scripts);
  for (const part of ["check-i18n-keys.ts", "i18n-keys"]) {
    cpSync(join(FRONTEND, "scripts", part), join(scripts, part), {
      recursive: true,
    });
  }
  symlinkSync(join(FRONTEND, "node_modules"), join(project, "node_modules"));
  for (const [path, text] of Object.entries(files)) {
    mkdirSync(dirname(join(project, path)), { recursive: true });
    writeFileSync(join(project, path), text);
  }
  const run = spawnSync("bun", [join(scripts, "check-i18n-keys.ts")], {
    cwd: project,
    encoding: "utf8",
    timeout: GIT_SPAWN_TIMEOUT_MS,
  });
  // A missing bun or a timeout says so, rather than reading as a red gate.
  expect(run.error).toBeUndefined();
  return { status: run.status, stderr: run.stderr };
}

const locale = (tree: unknown) => JSON.stringify(tree);

describe("check-i18n-keys.ts", { timeout: GIT_SPAWN_TIMEOUT_MS }, () => {
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

  it("reports an unread key and a missing key together", () => {
    const { status, stderr } = gate({
      "src/i18n/locales/en.json": locale({ page: { title: "T", gone: "G" } }),
      "src/page.tsx": `t("page.title"); t("page.typo");`,
    });
    expect(status).toBe(1);
    expect(stderr).toContain("page.gone (en.json) is read nowhere");
    expect(stderr).toContain(
      "page.typo (asked for in page.tsx) is missing from en.json",
    );
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
