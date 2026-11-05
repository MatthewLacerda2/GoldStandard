// @vitest-environment node
// Which base the baseline is compared with, and when a base that cannot be
// read fails the run (CI) rather than leaving the growth unchecked.
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { baseBaseline, baseCommit, type BaselineGate } from "./baseline-base";

// The throwaway repository is built without the machine's git config (a
// signing key, a hook path).
const ENV = {
  ...process.env,
  GIT_CONFIG_GLOBAL: "/dev/null",
  GIT_CONFIG_NOSYSTEM: "1",
  GIT_AUTHOR_NAME: "t",
  GIT_AUTHOR_EMAIL: "t@example.com",
  GIT_COMMITTER_NAME: "t",
  GIT_COMMITTER_EMAIL: "t@example.com",
};

let repo: string;
const commits: Record<string, string> = {};
const git = (...args: string[]) =>
  execFileSync("git", args, { cwd: repo, env: ENV, encoding: "utf8" }).trim();
const commit = (name: string, files: Record<string, string>) => {
  for (const [path, text] of Object.entries(files)) {
    mkdirSync(dirname(join(repo, path)), { recursive: true });
    writeFileSync(join(repo, path), text);
  }
  git("add", "-A");
  git("commit", "-q", "--allow-empty", "-m", name);
  commits[name] = git("rev-parse", "HEAD");
};
const gate = (): BaselineGate => ({
  name: "check-x",
  repo,
  baseline: "scripts/x/baseline.txt",
  script: "scripts/check-x.ts",
});

beforeAll(() => {
  vi.spyOn(console, "log").mockImplementation(() => {});
  repo = mkdtempSync(join(tmpdir(), "baseline-base-"));
  git("init", "-q");
  commit("before the gate", { "README.md": "x" });
  commit("the gate", {
    "scripts/check-x.ts": "export {};\n",
    "scripts/x/baseline.txt": "a\nb\n",
  });
  git("rm", "-q", "scripts/x/baseline.txt");
  commit("baseline gone", {});
}, 30_000);
afterAll(() => {
  rmSync(repo, { recursive: true, force: true });
  vi.restoreAllMocks();
});

describe("baseCommit", () => {
  it("is BASELINE_BASE when set", () => {
    const at = commits["the gate"];
    expect(baseCommit(gate(), { BASELINE_BASE: at })).toBe(at);
  });

  it("fails the run in CI on a BASELINE_BASE that is no commit, and says so locally", () => {
    expect(() =>
      baseCommit(gate(), { BASELINE_BASE: "no-such-ref", CI: "true" }),
    ).toThrow("check-x: BASELINE_BASE=no-such-ref is not a commit");
    expect(
      baseCommit(gate(), { BASELINE_BASE: "no-such-ref" }),
    ).toBeUndefined();
  });

  it("is the merge base with origin/main otherwise, and nothing without one", () => {
    expect(baseCommit(gate(), {})).toBeUndefined();
    expect(() => baseCommit(gate(), { CI: "true" })).toThrow("no origin/main");
    git("update-ref", "refs/remotes/origin/main", commits["the gate"]);
    expect(baseCommit(gate(), {})).toBe(commits["the gate"]);
    git("update-ref", "-d", "refs/remotes/origin/main");
  });
});

describe("baseBaseline", () => {
  it("is the baseline as the base has it", () => {
    expect(baseBaseline(gate(), commits["the gate"], {})).toBe("a\nb\n");
  });

  it("is nothing on a base that predates the gate, even in CI", () => {
    const base = commits["before the gate"];
    expect(baseBaseline(gate(), base, { CI: "true" })).toBeUndefined();
  });

  it("fails the run in CI when the base has the gate but not its baseline", () => {
    const base = commits["baseline gone"];
    expect(() => baseBaseline(gate(), base, { CI: "true" })).toThrow(
      "was the baseline moved?",
    );
    expect(baseBaseline(gate(), base, {})).toBeUndefined();
  });

  it("follows a gate this change moved back to where the base had it", () => {
    git("checkout", "-q", "-b", "moved", commits["the gate"]);
    git("mv", "scripts/check-x.ts", "scripts/check-y.ts");
    commit("script moved", {});
    const moved = { ...gate(), script: "scripts/check-y.ts" };
    // The baseline stayed: still compared, the gate's move aside.
    expect(baseBaseline(moved, commits["the gate"], {})).toBe("a\nb\n");
    git("mv", "scripts/x", "scripts/y");
    commit("baseline moved", {});
    const both = { ...moved, baseline: "scripts/y/baseline.txt" };
    expect(baseBaseline(both, commits["the gate"], {})).toBe("a\nb\n");
    // A moved gate whose baseline went is still a gate the base had: refused.
    git("rm", "-q", "scripts/y/baseline.txt");
    commit("moved and gone", {});
    const ci = { CI: "true" };
    expect(() => baseBaseline(both, commits["the gate"], ci)).toThrow(
      "was the baseline moved?",
    );
  });
});
