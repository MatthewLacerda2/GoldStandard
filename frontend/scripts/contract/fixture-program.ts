// A TypeScript program held in memory, for the contract gate's tests: a few
// files under `/app/src`, a `request` where the gate looks for it, and the
// standard library — nothing read from the real tree.
import ts from "typescript";
import { collect, type Finding } from "./collect";
import { isExcludedReader } from "./config";
import type { OpenApi, Schema } from "./openapi";

export const ROOT = "/app";

const CLIENT_SOURCE = `
export async function request<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  return JSON.parse(path + String(options.method)) as T;
}`;
const CLIENT = {
  file: "src/lib/api/client.ts",
  fetchers: ["request"],
  prefix: "",
};

const OPTIONS: ts.CompilerOptions = {
  target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.ESNext,
  moduleResolution: ts.ModuleResolutionKind.Bundler,
  strict: true,
  noEmit: true,
  skipLibCheck: true,
  types: [],
  lib: ["lib.es2022.d.ts"],
  jsx: ts.JsxEmit.Preserve,
};

// The standard library is all but a handful of a fixture program's ~60 files,
// and parsing it was nearly all of a program's cost, paid again by every
// program a test builds. Its files never change and every program here is
// built with the same options, so each is parsed once per test file and
// shared, as TypeScript's own language service shares them; a fixture's own
// files are parsed fresh every time, so no test sees another's.
const STANDARD_LIBRARY = new Map<string, ts.SourceFile | undefined>();

export function programOf(
  files: Record<string, string>,
  root = ROOT,
): ts.Program {
  const virtual = new Map(
    Object.entries({ [CLIENT.file]: CLIENT_SOURCE, ...files }).map(
      ([path, text]) => [`${root}/${path}`, text],
    ),
  );
  const host = ts.createCompilerHost(OPTIONS);
  const { getSourceFile, fileExists, readFile, directoryExists } = host;
  host.getSourceFile = (name, version, ...rest) => {
    const text = virtual.get(name);
    if (text !== undefined) return ts.createSourceFile(name, text, version);
    if (!STANDARD_LIBRARY.has(name))
      STANDARD_LIBRARY.set(
        name,
        getSourceFile.call(host, name, version, ...rest),
      );
    return STANDARD_LIBRARY.get(name);
  };
  host.fileExists = (name) => virtual.has(name) || fileExists.call(host, name);
  host.readFile = (name) => virtual.get(name) ?? readFile.call(host, name);
  host.directoryExists = (dir) =>
    [...virtual.keys()].some((path) => path.startsWith(`${dir}/`)) ||
    (directoryExists?.call(host, dir) ?? false);
  return ts.createProgram([...virtual.keys()], OPTIONS, host);
}

// The first program a file builds still pays for the compiler starting up:
// the library's one parse, and a checker not yet compiled to machine code. That
// is a cost of loading TypeScript, not of any test, and on a loaded machine it
// alone outran the first test's 5 s; so it is paid here, while the file loads,
// as `import ts` itself is.
ts.getPreEmitDiagnostics(programOf({}));

/** A contract with one `GET` per path, each answering the schema given. */
export function specOf(
  responses: Record<string, Schema>,
  schemas: Record<string, Schema> = {},
): OpenApi {
  const paths: OpenApi["paths"] = {};
  for (const [path, schema] of Object.entries(responses))
    paths[path] = { get: okWith(schema) };
  return { paths, components: { schemas } };
}

/** An operation answering `schema` with a 200. */
export const okWith = (schema: Schema) => ({
  responses: { "200": { content: { "application/json": { schema } } } },
});

export const object = (...fields: string[]): Schema => ({
  type: "object",
  properties: Object.fromEntries(fields.map((f) => [f, { type: "string" }])),
});

export const ref = (name: string): Schema => ({
  $ref: `#/components/schemas/${name}`,
});

/** The findings for these files against this contract, as `kind Key` lines. */
export function findingsOf(
  files: Record<string, string>,
  spec: OpenApi,
): string[] {
  return collectOf(files, spec).map((f: Finding) => `${f.kind} ${f.key}`);
}

/** The findings whole, with the checkout at `root` (`/app` by default) and
 *  the client's path prefix (none by default). */
export function collectOf(
  files: Record<string, string>,
  spec: OpenApi,
  { root = ROOT, prefix = "" }: { root?: string; prefix?: string } = {},
): Finding[] {
  const program = programOf(files, root);
  // A fixture that does not compile proves nothing: an import it cannot
  // resolve is an `any`, which carries no field at all.
  const errors = ts.getPreEmitDiagnostics(program);
  if (errors.length > 0) {
    throw new Error(
      errors
        .map((d) => ts.flattenDiagnosticMessageText(d.messageText, "\n"))
        .join("\n"),
    );
  }
  return collect(program, spec, {
    root,
    isProjectFile: (fileName) => fileName.startsWith(`${root}/src/`),
    isExcludedReader,
    client: { ...CLIENT, prefix },
  }).findings;
}
