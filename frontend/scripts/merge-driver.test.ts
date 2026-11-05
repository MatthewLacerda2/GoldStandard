// @vitest-environment node
// The merge driver end to end, through git itself: throwaway repositories
// with the real .gitattributes and the drivers registered by `make setup`,
// then a merge, a rebase, a `git merge-tree` and a rebase in a linked
// worktree (how a merge queue rebases) of two branches. Each driver is shown
// to settle what git's line merge alone calls a conflict, and to still report
// a real one, with markers.

import { mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { refusal } from "./merge-append";
import {
  branch,
  dropScratch,
  ENV,
  FRONTEND,
  git,
  GIT_SPAWN_TIMEOUT_MS,
  linkScripts,
  prettierAccepts,
  read,
  repo,
  ROOT,
  run,
  runIn,
  scratch,
} from "./merge-driver-fixture";
import { generateRouteTree, routeFilesOf } from "./merge-route-tree";

const LOCALES = join(FRONTEND, "src", "i18n", "locales");
// Any locale file that exists today: the driver is per file pattern, not per language.
const LOCALE = `frontend/src/i18n/locales/${readdirSync(LOCALES).find((n) => n.endsWith(".json"))}`;
const TREE = "frontend/src/routeTree.gen.ts";

afterEach(dropScratch);

const json = (value: unknown) => `${JSON.stringify(value, null, 2)}\n`;

/** Both branches add a different key at the same spot: a line-merge conflict. */
function localeRepo(options?: { install?: boolean }) {
  const base = { common: { save: "Save", close: "Close" } };
  const dir = repo({ [LOCALE]: json(base) }, options);
  branch(dir, "ours", {
    [LOCALE]: json({
      common: { save: "Save", cancel: "Cancel", close: "Close" },
    }),
  });
  branch(dir, "theirs", {
    [LOCALE]: json({
      common: { save: "Save", retry: "Retry", close: "Close" },
    }),
  });
  return dir;
}
const MERGED_LOCALE = json({
  common: { save: "Save", cancel: "Cancel", retry: "Retry", close: "Close" },
});
// Rebased onto theirs, "ours" in the merge is theirs: their key comes first.
const REBASED_LOCALE = json({
  common: { save: "Save", retry: "Retry", cancel: "Cancel", close: "Close" },
});
const LINE_MERGED = '<<<<<<< HEAD\n    "cancel": "Cancel",\n=======';

describe("locale files", { timeout: GIT_SPAWN_TIMEOUT_MS }, () => {
  it("conflict under git's line merge without the driver (the premise)", () => {
    const dir = localeRepo({ install: false });
    git(dir, "checkout", "-q", "ours");
    expect(run(dir, "git", "merge", "theirs").status).not.toBe(0);
  });

  it("merge cleanly with `git merge`, from a subfolder, into a file Prettier accepts", async () => {
    const dir = localeRepo();
    git(dir, "checkout", "-q", "ours");
    // Git runs a driver from the top of the worktree, wherever the merge starts.
    git(join(dir, "frontend", "src"), "merge", "-q", "--no-edit", "theirs");
    expect(read(dir, LOCALE)).toBe(MERGED_LOCALE);
    expect(await prettierAccepts(read(dir, LOCALE), LOCALE)).toBe(true);
  });

  it("merge cleanly with `git merge-tree`, which merges without touching a worktree", () => {
    const dir = localeRepo();
    const treeId = git(
      dir,
      "merge-tree",
      "--write-tree",
      "ours",
      "theirs",
    ).trim();
    expect(git(dir, "show", `${treeId}:${LOCALE}`)).toBe(MERGED_LOCALE);
  });

  it("rebase cleanly with `git rebase`, and in a throwaway linked worktree", () => {
    const dir = localeRepo();
    const tree = mkdtempSync(join(tmpdir(), "merge-driver-worktree-"));
    scratch.push(tree);
    git(dir, "worktree", "add", "-q", "--detach", join(tree, "w"), "ours");
    linkScripts(join(tree, "w"));
    git(join(tree, "w"), "rebase", "-q", "theirs");
    expect(read(join(tree, "w"), LOCALE)).toBe(REBASED_LOCALE);
    git(dir, "checkout", "-q", "ours");
    git(dir, "rebase", "-q", "theirs");
    expect(read(dir, LOCALE)).toBe(REBASED_LOCALE);
  });

  it("fall back to git's line merge, markers and all, when bun is not on PATH", () => {
    // The system dirs hold git, make and sh but not bun (its installer puts it under $HOME).
    const env = { ...ENV, PATH: "/usr/bin:/bin" };
    expect(runIn(env, "/", "sh", "-c", "command -v bun").status).not.toBe(0);
    const dir = localeRepo();
    git(dir, "checkout", "-q", "ours");
    const merge = runIn(env, dir, "git", "merge", "theirs");
    expect(merge.status).not.toBe(0);
    expect(merge.output).toContain("bun is not on PATH");
    expect(read(dir, LOCALE)).toContain(LINE_MERGED);
  });

  it("fall back to git's line merge when bun fails without writing a merge", () => {
    // A bun that exits 1 at once, as a crash or a missing module would.
    const fake = mkdtempSync(join(tmpdir(), "merge-driver-fake-bun-"));
    scratch.push(fake);
    writeFileSync(join(fake, "bun"), "#!/bin/sh\nexit 1\n", { mode: 0o755 });
    const env = { ...ENV, PATH: `${fake}:/usr/bin:/bin` };
    const dir = localeRepo();
    git(dir, "checkout", "-q", "ours");
    const merge = runIn(env, dir, "git", "merge", "theirs");
    expect(merge.status).not.toBe(0);
    expect(merge.output).toContain("bun exited 1 without a merge");
    expect(read(dir, LOCALE)).toContain(LINE_MERGED);
  });

  it("still conflict, with markers around just that key, when one key gets two values", () => {
    const dir = repo({
      [LOCALE]: json({ a: { save: "Save", close: "Close" } }),
    });
    branch(dir, "ours", {
      [LOCALE]: json({ a: { save: "Store", close: "Close", o: "O" } }),
    });
    branch(dir, "theirs", {
      [LOCALE]: json({ a: { save: "Keep", close: "Close", t: "T" } }),
    });
    git(dir, "checkout", "-q", "ours");
    const merge = run(dir, "git", "merge", "theirs");
    expect(merge.status).not.toBe(0);
    expect(merge.output).toContain("a.save");
    expect(read(dir, LOCALE)).toBe(
      [
        "{",
        '  "a": {',
        "<<<<<<< HEAD",
        '    "save": "Store",',
        "=======",
        '    "save": "Keep",',
        ">>>>>>> theirs",
        '    "close": "Close",',
        '    "o": "O",',
        '    "t": "T"',
        "  }",
        "}",
        "",
      ].join("\n"),
    );

    // A rebase stops on it too; its labels ("<sha> (subject)") reach the markers whole.
    git(dir, "merge", "--abort");
    const rebase = run(dir, "git", "rebase", "theirs");
    expect(rebase.status).not.toBe(0);
    expect(read(dir, LOCALE)).toMatch(/^>>>>>>> [0-9a-f]+ \(ours\)$/m);
    expect(read(dir, LOCALE)).toContain(
      '    "save": "Keep",\n=======\n    "save": "Store",',
    );
  });
});

describe("routeTree.gen.ts", { timeout: GIT_SPAWN_TIMEOUT_MS }, () => {
  const committed = readFileSync(join(ROOT, TREE), "utf8");
  const routes = routeFilesOf(committed);
  const tree = (...added: string[]) => generateRouteTree([...routes, ...added]);
  const page = (path: string) =>
    `export const Route = createFileRoute("/${path}")({});\n`;

  /** Two branches each add a page whose lines land at the same spots of the tree. */
  async function routeRepo(options?: { install?: boolean }) {
    const dir = repo({ [TREE]: committed }, options);
    for (const [side, name] of [
      ["ours", "speed-a"],
      ["theirs", "speed-b"],
    ]) {
      branch(dir, side, {
        [TREE]: await tree(name),
        [`frontend/src/routes/${name}.tsx`]: page(name),
      });
    }
    return dir;
  }

  it("conflicts under git's line merge without the driver (the premise)", async () => {
    const dir = await routeRepo({ install: false });
    git(dir, "checkout", "-q", "ours");
    expect(run(dir, "git", "merge", "theirs").status).not.toBe(0);
  });

  it("is regenerated from both branches' routes on merge and on rebase", async () => {
    const dir = await routeRepo();
    const expected = await tree("speed-a", "speed-b");
    git(dir, "checkout", "-q", "-b", "merged", "ours");
    git(dir, "merge", "-q", "--no-edit", "theirs");
    expect(read(dir, TREE)).toBe(expected);
    git(dir, "checkout", "-q", "ours");
    git(dir, "rebase", "-q", "theirs");
    expect(read(dir, TREE)).toBe(expected);
  });

  it("fails with git's markers when it cannot be regenerated", () => {
    // No root route on any side: there is no tree to generate.
    const dir = repo({ [TREE]: "a\n" });
    branch(dir, "ours", { [TREE]: "ours\n" });
    branch(dir, "theirs", { [TREE]: "theirs\n" });
    git(dir, "checkout", "-q", "ours");
    const merge = run(dir, "git", "merge", "theirs");
    expect(merge.status).not.toBe(0);
    expect(merge.output).toContain("could not be regenerated");
    expect(read(dir, TREE)).toBe(
      "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> theirs\n",
    );
  });
});

describe("house-rule registries", { timeout: GIT_SPAWN_TIMEOUT_MS }, () => {
  const INDEX = "frontend/eslint-rules/index.ts";
  const CONFIG = "frontend/eslint.config.ts";
  const REGISTRIES = [INDEX, CONFIG];
  const BASE = Object.fromEntries(
    REGISTRIES.map((path) => [path, readFileSync(join(ROOT, path), "utf8")]),
  );
  const lastLine = (text: string, pattern: RegExp) => {
    const found = text.split("\n").filter((line) => pattern.test(line));
    expect(found.length).toBeGreaterThan(0);
    return found[found.length - 1];
  };
  // Where every new house rule lands today: after the last of each kind of line.
  const LAST_IMPORT = lastLine(BASE[INDEX], /^import /);
  const LAST_ENTRY = lastLine(BASE[INDEX], /^ {4}"[a-z-]+": \w+,$/);
  const LAST_SEVERITY = lastLine(
    BASE[CONFIG],
    /^ {6}"local\/[a-z-]+": "error",$/,
  );
  const LAST_EXEMPTION = lastLine(
    BASE[CONFIG],
    /^ {6}"local\/[a-z-]+": "off",$/,
  );

  /** `text` with `lines` inserted after every line equal to `anchor`. */
  function after(text: string, anchor: string, ...lines: string[]) {
    return text
      .split("\n")
      .flatMap((line) => (line === anchor ? [line, ...lines] : [line]))
      .join("\n");
  }

  /** What a new house rule adds, at the spots every new rule adds it. */
  function newRule(rule: string, binding: string) {
    let index = after(
      BASE[INDEX],
      LAST_IMPORT,
      `import { ${binding} } from "./${rule}";`,
    );
    index = after(index, LAST_ENTRY, `    "${rule}": ${binding},`);
    let config = after(
      BASE[CONFIG],
      LAST_SEVERITY,
      `      "local/${rule}": "error",`,
    );
    config = after(config, LAST_EXEMPTION, `      "local/${rule}": "off",`);
    return { [INDEX]: index, [CONFIG]: config };
  }

  function rulesRepo(options?: { install?: boolean }) {
    const dir = repo(BASE, options);
    branch(dir, "ours", newRule("no-adhoc-alpha", "noAdhocAlpha"));
    branch(dir, "theirs", newRule("no-adhoc-beta", "noAdhocBeta"));
    return dir;
  }

  const count = (text: string, part: string) => text.split(part).length - 1;

  /** Both rules in every spot, `first` before `second`, in files that parse and Prettier accepts. */
  async function expectBoth(
    at: (path: string) => string,
    first: string,
    second: string,
  ) {
    const [index, config] = REGISTRIES.map(at);
    for (const text of [index, config]) expect(text).not.toContain("<<<<<<<");
    expect(index.indexOf(`./${first}"`)).toBeLessThan(
      index.indexOf(`./${second}"`),
    );
    for (const rule of [first, second]) {
      expect(count(index, `"${rule}": `)).toBe(1);
      expect(count(config, `"local/${rule}": "error"`)).toBe(1);
      expect(count(config, `"local/${rule}": "off"`)).toBe(
        count(BASE[CONFIG], LAST_EXEMPTION),
      );
    }
    for (const path of REGISTRIES) {
      expect(await refusal(path, at(path))).toBeNull();
      expect(await prettierAccepts(at(path), path)).toBe(true);
    }
  }

  it("conflict under git's line merge without the driver (the premise)", () => {
    const dir = rulesRepo({ install: false });
    git(dir, "checkout", "-q", "ours");
    const merge = run(dir, "git", "merge", "theirs");
    expect(merge.status).not.toBe(0);
    for (const path of REGISTRIES)
      expect(merge.output).toContain(`conflict in ${path}`);
  });

  it("merge, rebase and merge-tree cleanly, both rules registered", async () => {
    const dir = rulesRepo();
    git(dir, "checkout", "-q", "-b", "merged", "ours");
    git(dir, "merge", "-q", "--no-edit", "theirs");
    await expectBoth(
      (path) => read(dir, path),
      "no-adhoc-alpha",
      "no-adhoc-beta",
    );

    const treeId = git(
      dir,
      "merge-tree",
      "--write-tree",
      "ours",
      "theirs",
    ).trim();
    await expectBoth(
      (path) => git(dir, "show", `${treeId}:${path}`),
      "no-adhoc-alpha",
      "no-adhoc-beta",
    );

    // Rebased onto theirs, as a branch is rebased onto main: main's rule first.
    git(dir, "checkout", "-q", "ours");
    git(dir, "rebase", "-q", "theirs");
    await expectBoth(
      (path) => read(dir, path),
      "no-adhoc-beta",
      "no-adhoc-alpha",
    );
  });

  it("still conflict, with git's markers, where a branch changed a line", () => {
    const dir = repo(BASE);
    const warn = LAST_SEVERITY.replace('"error"', '"warn"');
    branch(dir, "ours", {
      [CONFIG]: BASE[CONFIG].replace(LAST_SEVERITY, warn),
    });
    branch(dir, "theirs", newRule("no-adhoc-beta", "noAdhocBeta"));
    git(dir, "checkout", "-q", "ours");
    const merge = run(dir, "git", "merge", "theirs");
    expect(merge.status).not.toBe(0);
    expect(merge.output).toContain("not two plain insertions");
    expect(read(dir, CONFIG)).toContain(`<<<<<<< HEAD\n${warn}\n`);
  });

  it("still conflict when both branches add the same entry beside different ones", () => {
    const dir = repo(BASE);
    const shared = '    "no-adhoc-gamma": noMarkerComment,';
    const adding = (extra: string) => ({
      [INDEX]: after(
        BASE[INDEX],
        LAST_ENTRY,
        shared,
        `    "${extra}": noMarkerComment,`,
      ),
    });
    branch(dir, "ours", adding("no-adhoc-x"));
    branch(dir, "theirs", adding("no-adhoc-y"));
    git(dir, "checkout", "-q", "ours");
    const merge = run(dir, "git", "merge", "theirs");
    expect(merge.status).not.toBe(0);
    expect(merge.output).toContain(
      'both insertions configure "no-adhoc-gamma"',
    );
    expect(read(dir, INDEX)).toContain("<<<<<<< HEAD");
  });
});
