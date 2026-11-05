// @vitest-environment node
// The frontend's types against the backend's contract: what a response model
// sends that nothing declares, what a type declares that nothing sends, and
// which operation a request lands on.
import { describe, expect, it } from "vitest";
import {
  collectOf,
  findingsOf,
  object,
  okWith,
  ref,
  specOf,
} from "./fixture-program";
import { judge } from "./gate";
import { DYNAMIC, findOperation, matchPaths, type OpenApi } from "./openapi";

const schemas = (row: string) => `export interface Row { ${row} }`;
const READ_A_B = `
  import { load } from "./lib/api/rows";
  export const show = async () => (await load()).map((r) => r.a + r.b);`;
const files = (row: string, reader = READ_A_B) => ({
  "src/lib/schemas/rows.ts": schemas(row),
  "src/lib/api/rows.ts": `
    import { request } from "./client";
    import type { Row } from "../schemas/rows";
    export const load = () => request<Row[]>(\`/api/rows?page=\${1}\`);`,
  "src/use.ts": reader,
});
const contract = (...fields: string[]) =>
  specOf(
    { "/api/rows": { type: "array", items: ref("RowOut") } },
    { RowOut: object(...fields) },
  );

describe("a field added to a response model", () => {
  // The gate's acceptance: red while nothing reads it, green once something
  // does or once it is allowed with a reason.
  it("is red while the frontend neither declares nor reads it", () => {
    expect(
      findingsOf(files("a: string; b: string"), contract("a", "b")),
    ).toEqual([]);
    expect(
      findingsOf(files("a: string; b: string"), contract("a", "b", "c")),
    ).toEqual(["undeclared RowOut.c"]);
  });

  it("is red while it is declared and not read, green once read or allowed", () => {
    const declared = findingsOf(
      files("a: string; b: string; c: string"),
      contract("a", "b", "c"),
    );
    expect(declared).toEqual(["unread lib/schemas/rows.ts#Row.c"]);
    const read = READ_A_B.replace("r.a + r.b", "r.a + r.b + r.c");
    expect(
      findingsOf(
        files("a: string; b: string; c: string", read),
        contract("a", "b", "c"),
      ),
    ).toEqual([]);
    const findings = [
      { kind: "unread" as const, key: "lib/schemas/rows.ts#Row.c" },
    ];
    expect(
      judge(
        findings,
        { lines: [], renamed: new Map() },
        {
          "unread lib/schemas/rows.ts#Row.c":
            "read by the CSV export, row by row",
        },
      ).fresh,
    ).toEqual([]);
  });
});

describe("a field the frontend declares", () => {
  it("that its endpoint does not send is a phantom", () => {
    const lines = findingsOf(
      files("a: string; b: string; volume: number"),
      contract("a", "b"),
    );
    expect(lines).toContain("phantom lib/schemas/rows.ts#Row.volume");
  });

  it("is never a phantom of a model that takes any field (a passthrough)", () => {
    const open: OpenApi = specOf({
      "/api/rows": { type: "array", items: { type: "object" } },
    });
    expect(
      findingsOf(files("a: string; b: string; extra: number"), open),
    ).toEqual(["unread lib/schemas/rows.ts#Row.extra"]);
  });
});

describe("pairing a request with its operation", () => {
  it("follows each field into the schema it nests", () => {
    const spec = specOf(
      { "/api/rows": { type: "array", items: ref("RowOut") } },
      {
        RowOut: {
          type: "object",
          properties: { a: {}, b: {}, pos: ref("Pos") },
        },
        Pos: object("lat", "lon", "fix"),
      },
    );
    const lines = findingsOf(
      files(
        "a: string; b: string; pos: { lat: number }",
        READ_A_B.replace("r.b", "r.b + r.pos.lat"),
      ),
      spec,
    );
    expect(lines.sort()).toEqual(["undeclared Pos.fix", "undeclared Pos.lon"]);
  });

  it("is unpaired when the path is built out of sight, unless the type names its schema", () => {
    const outOfSight = (tag: string) => ({
      "src/lib/schemas/rows.ts": `${tag}\nexport interface Row { a: string; b: string }`,
      "src/lib/api/rows.ts": `
        import { request } from "./client";
        import type { Row } from "../schemas/rows";
        const at = (path: (n: number) => string) => () => request<Row[]>(path(1));
        export const load = at((n) => \`/api/rows/\${n}\`);`,
      "src/use.ts": READ_A_B,
    });
    expect(findingsOf(outOfSight(""), contract("a", "b", "c"))).toEqual([
      "unpaired lib/api/rows.ts#at",
    ]);
    expect(
      findingsOf(outOfSight("/** @backend RowOut */"), contract("a", "b", "c")),
    ).toEqual(["undeclared RowOut.c"]);
    // A tag naming a schema the contract does not have pairs nothing.
    const [wrong] = collectOf(
      outOfSight("/** @backend RowOutt */"),
      contract("a", "b", "c"),
    );
    expect(wrong).toMatchObject({
      kind: "unpaired",
      key: "lib/api/rows.ts#at",
    });
    expect(wrong.detail).toBe(
      "@backend names RowOutt, which the contract does not have",
    );
  });

  it("reads a method from a shorthand or a constant, and never guesses one", () => {
    const spec: OpenApi = {
      paths: {
        "/api/rows": {
          get: okWith(ref("RowOut")),
          post: okWith(ref("RowOut")),
        },
      },
      components: { schemas: { RowOut: object("a", "b", "c") } },
    };
    const findings = collectOf(
      {
        "src/lib/schemas/rows.ts": schemas("a: string; b: string"),
        "src/lib/api/rows.ts": `
          import { request } from "./client";
          import type { Row } from "../schemas/rows";
          const INIT = { method: "POST" };
          export const create = () => request<Row>("/api/rows", INIT);
          export const save = (method: "POST") => request<Row>("/api/rows", { method });
          export const send = (init: { method: string }) => request<Row>("/api/rows", init);`,
        "src/use.ts": `
          import { create, save, send } from "./lib/api/rows";
          export const show = async () => {
            const rows = [await create(), await save("POST"), await send({ method: "PUT" })];
            return rows.map((r) => r.a + r.b);
          };`,
      },
      spec,
    );
    expect(
      findings.map((f) => `${f.kind} ${f.key}: ${f.detail ?? ""}`),
    ).toEqual([
      "undeclared RowOut.c: ",
      "unpaired lib/api/rows.ts#send: its method is decided out of sight",
    ]);
  });

  it("evaluates a helper with the arguments the call passes", () => {
    const spec: OpenApi = {
      paths: {
        "/api/a": { get: okWith(ref("A")) },
        "/api/b": { get: okWith(ref("B")) },
      },
      components: { schemas: { A: object("x"), B: object("y") } },
    };
    const lines = findingsOf(
      {
        "src/lib/schemas/rows.ts": `export interface A { x: string }`,
        "src/lib/api/rows.ts": `
          import { request } from "./client";
          import type { A } from "../schemas/rows";
          const at = (k: "a" | "b") => \`/api/\${k}\`;
          export const loadA = () => request<A>(at("a"));`,
        "src/use.ts": `
          import { loadA } from "./lib/api/rows";
          export const show = async () => (await loadA()).x;`,
      },
      spec,
    );
    expect(lines).toEqual([]);
  });

  it("takes the method a later spread can carry", () => {
    const spec: OpenApi = {
      paths: {
        "/api/rows": {
          post: okWith(ref("RowOut")),
          patch: okWith(ref("Other")),
        },
      },
      components: {
        schemas: { RowOut: object("a", "b"), Other: object("a", "b", "z") },
      },
    };
    const lines = findingsOf(
      {
        "src/lib/schemas/rows.ts": schemas("a: string; b: string"),
        "src/lib/api/rows.ts": `
          import { request } from "./client";
          import type { Row } from "../schemas/rows";
          const PATCH: { method?: "PATCH" } = { method: "PATCH" };
          export const save = () => request<Row>("/api/rows", { method: "POST", ...PATCH });`,
        "src/use.ts": `
          import { save } from "./lib/api/rows";
          export const show = async () => { const r = await save(); return r.a + r.b; };`,
      },
      spec,
    );
    expect(lines).toEqual(["undeclared Other.z"]);
  });

  it("reads an answer read as nothing as unread, whole", () => {
    // Whatever names no field quiets nothing: each sends all three unread.
    const all = [
      "undeclared RowOut.a",
      "undeclared RowOut.b",
      "undeclared RowOut.c",
    ];
    for (const type of [
      "void",
      "unknown",
      "object",
      "Record<string, unknown>[]",
      "{}",
    ]) {
      const lines = findingsOf(
        {
          "src/lib/api/rows.ts": `
            import { request } from "./client";
            export const peek = () => request<${type}>("/api/rows");`,
        },
        contract("a", "b", "c"),
      );
      expect(lines, type).toEqual(all);
    }
  });

  it("tells two types of one name apart by their files", () => {
    const lines = findingsOf(
      {
        "src/lib/schemas/one.ts": schemas("a: string; b: string"),
        "src/lib/schemas/two.ts": schemas("a: string; b: string"),
        "src/lib/api/rows.ts": `
          import { request } from "./client";
          import type { Row as One } from "../schemas/one";
          import type { Row as Two } from "../schemas/two";
          export const loadOne = () => request<One[]>("/api/rows");
          export const loadTwo = () => request<Two[]>("/api/others");`,
        "src/use.ts": `
          import { loadOne, loadTwo } from "./lib/api/rows";
          export const one = async () => (await loadOne()).map((r) => r.a + r.b);
          export const two = async () => (await loadTwo()).map((r) => r.a);`,
      },
      specOf(
        {
          "/api/rows": { type: "array", items: ref("RowOut") },
          "/api/others": { type: "array", items: ref("RowOut") },
        },
        { RowOut: object("a", "b") },
      ),
    );
    expect(lines).toEqual(["unread lib/schemas/two.ts#Row.b"]);
  });

  it("spells every path and method a choice can make", () => {
    const spec: OpenApi = {
      paths: {
        "/api/rows": { post: okWith(ref("RowOut")) },
        "/api/rows/{row_id}": { patch: okWith(ref("RowOut")) },
      },
      components: { schemas: { RowOut: object("a", "b", "c") } },
    };
    const lines = findingsOf(
      {
        "src/lib/schemas/rows.ts": schemas("a: string; b: string"),
        "src/lib/api/rows.ts": `
          import { request } from "./client";
          import type { Row } from "../schemas/rows";
          export const save = (id: string | null) =>
            request<Row>(id ? \`/api/rows/\${id}\` : "/api/rows", { method: id ? "PATCH" : "POST" });`,
        "src/use.ts": `
          import { save } from "./lib/api/rows";
          export const show = async () => { const r = await save(null); return r.a + r.b; };`,
      },
      spec,
    );
    expect(lines).toEqual(["undeclared RowOut.c"]);
  });
});

describe("matching a path", () => {
  const spec: OpenApi = {
    paths: {
      "/v/{id}": { delete: {} },
      "/v/options": { get: {} },
      "/chat/": {},
      "/v/{id}/overview": {},
    },
  };
  const matchPath = (path: string) => matchPaths(spec, path)[0];
  it("prefers the literal segment, as the router's order does", () => {
    expect(matchPath("/v/options")).toBe("/v/options");
    expect(matchPath(`/v/${DYNAMIC}`)).toBe("/v/{id}");
    expect(matchPath(`/v/${DYNAMIC}/overview`)).toBe("/v/{id}/overview");
  });
  it("reads a trailing slash as the same path, and a dynamic piece only as a parameter", () => {
    expect(matchPath("/chat")).toBe("/chat/");
    expect(matchPath(`/${DYNAMIC}/options`)).toBeUndefined();
  });
  it("lets the method choose: a literal path without it falls to the parameter's", () => {
    expect(findOperation(spec, "/v/options", "GET")?.path).toBe("/v/options");
    expect(findOperation(spec, "/v/options", "DELETE")?.path).toBe("/v/{id}");
  });
});

describe("the client", () => {
  const ROWS = {
    "src/lib/schemas/rows.ts": schemas("a: string; b: string"),
    "src/lib/api/rows.ts": `
      import { request } from "./client";
      import type { Row } from "../schemas/rows";
      export const load = () => request<Row[]>("/rows");
      export const drop = (id: string) => request<void>(\`/rows/\${id}\`, { method: "DELETE" });`,
    "src/use.ts": READ_A_B,
  };
  const spec: OpenApi = {
    paths: {
      "/api/v1/rows": { get: okWith({ type: "array", items: ref("RowOut") }) },
      "/api/v1/rows/{row_id}": { delete: { responses: { "204": {} } } },
    },
    components: { schemas: { RowOut: object("a", "b") } },
  };

  it("puts its prefix in front of every path, and an answer of no JSON is read as nothing", () => {
    expect(collectOf(ROWS, spec, { prefix: "/api/v1" })).toEqual([]);
  });

  it("with a prefix that drifted pairs nothing, and says what it looked for", () => {
    const findings = collectOf(ROWS, spec, { prefix: "/api/v2" });
    expect(findings.map((f) => `${f.kind} ${f.key}: ${f.detail}`)).toEqual([
      "unpaired lib/api/rows.ts#drop: no backend operation for DELETE /api/v2/rows/{…}",
      "unpaired lib/api/rows.ts#load: no backend operation for GET /api/v2/rows",
    ]);
  });
});

describe("what a value is", () => {
  const spec: OpenApi = {
    paths: {
      "/rows": { get: okWith({ type: "array", items: ref("RowOut") }) },
      "/rows/one": { get: okWith(ref("RowOut")) },
    },
    components: {
      schemas: {
        RowOut: {
          type: "object",
          properties: {
            a: { type: "string" },
            b: { anyOf: [{ type: "string" }, { type: "null" }] },
            pos: ref("Pos"),
          },
        },
        Pos: object("lat"),
      },
    },
  };
  const read = (
    call: string,
    row = "a: string; b: string | null; pos: { lat: string }",
  ) =>
    collectOf(
      {
        "src/lib/schemas/rows.ts": schemas(row),
        "src/lib/api/rows.ts": `
          import { request } from "./client";
          import type { Row } from "../schemas/rows";
          export const load = () => ${call};`,
        "src/use.ts": `
          import { load } from "./lib/api/rows";
          export const show = async () => { const r: unknown = await load(); return r; };`,
      },
      spec,
    ).filter((f) => f.kind === "mismatched");
  const lines = (findings: { key: string; detail?: string }[]) =>
    findings.map((f) => `${f.key}: ${f.detail}`);

  it("is red when a list is read as one object, or one object as a list", () => {
    expect(lines(read(`request<Row>("/rows")`))).toEqual([
      "GET /rows: read as an object, sent as a list",
    ]);
    expect(lines(read(`request<Row[]>("/rows/one")`))).toEqual([
      "GET /rows/one: read as a list, sent as an object",
    ]);
  });

  it("is red when an object is read as a scalar", () => {
    expect(lines(read(`request<string>("/rows/one")`))).toEqual([
      "GET /rows/one: read as a scalar, sent as an object",
    ]);
  });

  it("follows each field into its own value", () => {
    expect(
      lines(
        read(`request<Row[]>("/rows")`, "a: string; b: string; pos: string"),
      ),
    ).toEqual(["RowOut.pos: read as a scalar, sent as an object"]);
  });

  it("agrees through a null, a branded scalar and a list read as a list", () => {
    const row = `a: string & { readonly brand: "A" }; b: string | null; pos: { lat: string }`;
    expect(read(`request<Row[]>("/rows")`, row)).toEqual([]);
    expect(read(`request<Row>("/rows/one")`, row)).toEqual([]);
  });
});

describe("a gate that finds no request", () => {
  it("fails rather than pass having checked nothing", () => {
    const noRequest = { "src/use.ts": `export const nothing = 1;` };
    expect(() => collectOf(noRequest, contract("a"))).toThrow(
      "no call of request from src/lib/api/client.ts was found",
    );
  });
});
