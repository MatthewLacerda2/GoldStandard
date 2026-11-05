// Walks a TypeScript type and the backend schema it mirrors side by side —
// arrays to their items, records to their values, each field to its own —
// and notes, per field of each backend schema, whether the frontend declares
// it, per declared field, whether the backend sends it, and where the two
// disagree on what a value is: a list, an object, or a scalar.
import ts from "typescript";
import { isOpaque, refName, type OpenApi, type Schema } from "./openapi";
import { elementOf, rootsOf, typeId } from "./types";

export interface Pairing {
  /** `Schema.field` -> whether some frontend type declares it. */
  sent: Map<string, boolean>;
  /** A declared field's property symbols -> the backend schemas that do not send it. */
  phantom: Map<ts.Symbol, Set<string>>;
  /** Every backend schema some frontend type was paired with. */
  schemas: Set<string>;
  /** Where a frontend type reads a value as another kind than the backend
   *  sends (the field, `ItemRead.tags`, or the operation, `GET /api/v1/items`)
   *  -> how they differ. */
  mismatched: Map<string, string>;
}

interface Member {
  name?: string;
  schema: Schema;
}

export function createPairing(): Pairing {
  return {
    sent: new Map(),
    phantom: new Map(),
    schemas: new Set(),
    mismatched: new Map(),
  };
}

export function pair(
  checker: ts.TypeChecker,
  spec: OpenApi,
  type: ts.Type,
  schema: Schema,
  /** What the schema is called when it has no name of its own: the operation. */
  label: string,
  into: Pairing,
): void {
  const seen = new Set<string>();
  const components = spec.components?.schemas ?? {};

  const parts = (t: ts.Type): ts.Type[] =>
    t.isUnion()
      ? t.types.flatMap(parts)
      : t.flags & (ts.TypeFlags.Null | ts.TypeFlags.Undefined)
        ? []
        : [t];
  const isObject = (t: ts.Type) =>
    !!(t.flags & ts.TypeFlags.Object) || t.isIntersection();

  const resolve = (s: Schema) => resolveSchema(components, s);

  const walk = (t: ts.Type, s: Schema, at: string) => {
    const members = resolve(s);
    if (members.length === 0) return;
    const owners = members.map((m) => m.name ?? at);
    const key = `${typeId(t)}>${owners.join("|")}`;
    if (seen.has(key)) return;
    seen.add(key);
    const owner = [...new Set(owners)].join(" | ");
    const differ = kindsDiffer(checker, parts(t), members);
    if (differ) {
      into.mismatched.set(at, differ);
      return;
    }
    if (members.some((m) => isOpaque(m.schema))) return;
    for (const m of members) if (m.name) into.schemas.add(m.name);
    const tsParts = parts(t).filter(isObject);
    if (tsParts.length === 0) return;

    // Arrays and records: their items, as one schema however many members
    // (`list[A] | list[B]` is a list of `A | B`).
    const items = members.flatMap((m) =>
      m.schema.type === "array" && m.schema.items ? [m.schema.items] : [],
    );
    if (items.length > 0) {
      for (const part of tsParts) {
        const each = elementOf(checker, part);
        if (each) walk(each, { anyOf: items }, `${owner}[]`);
      }
      return;
    }
    const values = members.flatMap(({ schema: m }) =>
      !m.properties && typeof m.additionalProperties === "object"
        ? [m.additionalProperties]
        : [],
    );
    for (const part of values.length > 0 ? tsParts : []) {
      const index = part.getStringIndexType();
      if (index) walk(index, { anyOf: values }, `${owner}{}`);
    }
    const objects = members.filter((m) => m.schema.properties);
    if (objects.length === 0) return;

    // Each member is compared with the frontend's types that look most like
    // it: `Token | Challenge` on both sides pairs member with member, and
    // `FileRow | FolderRow` read from the folders' endpoint is a `FolderRow`.
    const candidates = tsParts.filter((part) => !elementOf(checker, part));
    const declaredSomewhere = new Map<string, ts.Symbol[]>();
    for (const m of objects) {
      const fields = m.schema.properties!;
      const overlap = (part: ts.Type) =>
        checker.getPropertiesOfType(part).filter((p) => p.getName() in fields)
          .length;
      const best = Math.max(0, ...candidates.map(overlap));
      const declared = new Map<string, ts.Symbol[]>();
      for (const part of candidates.filter((c) => overlap(c) === best)) {
        for (const prop of checker.getPropertiesOfType(part)) {
          declared.set(prop.getName(), [
            ...(declared.get(prop.getName()) ?? []),
            prop,
          ]);
        }
      }
      if (declared.size === 0) continue;
      const sender = m.name ?? at;
      for (const [field, fieldSchema] of Object.entries(fields)) {
        const props = declared.get(field);
        const fieldKey = `${sender}.${field}`;
        into.sent.set(fieldKey, (into.sent.get(fieldKey) ?? false) || !!props);
        for (const prop of props ?? [])
          walk(checker.getTypeOfSymbol(prop), fieldSchema, fieldKey);
      }
      for (const [field, props] of declared)
        declaredSomewhere.set(field, props);
    }
    // A field the frontend declares that no member sends, unless one of them
    // takes any field (`extra="allow"`).
    if (objects.some((m) => !!m.schema.additionalProperties)) return;
    for (const [field, props] of declaredSomewhere) {
      if (objects.some((m) => field in m.schema.properties!)) continue;
      for (const prop of props) {
        for (const root of rootsOf(checker, prop)) {
          const set = into.phantom.get(root) ?? new Set<string>();
          set.add(owner);
          into.phantom.set(root, set);
        }
      }
    }
  };

  walk(type, schema, label);
}

/** An answer the frontend reads as nothing (`void`, `unknown`): every field
 *  it sends is one no frontend type declares, unless another request's type
 *  declares it. Turning `request<Row>` into `request<unknown>` must not
 *  quiet the gate. */
export function discard(
  spec: OpenApi,
  schema: Schema,
  label: string,
  into: Pairing,
): void {
  const components = spec.components?.schemas ?? {};
  const seen = new Set<Schema>();
  const visit = (s: Schema, at: string) => {
    for (const m of resolveSchema(components, s)) {
      if (seen.has(m.schema) || isOpaque(m.schema)) continue;
      seen.add(m.schema);
      const owner = m.name ?? at;
      if (m.name) into.schemas.add(m.name);
      const { items, properties, additionalProperties: values } = m.schema;
      if (m.schema.type === "array" && items) visit(items, `${owner}[]`);
      else if (!properties && typeof values === "object")
        visit(values, `${owner}{}`);
      for (const field of Object.keys(properties ?? {})) {
        into.sent.set(
          `${owner}.${field}`,
          into.sent.get(`${owner}.${field}`) ?? false,
        );
      }
    }
  };
  visit(schema, label);
}

// The schema with its `$ref`s followed and its nulls dropped: the members it
// may be, each under its component name when it has one.
function resolveSchema(
  components: Record<string, Schema>,
  s: Schema,
  name?: string,
): Member[] {
  if (s.$ref) {
    const target = components[refName(s.$ref)];
    return target ? resolveSchema(components, target, refName(s.$ref)) : [];
  }
  const union = s.anyOf ?? s.oneOf;
  if (union) {
    return union
      .filter((m) => m.type !== "null")
      .flatMap((m) => resolveSchema(components, m));
  }
  if (s.allOf?.length === 1) return resolveSchema(components, s.allOf[0], name);
  return [{ name, schema: s }];
}

type Kind = "list" | "object" | "scalar";
const KIND_NAMES: Record<Kind, string> = {
  list: "a list",
  object: "an object",
  scalar: "a scalar",
};

// How a value is read and how it is sent, when no kind is both: an answer
// read as one object that is a list, a list read as one object, a field read
// as an object that is a string. `undefined` when they agree, or when either
// side says nothing (`any`, `unknown`, a schema with no type).
function kindsDiffer(
  checker: ts.TypeChecker,
  tsParts: readonly ts.Type[],
  members: readonly Member[],
): string | undefined {
  const read = new Set<Kind>();
  for (const part of tsParts) {
    const kind = tsKind(checker, part);
    if (!kind) return undefined;
    read.add(kind);
  }
  const sent = new Set<Kind>();
  for (const { schema } of members) {
    const kind = schemaKind(schema);
    if (!kind) return undefined;
    sent.add(kind);
  }
  if (read.size === 0 || [...read].some((kind) => sent.has(kind)))
    return undefined;
  const names = (kinds: Set<Kind>) =>
    [...kinds].map((kind) => KIND_NAMES[kind]).join(" or ");
  return `read as ${names(read)}, sent as ${names(sent)}`;
}

const SCALAR =
  ts.TypeFlags.StringLike |
  ts.TypeFlags.NumberLike |
  ts.TypeFlags.BooleanLike |
  ts.TypeFlags.BigIntLike |
  ts.TypeFlags.EnumLike;

function tsKind(checker: ts.TypeChecker, type: ts.Type): Kind | undefined {
  if (elementOf(checker, type)) return "list";
  if (type.flags & SCALAR) return "scalar";
  // A branded scalar (`string & { __brand: "Id" }`) is still a scalar.
  if (type.isIntersection())
    return type.types.some((t) => t.flags & SCALAR) ? "scalar" : "object";
  return type.flags & ts.TypeFlags.Object ? "object" : undefined;
}

function schemaKind(schema: Schema): Kind | undefined {
  if (schema.type === "array") return "list";
  if (schema.type === "object" || schema.properties) return "object";
  if (typeof schema.additionalProperties === "object") return "object";
  const scalars = ["string", "number", "integer", "boolean"];
  return schema.type && scalars.includes(schema.type) ? "scalar" : undefined;
}
