// @vitest-environment node
// The baseline only shrinks and the allowlist stays true.
import { describe, expect, it } from "vitest";
import type { Finding } from "./collect";
import { formatBaseline, judge, parseBaseline, type Baseline } from "./gate";

const found = (...ids: string[]): Finding[] =>
  ids.map((id) => {
    const [kind, key] = id.split(" ");
    return { kind: kind as Finding["kind"], key };
  });
const lines = (...ids: string[]): Baseline => ({
  lines: ids,
  renamed: new Map(),
});

describe("judge", () => {
  it("passes what the baseline or the allowlist names, and fails anything new", () => {
    const verdict = judge(
      found("unread A.x", "unread B.y", "undeclared C.z"),
      lines("unread A.x"),
      { "unread B.y": "an export reads the whole row" },
    );
    expect(verdict.fresh.map((f) => f.key)).toEqual(["C.z"]);
    expect(verdict.staleBaseline).toEqual([]);
    expect(verdict.staleAllowed).toEqual([]);
  });

  it("reports a baseline line nothing matches any more, so it is deleted", () => {
    const verdict = judge(
      found("unread A.x"),
      lines("unread A.x", "unread Gone.field"),
      {},
    );
    expect(verdict.staleBaseline).toEqual(["unread Gone.field"]);
  });

  it("reports an allowlist entry nothing matches, and a baseline line the allowlist covers", () => {
    const verdict = judge(found("unread A.x"), lines("unread A.x"), {
      "unread A.x": "read by name",
      "unread Read.now": "was read by name",
    });
    expect(verdict.staleAllowed).toEqual(["unread Read.now"]);
    expect(verdict.staleBaseline).toEqual(["unread A.x"]);
  });

  it("refuses a baseline line the base branch did not have", () => {
    const verdict = judge(
      found("unread A.x", "unread New.y"),
      lines("unread A.x", "unread New.y"),
      {},
      ["unread A.x"],
    );
    expect(verdict.fresh).toEqual([]);
    expect(verdict.grown).toEqual(["unread New.y"]);
    expect(
      judge(found("unread A.x"), lines("unread A.x"), {}, undefined).grown,
    ).toEqual([]);
  });

  it("takes a line that renames one the base had, once, and only if the old one went", () => {
    const base = ["unread Old.x", "unread Old.y"];
    const renamed = (...pairs: [string, string][]): Baseline => ({
      lines: pairs.map(([line]) => line),
      renamed: new Map(pairs.filter(([, old]) => old)),
    });
    const grown = (baseline: Baseline) =>
      judge(found(...baseline.lines), baseline, {}, base).grown;

    expect(
      grown(
        renamed(
          ["unread New.x", "unread Old.x"],
          ["unread New.y", "unread Old.y"],
        ),
      ),
    ).toEqual([]);
    // `Old` keeps a line: it was not renamed, so `New.x` is a field let in.
    expect(
      grown(renamed(["unread New.x", "unread Old.x"], ["unread Old.y", ""])),
    ).toEqual(["unread New.x"]);
    // The old line is still there: the new one is growth, not a rename.
    expect(
      grown(renamed(["unread New.x", "unread Old.x"], ["unread Old.x", ""])),
    ).toEqual(["unread New.x"]);
    // One old line cannot stand for two new ones; nor can a line the base never had.
    expect(
      grown(
        renamed(
          ["unread New.x", "unread Old.x"],
          ["unread Other.x", "unread Old.x"],
        ),
      ),
    ).toEqual(["unread Other.x"]);
    expect(grown(renamed(["unread New.z", "unread Never.z"]))).toEqual([
      "unread New.z",
    ]);
  });

  it("never takes a fixed field as room for another one", () => {
    // The swap: one field fixed, an unrelated one added under its name.
    const base = ["unread Route.average_speed"];
    const swap = (line: string): Baseline => ({
      lines: [line],
      renamed: new Map([[line, "unread Route.average_speed"]]),
    });
    const grown = (line: string) =>
      judge(found(line), swap(line), {}, base).grown;
    expect(grown("undeclared Overview.secret")).toEqual([
      "undeclared Overview.secret",
    ]);
    expect(grown("unread Route.secret")).toEqual(["unread Route.secret"]);
    expect(grown("undeclared Route.average_speed")).toEqual([
      "undeclared Route.average_speed",
    ]);
    expect(grown("unread lib/schemas/b.ts#Route.average_speed")).toEqual([]);
  });
});

describe("the baseline file", () => {
  it("reads back what it writes, sorted, without its comments", () => {
    const text = formatBaseline(["unread B.y", "unread A.x", "unread A.x"]);
    expect(text.startsWith("#")).toBe(true);
    expect(parseBaseline(text)).toEqual({
      lines: ["unread A.x", "unread B.y"],
      renamed: new Map(),
    });
  });

  it("keeps a rename a line declares", () => {
    const renamed = new Map([["unread New.x", "unread Old.x"]]);
    const text = formatBaseline(["unread New.x", "unread A.y"], renamed);
    expect(text).toContain("unread New.x  # was unread Old.x\n");
    expect(parseBaseline(text)).toEqual({
      lines: ["unread A.y", "unread New.x"],
      renamed,
    });
  });
});
