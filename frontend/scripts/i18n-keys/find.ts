// Which locale keys the app reads, judged from its source text alone.
//
// A key counts as read when one of these holds in a source file's string
// literals (comments are not source, so a key quoted in one is not a read):
//   1. the whole dotted key is a string literal: `t("items.heading")`, or a
//      key kept in a field or prop (`labelKey: "items.heading"`);
//   2. it is a plural variant (`items.count_one`) of a key that is read:
//      code asks for the base and i18next picks the suffix from the count;
//   3. it starts with the static head of a template literal, when that head
//      is two segments or more: t(`items.columns.${column}`) reads every key
//      under `items.columns.`, t(`items.status_${s}`) every `items.status_*`;
//   4. a dotted ancestor of two segments or more is a string literal:
//      `items.form` kept in a constant and completed later, or a subtree read
//      whole.
// One segment is never enough, for an ancestor or a template head: "items"
// or `form.${name}` is as likely a query key or a DOM id as a namespace, and
// would keep a whole dead subtree alive.
//
// So the check can be wrong both ways. A literal that happens to spell a key
// keeps that key alive. And a key built in a way it does not see is reported
// though read: concatenation (`"items.columns." + c`), `useTranslation`'s
// `keyPrefix`, i18next's `context` suffix, a one-segment head. That key goes
// in `KEPT` (check-i18n-keys.ts) with the reason, or is asked for in a form
// the check reads.
import ts from "typescript";

/** A locale file's name and its parsed JSON. */
export interface Locale {
  file: string;
  tree: unknown;
}

/** A source file's name and text. */
export interface Source {
  file: string;
  text: string;
}

/** What the source text could be reading: whole string literals, and the
 *  static heads of template literals (rule 3). */
export interface Reads {
  literals: Set<string>;
  heads: string[];
}

/** A key no source reads, and the locale files that carry it. */
export interface Unused {
  key: string;
  files: string[];
}

const PLURAL_SUFFIX = /_(?:ordinal_)?(?:zero|one|two|few|many|other)$/;
// Two segments or more, optionally ending in the separator before the
// interpolation: `a.b.`, `a.b_`, `a.b`.
const KEY_HEAD = /^[\w-]+(?:\.[\w-]+)+\.?$/;

/** Whether a file under `src/` is read for keys: a test is not a reader, as
 *  a key only a test asks for is shown to nobody. */
export function isReader(path: string): boolean {
  return /\.tsx?$/.test(path) && !/\.test\.tsx?$/.test(path);
}

/** Every leaf key of a locale tree, dotted: `{a: {b: "x"}}` -> `["a.b"]`. */
export function leafKeys(tree: unknown, prefix = ""): string[] {
  if (tree === null || typeof tree !== "object" || Array.isArray(tree)) {
    return prefix ? [prefix] : [];
  }
  return Object.entries(tree).flatMap(([name, value]) =>
    leafKeys(value, prefix ? `${prefix}.${name}` : name),
  );
}

/** The string literals and template heads in `sources`, comments aside. */
export function readsIn(sources: Source[]): Reads {
  const reads: Reads = { literals: new Set(), heads: [] };
  const visit = (node: ts.Node): void => {
    if (ts.isStringLiteralLike(node)) reads.literals.add(node.text);
    else if (ts.isTemplateExpression(node) && KEY_HEAD.test(node.head.text)) {
      reads.heads.push(node.head.text);
    }
    ts.forEachChild(node, visit);
  };
  for (const { file, text } of sources) {
    visit(ts.createSourceFile(file, text, ts.ScriptTarget.Latest, false));
  }
  return reads;
}

/** Whether `key` is read, by rules 1-4 above. */
export function isRead(key: string, reads: Reads): boolean {
  const { literals, heads } = reads;
  if (literals.has(key) || literals.has(key.replace(PLURAL_SUFFIX, ""))) {
    return true;
  }
  if (heads.some((head) => key.startsWith(head))) return true;
  const parts = key.split(".");
  return parts
    .slice(2)
    .some((_, i) => literals.has(parts.slice(0, i + 2).join(".")));
}

/** The `kept` entry covering `key`: the key itself, or a namespace above it. */
function keptBy(key: string, kept: Readonly<Record<string, string>>) {
  return Object.keys(kept).find(
    (entry) => key === entry || key.startsWith(`${entry}.`),
  );
}

/** The keys of every locale that nothing reads, and the `kept` entries that
 *  are wrong: no reason, no key under them in any locale, or every key under
 *  them read anyway. */
export function judge(
  locales: Locale[],
  reads: Reads,
  kept: Readonly<Record<string, string>>,
): { unused: Unused[]; staleKept: string[] } {
  const carriers = new Map<string, string[]>();
  for (const { file, tree } of locales) {
    for (const key of leafKeys(tree)) {
      carriers.set(key, [...(carriers.get(key) ?? []), file]);
    }
  }
  const excused = new Set<string>();
  const unused: Unused[] = [];
  for (const [key, files] of carriers) {
    if (isRead(key, reads)) continue;
    const entry = keptBy(key, kept);
    if (entry === undefined) unused.push({ key, files });
    else excused.add(entry);
  }
  const staleKept = Object.entries(kept)
    .filter(([entry, why]) => !excused.has(entry) || !/\w/.test(why))
    .map(([entry]) => entry);
  return { unused, staleKept };
}
