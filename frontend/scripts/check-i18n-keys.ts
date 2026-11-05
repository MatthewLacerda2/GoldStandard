// The i18n half of the dead-code gate (`bun run deadcode`, run by
// `make front-deadcode`): every key in `src/i18n/locales/*.json` is read
// somewhere in `src/`. Knip judges files, exports and dependencies; it never
// opens the locale JSON. What counts as a read is in `i18n-keys/find.ts`. A
// test file is not a reader: a key only a test asks for is shown to nobody.
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { isReader, judge, readsIn } from "./i18n-keys/find";

const NAME = "check-i18n-keys";
const FRONTEND = join(import.meta.dirname, "..");
const SRC = join(FRONTEND, "src");
const LOCALES = join(SRC, "i18n", "locales");

/** Keys read in a way the check cannot see (`find.ts` lists the forms), each
 *  with its reason. An entry is a key or a namespace (`"items.status"` keeps
 *  every key under it). An entry without a reason, or that excuses nothing,
 *  is reported, so the list stays true. */
const KEPT: Readonly<Record<string, string>> = {};

const locales = readdirSync(LOCALES)
  .filter((name) => name.endsWith(".json"))
  .map((file) => ({
    file,
    tree: JSON.parse(readFileSync(join(LOCALES, file), "utf8")) as unknown,
  }));
const sources = readdirSync(SRC, { recursive: true, encoding: "utf8" })
  .filter(isReader)
  .map((path) => ({
    file: path,
    text: readFileSync(join(SRC, path), "utf8"),
  }));
const { unused, staleKept } = judge(locales, readsIn(sources), KEPT);

for (const { key, files } of unused) {
  console.error(`${NAME}: ${key} (${files.join(", ")}) is read nowhere`);
}
for (const key of staleKept) {
  console.error(
    `${NAME}: KEPT names "${key}" without a reason, or it excuses nothing (read now, or in no locale) — give the reason or delete the entry.`,
  );
}
if (unused.length + staleKept.length > 0) {
  console.error(
    `\nDelete each unread key from every locale file in ${relative(FRONTEND, LOCALES)}/, or read it` +
      " in code. A key read in a way this check cannot see goes in KEPT" +
      " (scripts/check-i18n-keys.ts) with the reason.",
  );
  process.exit(1);
}
console.log(
  `${NAME}: ${locales.length} locales, ${sources.length} source files, every key read.`,
);
