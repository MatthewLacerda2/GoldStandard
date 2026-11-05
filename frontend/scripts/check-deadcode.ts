// The frontend's dead-code gate (`bun run deadcode`, run by
// `make front-deadcode`). Three checks, each reported even when another fails:
//   1. knip (`knip.ts`): files, exports and dependencies nothing uses;
//   2. the `@keep` tags knip skips (`deadcode/keep.ts`): each gives a reason
//      and still excuses an export knip would report;
//   3. the locale keys nothing reads (`check-i18n-keys.ts`).
import { spawnSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { judgeKeeps, keepTags } from "./deadcode/keep";

const NAME = "check-deadcode";
const FRONTEND = join(import.meta.dirname, "..");
const KNIP = join(FRONTEND, "node_modules", ".bin", "knip");
// Where an export can live: the app, the tooling, and the config files beside
// them (node_modules and dist are never walked).
const ROOTS = ["src", "scripts", "eslint-rules"];

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

function keeps(): boolean {
  // Knip asked for the tagged exports only: those it would report untagged.
  const { stdout } = spawnSync(
    KNIP,
    [
      ...["--no-config-hints", "--no-exit-code", "--reporter", "json"],
      ...["--include", "exports,types", "--tags", "+keep"],
    ],
    { cwd: FRONTEND, encoding: "utf8" },
  );
  const report = JSON.parse(stdout) as {
    issues: {
      file: string;
      exports: { name: string }[];
      types: { name: string }[];
    }[];
  };
  const excusing = new Set(
    report.issues.flatMap(({ file, exports, types }) =>
      [...exports, ...types].map(({ name }) => `${file}#${name}`),
    ),
  );
  const files = [
    ...readdirSync(FRONTEND),
    ...ROOTS.flatMap((root) =>
      readdirSync(join(FRONTEND, root), {
        recursive: true,
        encoding: "utf8",
      }).map((file) => join(root, file)),
    ),
  ];
  const sources = files
    .filter((file) => /\.tsx?$/.test(file))
    .map((file) => ({
      file,
      text: readFileSync(join(FRONTEND, file), "utf8"),
    }));
  const wrong = judgeKeeps(keepTags(sources), excusing);
  for (const line of wrong) console.error(`${NAME}: ${line}`);
  if (wrong.length === 0) return true;
  console.error(
    "\nA @keep says why the export stays: `/** @keep <why> */`. One on an export something" +
      " imports now is deleted.\n",
  );
  return false;
}

const results = [knip(), keeps(), run("bun", ["scripts/check-i18n-keys.ts"])];
if (results.includes(false)) process.exit(1);
