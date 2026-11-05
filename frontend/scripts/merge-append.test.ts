// @vitest-environment node
// The append resolver on git's diff3 output, without git: which conflicts it
// takes as "both", which it leaves to a person, and what it checks before it
// takes one. merge-driver.test.ts drives it through git end to end.

import { describe, expect, it } from "vitest";
import { refusal, resolveInsertions } from "./merge-append";

const M = 7;
const conflict = (ours: string[], base: string[], theirs: string[]) => [
  `${"<".repeat(M)} ours`,
  ...ours,
  `${"|".repeat(M)} base`,
  ...base,
  "=".repeat(M),
  ...theirs,
  `${">".repeat(M)} theirs`,
];

describe("resolveInsertions", () => {
  it("keeps both sides' insertions at one spot, ours first", () => {
    const diff3 = ["a", ...conflict(["x1", "x2"], [], ["y"]), "b", ""].join(
      "\n",
    );
    expect(resolveInsertions(diff3, M)).toMatchObject({
      text: "a\nx1\nx2\ny\nb\n",
    });
  });

  it("resolves every such conflict in the file", () => {
    const diff3 = [
      ...conflict(["x"], [], ["y"]),
      "mid",
      ...conflict(["p"], [], ["q"]),
      "",
    ];
    expect(resolveInsertions(diff3.join("\n"), M)).toMatchObject({
      text: "x\ny\nmid\np\nq\n",
    });
  });

  it("refuses a conflict where a side changed a line of the base", () => {
    const diff3 = ["a", ...conflict(["new"], ["old"], ["other"]), ""].join(
      "\n",
    );
    expect(resolveInsertions(diff3, M)).toEqual({
      refused: "line 2: a side changed or removed a line, not only added",
    });
  });

  it("refuses a conflict where a side removed a line of the base", () => {
    const diff3 = [...conflict([], ["gone"], ["gone", "added"]), ""].join("\n");
    expect(resolveInsertions(diff3, M)).toHaveProperty("refused");
  });

  it("refuses output without a base section, which it cannot judge", () => {
    const diff3 = [
      `${"<".repeat(M)} ours`,
      "x",
      "=".repeat(M),
      "y",
      `${">".repeat(M)} t`,
      "",
    ];
    expect(resolveInsertions(diff3.join("\n"), M)).toEqual({
      refused: "unreadable conflict at line 1",
    });
  });

  it("keeps one blank line where the two insertions meet, never two", () => {
    const diff3 = ["a", ...conflict(["x", ""], [], ["", "y"]), "b", ""].join(
      "\n",
    );
    expect(resolveInsertions(diff3, M)).toMatchObject({
      text: "a\nx\n\ny\nb\n",
    });
  });

  it("refuses a block xdiff slid into its neighbour", () => {
    // Base: [{ rules: { "local/a": "error" } }]. One side adds a block before
    // it, which xdiff places after the existing `rules: {`; the other adds a
    // rule there.
    const diff3 = [
      "export default [",
      "  {",
      "    rules: {",
      ...conflict(
        ['      "local/b": "error",'],
        [],
        ['      "local/n": "off",', "    },", "  },", "  {", "    rules: {"],
      ),
      '      "local/a": "error",',
      "    },",
      "  },",
      "];",
      "",
    ];
    expect(resolveInsertions(diff3.join("\n"), M)).toEqual({
      refused: "line 4: an insertion is not a balanced block",
    });
  });

  it("takes balanced blocks, brackets in strings and comments aside", () => {
    const block = (rule: string) => [
      "  {",
      `    files: ["src/${rule}-[id].tsx"], // a ( stray ] bracket`,
      `    rules: { "local/${rule}": "off" },`,
      "  },",
    ];
    const diff3 = ["[", ...conflict(block("a"), [], block("b")), "];", ""];
    expect(resolveInsertions(diff3.join("\n"), M)).toHaveProperty("text");
  });

  it("refuses two insertions that open or close with the same worded line", () => {
    const comment = "  // Rules for the new pages.";
    const opening = [
      "[",
      ...conflict([comment, "  a,"], [], [comment, "  b,"]),
      "];",
      "",
    ];
    expect(resolveInsertions(opening.join("\n"), M)).toEqual({
      refused: `line 2: both insertions open with the line "${comment.trim()}"`,
    });
    const closing = [
      "[",
      ...conflict(["  a,", "  c,"], [], ["  b,", "  c,"]),
      "",
    ];
    expect(resolveInsertions(closing.join("\n"), M)).toEqual({
      refused: 'line 2: both insertions close with the line "c,"',
    });
  });

  it("records where each side's insertion landed", () => {
    const diff3 = ["a", ...conflict(["x1", "x2"], [], ["y"]), "b", ""];
    expect(resolveInsertions(diff3.join("\n"), M)).toMatchObject({
      seams: [{ ours: [1, 3], theirs: [3, 4] }],
    });
  });

  it("does not take a shorter run of marker characters for a marker", () => {
    const diff3 = ["=======", ...conflict(["x"], [], ["y"]), ""].join("\n");
    expect(resolveInsertions(diff3, 9)).toMatchObject({ text: diff3 });
  });
});

describe("refusal", () => {
  /** Two insertions at one spot, resolved, then judged. */
  async function judged(ours: string[], theirs: string[]) {
    const diff3 = ["export default [", ...conflict(ours, [], theirs), "];", ""];
    const merge = resolveInsertions(diff3.join("\n"), M);
    if ("refused" in merge) throw new Error(merge.refused);
    return refusal("frontend/eslint.config.ts", merge.text, merge.seams);
  }
  const block = (file: string, rule: string) => [
    `  { files: ["${file}"], rules: { ${rule}: "off" } },`,
  ];

  it("refuses two insertions that set the same rule, quoted or not", async () => {
    // In a last-wins list a rebase and a merge would order them oppositely.
    for (const [rule, key] of [
      ['"local/a"', "local/a"],
      ["complexity", "complexity"],
    ]) {
      expect(await judged(block("x.tsx", rule), block("y.tsx", rule))).toBe(
        `both insertions configure ${JSON.stringify(key)}`,
      );
    }
  });

  it("takes two insertions that set different rules", async () => {
    expect(
      await judged(block("x.tsx", "complexity"), block("y.tsx", "eqeqeq")),
    ).toBeNull();
  });

  it("takes two appended config blocks as valid TypeScript", async () => {
    const merged = [
      "export default [",
      '  { files: ["a/**"], rules: { "local/a": "off" } },',
      '  { files: ["b/**"], rules: { "local/b": "off" } },',
      "];",
      "",
    ].join("\n");
    expect(await refusal("frontend/eslint.config.ts", merged)).toBeNull();
  });

  it("refuses TypeScript that no longer parses", async () => {
    const merged =
      'export default {\n  rules: {\n    "a": 1\n    "b": 2,\n  },\n};\n';
    expect(await refusal("x.ts", merged)).toMatch(/^it no longer parses: /);
  });

  it("refuses the same object key twice (both branches added that entry)", async () => {
    const merged =
      'export default { rules: { "no-a": "error", "no-a": "error" } };\n';
    expect(await refusal("x.ts", merged)).toBe(
      'the key "no-a" would appear twice',
    );
  });

  it("refuses the same import name twice", async () => {
    const merged =
      'import noA from "./no-a";\nimport noA from "./no-a";\nexport { noA };\n';
    expect(await refusal("x.ts", merged)).toBe(
      'the name "noA" would appear twice',
    );
  });

  it("refuses the same top-level name twice (both branches declared it)", async () => {
    const merged =
      'const OWNERS = ["a"];\nconst OWNERS = ["b"];\nexport { OWNERS };\n';
    expect(await refusal("x.ts", merged)).toBe(
      'the name "OWNERS" would appear twice',
    );
    const overloads =
      "function f(a: string): void;\nfunction f(a: string) {}\nexport { f };\n";
    expect(await refusal("x.ts", overloads)).toBeNull();
  });

  it("lets a getter and its setter share a name", async () => {
    const merged =
      "export const o = { get v() { return 1; }, set v(_: number) {} };\n";
    expect(await refusal("x.ts", merged)).toBeNull();
  });
});
