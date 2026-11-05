// The git merge driver for the files nearly every frontend branch touches
// (`.gitattributes` names them). Their conflicts are mechanical, so git
// settles them here instead of stopping a merge or a rebase for a person:
//
//   - locale: a three-way merge per key (merge-locale.ts). New keys from
//     either side merge; the same key changed differently on both sides is
//     still a conflict, with markers around that key, exit 1.
//   - route-tree: regenerated from the merged route set
//     (merge-route-tree.ts). When it cannot be, a line merge with markers,
//     exit 1.
//   - append: two branches that only inserted lines at the same spot keep
//     both, checked (merge-append.ts says what, and where it must never be
//     used). Any other conflict is git's line merge with markers, exit 1.
//
// Registered by `make setup` (merge-driver.sh install). Git calls it through
// merge-driver.sh, which falls back to a line merge when this cannot run, as
//   bun frontend/scripts/merge-driver.ts <locale|route-tree|append> %O %A %B %L %P %S %X %Y
// and reads the result from %A (our version's temporary file).

import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PARSE_MARKER_SIZE, refusal, resolveInsertions } from "./merge-append";
import { mergeLocale } from "./merge-locale";
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

function mergeLocaleFile(): number {
  let merge;
  try {
    merge = mergeLocale(read(base), read(ours), read(theirs));
  } catch (error) {
    console.error(
      `merge-driver: ${path} is not JSON on some side (${String(error)}); line merge`,
    );
    return Math.min(lineMerge(ours, base, theirs), 1);
  }
  if (merge.clean) {
    writeFileSync(ours, merge.text);
    return 0;
  }
  console.error(
    `merge-driver: ${path}: changed differently on both sides: ${merge.conflicts.join(", ")}`,
  );
  // A line merge of the three sides, each with every other key already
  // merged, marks exactly the conflicting keys.
  const scratch = mkdtempSync(join(tmpdir(), "locale-merge-"));
  try {
    writeFileSync(ours, merge.ours);
    writeFileSync(join(scratch, "base"), merge.base);
    writeFileSync(join(scratch, "theirs"), merge.theirs);
    lineMerge(ours, join(scratch, "base"), join(scratch, "theirs"));
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
  return 1;
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
    lineMerge(ours, base, theirs);
    return 1;
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
    why = await refusal(path, merge.text).catch(
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
  lineMerge(ours, base, theirs);
  return 1;
}

if (kind === "locale") process.exit(mergeLocaleFile());
else if (kind === "route-tree") process.exit(await mergeRouteTreeFile());
else if (kind === "append") process.exit(await mergeAppendFile());
else {
  console.error(`merge-driver: unknown kind ${JSON.stringify(kind)}`);
  process.exit(2);
}
