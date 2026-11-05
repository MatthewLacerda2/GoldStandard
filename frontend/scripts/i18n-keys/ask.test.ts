// @vitest-environment node
import { describe, expect, it } from "vitest";
import { asksIn, missingFrom } from "./ask";
import type { Locale } from "./find";

const asked = (text: string) =>
  asksIn([{ file: "page.tsx", text }]).map(({ key, head }) =>
    head ? `${key}…` : key,
  );
const missingIn = (locales: Locale[], text: string) =>
  missingFrom(locales, asksIn([{ file: "page.tsx", text }]));
const en = (tree: unknown): Locale[] => [{ file: "en.json", tree }];

describe("asksIn", () => {
  it("reads the key a call to t names, and an i18nKey", () => {
    const text = [
      `t("a.title"); i18n.t("a.other");`,
      `<Trans i18nKey="a.trans" />; <Trans i18nKey={"a.braced"} />;`,
      `const props = { i18nKey: "a.prop" };`,
    ].join("\n");
    expect(asked(text)).toEqual([
      "a.title",
      "a.other",
      "a.trans",
      "a.braced",
      "a.prop",
    ]);
  });

  it("reads both branches of a conditional, and a template head", () => {
    const text = "t(busy ? (`a.busy`) : 'a.idle'); t(`a.status.${s}`);";
    expect(asked(text)).toEqual(["a.busy", "a.idle", "a.status.…"]);
  });

  it("sees through a type, a fallback and a quoted i18nKey, and drops the default namespace", () => {
    const text = [
      `t("a.const" as const); t("a.sat" satisfies string); t(key! ?? "a.nn");`,
      `t(error ?? "a.fallback"); t(label || "a.or");`,
      `const props = { "i18nKey": "a.quoted" }; t("translation:a.ns");`,
    ].join("\n");
    expect(asked(text)).toEqual([
      "a.const",
      "a.sat",
      "a.nn",
      "a.fallback",
      "a.or",
      "a.quoted",
      "a.ns",
    ]);
  });

  it("names each file asking once", () => {
    const asks = asksIn([
      { file: "a.tsx", text: `t("a.x"); t("a.x");` },
      { file: "b.tsx", text: `t("a.x");` },
    ]);
    expect(asks).toEqual([
      { key: "a.x", head: false, files: ["a.tsx", "b.tsx"] },
    ]);
  });

  it("does not read a comment, another call, any other literal, or a key it cannot see", () => {
    const text = [
      `// t("a.commented")`,
      `format("a.format"); const LABEL = "a.constant";`,
      `t(LABEL); t("a." + name); t(\`\${ns}.title\`); t("");`,
    ].join("\n");
    expect(asked(text)).toEqual([]);
  });
});

describe("missingFrom", () => {
  it("flags a key no locale has, naming every locale", () => {
    const locales = [
      { file: "en.json", tree: { a: { title: "x" } } },
      { file: "pt.json", tree: { a: { title: "x" } } },
    ];
    expect(missingIn(locales, `t("a.typo")`)).toEqual([
      {
        key: "a.typo",
        head: false,
        files: ["page.tsx"],
        locales: ["en.json", "pt.json"],
      },
    ]);
  });

  it("names only the locale that lacks a key", () => {
    const locales = [
      { file: "en.json", tree: { a: { title: "x", added: "y" } } },
      { file: "pt.json", tree: { a: { title: "x" } } },
      { file: "es.json", tree: { a: { title: "x", added: "y" } } },
    ];
    const text = `t("a.title"); t("a.added");`;
    expect(missingIn(locales, text).map((m) => [m.key, m.locales])).toEqual([
      ["a.added", ["pt.json"]],
    ]);
  });

  it("passes a leaf, a subtree, a plural base and a template head a locale has", () => {
    const tree = {
      a: {
        title: "x",
        count_one: "1",
        count_other: "n",
        rank_ordinal_two: "2",
      },
      b: { form: { name: "n" } },
      c: { status: { open: "o" } },
    };
    const text = [
      `t("a.title"); t("a.count", { count }); t("a.rank", { ordinal: true });`,
      `<Trans i18nKey="b.form" />; t(\`c.status.\${status}\`);`,
    ].join("\n");
    expect(missingIn(en(tree), text)).toEqual([]);
  });

  it("flags a key a locale only has a longer sibling of, and a head it has nothing under", () => {
    const tree = { a: { titles: "x", count_label: "y" }, b: { other: "z" } };
    const text = "t('a.title'); t('a.count'); t(`b.status.${s}`);";
    expect(missingIn(en(tree), text).map((m) => m.key)).toEqual([
      "a.title",
      "a.count",
      "b.status.",
    ]);
  });
});
