// The git merge driver for the files nearly every frontend branch touches
// (`.gitattributes` names them). Their conflicts are mechanical, so git
// settles them here instead of stopping a merge or a rebase for a person:
//
//   - locale: a three-way merge per key (merge-locale.ts), written as the
//     repo's Prettier writes it. New keys from either side merge; the same
//     key changed differently on both sides is still a conflict, with
//     markers around that key.
//   - route-tree: regenerated from the merged route set
//     (merge-route-tree.ts). When it cannot be, git's line merge.
//   - openapi: the contract, a three-way merge per key (merge-openapi.ts),
//     written in the contract's own sorted form, so a clean merge is what
//     `make openapi` writes. A key changed differently on both sides is still
//     a conflict, with markers around that key.
//   - append: two branches that only inserted lines at the same spot keep
//     both, checked (merge-append.ts says what, and where it must never be
//     used). Any other conflict is git's line merge.
//
// Registered by `make setup` (merge-driver.sh install). Git calls it through
// merge-driver.sh, which falls back to a line merge when this cannot run, as
//   bun --no-install frontend/scripts/merge-driver.ts <locale|openapi|route-tree|append> %O %A %B %L %P %S %X %Y
// and reads the result from %A (our version's temporary file). It exits 0
// for a clean merge in %A and CONFLICT for a conflict written into %A with
// markers; any other status means it wrote nothing, and the shell runs the
// line merge.

import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PARSE_MARKER_SIZE, refusal, resolveInsertions } from "./merge-append";
import { mergeLocale, type JsonMerge } from "./merge-locale";
import { mergeContract } from "./merge-openapi";
import { mergeRouteTree } from "./merge-route-tree";

const [kind, base, ours, theirs, markerSize, path, ...labels] =
  process.argv.slice(2);
// %S %X %Y are git's own labels for the sides; an older git leaves them unexpanded.
const label = (given: string | undefined, fallback: string) =>
  given && !given.startsWith("%") ? given : fallback;
const [baseLabel, oursLabel, theirsLabel] = [
  label(labels[0], "base"),
  label(labels[1], "ours"),
  label(labels[2], "theirs"),
];
const read = (file: string) => readFileSync(file, "utf8");

/** What merge-driver.sh reads as "a conflict, with markers, is in %A". */
const CONFLICT = 3;
/** What it reads as "nothing was written": it runs the line merge itself. */
const FAILED = 2;

/** This script's exit status for a `git merge-file` exit status. */
function outcome(status: number): number {
  if (status === 0) return 0;
  return status > 0 && status < 128 ? CONFLICT : FAILED;
}

/** `text` as the repo's Prettier writes `path`, or as is when Prettier cannot run. */
async function prettierFormat(text: string): Promise<string> {
  try {
    const prettier = await import("prettier");
    const filepath = join(process.cwd(), path);
    const options = await prettier.resolveConfig(filepath);
    return await prettier.format(text, { ...options, filepath });
  } catch {
    return text;
  }
}

/** Git's own line merge into `oursFile`; its exit status counts the conflicts. */
function lineMerge(
  oursFile: string,
  baseFile: string,
  theirsFile: string,
): number {
  const result = spawnSync(
    "git",
    [
      "merge-file",
      `--marker-size=${Number(markerSize) || 7}`,
      ...["-L", oursLabel, "-L", baseLabel, "-L", theirsLabel],
      oursFile,
      baseFile,
      theirsFile,
    ],
    { stdio: ["ignore", "ignore", "inherit"] },
  );
  return result.status ?? 1;
}

/**
 * A JSON file merged key by key by `merge`, each result written through
 * `format`. A side that is not JSON, or one `merge` cannot write, gets git's
 * line merge.
 */
async function mergeJsonFile(
  merge: (base: string, ours: string, theirs: string) => JsonMerge,
  format: (text: string) => Promise<string>,
): Promise<number> {
  let result;
  try {
    result = merge(read(base), read(ours), read(theirs));
  } catch (error) {
    console.error(
      `merge-driver: ${path}: no key-by-key merge (${String(error)}); line merge`,
    );
    return outcome(lineMerge(ours, base, theirs));
  }
  if (result.clean) {
    writeFileSync(ours, await format(result.text));
    return 0;
  }
  console.error(
    `merge-driver: ${path}: changed differently on both sides: ${result.conflicts.join(", ")}`,
  );
  // A line merge of the three sides, each with every other key already
  // merged, marks exactly the conflicting keys.
  const scratch = mkdtempSync(join(tmpdir(), "json-merge-"));
  try {
    writeFileSync(ours, await format(result.ours));
    writeFileSync(join(scratch, "base"), await format(result.base));
    writeFileSync(join(scratch, "theirs"), await format(result.theirs));
    return outcome(
      lineMerge(ours, join(scratch, "base"), join(scratch, "theirs")),
    );
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
}

async function mergeRouteTreeFile(): Promise<number> {
  try {
    writeFileSync(
      ours,
      await mergeRouteTree(read(base), read(ours), read(theirs)),
    );
    return 0;
  } catch (error) {
    console.error(
      `merge-driver: ${path} could not be regenerated (${String(error)}); line merge`,
    );
    return outcome(lineMerge(ours, base, theirs));
  }
}

async function mergeAppendFile(): Promise<number> {
  const diff3 = spawnSync(
    "git",
    [
      "merge-file",
      "-p",
      "--diff3",
      `--marker-size=${PARSE_MARKER_SIZE}`,
      ours,
      base,
      theirs,
    ],
    { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
  );
  // A clean line merge (insertions at different spots) is git's own: none of
  // merge-append.ts's checks run on it (its header says what that lets through).
  if (diff3.status === 0) {
    writeFileSync(ours, diff3.stdout);
    return 0;
  }
  const conflicted =
    diff3.status !== null && diff3.status > 0 && diff3.status < 128;
  const merge = conflicted ? resolveInsertions(diff3.stdout) : null;
  let why: string | null;
  if (merge === null) why = `git merge-file failed (${diff3.stderr.trim()})`;
  else if ("refused" in merge) why = merge.refused;
  else {
    why = await refusal(path, merge.text, merge.seams).catch(
      (error) => `unchecked: ${String(error)}`,
    );
    if (why === null) {
      writeFileSync(ours, merge.text);
      return 0;
    }
  }
  console.error(
    `merge-driver: ${path}: not two plain insertions (${why}); line merge`,
  );
  return outcome(lineMerge(ours, base, theirs));
}

if (kind === "locale")
  process.exit(await mergeJsonFile(mergeLocale, prettierFormat));
// The contract is Prettier-ignored: merge-openapi.ts writes its form whole.
else if (kind === "openapi")
  process.exit(await mergeJsonFile(mergeContract, async (text) => text));
else if (kind === "route-tree") process.exit(await mergeRouteTreeFile());
else if (kind === "append") process.exit(await mergeAppendFile());
else {
  console.error(`merge-driver: unknown kind ${JSON.stringify(kind)}`);
  process.exit(FAILED);
}
