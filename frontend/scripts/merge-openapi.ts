// The OpenAPI-contract half of the git merge driver (merge-driver.ts): a
// three-way merge of frontend/openapi.json key by key, instead of line by line.
//
// Every branch that changes an API answer rewrites the contract (`make
// openapi`), and two such branches conflict there on every rebase although
// each only added or changed its own paths and schemas. The merge is the
// locale files' (merge-locale.ts `mergeJson`): what one side changed and the
// other left alone is taken, and a key the two changed differently is still a
// conflict, with markers around just that key.
//
// What differs is the writer. The contract has one form, the one
// backend/tools/openapi_contract.py `render` writes: keys sorted at every
// level, two-space indent, a final newline. The merge is written back in that
// form, so a clean merge is byte for byte what `make openapi` writes for the
// merged backend, and the next `make openapi` moves no line. Keeping ours'
// key order, as the locale merge does, would leave two keys added at the same
// spot unsorted. A shared fixture (openapi-form.json) holds this writer and
// the Python one to the same bytes, from both test suites.
//
// The merge cannot know the backend, so `make back-build` still judges the
// result: a schema one side stopped using and deleted, while the other side
// started using it, merges as deleted, and that build names the fix.
//
// Python's `json.dumps` and this writer agree on everything the contract
// holds: strings, booleans, null, arrays and objects (no numbers: a schema's
// shape keeps none). Python sorts keys by code point, which JavaScript's
// default sort does not (it compares UTF-16 units), so the sort here is by
// code point too.

import {
  mergeJson,
  stringifyOrdered,
  type Json,
  type JsonMerge,
} from "./merge-locale";

/** Python's `sorted()` order for strings: by code point, not by UTF-16 unit. */
function byCodePoint(a: string, b: string): number {
  const [x, y] = [a, b].map((s) => Array.from(s, (c) => c.codePointAt(0)!));
  for (let i = 0; i < Math.min(x.length, y.length); i++)
    if (x[i] !== y[i]) return x[i] - y[i];
  return x.length - y.length;
}

function sortKeys(value: Json): Json {
  if (value instanceof Map)
    return new Map(
      [...value]
        .sort(([a], [b]) => byCodePoint(a, b))
        .map(([k, v]) => [k, sortKeys(v)]),
    );
  return Array.isArray(value) ? value.map(sortKeys) : value;
}

/** The contract's file form, as openapi_contract.py `render` writes it. */
export const stringifyContract = (value: Json) =>
  stringifyOrdered(sortKeys(value));

/** Merges three versions of the contract. Throws a SyntaxError on a side that is not JSON. */
export const mergeContract = (
  base: string,
  ours: string,
  theirs: string,
): JsonMerge => mergeJson(base, ours, theirs, stringifyContract);
