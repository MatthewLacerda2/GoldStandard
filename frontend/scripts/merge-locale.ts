// The locale half of the git merge driver (merge-driver.ts): a three-way
// merge of src/i18n/locales/*.json key by key, instead of line by line.
//
// Nearly every frontend branch adds keys to the locale files, and two
// branches that each add one at the same spot conflict in git's line merge
// although nothing is in dispute. Here a key is settled on its own: what one
// side changed (added, edited, deleted) and the other left alone is taken; the
// same change on both sides is taken once; objects on both sides merge key by
// key. Only a key the two sides changed differently is a conflict, and that
// conflict still reaches a person, with git's markers around just that key.
//
// Key order is ours, with each key theirs added placed after the key that
// precedes it on their side. The text is written as JSON.stringify writes it
// with two spaces, which is Prettier's output for objects of strings
// (merge-locale.test.ts holds it to every real locale file); merge-driver.ts
// passes it through the repo's Prettier as well, which collapses a short
// array onto one line. A string's escapes are JSON.stringify's (`\u00e9`
// comes out as `é`): the same text, and Prettier accepts either.

/** An absent key — a side that does not have it (never added, or deleted). */
const ABSENT = Symbol("absent");

type Json = string | number | boolean | null | Json[] | JsonObject;
/** A Map, not a plain object: a plain object puts integer-like keys first. */
type JsonObject = Map<string, Json>;
type Side = Json | typeof ABSENT;

interface Conflict {
  conflict: true;
  base: Side;
  ours: Side;
  theirs: Side;
}
type Merged = Json | Conflict | MergedObject;
interface MergedObject {
  merged: Map<string, Merged>;
}

/** Parses JSON keeping every object's key order as written. */
export function parseOrdered(text: string): Json {
  let at = 0;
  const ws = () => {
    while (at < text.length && " \t\n\r".includes(text[at])) at++;
  };
  const fail = (what: string): never => {
    throw new SyntaxError(`${what} at offset ${at}`);
  };
  const string = (): string => {
    const start = at;
    at++;
    while (at < text.length && text[at] !== '"')
      at += text[at] === "\\" ? 2 : 1;
    if (at >= text.length) fail("unterminated string");
    at++;
    return JSON.parse(text.slice(start, at)) as string;
  };
  const value = (): Json => {
    ws();
    const c = text[at];
    if (c === "{") {
      at++;
      const object: JsonObject = new Map();
      ws();
      if (text[at] === "}") {
        at++;
        return object;
      }
      for (;;) {
        ws();
        if (text[at] !== '"') fail("expected a key");
        const key = string();
        if (object.has(key)) fail(`duplicate key ${JSON.stringify(key)}`);
        ws();
        if (text[at] !== ":") fail("expected ':'");
        at++;
        object.set(key, value());
        ws();
        if (text[at] === ",") at++;
        else if (text[at] === "}") {
          at++;
          return object;
        } else fail("expected ',' or '}'");
      }
    }
    if (c === "[") {
      at++;
      const array: Json[] = [];
      ws();
      if (text[at] === "]") {
        at++;
        return array;
      }
      for (;;) {
        array.push(value());
        ws();
        if (text[at] === ",") at++;
        else if (text[at] === "]") {
          at++;
          return array;
        } else fail("expected ',' or ']'");
      }
    }
    if (c === '"') return string();
    const literal =
      /^(?:-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)/.exec(
        text.slice(at),
      );
    if (!literal) return fail("unexpected character");
    at += literal[0].length;
    return JSON.parse(literal[0]) as Json;
  };
  const result = value();
  ws();
  if (at !== text.length) fail("trailing content");
  return result;
}

/** Writes JSON the way Prettier (and JSON.stringify with 2 spaces) writes these files. */
export function stringifyOrdered(value: Json): string {
  return `${write(value, "")}\n`;
}

function write(value: Json, indent: string): string {
  const inner = `${indent}  `;
  if (value instanceof Map) {
    if (value.size === 0) return "{}";
    const lines = [...value].map(
      ([k, v]) => `${inner}${JSON.stringify(k)}: ${write(v, inner)}`,
    );
    return `{\n${lines.join(",\n")}\n${indent}}`;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    return `[\n${value.map((v) => `${inner}${write(v, inner)}`).join(",\n")}\n${indent}]`;
  }
  return JSON.stringify(value);
}

function canonical(value: Side): string {
  if (value === ABSENT) return "\u0000absent";
  if (value instanceof Map) {
    const entries = [...value].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;
  }
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return JSON.stringify(value);
}

const same = (a: Side, b: Side) => canonical(a) === canonical(b);

function mergeValue(
  base: Side,
  ours: Side,
  theirs: Side,
): Merged | typeof ABSENT {
  if (same(ours, theirs)) return ours;
  if (same(base, ours)) return theirs;
  if (same(base, theirs)) return ours;
  if (ours instanceof Map && theirs instanceof Map) {
    return {
      merged: mergeObjects(
        base instanceof Map ? base : new Map(),
        ours,
        theirs,
      ),
    };
  }
  return { conflict: true, base, ours, theirs };
}

/** Our keys in our order, and each key only theirs has after its predecessor on their side. */
function keyOrder(
  base: JsonObject,
  ours: JsonObject,
  theirs: JsonObject,
): string[] {
  const order = [...ours.keys()];
  let anchor = -1;
  for (const key of theirs.keys()) {
    const found = order.indexOf(key);
    if (found >= 0) {
      anchor = found;
      continue;
    }
    // Keys we added right after the same anchor stay first: ours, then theirs.
    let at = anchor + 1;
    while (at < order.length && !theirs.has(order[at]) && !base.has(order[at]))
      at++;
    order.splice(at, 0, key);
    anchor = at;
  }
  return order;
}

function mergeObjects(
  base: JsonObject,
  ours: JsonObject,
  theirs: JsonObject,
): Map<string, Merged> {
  const merged = new Map<string, Merged>();
  for (const key of keyOrder(base, ours, theirs)) {
    const value = mergeValue(
      base.has(key) ? base.get(key)! : ABSENT,
      ours.has(key) ? ours.get(key)! : ABSENT,
      theirs.has(key) ? theirs.get(key)! : ABSENT,
    );
    if (value !== ABSENT) merged.set(key, value);
  }
  return merged;
}

const isConflict = (m: Merged): m is Conflict =>
  typeof m === "object" && m !== null && "conflict" in m;
const isMergedObject = (m: Merged): m is MergedObject =>
  typeof m === "object" && m !== null && "merged" in m && !(m instanceof Map);

/** The merged value with every conflict resolved to one side's value. */
function resolve(m: Merged, pick: "base" | "ours" | "theirs"): Side {
  if (isConflict(m)) return m[pick];
  if (isMergedObject(m)) {
    const object: JsonObject = new Map();
    for (const [k, v] of m.merged) {
      const r = resolve(v, pick);
      if (r !== ABSENT) object.set(k, r);
    }
    return object;
  }
  return m;
}

function conflictPaths(m: Merged, path: string[] = []): string[] {
  if (isConflict(m)) return [path.join(".")];
  if (isMergedObject(m))
    return [...m.merged].flatMap(([k, v]) => conflictPaths(v, [...path, k]));
  return [];
}

export type LocaleMerge =
  | { clean: true; text: string }
  /**
   * The same key changed differently on both sides. `ours`, `base` and
   * `theirs` are the whole merged file with every conflicting key resolved to
   * that side, so a line merge of the three marks exactly those keys.
   */
  | {
      clean: false;
      conflicts: string[];
      base: string;
      ours: string;
      theirs: string;
    };

/** Merges three versions of a locale file. Throws a SyntaxError on a file that is not JSON. */
export function mergeLocale(
  base: string,
  ours: string,
  theirs: string,
): LocaleMerge {
  // Both sides adding the same new file: git passes an empty base.
  const merged = mergeValue(
    parseOrdered(base.trim() === "" ? "{}" : base),
    parseOrdered(ours),
    parseOrdered(theirs),
  );
  const textOf = (pick: "base" | "ours" | "theirs") => {
    const side = merged === ABSENT ? ABSENT : resolve(merged, pick);
    return side === ABSENT ? "" : stringifyOrdered(side);
  };
  const conflicts = merged === ABSENT ? [] : conflictPaths(merged);
  if (conflicts.length === 0) return { clean: true, text: textOf("ours") };
  return {
    clean: false,
    conflicts,
    base: textOf("base"),
    ours: textOf("ours"),
    theirs: textOf("theirs"),
  };
}
