// Which locale keys the app asks for, and which locales lack them: the other
// direction from `find.ts`. i18next renders a key that no locale has as the
// key itself, and one that only some locales have in the fallback language
// (`fallbackLng`, src/i18n/index.ts). This check finds a key that is absent;
// what it takes as present is below, and it is presence only.
//
// A key is asked for by a string literal in a place that can only mean a key:
//   1. the first argument of a call to a function named `t`:
//      `t("items.heading")`, `i18n.t("items.heading")`;
//   2. an `i18nKey`, as a JSX attribute or a property:
//      `<Trans i18nKey="items.heading" />`, `{ "i18nKey": "items.heading" }`;
//   3. in either place, the static head of a template literal:
//      t(`items.columns.${column}`) asks for something under `items.columns.`;
// seen through parentheses, a type (`as const`, `satisfies`, `!`), both
// branches of a conditional and both sides of `??` and `||`:
// t(busy ? "a.busy" : "a.idle"), t(error ?? "a.fallback"). A key may carry
// the default namespace (`"translation:a.b"`), as i18next accepts it.
//
// A locale has a key when it holds it as a leaf, as a subtree (any key under
// it), or as any one plural variant (`items.count_one`); it has a head when
// one of its keys starts with it. Presence, not correctness: `t` on a subtree
// renders a placeholder, a plural base asked for without a `count` renders
// nothing useful, and a locale whose language needs `_many` (pt, es) passes
// with `_one` and `_other` alone.
//
// A literal anywhere else is not an ask, unlike in `find.ts`: `"items.form"`
// in a constant may be a key, a route or nothing. So a key kept in a field and
// handed to `t` later goes unchecked, as do the forms `find.ts` cannot see
// either: concatenation, a `t` under another name, a list of fallback keys.
// And some asks fail though i18next resolves them, with no exception list
// yet: the `context` option (the base is checked, and a locale may hold only
// `key_male`), another namespace, a key under `useTranslation`'s `keyPrefix`
// (checked whole, without the prefix: ask for the whole key), and a call to a
// local function that happens to be named `t`.
import ts from "typescript";
import {
  leafKeys,
  pluralBase,
  walk,
  withoutNamespace,
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
    (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name)) &&
    node.name.text === "i18nKey";
  return isKeyProp ? node.initializer : undefined;
}

/** Whether a binary operator hands on either side as its value. */
const isFallback = (kind: ts.SyntaxKind) =>
  kind === ts.SyntaxKind.QuestionQuestionToken ||
  kind === ts.SyntaxKind.BarBarToken;

/** The keys a node names: a literal, a template head (rule 3), or any of
 *  those through what only wraps or picks a value. Anything else names none. */
function named(node: ts.Node | undefined): Key[] {
  if (node === undefined) return [];
  if (ts.isStringLiteralLike(node)) {
    const key = withoutNamespace(node.text);
    return key ? [{ key, head: false }] : [];
  }
  if (ts.isTemplateExpression(node)) {
    const key = withoutNamespace(node.head.text);
    return key ? [{ key, head: true }] : [];
  }
  if (ts.isConditionalExpression(node)) {
    return [...named(node.whenTrue), ...named(node.whenFalse)];
  }
  if (ts.isBinaryExpression(node) && isFallback(node.operatorToken.kind)) {
    return [...named(node.left), ...named(node.right)];
  }
  const wraps =
    ts.isParenthesizedExpression(node) ||
    ts.isJsxExpression(node) ||
    ts.isAsExpression(node) ||
    ts.isSatisfiesExpression(node) ||
    ts.isNonNullExpression(node) ||
    ts.isTypeAssertionExpression(node);
  return wraps ? named(node.expression) : [];
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
      leaf === key || leaf.startsWith(`${key}.`) || pluralBase(leaf) === key,
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
