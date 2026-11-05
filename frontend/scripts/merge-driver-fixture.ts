// The scaffolding of the merge driver's end-to-end tests (merge-driver.test.ts):
// throwaway repositories holding the real .gitattributes, with the drivers
// registered by the real `make setup` and this checkout's scripts linked in.
// Nothing here reads or writes this clone's own git config. Each test file
// calls `afterEach(dropScratch)`.

import { spawnSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import * as prettier from "prettier";
import { expect } from "vitest";

export const FRONTEND = join(import.meta.dirname, "..");
export const ROOT = join(FRONTEND, "..");

// No git, make or user config leaks in: a hook or another make may be running
// this, and its GIT_DIR would point every command below at this clone.
const inherited = Object.fromEntries(
  Object.entries(process.env).filter(
    ([name]) =>
      !name.startsWith("GIT_") &&
      !["MAKEFLAGS", "MAKELEVEL", "MFLAGS"].includes(name),
  ),
);
export const ENV: NodeJS.ProcessEnv = {
  ...inherited,
  GIT_CONFIG_GLOBAL: "/dev/null",
  GIT_CONFIG_NOSYSTEM: "1",
  GIT_AUTHOR_NAME: "t",
  GIT_AUTHOR_EMAIL: "t@example.com",
  GIT_COMMITTER_NAME: "t",
  GIT_COMMITTER_EMAIL: "t@example.com",
  GIT_EDITOR: "true",
};

// Every test builds throwaway repositories and spawns git, sh and bun (the
// driver itself runs bun, and regenerating the tree runs the router
// generator): a second or so alone, several times that on a loaded machine,
// so each describe gets this budget instead of the 5 s default.
export const GIT_SPAWN_TIMEOUT_MS = 60_000;

export const scratch: string[] = [];
export function dropScratch() {
  for (const dir of scratch.splice(0))
    rmSync(dir, { recursive: true, force: true });
}

export function run(cwd: string, command: string, ...args: string[]) {
  return runIn(ENV, cwd, command, ...args);
}

export function runIn(
  env: NodeJS.ProcessEnv,
  cwd: string,
  command: string,
  ...args: string[]
) {
  const result = spawnSync(command, args, { cwd, env, encoding: "utf8" });
  return { status: result.status, output: `${result.stdout}${result.stderr}` };
}

export function git(cwd: string, ...args: string[]) {
  const result = run(cwd, "git", ...args);
  if (result.status !== 0)
    throw new Error(`git ${args.join(" ")}: ${result.output}`);
  return result.output;
}

/** Links this checkout's scripts into the worktree `dir`, untracked, where the driver runs them. */
export function linkScripts(dir: string) {
  mkdirSync(join(dir, "frontend"), { recursive: true });
  symlinkSync(join(FRONTEND, "scripts"), join(dir, "frontend", "scripts"));
}

/** A repository on `main` holding `files`, with `make setup` run in it unless told not to. */
export function repo(files: Record<string, string>, { install = true } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "merge-driver-test-"));
  scratch.push(dir);
  git(dir, "init", "-q", "-b", "main");
  linkScripts(dir);
  writeFileSync(join(dir, ".git", "info", "exclude"), "frontend/scripts\n");
  if (install) {
    // The real target, run from the scratch repository: its `git config`
    // lands there. It also points core.hooksPath at a .githooks/ this
    // repository does not have, so no hook runs.
    const setup = run(
      dir,
      "make",
      "--no-print-directory",
      "-f",
      join(ROOT, "Makefile"),
      "setup",
    );
    expect(setup.status, setup.output).toBe(0);
  }
  write(dir, {
    ".gitattributes": readFileSync(join(ROOT, ".gitattributes"), "utf8"),
    ...files,
  });
  git(dir, "add", "-A");
  git(dir, "commit", "-q", "-m", "base");
  return dir;
}

export function write(dir: string, files: Record<string, string>) {
  for (const [path, content] of Object.entries(files)) {
    mkdirSync(dirname(join(dir, path)), { recursive: true });
    writeFileSync(join(dir, path), content);
  }
}

export function branch(
  dir: string,
  name: string,
  files: Record<string, string>,
) {
  git(dir, "checkout", "-q", "-b", name, "main");
  write(dir, files);
  git(dir, "add", "-A");
  git(dir, "commit", "-q", "-m", name);
  git(dir, "checkout", "-q", "main");
}

export const read = (dir: string, path: string) =>
  readFileSync(join(dir, path), "utf8");

export async function prettierAccepts(
  text: string,
  path: string,
): Promise<boolean> {
  const filepath = join(ROOT, path);
  const options = await prettier.resolveConfig(filepath);
  return prettier.check(text, { ...options, filepath });
}
