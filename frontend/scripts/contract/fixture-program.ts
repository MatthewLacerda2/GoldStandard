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

export function programOf(
  files: Record<string, string>,
  root = ROOT,
): ts.Program {
  const options: ts.CompilerOptions = {
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
  const virtual = new Map(
    Object.entries({ [CLIENT.file]: CLIENT_SOURCE, ...files }).map(
      ([path, text]) => [`${root}/${path}`, text],
    ),
  );
  const host = ts.createCompilerHost(options);
  const { getSourceFile, fileExists, readFile, directoryExists } = host;
  host.getSourceFile = (name, version, ...rest) => {
    const text = virtual.get(name);
    return text === undefined
      ? getSourceFile.call(host, name, version, ...rest)
      : ts.createSourceFile(name, text, version);
  };
  host.fileExists = (name) => virtual.has(name) || fileExists.call(host, name);
  host.readFile = (name) => virtual.get(name) ?? readFile.call(host, name);
  host.directoryExists = (dir) =>
    [...virtual.keys()].some((path) => path.startsWith(`${dir}/`)) ||
    (directoryExists?.call(host, dir) ?? false);
  return ts.createProgram([...virtual.keys()], options, host);
}

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
