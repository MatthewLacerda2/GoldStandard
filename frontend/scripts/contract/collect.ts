// Puts the halves together: the fields the frontend declares for the API's
// answers, which of them it reads, and how they compare with what the
// backend's contract says it sends.
import ts from "typescript";
import { join, relative } from "node:path";
import { analyze, type Field } from "./analyze";
import {
  DYNAMIC,
  findOperation,
  type MatchedOperation,
  type OpenApi,
  type Schema,
} from "./openapi";
import { createPairing, discard, pair } from "./pair";
import { findRequests, type Client, type Request } from "./requests";
import { elementOf, rootsOf } from "./types";

export type FindingKind =
  "unread" | "undeclared" | "phantom" | "mismatched" | "unpaired";

export interface Finding {
  kind: FindingKind;
  /** `unread`, `phantom`: the frontend field, `lib/schemas/items.ts#Item.name`;
   *  `undeclared`: the backend schema's, `ItemRead.name`; `mismatched`: the
   *  backend's value (`ItemRead.tags`, or the operation `GET /api/v1/items`);
   *  `unpaired`: the call site, `lib/api/items.ts#listItems`. */
  key: string;
  /** `file:line` of the declaration, when there is one. */
  where?: string;
  detail?: string;
}

export interface CollectOptions {
  /** The frontend's root (`frontend/`): keys and locations are relative to it. */
  root: string;
  /** Files whose accesses do not count as reads: the schema modules, tests, mocks. */
  isExcludedReader: (fileName: string) => boolean;
  /** The app's own source, where tracked fields are declared. */
  isProjectFile: (fileName: string) => boolean;
  /** The API client (its file relative to `root`), and the prefix it puts in
   *  front of every path. */
  client: Client & { prefix: string };
}

export interface Collected {
  findings: Finding[];
  stats: { requests: number; paired: number; fields: number };
}

const UNTYPED =
  ts.TypeFlags.Void |
  ts.TypeFlags.Undefined |
  ts.TypeFlags.Unknown |
  ts.TypeFlags.Any;

/** Whether an answer is read as nothing: `void`, `unknown`, `any`, or a type
 *  that names no field (`object`, `{}`, `Record<string, unknown>`), alone or
 *  as an array's items. Any of them would otherwise quiet the gate. */
function readsNothing(checker: ts.TypeChecker, type: ts.Type): boolean {
  if (type.flags & (UNTYPED | ts.TypeFlags.NonPrimitive)) return true;
  const element = elementOf(checker, type);
  if (element) return readsNothing(checker, element);
  if (
    !(type.flags & ts.TypeFlags.Object) ||
    checker.getPropertiesOfType(type).length > 0
  ) {
    return false;
  }
  const values = type.getStringIndexType();
  return !values || !!(values.flags & UNTYPED);
}

export function collect(
  program: ts.Program,
  spec: OpenApi,
  options: CollectOptions,
): Collected {
  const checker = program.getTypeChecker();
  const analysis = analyze(program, options);
  const rel = (fileName: string) => relative(options.root, fileName);
  const isReaderFile = (f: string) =>
    options.isProjectFile(f) && !options.isExcludedReader(f);

  const findings: Finding[] = [];
  const pairing = createPairing();
  const roots: ts.Type[] = [];
  const client = {
    ...options.client,
    file: join(options.root, options.client.file),
  };
  const requests = findRequests(program, client, isReaderFile, (node) =>
    siteOf(node, rel),
  );
  // A client the config no longer describes finds no request, and a gate
  // that checked nothing must not pass.
  if (requests.length === 0) {
    throw new Error(
      `contract: no call of ${client.fetchers.join(" or ")} from ${options.client.file}` +
        " was found; does CLIENT in scripts/contract/config.ts still describe the API client?",
    );
  }
  let paired = 0;
  for (const request of requests) {
    // Every operation the call can land on: each path it can spell with each
    // method it can use. A method decided out of sight is not guessed.
    const operations = request.paths.flatMap((path) =>
      request.methods.flatMap(
        (method) =>
          findOperation(spec, options.client.prefix + path, method) ?? [],
      ),
    );
    const derived = operations.flatMap((o) =>
      o.schema
        ? [{ schema: o.schema, label: `${o.method.toUpperCase()} ${o.path}` }]
        : [],
    );
    // An answer read as nothing: whatever it sends, nothing reads. One that
    // sends no JSON is right to be read so.
    if (readsNothing(checker, request.type)) {
      for (const { schema, label } of derived)
        discard(spec, schema, label, pairing);
      if (operations.length > 0) {
        paired++;
        continue;
      }
      findings.push({
        kind: "unpaired",
        key: request.site,
        detail: unpairedBecause(request, [], options.client.prefix),
      });
      continue;
    }
    roots.push(request.type);
    const marked = markedSchema(checker, request.type);
    const known = !marked || marked.name in (spec.components?.schemas ?? {});
    const schemas =
      derived.length > 0
        ? derived
        : marked && known
          ? [{ schema: marked.schema, label: "@backend" }]
          : [];
    for (const { schema, label } of schemas)
      pair(checker, spec, request.type, schema, label, pairing);
    if (schemas.length > 0) {
      paired++;
      continue;
    }
    findings.push({
      kind: "unpaired",
      key: request.site,
      detail: known
        ? unpairedBecause(request, operations, options.client.prefix)
        : `@backend names ${marked!.name}, which the contract does not have`,
    });
  }

  // Every field the answers carry, as declared by the frontend, by where it
  // was declared — two types of one name must not read for each other.
  const declared = new Map<
    string,
    { field: Field; read: boolean; whole?: string }
  >();
  const seen = new Set<ts.Type>();
  const walk = (type: ts.Type) => {
    if (seen.has(type)) return;
    seen.add(type);
    if (type.isUnion() || type.isIntersection())
      return type.types.forEach(walk);
    const element = elementOf(checker, type);
    if (element) return walk(element);
    if (!(type.flags & ts.TypeFlags.Object)) return;
    const values = type.getStringIndexType();
    if (values) walk(values);
    for (const prop of checker.getPropertiesOfType(type)) {
      let tracked = false;
      for (const root of rootsOf(checker, prop)) {
        const field = analysis.fieldOf(root);
        if (!field) continue;
        tracked = true;
        const prev = declared.get(field.key);
        const whole = prev?.whole ?? analysis.wholeUseOf(root);
        declared.set(field.key, {
          field,
          read: (prev?.read ?? false) || analysis.isRead(root),
          whole,
        });
      }
      if (tracked)
        walk(checker.getNonNullableType(checker.getTypeOfSymbol(prop)));
    }
  };
  roots.forEach(walk);

  const phantoms = [...pairing.phantom].flatMap(([symbol, schemas]) => {
    const field = analysis.fieldOf(symbol);
    return field ? [{ field, schemas }] : [];
  });
  const where = (field: Field) => `${rel(field.file)}:${field.line}`;
  for (const { field, read, whole } of declared.values()) {
    if (read) continue;
    const detail = whole ? `handed over whole at ${rel(whole)}` : undefined;
    findings.push({
      kind: "unread",
      key: field.key,
      where: where(field),
      detail,
    });
  }
  for (const [key, isDeclared] of pairing.sent) {
    if (!isDeclared) findings.push({ kind: "undeclared", key });
  }
  for (const [key, detail] of pairing.mismatched) {
    findings.push({ kind: "mismatched", key, detail });
  }
  for (const { field, schemas } of phantoms) {
    findings.push({
      kind: "phantom",
      key: field.key,
      where: where(field),
      detail: `not in ${[...schemas].sort().join(", ")}`,
    });
  }
  return {
    findings: dedupe(findings),
    stats: { requests: requests.length, paired, fields: declared.size },
  };
}

// Why a request found no schema to pair with.
function unpairedBecause(
  request: Request,
  operations: MatchedOperation[],
  prefix: string,
): string {
  if (operations.length > 0) {
    const ops = operations
      .map((o) => `${o.method.toUpperCase()} ${o.path}`)
      .join(", ");
    return `${ops} answers no JSON`;
  }
  if (request.paths.length === 0) return "its path is built out of sight";
  if (request.methods.length === 0) return "its method is decided out of sight";
  const spelled = request.paths
    .map((p) => prefix + p.replaceAll(DYNAMIC, "{…}"))
    .join(" | ");
  return `no backend operation for ${request.methods.join("/").toUpperCase()} ${spelled}`;
}

/** `@backend Name` on the type (or on its elements' type): the schema it mirrors. */
function markedSchema(
  checker: ts.TypeChecker,
  type: ts.Type,
): { name: string; schema: Schema } | undefined {
  const element = elementOf(checker, type);
  const target = element ?? type;
  const symbol = target.aliasSymbol ?? target.getSymbol();
  for (const decl of symbol?.declarations ?? []) {
    for (const tag of ts.getJSDocTags(decl)) {
      if (tag.tagName.text !== "backend") continue;
      const name = ts.getTextOfJSDocComment(tag.comment)?.trim();
      if (!name) continue;
      const ref: Schema = { $ref: `#/components/schemas/${name}` };
      return { name, schema: element ? { type: "array", items: ref } : ref };
    }
  }
  return undefined;
}

// A call site by the declaration it sits in, so a line moving changes nothing.
function siteOf(node: ts.Node, rel: (fileName: string) => string): string {
  const names: string[] = [];
  for (
    let n: ts.Node | undefined = node.parent;
    n && !ts.isSourceFile(n);
    n = n.parent
  ) {
    const name = (n as ts.NamedDeclaration).name;
    if (
      name &&
      ts.isIdentifier(name) &&
      (ts.isVariableDeclaration(n) ||
        ts.isFunctionDeclaration(n) ||
        ts.isMethodDeclaration(n) ||
        ts.isPropertyAssignment(n))
    ) {
      names.unshift(name.text);
    }
  }
  const file = rel(node.getSourceFile().fileName).replace(/^src\//, "");
  return `${file}#${names.join(".") || "(module)"}`;
}

function dedupe(findings: Finding[]): Finding[] {
  const byId = new Map<string, Finding>();
  for (const f of findings) {
    const id = `${f.kind} ${f.key}`;
    if (!byId.has(id)) byId.set(id, f);
  }
  return [...byId.values()].sort((a, b) =>
    `${a.kind} ${a.key}`.localeCompare(`${b.kind} ${b.key}`),
  );
}
