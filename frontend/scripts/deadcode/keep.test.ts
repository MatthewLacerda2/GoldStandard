// @vitest-environment node
import { describe, expect, it } from "vitest";
import { judgeTags, reportedExports, taggedExports } from "./keep";

const judge = (text: string, excusing: string[] = []) =>
  judgeTags(
    taggedExports([{ file: "src/a.ts", text }]),
    new Set(excusing.map((name) => `src/a.ts#${name}`)),
  ).map((line) => line.replace(/^src\/a\.ts:\d+: /, ""));

describe("judgeTags", () => {
  it("passes a reasoned keep tag on an export knip finds unused", () => {
    const text = [
      "/** @keep the worked example's next page */",
      "export function kept() {}",
      "/**",
      " * Items, for the next page.",
      " * @keep no page lists them yet",
      " */",
      "export default function listed() {}",
    ].join("\n");
    expect(judge(text, ["kept", "default"])).toEqual([]);
  });

  it("refuses a keep tag knip reads that is not one doc-comment tag", () => {
    const text = [
      "// @keep in a line comment",
      "export function line() {}",
      "/* @keep in a block comment */",
      "export function block() {}",
      "/** Mentions @keep in its prose. */",
      "export function prose() {}",
      "/** @keep once\n * @keep twice */",
      "export function twice() {}",
    ].join("\n");
    const spelled = "a keep tag is written once, as /** @keep <why> */";
    expect(judge(text, ["line", "block", "prose", "twice"])).toEqual(
      ["line", "block", "prose", "twice"].map((name) => `${name}: ${spelled}`),
    );
  });

  it("flags a keep tag without a reason, and one that excuses nothing", () => {
    const text = [
      "/** @keep — */",
      "export const bare = 1;",
      "/** @keep a reason */",
      "export type Imported = string;",
    ].join("\n");
    expect(judge(text, ["bare"])).toEqual([
      "bare: its keep tag gives no reason",
      "Imported: its keep tag excuses nothing, something imports it",
    ]);
  });

  it("refuses the tags knip always skips an export for", () => {
    const text = ["public", "beta", "alias"]
      .map((tag) => `/** @${tag} */\nexport function ${tag}Dead() {}`)
      .join("\n");
    expect(judge(text)).toEqual(
      ["public", "beta", "alias"].map(
        (tag) =>
          `${tag}Dead carries @${tag}, which knip always skips: not allowed here`,
      ),
    );
  });
});

describe("reportedExports", () => {
  it("reads knip's JSON report, and says so when knip did not answer", () => {
    const json = JSON.stringify({
      issues: [{ file: "src/a.ts", exports: [{ name: "x" }], types: [] }],
    });
    expect(reportedExports(json)).toEqual(new Set(["src/a.ts#x"]));
    expect(reportedExports("")).toMatch(/^knip could not run: /);
  });
});
