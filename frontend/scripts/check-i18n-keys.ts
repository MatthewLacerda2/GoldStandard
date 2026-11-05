// The i18n part of the dead-code gate (`bun run deadcode`, run by
// `make front-deadcode`), both directions between `src/` and
// `src/i18n/locales/*.json`, each reported even when the other fails:
//   1. every locale key is read somewhere in `src/` (`i18n-keys/find.ts` says
//      what counts as a read). Knip judges files, exports and dependencies; it
//      never opens the locale JSON;
//   2. every key `src/` asks for is in every locale (`i18n-keys/ask.ts` says
//      what counts as an ask). i18next shows a key it cannot find as the key.
// A test file is neither: a key only a test asks for is shown to nobody.
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { asksIn, missingFrom } from "./i18n-keys/ask";
import { isReader, judge, readsIn } from "./i18n-keys/find";

const NAME = "check-i18n-keys";
const FRONTEND = join(import.meta.dirname, "..");
const SRC = join(FRONTEND, "src");
const LOCALES = join(SRC, "i18n", "locales");
const LOCALES_DIR = `${relative(FRONTEND, LOCALES)}/`;

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

function everyKeyRead(): boolean {
  const { unused, staleKept } = judge(locales, readsIn(sources), KEPT);
  for (const { key, files } of unused) {
    console.error(`${NAME}: ${key} (${files.join(", ")}) is read nowhere`);
  }
  for (const key of staleKept) {
    console.error(
      `${NAME}: KEPT names "${key}" without a reason, or it excuses nothing (read now, or in no locale) — give the reason or delete the entry.`,
    );
  }
  if (unused.length + staleKept.length === 0) return true;
  console.error(
    `\nDelete each unread key from every locale file in ${LOCALES_DIR}, or read it` +
      " in code. A key read in a way this check cannot see goes in KEPT" +
      " (scripts/check-i18n-keys.ts) with the reason.\n",
  );
  return false;
}

function everyAskHad(): boolean {
  const missing = missingFrom(locales, asksIn(sources));
  for (const { key, head, files, locales: lacking } of missing) {
    const asked = head ? `a key under ${key}…` : key;
    console.error(
      `${NAME}: ${asked} (asked for in ${files.join(", ")}) is missing from ${lacking.join(", ")}`,
    );
  }
  if (missing.length === 0) return true;
  console.error(
    `\nAdd each missing key to every locale file named, in ${LOCALES_DIR}, or fix the` +
      " call to ask for a key that exists. i18next shows a key it cannot find as the key" +
      " itself, or in the fallback language.\n",
  );
  return false;
}

const results = [everyKeyRead(), everyAskHad()];
if (results.includes(false)) process.exit(1);
console.log(
  `${NAME}: ${locales.length} locales, ${sources.length} source files, every key read and every key asked for there.`,
);
