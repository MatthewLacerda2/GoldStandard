// The backend half of the contract gate: the committed OpenAPI contract
// (`frontend/openapi.json`, written by `make openapi`), the operation a
// request lands on, and the schema its 2xx answer carries.

export interface Schema {
  $ref?: string;
  type?: string;
  properties?: Record<string, Schema>;
  items?: Schema;
  additionalProperties?: boolean | Schema;
  anyOf?: Schema[];
  oneOf?: Schema[];
  allOf?: Schema[];
}

interface Operation {
  responses?: Record<string, { content?: Record<string, { schema?: Schema }> }>;
}

export interface OpenApi {
  paths: Record<string, Record<string, Operation>>;
  components?: { schemas?: Record<string, Schema> };
}

export const HTTP_METHODS = ["get", "post", "put", "patch", "delete"] as const;

/** The one placeholder a request path can carry where the code builds it at
 *  run time (an id, a parameter). */
export const DYNAMIC = "\u0000";

export interface MatchedOperation {
  method: string;
  path: string;
  /** The JSON its 2xx answer carries; `undefined` when it answers no JSON. */
  schema: Schema | undefined;
}

/** The OpenAPI paths a request path fits, best first: segment by segment, a
 *  literal segment of the request matching the same literal or a `{param}`,
 *  a dynamic one only a `{param}`. More literal matches rank first
 *  (`/items/archived` before `/items/{id}`): FastAPI serves the first route
 *  whose path and method both match, and a literal route is declared before
 *  its `{param}` sibling — so the method decides among them
 *  (`findOperation`). */
export function matchPaths(spec: OpenApi, requestPath: string): string[] {
  const wanted = requestPath.split("/");
  const fitting: { path: string; score: number }[] = [];
  for (const path of Object.keys(spec.paths)) {
    // FastAPI serves `/chat/` at `/chat` too; the code spells either.
    const segments = path.replace(/(.)\/$/, "$1").split("/");
    if (segments.length !== wanted.length) continue;
    let score = 0;
    let fits = true;
    for (let i = 0; i < segments.length && fits; i++) {
      const isParam = /^\{[^}]+\}$/.test(segments[i]);
      if (wanted[i].includes(DYNAMIC)) fits = isParam && wanted[i] === DYNAMIC;
      else if (segments[i] === wanted[i]) score++;
      else fits = isParam;
    }
    if (fits) fitting.push({ path, score });
  }
  return fitting.sort((a, b) => b.score - a.score).map((f) => f.path);
}

/** The schema of an operation's first 2xx JSON answer. */
export function responseSchema(operation: Operation): Schema | undefined {
  const codes = Object.keys(operation.responses ?? {})
    .filter((code) => code.startsWith("2"))
    .sort();
  for (const code of codes) {
    const schema =
      operation.responses?.[code]?.content?.["application/json"]?.schema;
    if (schema) return schema;
  }
  return undefined;
}

/** The operation a request lands on. */
export function findOperation(
  spec: OpenApi,
  requestPath: string,
  method: string,
): MatchedOperation | undefined {
  const verb = method.toLowerCase();
  const path = matchPaths(spec, requestPath).find((p) => spec.paths[p][verb]);
  return path
    ? { method: verb, path, schema: responseSchema(spec.paths[path][verb]) }
    : undefined;
}

/** The component name a `$ref` points at. */
export const refName = (ref: string) =>
  ref.replace(/^#\/components\/schemas\//, "");

/** Whether a schema says nothing about its fields: a free-form object (a
 *  `dict` the API passes through), or no schema at all. */
export function isOpaque(schema: Schema): boolean {
  if (schema.$ref || schema.anyOf || schema.oneOf || schema.allOf) return false;
  if (schema.properties) return false;
  if (schema.type === "array")
    return schema.items ? isOpaque(schema.items) : true;
  if (typeof schema.additionalProperties === "object") return false;
  return schema.type === "object" || schema.type === undefined;
}
