// @vitest-environment node
import { describe, expect, it } from "vitest";
import { isReader, judge, leafKeys, readsIn } from "./find";

const reads = (text: string) => readsIn([{ file: "page.tsx", text }]);
const unusedIn = (tree: unknown, text: string, kept = {}) =>
  judge([{ file: "en.json", tree }], reads(text), kept);

describe("leafKeys", () => {
  it("dots the path to every leaf", () => {
    expect(leafKeys({ a: { b: "x", c: { d: "y" } }, e: "z" })).toEqual([
      "a.b",
      "a.c.d",
      "e",
    ]);
  });
});

describe("isReader", () => {
  it("reads source files, never a test", () => {
    expect(["routes/login.tsx", "lib/api/items.ts"].every(isReader)).toBe(true);
    expect(isReader("lib/session.test.ts")).toBe(false);
    expect(isReader("routes/page.test.tsx")).toBe(false);
    expect(isReader("i18n/locales/en.json")).toBe(false);
  });
});

describe("judge", () => {
  it("flags a key nothing reads, naming every locale that carries it", () => {
    const { unused } = judge(
      [
        { file: "en.json", tree: { items: { heading: "x", gone: "y" } } },
        { file: "pt.json", tree: { items: { gone: "y" } } },
      ],
      reads(`t("items.heading")`),
      {},
    );
    expect(unused).toEqual([
      { key: "items.gone", files: ["en.json", "pt.json"] },
    ]);
  });

  it("passes a key read by literal, plural base, template head or dotted ancestor", () => {
    const tree = {
      a: { title: "x", count_one: "1", count_other: "n" },
      b: { status: { open: "o" } },
      c: { form: { submit: "s" } },
      d: { state_on: "on", state_off: "off" },
    };
    const text = [
      `t("a.title"); t("a.count", { count });`,
      "t(`b.status.${status}`);",
      `const FORM = "c.form";`,
      "t(`d.state_${state}`);",
    ].join("\n");
    expect(unusedIn(tree, text).unused).toEqual([]);
  });

  it("does not count a one-segment template head as a namespace", () => {
    const tree = { form: { name: "x" } };
    expect(unusedIn(tree, "id={`form.${name}`}").unused).toEqual([
      { key: "form.name", files: ["en.json"] },
    ]);
  });

  it("does not count a key quoted in a comment, or a bare word as its namespace", () => {
    const tree = { items: { heading: "x" }, login: { submit: "y" } };
    const text = `// t("login.submit")\nconst queryKey = ["items"];`;
    expect(unusedIn(tree, text).unused.map((u) => u.key)).toEqual([
      "items.heading",
      "login.submit",
    ]);
  });

  it("passes a kept key or namespace, and reports a kept entry that no longer holds", () => {
    const tree = {
      a: { kept: "x", read: "y" },
      b: { s: { on: "1", off: "0" } },
    };
    const kept = {
      "a.kept": "why",
      "b.s": "built by concatenation",
      "a.read": "why",
      "a.gone": "why",
      toString: "why",
    };
    const verdict = unusedIn(tree, `t("a.read")`, kept);
    expect(verdict.unused).toEqual([]);
    expect(verdict.staleKept).toEqual(["a.read", "a.gone", "toString"]);
  });

  it("reports a kept entry without a reason", () => {
    const verdict = unusedIn({ a: { kept: "x" } }, "", { "a.kept": " " });
    expect(verdict.unused).toEqual([]);
    expect(verdict.staleKept).toEqual(["a.kept"]);
  });
});
