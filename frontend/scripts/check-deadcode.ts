// The frontend's dead-code gate (`bun run deadcode`, run by
// `make front-deadcode`). Three checks, each reported even when another fails:
//   1. knip (`knip.ts`): files, exports and dependencies nothing uses;
//   2. the tags knip skips an export for (`deadcode/keep.ts`): only the keep
//      tag, with a reason, on an export knip would report without it;
//   3. the locale keys nothing reads, and the keys the code asks for that a
//      locale lacks (`check-i18n-keys.ts`).
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { judgeTags, reportedExports, taggedExports } from "./deadcode/keep";

const NAME = "check-deadcode";
const FRONTEND = join(import.meta.dirname, "..");
const KNIP = join(FRONTEND, "node_modules", ".bin", "knip");

const run = (command: string, args: string[]) =>
  spawnSync(command, args, { cwd: FRONTEND, stdio: "inherit" }).status === 0;

function knip(): boolean {
  // Tag hints are off: check 2 judges the `@keep` tags, reasons included.
  if (run(KNIP, ["--no-config-hints", "--no-tag-hints"])) return true;
  console.error(
    "\nDelete what knip names: the file, the `export` (or the whole symbol, if nothing in" +
      " its file uses it either), or the dependency (`bun remove <name>`). An export that" +
      " stays on purpose says why on itself: `/** @keep <why> */`. A file a tool reaches" +
      " that knip does not see is an entry in knip.ts, with the reason.\n",
  );
  return false;
}

function tags(): boolean {
  // Knip asked for the kept exports only: those it would report untagged.
  const knipRun = spawnSync(
    KNIP,
    [
      ...["--no-config-hints", "--no-exit-code", "--reporter", "json"],
      ...["--include", "exports,types", "--tags", "+keep"],
    ],
    { cwd: FRONTEND, encoding: "utf8" },
  );
  const excusing = reportedExports(knipRun.stdout ?? "");
  if (typeof excusing === "string") {
    console.error(`${NAME}: ${excusing}\n${knipRun.stderr ?? ""}`);
    return false;
  }
  // Every TypeScript file knip can read: tracked, or new and not ignored.
  const listed = spawnSync(
    "git",
    ["ls-files", "--cached", "--others", "--exclude-standard", "*.ts", "*.tsx"],
    { cwd: FRONTEND, encoding: "utf8" },
  );
  const sources = listed.stdout
    .split("\n")
    .filter(Boolean)
    .map((file) => ({
      file,
      text: readFileSync(join(FRONTEND, file), "utf8"),
    }));
  const wrong = judgeTags(taggedExports(sources), excusing);
  for (const line of wrong) console.error(`${NAME}: ${line}`);
  if (wrong.length === 0) return true;
  console.error(
    "\nAn export that stays on purpose says why on itself, once: `/** @keep <why> */`." +
      " Delete a keep tag on an export something imports now, and any @public, @beta or" +
      " @alias: knip skips those with no reason asked.\n",
  );
  return false;
}

const results = [knip(), tags(), run("bun", ["scripts/check-i18n-keys.ts"])];
if (results.includes(false)) process.exit(1);
