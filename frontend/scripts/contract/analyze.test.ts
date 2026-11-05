// @vitest-environment node
// What counts as reading a field the API sends — the false positives the gate
// is built around, and the reads it must not invent.
import { describe, expect, it } from "vitest";
import { collectOf, findingsOf, object, ref, specOf } from "./fixture-program";
import type { Schema } from "./openapi";

const RECORD = `
export interface Place { id: string; name: string; km: number | null; color: string }
export type PlaceHit = Pick<Place, "id" | "name" | "km">;
`;
const api = (type: string, path = "/places") => `
import { request } from "./client";
import type { ${type} } from "../schemas/records";
export const load = () => request<${type}[]>("${path}");
`;
const spec = specOf(
  { "/places": { type: "array", items: ref("PlaceOut") } },
  { PlaceOut: object("id", "name", "km", "color") },
);
const unread = (lines: string[]) =>
  lines.filter((l) => l.startsWith("unread "));
// Just enough JSX for a component and two DOM elements, no React.
const JSX_TYPES = `
declare namespace JSX {
  interface Element {}
  interface IntrinsicElements { div: { id?: string; children?: unknown }; span: { children?: unknown } }
}`;

describe("a read", () => {
  it("through a Pick is a read of the field it was picked from", () => {
    const lines = findingsOf(
      {
        "src/lib/schemas/records.ts": RECORD,
        "src/lib/api/records.ts": api("PlaceHit"),
        "src/use.ts": `
          import { load } from "./lib/api/records";
          export const names = async () => (await load()).map((h) => h.name + h.id + h.km);`,
      },
      specOf({
        "/places": { type: "array", items: object("id", "name", "km") },
      }),
    );
    expect(unread(lines)).toEqual([]);
  });

  it("through an Omit is a read too, and what nobody reads is still reported", () => {
    const lines = findingsOf(
      {
        "src/lib/schemas/records.ts": `${RECORD}
          export type Plain = Omit<Place, "color">;`,
        "src/lib/api/records.ts": api("Plain"),
        "src/use.ts": `
          import { load } from "./lib/api/records";
          export const names = async () => (await load()).map((z) => z.name + z.id);`,
      },
      spec,
    );
    expect(unread(lines)).toEqual(["unread lib/schemas/records.ts#Place.km"]);
  });

  it("is a destructuring, of a variable or of a parameter", () => {
    const lines = findingsOf(
      {
        "src/lib/schemas/records.ts": RECORD,
        "src/lib/api/records.ts": api("Place"),
        "src/use.ts": `
          import { load } from "./lib/api/records";
          import type { Place } from "./lib/schemas/records";
          const label = ({ name, km: km }: Place) => name + km;
          export const go = async () => (await load()).map((z) => { const { id } = z; return id + label(z); });`,
      },
      spec,
    );
    expect(unread(lines)).toEqual([
      "unread lib/schemas/records.ts#Place.color",
    ]);
  });

  it("is a destructuring assignment", () => {
    const lines = findingsOf(
      {
        "src/lib/schemas/records.ts": RECORD,
        "src/lib/api/records.ts": api("Place"),
        "src/use.ts": `
          import { load } from "./lib/api/records";
          export const go = async () => {
            let id = "";
            let km: number | null = null;
            for (const z of await load()) ({ id, km: km } = z);
            return id + km;
          };`,
      },
      spec,
    );
    expect(unread(lines)).toEqual([
      "unread lib/schemas/records.ts#Place.color",
      "unread lib/schemas/records.ts#Place.name",
    ]);
  });

  // The case "find references" misses: each `PlaceHit` handed to
  // `entryFrom(kind, row: { id; name; km }, city)`.
  const ENTRY_FROM = `
    function entryFrom(kind: string, row: { id: string; name: string; km: number | null }, city: string | null) {
      return { key: kind + row.id + city, label: row.name };
    }`;
  const hits = specOf({
    "/places": { type: "array", items: object("id", "name", "km") },
  });

  it("of a parameter of another type reads the field the argument carries", () => {
    const files = (body: string) => ({
      "src/lib/schemas/records.ts": RECORD,
      "src/lib/api/records.ts": api("PlaceHit"),
      "src/search.ts": `import { load } from "./lib/api/records";${body}`,
    });
    const call = `export const index = async () => (await load()).map((g) => entryFrom("place", g, null));`;
    expect(unread(findingsOf(files(ENTRY_FROM + call), hits))).toEqual([
      "unread lib/schemas/records.ts#Place.km",
    ]);
    const readsKm = ENTRY_FROM.replace(
      "label: row.name",
      "label: row.name, km: row.km",
    );
    expect(unread(findingsOf(files(readsKm + call), hits))).toEqual([]);
  });

  it("of a callback's parameter reads what the caller hands it", () => {
    const lines = findingsOf(
      {
        "src/lib/schemas/records.ts": RECORD,
        "src/lib/api/records.ts": api("PlaceHit"),
        "src/search.ts": `
          import { load } from "./lib/api/records";
          const entry = (row: { id: string; name: string }) => row.id + row.name;
          export const index = async () => (await load()).map(entry);`,
      },
      hits,
    );
    expect(unread(lines)).toEqual(["unread lib/schemas/records.ts#Place.km"]);
  });

  it("names a literal written inline by where it is written", () => {
    const files = {
      "src/lib/api/records.ts": `
        import { request } from "./client";
        export const load = () => request<{ items: string[]; total: number }>("/places");`,
      "src/use.ts": `
        import { load } from "./lib/api/records";
        export const go = async () => (await load()).items;`,
    };
    const answer = {
      "/places": { type: "object", properties: { items: {}, total: {} } },
    };
    const lines = findingsOf(files, specOf(answer));
    expect(lines).toEqual(["unread lib/api/records.ts#load.total"]);
    // The same wherever the checkout lives, a `src/` above it included.
    const elsewhere = collectOf(files, specOf(answer), {
      root: "/home/me/src/app",
    });
    expect(elsewhere.map((f) => f.key)).toEqual([
      "lib/api/records.ts#load.total",
    ]);
  });

  it("through a generic accessor reads the key the call passes", () => {
    const lines = findingsOf(
      {
        "src/lib/schemas/records.ts": RECORD,
        "src/lib/api/records.ts": api("Place"),
        "src/use.ts": `
          import { load } from "./lib/api/records";
          const get = <T, K extends keyof T>(o: T, k: K) => o[k];
          const sortBy = <T,>(rows: readonly T[], k: keyof T) => [...rows].sort((a, b) => String(a[k]).localeCompare(String(b[k])));
          export const go = async () => {
            const places = await load();
            return sortBy(places, "km").map((z) => get(z, "name") + get(z, "id"));
          };`,
      },
      spec,
    );
    expect(unread(lines)).toEqual([
      "unread lib/schemas/records.ts#Place.color",
    ]);
  });

  it("inside a generic helper reads what its constraint names of the rows handed in", () => {
    const files = (body: string) => ({
      "src/lib/schemas/records.ts": RECORD,
      "src/lib/api/records.ts": api("Place"),
      "src/lib/pick.ts": `
        export type Located = { id: string; km: number | null };
        export function ofColor<T extends { color?: string | null }>(rows: readonly T[], c: string | null): T[] {
          return rows.filter((row) => !c || row.color === c);
        }
        export function located<T extends Located>(rows: readonly T[], held: readonly string[] = []) {
          return rows.filter((row) => row.km !== null || held.includes(row.id)).map((row) => ({ ...row, far: false }));
        }
        export function first<T extends { name: string }>(rows: readonly T[]): T | undefined {
          return rows[0];
        }`,
      "src/use.ts": `
        import { load } from "./lib/api/records";
        import { first, located, ofColor } from "./lib/pick";
        export const go = async () => ${body};`,
    });
    // Each field is read only inside a helper: the call site names none of them.
    expect(
      unread(
        findingsOf(files("located(ofColor(await load(), null)).length"), spec),
      ),
    ).toEqual(["unread lib/schemas/records.ts#Place.name"]);
    // A key typed by its constraint (`K extends keyof Place`) names
    // only what a call passes, and nothing when the helper is never called.
    const unusedGet = `
        import type { Place } from "./lib/schemas/records";
        export const get = <K extends keyof Place>(r: Place, k: K) => r[k];`;
    const withGet = {
      ...files("(await load()).length"),
      "src/get.ts": unusedGet,
    };
    expect(unread(findingsOf(withGet, spec))).toEqual([
      "unread lib/schemas/records.ts#Place.color",
      "unread lib/schemas/records.ts#Place.id",
      "unread lib/schemas/records.ts#Place.km",
      "unread lib/schemas/records.ts#Place.name",
    ]);
    // A helper whose constraint names a field it never reads reads nothing.
    expect(unread(findingsOf(files("first(await load())"), spec))).toEqual([
      "unread lib/schemas/records.ts#Place.color",
      "unread lib/schemas/records.ts#Place.id",
      "unread lib/schemas/records.ts#Place.km",
      "unread lib/schemas/records.ts#Place.name",
    ]);
  });

  it("of a query result's data reads it through NoInfer, as TanStack Query types it", () => {
    const lines = findingsOf(
      {
        "src/lib/schemas/records.ts": RECORD,
        "src/lib/api/records.ts": api("Place"),
        "src/use.ts": `
          import { load } from "./lib/api/records";
          type Result<T> = { data: NoInfer<T> | undefined; isPending: boolean };
          declare function useResult<T>(read: () => Promise<T>): Result<T>;
          const names = (query: { data?: readonly { id: string; name: string }[] }) =>
            query.data?.map((row) => row.id + row.name);
          export const go = () => names(useResult(load));`,
      },
      spec,
    );
    expect(unread(lines)).toEqual([
      "unread lib/schemas/records.ts#Place.color",
      "unread lib/schemas/records.ts#Place.km",
    ]);
  });

  it("of a component's prop reads what a spread of props hands it", () => {
    const view = (spread: string) => ({
      "src/lib/schemas/records.ts": RECORD,
      "src/lib/api/records.ts": api("Place"),
      "src/jsx.d.ts": JSX_TYPES,
      "src/view.tsx": `
        import { load } from "./lib/api/records";
        const Label = (p: { name: string; id: string }) => <span>{p.name}</span>;
        export const view = async () => (await load()).map((z) => ${spread});`,
    });
    expect(unread(findingsOf(view("<Label {...z} />"), spec))).toEqual([
      "unread lib/schemas/records.ts#Place.color",
      "unread lib/schemas/records.ts#Place.id",
      "unread lib/schemas/records.ts#Place.km",
    ]);
    // A DOM element takes every field as an attribute: no read, but the hint.
    const dom = collectOf(view(`<div {...z}><Label {...z} /></div>`), spec);
    expect(
      dom.find((f) => f.key === "lib/schemas/records.ts#Place.color")?.detail,
    ).toBe("handed over whole at src/view.tsx:4");
  });

  it("does not depend on how deep a type was first met", () => {
    // The answer is met four arrays deep first, its element two
    // deep after; a cache keyed by the type alone forgot the second could carry.
    const nested = (schema: Schema, n: number): Schema =>
      n === 0 ? schema : { type: "array", items: nested(schema, n - 1) };
    const lines = findingsOf(
      {
        "src/lib/schemas/records.ts": RECORD,
        "src/lib/api/records.ts": `
          import { request } from "./client";
          import type { Place } from "../schemas/records";
          export const load = () => request<Place[][][][]>("/places");`,
        "src/use.ts": `
          import { load } from "./lib/api/records";
          const firstName = (rows: { name: string }[][]) => rows[0][0].name;
          export const go = async () => { const z = await load(); return firstName(z[0][0]); };`,
      },
      specOf(
        { "/places": nested(ref("PlaceOut"), 4) },
        { PlaceOut: object("id", "name", "km", "color") },
      ),
    );
    expect(unread(lines)).toEqual([
      "unread lib/schemas/records.ts#Place.color",
      "unread lib/schemas/records.ts#Place.id",
      "unread lib/schemas/records.ts#Place.km",
    ]);
  });

  it("by a literal key, or a key typed as a union of names, reads those names", () => {
    const lines = findingsOf(
      {
        "src/lib/schemas/records.ts": RECORD,
        "src/lib/api/records.ts": api("Place"),
        "src/use.ts": `
          import { load } from "./lib/api/records";
          export const go = async (key: "name" | "color") =>
            (await load()).map((z) => z["id"] + z[key]);`,
      },
      spec,
    );
    expect(unread(lines)).toEqual(["unread lib/schemas/records.ts#Place.km"]);
  });
});

describe("not a read", () => {
  it("is a write, or anything a test, a mock or a schema module does", () => {
    const lines = findingsOf(
      {
        "src/lib/schemas/records.ts": `${RECORD}
          export const nameOf = (z: Place) => z.color;`,
        "src/lib/api/records.ts": api("Place"),
        "src/use.ts": `
          import { load } from "./lib/api/records";
          export const go = async () => (await load()).map((z) => { z.km = 0; return z.id + z.name; });`,
        "src/use.test.ts": `
          import type { Place } from "./lib/schemas/records";
          export const seen = (z: Place) => z.km;`,
        "src/lib/mock-places.ts": `
          import type { Place } from "./schemas/records";
          export const seen = (z: Place) => z.color;`,
      },
      spec,
    );
    expect(unread(lines)).toEqual([
      "unread lib/schemas/records.ts#Place.color",
      "unread lib/schemas/records.ts#Place.km",
    ]);
  });
});
