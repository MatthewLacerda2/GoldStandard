// @vitest-environment node
import { describe, expect, it } from "vitest";
import { judgeKeeps, keepTags } from "./keep";

const text = [
  "/** @keep the worked example's next page */",
  "export function kept() {}",
  "/** @keep */",
  "export const bare = 1, other = 2;",
  "/** @keep a reason */",
  "export type Imported = string;",
  "/** @keep not exported, so not knip's */",
  "function local() {}",
].join("\n");
const keeps = keepTags([{ file: "src/a.ts", text }]);

describe("keepTags", () => {
  it("finds every exported declaration tagged @keep, with its reason", () => {
    expect(keeps.map((k) => [k.name, k.line, k.reason])).toEqual([
      ["kept", 1, "the worked example's next page"],
      ["bare", 3, ""],
      ["other", 3, ""],
      ["Imported", 5, "a reason"],
    ]);
  });
});

describe("judgeKeeps", () => {
  it("passes a reasoned @keep on an export knip finds unused", () => {
    const excusing = new Set(["src/a.ts#kept", "src/a.ts#Imported"]);
    expect(judgeKeeps(keeps.slice(0, 1), excusing)).toEqual([]);
  });

  it("flags a @keep without a reason, and one that excuses nothing", () => {
    expect(judgeKeeps(keeps, new Set(["src/a.ts#kept"]))).toEqual([
      "src/a.ts:3: @keep on bare gives no reason",
      "src/a.ts:3: @keep on other gives no reason",
      "src/a.ts:5: @keep on Imported excuses nothing: something imports it now",
    ]);
  });
});
