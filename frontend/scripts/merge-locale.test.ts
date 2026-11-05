// @vitest-environment node
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { mergeLocale, parseOrdered, stringifyOrdered } from "./merge-locale";

const FRONTEND = join(import.meta.dirname, "..");
const LOCALES = join(FRONTEND, "src", "i18n", "locales");
// Whatever locale files exist — the set changes as languages come and go.
const localeFiles = readdirSync(LOCALES).filter((name) =>
  name.endsWith(".json"),
);

const json = (value: unknown) => `${JSON.stringify(value, null, 2)}\n`;

function clean(base: unknown, ours: unknown, theirs: unknown): string {
  const merge = mergeLocale(json(base), json(ours), json(theirs));
  if (!merge.clean)
    throw new Error(`unexpected conflict: ${merge.conflicts.join(", ")}`);
  return merge.text;
}

describe("the locale files", () => {
  it.each(localeFiles)("%s is written back byte for byte", (name) => {
    const text = readFileSync(join(LOCALES, name), "utf8");
    expect(stringifyOrdered(parseOrdered(text))).toBe(text);
  });

  it("finds at least one locale file", () => {
    expect(localeFiles.length).toBeGreaterThan(0);
  });
});

describe("parseOrdered", () => {
  it("keeps integer-like keys where they were written, unlike a plain object", () => {
    const text = '{\n  "b": "x",\n  "1": "y"\n}\n';
    expect(stringifyOrdered(parseOrdered(text))).toBe(text);
  });

  it("refuses what is not JSON", () => {
    expect(() => parseOrdered('{\n<<<<<<< ours\n  "a": "b"\n}')).toThrow(
      SyntaxError,
    );
    expect(() => parseOrdered('{"a": "b"} trailing')).toThrow(SyntaxError);
  });
});

describe("mergeLocale — what merges", () => {
  const base = { common: { save: "Save", close: "Close" } };

  it("keeps both sides' new keys at the same spot: ours first, then theirs", () => {
    const text = clean(
      base,
      { common: { save: "Save", cancel: "Cancel", close: "Close" } },
      { common: { save: "Save", retry: "Retry", close: "Close" } },
    );
    expect(text).toBe(
      json({
        common: {
          save: "Save",
          cancel: "Cancel",
          retry: "Retry",
          close: "Close",
        },
      }),
    );
  });

  it("places a key theirs added after the key that precedes it on their side", () => {
    const text = clean(
      { a: "1", b: "2", c: "3" },
      { a: "1", b: "2", c: "3", z: "ours" },
      { first: "0", a: "1", b: "2", b2: "2.5", c: "3" },
    );
    expect(text).toBe(
      json({ first: "0", a: "1", b: "2", b2: "2.5", c: "3", z: "ours" }),
    );
  });

  it("merges a whole new namespace from each side", () => {
    const text = clean(
      base,
      { ...base, alerts: { title: "Alerts" } },
      { ...base, fuel: { a: "A" } },
    );
    expect(text).toBe(
      json({ ...base, alerts: { title: "Alerts" }, fuel: { a: "A" } }),
    );
  });

  it("takes an edit or a deletion the other side did not touch", () => {
    const text = clean(
      { a: "old", b: "keep", c: "gone" },
      { a: "new", b: "keep", c: "gone" },
      { a: "old", b: "keep" },
    );
    expect(text).toBe(json({ a: "new", b: "keep" }));
  });

  it("takes the same change made on both sides once", () => {
    const text = clean(
      { a: "old" },
      { a: "new", b: "both" },
      { a: "new", b: "both" },
    );
    expect(text).toBe(json({ a: "new", b: "both" }));
  });
});

describe("mergeLocale — what is a conflict", () => {
  it("is a conflict when one key gets two different values, and only that key is", () => {
    const merge = mergeLocale(
      json({ common: { save: "Save", close: "Close" } }),
      json({ common: { save: "Store", close: "Close", ours: "O" } }),
      json({ common: { save: "Keep", close: "Close", theirs: "T" } }),
    );
    expect(merge).toMatchObject({ clean: false, conflicts: ["common.save"] });
    if (merge.clean) return;
    // The three sides agree everywhere but on the conflicting key.
    const resolved = { close: "Close", ours: "O", theirs: "T" };
    expect(merge.ours).toBe(json({ common: { save: "Store", ...resolved } }));
    expect(merge.theirs).toBe(json({ common: { save: "Keep", ...resolved } }));
    expect(merge.base).toBe(json({ common: { save: "Save", ...resolved } }));
  });

  it("is a conflict when both sides add the same key with different values", () => {
    const merge = mergeLocale(json({}), json({ a: "x" }), json({ a: "y" }));
    expect(merge).toMatchObject({ clean: false, conflicts: ["a"] });
  });

  it("is a conflict when one side edits a key the other deleted", () => {
    const merge = mergeLocale(
      json({ a: "x", b: "b" }),
      json({ a: "y", b: "b" }),
      json({ b: "b" }),
    );
    expect(merge).toMatchObject({ clean: false, conflicts: ["a"] });
  });
});
