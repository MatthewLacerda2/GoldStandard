// Which locale keys the app asks for, and which locales lack them: the other
// direction from `find.ts`. i18next renders a key that no locale has as the
// key itself, and one that only some locales have in the fallback language
// (`fallbackLng`, src/i18n/index.ts), so either way a user reads it
// untranslated and every other gate stays green.
//
// A key is asked for by a string literal in a place that can only mean a key:
//   1. the first argument of a call to `t`: `t("items.heading")`,
//      `i18n.t("items.heading")`;
//   2. an `i18nKey`, as a JSX attribute or a property:
//      `<Trans i18nKey="items.heading" />`;
//   3. in either place, the static head of a template literal:
//      t(`items.columns.${column}`) asks for something under `items.columns.`;
// through either branch of a conditional: t(busy ? "a.busy" : "a.idle").
// A locale has the key as a leaf, as a subtree (a key under it), or as a
// plural variant (`items.count_one`): code asks for the base and i18next picks
// the suffix from the count. It has a head when one of its keys starts with it.
//
// A literal anywhere else is not an ask, unlike in `find.ts`: `"items.form"`
// in a constant may be a key, a route or nothing. So a key kept in a field and
// handed to `t` later goes unchecked, as do the forms `find.ts` cannot see
// either: concatenation, a `t` under another name, a list of fallback keys,
// and the `context` option (only the base is checked). A key under
// `useTranslation`'s `keyPrefix` is checked whole, without the prefix, and
// fails: ask for the whole key.
import ts from "typescript";
import {
  leafKeys,
  PLURAL_SUFFIX,
  walk,
  type Locale,
  type Source,
} from "./find";

/** A key asked for, or the head of one (`items.columns.`). */
interface Key {
  key: string;
  head: boolean;
}

/** A key, and the files asking for it. */
export interface Ask extends Key {
  files: string[];
}

/** An asked key, and the locale files that lack it. */
export interface Missing extends Ask {
  locales: string[];
}

/** The node naming the key, when `node` asks for one (rules 1 and 2). */
function keyArgument(node: ts.Node): ts.Node | undefined {
  if (ts.isCallExpression(node)) {
    const callee = node.expression;
    const name = ts.isPropertyAccessExpression(callee) ? callee.name : callee;
    const isT = ts.isIdentifier(name) && name.text === "t";
    return isT ? node.arguments[0] : undefined;
  }
  const isKeyProp =
    (ts.isJsxAttribute(node) || ts.isPropertyAssignment(node)) &&
    ts.isIdentifier(node.name) &&
    node.name.text === "i18nKey";
  return isKeyProp ? node.initializer : undefined;
}

/** The keys a node names: a literal, a template head (rule 3), or any of
 *  those through a conditional or parentheses. Anything else names none. */
function named(node: ts.Node | undefined): Key[] {
  if (node === undefined) return [];
  if (ts.isStringLiteralLike(node)) {
    return node.text ? [{ key: node.text, head: false }] : [];
  }
  if (ts.isTemplateExpression(node)) {
    return node.head.text ? [{ key: node.head.text, head: true }] : [];
  }
  if (ts.isConditionalExpression(node)) {
    return [...named(node.whenTrue), ...named(node.whenFalse)];
  }
  if (ts.isParenthesizedExpression(node) || ts.isJsxExpression(node)) {
    return named(node.expression);
  }
  return [];
}

/** Every key `sources` ask for, each once, with the files asking. */
export function asksIn(sources: Source[]): Ask[] {
  const asks = new Map<string, Ask>();
  walk(sources, (node, file) => {
    for (const { key, head } of named(keyArgument(node))) {
      const id = `${head ? "head" : "key"} ${key}`;
      const ask = asks.get(id) ?? { key, head, files: [] };
      if (!ask.files.includes(file)) ask.files.push(file);
      asks.set(id, ask);
    }
  });
  return [...asks.values()];
}

/** Whether a locale with these leaf keys has what `ask` names. */
function has(leaves: string[], { key, head }: Key): boolean {
  if (head) return leaves.some((leaf) => leaf.startsWith(key));
  return leaves.some(
    (leaf) =>
      leaf === key ||
      leaf.startsWith(`${key}.`) ||
      leaf.replace(PLURAL_SUFFIX, "") === key,
  );
}

/** Each ask some locale lacks, with the locale files that lack it. */
export function missingFrom(locales: Locale[], asks: Ask[]): Missing[] {
  const leavesOf = locales.map(({ file, tree }) => ({
    file,
    leaves: leafKeys(tree),
  }));
  return asks.flatMap((ask) => {
    const lacking = leavesOf
      .filter(({ leaves }) => !has(leaves, ask))
      .map(({ file }) => file);
    return lacking.length > 0 ? [{ ...ask, locales: lacking }] : [];
  });
}
