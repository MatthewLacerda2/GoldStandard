// @vitest-environment node
// The OpenAPI contract's merge: its writer against the backend's (the shared
// openapi-form.json), the merge itself, and the driver end to end through git
// itself, as merge-driver.test.ts runs the others.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  branch,
  dropScratch,
  git,
  GIT_SPAWN_TIMEOUT_MS,
  read,
  repo,
  ROOT,
  run,
} from "./merge-driver-fixture";
import { mergeLocale, parseOrdered, type Json } from "./merge-locale";
import { mergeContract, stringifyContract } from "./merge-openapi";

afterEach(dropScratch);

const CONTRACT = "frontend/openapi.json";
const json = (value: unknown) => `${JSON.stringify(value, null, 2)}\n`;
/** `value` in the contract's file form. */
const contract = (value: unknown) =>
  stringifyContract(parseOrdered(json(value)));

function reversed(value: Json): Json {
  if (value instanceof Map)
    return new Map([...value].reverse().map(([k, v]) => [k, reversed(v)]));
  return Array.isArray(value) ? value.map(reversed) : value;
}

describe("stringifyContract", () => {
  it("writes the shared fixture as the backend's render does, from any key order", () => {
    // backend/tests/tools/test_openapi_contract.py holds Python to this file.
    const form = readFileSync(
      join(import.meta.dirname, "openapi-form.json"),
      "utf8",
    );
    expect(stringifyContract(reversed(parseOrdered(form)))).toBe(form);
  });

  it("sorts by code point, as Python does, not by UTF-16 unit", () => {
    // The default sort puts an emoji (a surrogate pair) before U+FF01.
    expect(["！", "😀"].sort()).toEqual(["😀", "！"]);
    expect(contract({ "😀": "", "！": "" })).toBe(json({ "！": "", "😀": "" }));
  });
});

describe("mergeContract", () => {
  it("writes two keys added at the same spot sorted, where the locale merge would not", () => {
    const sides = [
      { a: "", z: "" },
      { a: "", m: "", z: "" },
      { a: "", c: "", z: "" },
    ];
    const [base, ours, theirs] = sides.map(json);
    expect(mergeLocale(base, ours, theirs)).toEqual({
      clean: true,
      text: json({ a: "", m: "", c: "", z: "" }),
    });
    expect(mergeContract(base, ours, theirs)).toEqual({
      clean: true,
      text: json({ a: "", c: "", m: "", z: "" }),
    });
  });
});

type Contract = {
  paths: Record<string, unknown>;
  components: {
    schemas: Record<
      string,
      { properties?: Record<string, { type?: unknown }>; type?: string }
    >;
  };
};
const COMMITTED = JSON.parse(
  readFileSync(join(ROOT, CONTRACT), "utf8"),
) as Contract;

/** The committed contract with an endpoint `/<path>` answering a new schema `name`, for each pair. */
function withEndpoints(
  from: Contract,
  ...endpoints: [string, string][]
): Contract {
  const next = structuredClone(from);
  for (const [path, name] of endpoints) {
    const schema = { $ref: `#/components/schemas/${name}` };
    next.paths[`/${path}`] = {
      get: {
        responses: { "200": { content: { "application/json": { schema } } } },
      },
    };
    next.components.schemas[name] = {
      properties: { id: { type: "string" } },
      type: "object",
    };
  }
  return next;
}
const A: [string, string] = ["speed-a", "SpeedA"];
const B: [string, string] = ["speed-b", "SpeedB"];

/** Two branches each add an endpoint and its schema, at the same spots of the sorted file. */
function contractRepo(
  sides: { ours: Contract; theirs: Contract },
  options?: { install?: boolean },
) {
  const dir = repo({ [CONTRACT]: contract(COMMITTED) }, options);
  branch(dir, "ours", { [CONTRACT]: contract(sides.ours) });
  branch(dir, "theirs", { [CONTRACT]: contract(sides.theirs) });
  return dir;
}
const twoEndpoints = () => ({
  ours: withEndpoints(COMMITTED, A),
  theirs: withEndpoints(COMMITTED, B),
});

describe("openapi.json through git", { timeout: GIT_SPAWN_TIMEOUT_MS }, () => {
  it("conflicts under git's line merge without the driver (the premise)", () => {
    const dir = contractRepo(twoEndpoints(), { install: false });
    git(dir, "checkout", "-q", "ours");
    expect(run(dir, "git", "merge", "theirs").status).not.toBe(0);
  });

  it("merges, rebases and merge-trees into what `make openapi` writes for both", () => {
    const dir = contractRepo(twoEndpoints());
    const expected = contract(withEndpoints(COMMITTED, A, B));
    git(dir, "checkout", "-q", "-b", "merged", "ours");
    git(dir, "merge", "-q", "--no-edit", "theirs");
    expect(read(dir, CONTRACT)).toBe(expected);
    const treeId = git(
      dir,
      "merge-tree",
      "--write-tree",
      "ours",
      "theirs",
    ).trim();
    expect(git(dir, "show", `${treeId}:${CONTRACT}`)).toBe(expected);
    // Rebased, "ours" in the merge is theirs: still the one sorted file.
    git(dir, "checkout", "-q", "ours");
    git(dir, "rebase", "-q", "theirs");
    expect(read(dir, CONTRACT)).toBe(expected);
  });

  it("still conflicts, with markers around just that key, when one key gets two values", () => {
    const retyped = (type: string, endpoint: [string, string]) => {
      const next = withEndpoints(COMMITTED, endpoint);
      next.components.schemas.ItemRead.properties!.name.type = type;
      return next;
    };
    const dir = contractRepo({
      ours: retyped("integer", A),
      theirs: retyped("boolean", B),
    });
    git(dir, "checkout", "-q", "ours");
    const merge = run(dir, "git", "merge", "theirs");
    expect(merge.status).not.toBe(0);
    expect(merge.output).toContain(
      "components.schemas.ItemRead.properties.name.type",
    );
    const text = read(dir, CONTRACT);
    const field = (type: string) => `            "type": "${type}"\n`;
    expect(text).toContain(
      `<<<<<<< HEAD\n${field("integer")}=======\n${field("boolean")}>>>>>>> theirs\n`,
    );
    // Everything else is merged: both new schemas, outside the markers.
    expect(text.match(/^<<<<<<< /gm)).toHaveLength(1);
    for (const name of ["SpeedA", "SpeedB"])
      expect(text).toContain(`"${name}": {`);
  });

  it("falls back to git's line merge, markers and all, when a side is not JSON", () => {
    const dir = repo({ [CONTRACT]: contract(COMMITTED) });
    branch(dir, "ours", { [CONTRACT]: "not json\n" });
    branch(dir, "theirs", {
      [CONTRACT]: contract(withEndpoints(COMMITTED, B)),
    });
    git(dir, "checkout", "-q", "ours");
    const merge = run(dir, "git", "merge", "theirs");
    expect(merge.status).not.toBe(0);
    expect(merge.output).toContain("is not JSON on some side");
    expect(read(dir, CONTRACT)).toContain("<<<<<<< HEAD\nnot json\n");
  });
});
