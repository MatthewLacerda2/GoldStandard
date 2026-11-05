// The base branch's copy of the gate's baseline: a line the base did not have
// is refused, so the gate reads the base's file from git and compares.
//
// The base is `BASELINE_BASE` when set (any commit), else the merge base with
// `origin/main` — on a push to `main` that is the commit itself, so nothing
// grows. Only the change that brings the gate has a base without it, so only
// then may the base lack the baseline; a script or a baseline this change
// moved is looked for at its old path. Any other failure to read the base
// fails the run, locally as in CI: a check that only CI makes would let the
// same commit be green here and red there.
import { execFileSync } from "node:child_process";

/** The gate's baseline, as its base is asked about it. */
export interface BaselineGate {
  /** The gate's name, opening every line it prints. */
  name: string;
  /** The repository root. */
  repo: string;
  /** The baseline file, relative to the repository root. */
  baseline: string;
  /** The gate's script, relative to the repository root: a base without it
   *  predates the gate. */
  script: string;
}

type Env = Record<string, string | undefined>;

const gitIn =
  (repo: string) =>
  (...args: string[]) =>
    execFileSync("git", args, {
      cwd: repo,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });

/** The commit the change is judged against. */
export function baseCommit(gate: BaselineGate, env: Env = process.env): string {
  const explicit = env.BASELINE_BASE;
  const git = gitIn(gate.repo);
  try {
    return explicit
      ? git("rev-parse", "--verify", `${explicit}^{commit}`).trim()
      : git("merge-base", "HEAD", "origin/main").trim();
  } catch (error) {
    throw new Error(
      explicit
        ? `${gate.name}: BASELINE_BASE=${explicit} is not a commit.`
        : `${gate.name}: no origin/main to compare the baseline with: run \`git fetch origin\`, or set BASELINE_BASE to the commit to compare with.`,
      { cause: error },
    );
  }
}

/** The baseline's text as `commit` has it, or undefined when there is none to compare. */
export function baseBaseline(
  gate: BaselineGate,
  commit: string,
): string | undefined {
  const git = gitIn(gate.repo);
  const has = (file: string) => {
    try {
      git("cat-file", "-e", `${commit}:${file}`);
      return true;
    } catch {
      return false;
    }
  };
  // A file this change moved (`git mv`, committed or staged) is looked for
  // where the base had it, so a move hides neither the gate nor its baseline.
  const movedFrom = new Map(
    git("diff", "--name-status", "-M", "--diff-filter=R", commit)
      .split("\n")
      .map((line) => line.split("\t"))
      .filter((fields) => fields.length === 3)
      .map(([, from, to]) => [to, from]),
  );
  const atBase = (file: string) =>
    [file, movedFrom.get(file)].find((path) => path !== undefined && has(path));
  const baseline = atBase(gate.baseline);
  if (baseline) return git("show", `${commit}:${baseline}`);
  if (!atBase(gate.script)) {
    console.log(
      `${gate.name}: the base has no such gate yet; nothing to compare.`,
    );
    return undefined;
  }
  throw new Error(
    `${gate.name}: the base (${commit.slice(0, 12)}) has the gate but no ${gate.baseline}: was the baseline moved?`,
  );
}
