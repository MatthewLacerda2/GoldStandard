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
// holds: strings, booleans, null, arrays and objects. Not on every number
// (`1e-05` against `0.00001`), but a schema's shape keeps none, so a number is
// refused and the driver takes git's line merge. Python sorts keys by code
// point, which JavaScript's default sort does not (it compares UTF-16 units),
// so the sort here is by code point too.

import {
  mergeJson,
  stringifyOrdered,
  type Json,
  type JsonMerge,
} from "./merge-locale";

/**
 * `value` with every object's keys in Python's `sorted()` order: by code
 * point, which is UTF-8 byte order (JavaScript's default sort compares UTF-16
 * units). A number throws, naming where: the writers could print it apart.
 */
function sortKeys(value: Json, at: string[] = []): Json {
  if (typeof value === "number")
    throw new TypeError(
      `a number at ${at.join(".")}: the contract holds none (openapi_contract.py SHAPE)`,
    );
  if (Array.isArray(value))
    return value.map((v, i) => sortKeys(v, [...at, `${i}`]));
  if (!(value instanceof Map)) return value;
  return new Map(
    [...value]
      .sort(([a], [b]) => Buffer.compare(Buffer.from(a), Buffer.from(b)))
      .map(([k, v]) => [k, sortKeys(v, [...at, k])]),
  );
}

/** The contract's file form, as openapi_contract.py `render` writes it. */
export const stringifyContract = (value: Json) =>
  stringifyOrdered(sortKeys(value));

/**
 * Merges three versions of the contract. Throws a SyntaxError on a side that
 * is not JSON, and a TypeError on one holding a number.
 */
export const mergeContract = (
  base: string,
  ours: string,
  theirs: string,
): JsonMerge => mergeJson(base, ours, theirs, stringifyContract);
