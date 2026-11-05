// The TypeScript half of the contract gate: which fields of the API's
// answers the frontend declares, and which of them some code reads.
//
// One pass with the TypeChecker over the program (`findReferences` per field
// does not scale to thousands of fields):
//
// - A READ is a property access `a.b`, an element access with a literal
//   `a["b"]`, a destructuring `{ b } = a` / `({ b }) =>`, or an `in` test
//   `"b" in a` — anywhere outside the excluded readers (the schema modules,
//   tests, mocks). `getRootSymbols` takes the symbol back from a `Pick`, an
//   `Omit`, a mapped type, a union or an intersection to the declaration the
//   field was written in, so a read through `Pick<Item, "name">` is a read
//   of `Item.name`.
// - A WRITE is not a read: the left side of `=`, and every object literal a
//   test or a mock builds.
// - A FLOW carries a read backwards. Wherever a value of one type lands where
//   another is expected — an argument and its parameter, an initializer and
//   its variable's type, a return and the declared return type, a JSX
//   attribute and its prop, a spread of props and the component's — each property of the expected type is linked to
//   the property of the same name in the value's type. Reading the expected
//   one reads the value's: `labelOf(row: { id; name })` reading `row.name`
//   reads `Item.name`, which "find references" never connects. An argument of a generic helper is linked to the parameter as
//   declared too, each type parameter standing for its constraint:
//   `ownedBy(rows, id)` reading `row.owner_id` of `T extends { owner_id }`
//   reads the `owner_id` of the rows handed in.
import ts from "typescript";
import { relative } from "node:path";
import { genericKeyReads } from "./generic-keys";
import { isCarrier, isIntrinsicSpread, isOpenSink, isSink } from "./sinks";

/** A field the frontend declares: the declaration it was written in. */
export interface Field {
  /** `Type.field`, nested literals as `Type.outer.field`. */
  key: string;
  file: string;
  line: number;
}

export interface AnalyzeOptions {
  /** The frontend's root (`frontend/`): an inline literal is named by its path from here. */
  root: string;
  /** Files whose accesses do not count as reads. */
  isExcludedReader: (fileName: string) => boolean;
  /** Files whose declarations can be tracked fields (the app's own source). */
  isProjectFile: (fileName: string) => boolean;
}

export interface Analysis {
  /** Every property declaration the program reads, by its root symbol. */
  isRead: (symbol: ts.Symbol) => boolean;
  /** The field a property symbol was declared as, `undefined` outside the project. */
  fieldOf: (symbol: ts.Symbol) => Field | undefined;
  /** Where an object carrying the field is handed over whole — to
   *  `Object.entries`, `JSON.stringify`, a `for…in`, a spread nothing types —
   *  which may read it by a name no code spells: the hint an unread field's
   *  report carries. */
  wholeUseOf: (symbol: ts.Symbol) => string | undefined;
}

const WHOLE_READERS = new Set([
  "Object.keys",
  "Object.values",
  "Object.entries",
  "Object.assign",
  "JSON.stringify",
  "structuredClone",
]);

const MAX_LINK_DEPTH = 6;
const MAX_CARRY_DEPTH = 3;

export function analyze(
  program: ts.Program,
  options: AnalyzeOptions,
): Analysis {
  const checker = program.getTypeChecker();
  const read = new Set<ts.Symbol>();
  // target property -> the source properties a read of it reads too
  const flows = new Map<ts.Symbol, Set<ts.Symbol>>();
  // A pair of types linked, with the least depth it was linked at.
  const linked = new Map<string, number>();
  const wholeUses = new Map<ts.Symbol, string>();

  const roots = (symbol: ts.Symbol): readonly ts.Symbol[] => {
    const all = checker.getRootSymbols(symbol);
    return all.length > 0 ? all : [symbol];
  };
  const markRead = (symbol: ts.Symbol | undefined) => {
    if (!symbol || !(symbol.flags & ts.SymbolFlags.Property)) return;
    for (const root of roots(symbol)) read.add(root);
  };
  const addFlow = (target: ts.Symbol, source: ts.Symbol) => {
    for (const t of roots(target)) {
      for (const s of roots(source)) {
        if (t === s) continue;
        let set = flows.get(t);
        if (!set) flows.set(t, (set = new Set()));
        set.add(s);
      }
    }
  };

  const typeId = (type: ts.Type) => (type as unknown as { id: number }).id;
  // A union's members, each without `null`/`undefined`; `NoInfer<T>` as `T`
  // (TanStack Query types a result's `data` so).
  const parts = (type: ts.Type): ts.Type[] => {
    if (type.isUnion()) return type.types.flatMap(parts);
    if (type.flags & ts.TypeFlags.Substitution)
      return parts((type as ts.SubstitutionType).baseType);
    return [checker.getNonNullableType(type)];
  };
  // `parts` of an expected type, a type parameter taken as its constraint:
  // what a generic helper's reads are written against (`linkGeneric`). Only
  // the expected side of a link: a key typed `K extends keyof Row` is no read
  // of every field of `Row` (`genericKeyReads` reads what a call passes).
  const expectedParts = (type: ts.Type): ts.Type[] =>
    parts(type).flatMap((part) => {
      if (!(part.flags & ts.TypeFlags.TypeParameter)) return [part];
      const constraint = checker.getBaseConstraintOfType(part);
      return constraint && constraint !== part ? expectedParts(constraint) : [];
    });
  const elements = new Map<ts.Type, ts.Type | undefined>();
  const elementOf = (type: ts.Type): ts.Type | undefined => {
    if (!elements.has(type)) {
      elements.set(
        type,
        checker.isArrayType(type) || checker.isTupleType(type)
          ? checker.getIndexTypeOfType(type, ts.IndexKind.Number)
          : undefined,
      );
    }
    return elements.get(type);
  };

  // Whether a value of this type can hand a field of the app's own types on:
  // it has a property declared in a project type (an interface or a type
  // literal, not an object literal — building one is a write), here or up to
  // `budget` levels down. Library types (React's, the DOM's) and primitives
  // cannot, and skipping them is most of what keeps the pass fast. The answer
  // is cached by type and budget, so it never depends on what was asked
  // before (a type first met deep down, its budget nearly spent, would
  // otherwise answer "no" for good) — and the budget, shrinking on every
  // level, ends any cycle.
  const carrying = new Map<string, boolean>();
  const carries = (type: ts.Type, budget = MAX_CARRY_DEPTH): boolean => {
    if (budget < 0) return false;
    const key = `${typeId(type)}:${budget}`;
    const known = carrying.get(key);
    if (known !== undefined) return known;
    const next = budget - 1;
    let result = false;
    for (const part of parts(type)) {
      if (!(part.flags & ts.TypeFlags.Object) && !part.isIntersection())
        continue;
      const element = elementOf(part);
      if (element) result = carries(element, next);
      else if (part.getProperty("then")) {
        const awaited = checker.getAwaitedType(part);
        result = !!awaited && awaited !== part && carries(awaited, next);
      } else {
        for (const prop of part.getProperties()) {
          if (roots(prop).some(isProjectSignature)) result = true;
          else if (
            prop.flags & ts.SymbolFlags.Property &&
            !(prop.flags & ts.SymbolFlags.Optional)
          ) {
            result = carries(checker.getTypeOfSymbol(prop), next);
          }
          if (result) break;
        }
        const values = !result && part.getStringIndexType();
        if (values) result = carries(values, next);
      }
      if (result) break;
    }
    carrying.set(key, result);
    return result;
  };
  const isProjectSignature = (symbol: ts.Symbol) => {
    const decl = symbol.declarations?.[0];
    return (
      !!decl &&
      ts.isPropertySignature(decl) &&
      options.isProjectFile(decl.getSourceFile().fileName)
    );
  };

  // Links every property of `target` to the same-named one of `source`, and
  // recurses into their types: arrays to their elements, records to their
  // values, unions to each member. A pair met again at a lesser depth is
  // linked again, so how deep the links go never depends on which code the
  // pass happened to visit first.
  const link = (source: ts.Type, target: ts.Type, depth: number) => {
    if (depth > MAX_LINK_DEPTH) return;
    const id = `${typeId(source)}>${typeId(target)}`;
    const before = linked.get(id);
    if (before !== undefined && before <= depth) return;
    linked.set(id, depth);
    linkCallback(source, target, depth);
    if (!carries(source)) return;
    for (const s of parts(source)) {
      if (!(s.flags & ts.TypeFlags.Object) && !s.isIntersection()) continue;
      for (const t of expectedParts(target)) {
        if (!(t.flags & ts.TypeFlags.Object) && !t.isIntersection()) continue;
        if (s.getProperty("then") && t.getProperty("then")) {
          const sa = checker.getAwaitedType(s);
          const ta = checker.getAwaitedType(t);
          if (sa && ta && sa !== s && ta !== t) link(sa, ta, depth + 1);
          continue;
        }
        const se = elementOf(s);
        const te = elementOf(t);
        if (se && te) {
          link(se, te, depth + 1);
          continue;
        }
        const si = s.getStringIndexType();
        const ti = t.getStringIndexType();
        if (si && ti) link(si, ti, depth + 1);
        if (se || te) continue;
        for (const tp of t.getProperties()) {
          const sp = s.getProperty(tp.getName());
          if (!sp || sp === tp) continue;
          addFlow(tp, sp);
          link(
            checker.getTypeOfSymbol(sp),
            checker.getTypeOfSymbol(tp),
            depth + 1,
          );
        }
      }
    }
  };

  // A function handed where a callback is expected (`items.map(labelOf)`):
  // what the caller passes in flows into its parameters — the other way round
  // from a value — and what it returns flows out.
  const linkCallback = (source: ts.Type, target: ts.Type, depth: number) => {
    const [s] = checker.getNonNullableType(source).getCallSignatures();
    const [t] = checker.getNonNullableType(target).getCallSignatures();
    if (!s || !t) return;
    const count = Math.min(s.parameters.length, t.parameters.length);
    for (let i = 0; i < count; i++) {
      link(
        checker.getTypeOfSymbol(t.parameters[i]),
        checker.getTypeOfSymbol(s.parameters[i]),
        depth + 1,
      );
    }
    link(s.getReturnType(), t.getReturnType(), depth + 1);
  };

  const isAssignmentTarget = (node: ts.Node): boolean => {
    const parent = node.parent;
    return (
      ts.isBinaryExpression(parent) &&
      parent.left === node &&
      parent.operatorToken.kind === ts.SyntaxKind.EqualsToken
    );
  };

  // The property a destructured name reads, from the type being destructured.
  const bindingRead = (element: ts.BindingElement) => {
    const pattern = element.parent;
    if (!ts.isObjectBindingPattern(pattern) || element.dotDotDotToken) return;
    const nameNode = element.propertyName ?? element.name;
    const name =
      ts.isIdentifier(nameNode) || ts.isStringLiteral(nameNode)
        ? nameNode.text
        : null;
    if (name === null) return;
    for (const type of parts(checker.getTypeAtLocation(pattern))) {
      markRead(checker.getPropertyOfType(type, name));
    }
  };

  // `a["b"]` reads `b`; `a[key]` with `key: "b" | "c"` (a `keyof`, a union of
  // names) reads every name it can be. A key typed `string` names nothing.
  const keyRead = (node: ts.ElementAccessExpression) => {
    const names = parts(
      checker.getTypeAtLocation(node.argumentExpression),
    ).flatMap((t) => (t.isStringLiteral() ? [t.value] : []));
    if (names.length === 0) return;
    for (const type of parts(checker.getTypeAtLocation(node.expression))) {
      for (const name of names) markRead(checker.getPropertyOfType(type, name));
    }
  };

  // An argument of one of the app's own functions — a library's open
  // parameter (React's dependency list, the query cache) stores a value, it
  // does not read it.
  const isProjectCallArgument = (expr: ts.Expression) => {
    const call = expr.parent;
    if (!ts.isCallExpression(call) || call.expression === expr) return false;
    const decl = checker.getResolvedSignature(call)?.declaration;
    return !!decl && options.isProjectFile(decl.getSourceFile().fileName);
  };

  const visitFlow = (expr: ts.Expression) => {
    const source = checker.getTypeAtLocation(expr);
    if (!carries(source) && source.getCallSignatures().length === 0) return;
    // `<div {...row} />` hands every field to the DOM as an attribute.
    if (isIntrinsicSpread(expr)) return wholeUse(expr);
    const target = checker.getContextualType(expr);
    if (!target || target === source) return;
    if (!isOpenSink(target)) link(source, target, 0);
    else if (
      isProjectCallArgument(expr) ||
      ts.isJsxSpreadAttribute(expr.parent)
    )
      wholeUse(expr);
  };

  // An argument of one of the app's generic helpers (`ownedBy(rows, id)`):
  // its contextual type is the parameter
  // instantiated on the argument itself, which links the rows to themselves.
  // What the helper reads it reads through its type parameters' constraints
  // (`row.owner_id` of `T extends { owner_id?: … }`), so the argument is also
  // linked to the parameter as declared, each `T` standing for its constraint.
  const linkGeneric = (call: ts.CallExpression) => {
    const decl = checker.getResolvedSignature(call)?.declaration;
    if (!decl || ts.isJSDocSignature(decl) || !decl.typeParameters) return;
    if (!options.isProjectFile(decl.getSourceFile().fileName)) return;
    const declared = checker.getSignatureFromDeclaration(decl);
    if (!declared) return;
    call.arguments.forEach((arg, i) => {
      const param = decl.parameters[i];
      if (!param || param.dotDotDotToken) return;
      const source = checker.getTypeAtLocation(arg);
      if (carries(source))
        link(source, checker.getTypeOfSymbol(declared.parameters[i]), 0);
    });
  };

  const wholeUse = (expr: ts.Expression) => {
    const sf = expr.getSourceFile();
    const site = `${sf.fileName}:${sf.getLineAndCharacterOfPosition(expr.getStart(sf)).line + 1}`;
    for (const part of parts(checker.getTypeAtLocation(expr))) {
      const type = elementOf(part) ?? part;
      for (const prop of type.isUnion() ? [] : type.getProperties()) {
        for (const root of roots(prop))
          if (!wholeUses.has(root)) wholeUses.set(root, site);
      }
    }
  };

  const visit = (node: ts.Node) => {
    if (ts.isCallExpression(node) && node.arguments.length > 0) {
      if (WHOLE_READERS.has(node.expression.getText()))
        node.arguments.forEach(wholeUse);
      genericKeyReads(checker, node).forEach(markRead);
      linkGeneric(node);
    } else if (ts.isForInStatement(node)) {
      wholeUse(node.expression);
    } else if (
      ts.isSpreadAssignment(node) &&
      !checker.getContextualType(node.parent)
    ) {
      wholeUse(node.expression);
    }
    if (ts.isPropertyAccessExpression(node)) {
      if (!isAssignmentTarget(node))
        markRead(checker.getSymbolAtLocation(node.name));
    } else if (ts.isElementAccessExpression(node)) {
      if (!isAssignmentTarget(node)) keyRead(node);
    } else if (ts.isBindingElement(node)) {
      bindingRead(node);
    } else if (
      ts.isBinaryExpression(node) &&
      node.operatorToken.kind === ts.SyntaxKind.InKeyword &&
      ts.isStringLiteralLike(node.left)
    ) {
      const name = node.left.text;
      for (const type of parts(checker.getTypeAtLocation(node.right))) {
        markRead(checker.getPropertyOfType(type, name));
      }
    } else if (
      ts.isBinaryExpression(node) &&
      node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
      ts.isObjectLiteralExpression(node.left)
    ) {
      // `({ a, b: c } = row)` reads `a` and `b` of `row`.
      for (const prop of node.left.properties) {
        const name =
          ts.isShorthandPropertyAssignment(prop) ||
          ts.isPropertyAssignment(prop)
            ? prop.name
            : null;
        if (!name || !(ts.isIdentifier(name) || ts.isStringLiteral(name)))
          continue;
        for (const type of parts(checker.getTypeAtLocation(node.right))) {
          markRead(checker.getPropertyOfType(type, name.text));
        }
      }
    } else if (ts.isShorthandPropertyAssignment(node)) {
      const target = checker.getContextualType(node.parent);
      const prop = target && checker.getPropertyOfType(target, node.name.text);
      if (prop)
        link(
          checker.getTypeAtLocation(node.name),
          checker.getTypeOfSymbol(prop),
          0,
        );
    }
    if (isCarrier(node) && isSink(node)) visitFlow(node);
    ts.forEachChild(node, visit);
  };

  for (const sf of program.getSourceFiles()) {
    if (sf.isDeclarationFile || !options.isProjectFile(sf.fileName)) continue;
    if (options.isExcludedReader(sf.fileName)) continue;
    visit(sf);
  }

  // Close the reads, and the whole uses, over the flows.
  close(read, flows);
  const wholeQueue = [...wholeUses.keys()];
  while (wholeQueue.length > 0) {
    const symbol = wholeQueue.pop()!;
    for (const source of flows.get(symbol) ?? []) {
      if (!wholeUses.has(source)) {
        wholeUses.set(source, wholeUses.get(symbol)!);
        wholeQueue.push(source);
      }
    }
  }

  const fields = new Map<ts.Symbol, Field | null>();
  const fieldOf = (symbol: ts.Symbol): Field | undefined => {
    if (!fields.has(symbol)) fields.set(symbol, describe(symbol, options));
    return fields.get(symbol) ?? undefined;
  };
  return {
    isRead: (symbol) => roots(symbol).some((r) => read.has(r)),
    fieldOf,
    wholeUseOf: (symbol) =>
      roots(symbol).flatMap((r) => wholeUses.get(r) ?? [])[0],
  };
}

// Everything reachable backwards over the flows from what is marked.
function close(
  marked: Set<ts.Symbol>,
  flows: Map<ts.Symbol, Set<ts.Symbol>>,
): void {
  const queue = [...marked];
  while (queue.length > 0) {
    for (const source of flows.get(queue.pop()!) ?? []) {
      if (!marked.has(source)) {
        marked.add(source);
        queue.push(source);
      }
    }
  }
}

function describe(symbol: ts.Symbol, options: AnalyzeOptions): Field | null {
  const decl = symbol.declarations?.[0];
  if (!decl || !ts.isPropertySignature(decl)) return null;
  const sf = decl.getSourceFile();
  if (!options.isProjectFile(sf.fileName)) return null;
  // `Type.outer.field`; a literal written inline, outside any named type
  // (`request<{ items: Row[] }>`), is named by the file and the declarations
  // around it: `lib/api/voyage/voyages.ts#listVoyageSearchIndex.items`.
  const path: string[] = [symbol.getName()];
  let named = false;
  for (
    let node: ts.Node = decl.parent;
    !ts.isSourceFile(node);
    node = node.parent
  ) {
    if (ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node)) {
      path.unshift(node.name.text);
      named = true;
      break;
    }
    const name = (node as ts.NamedDeclaration).name;
    if (
      name &&
      ts.isIdentifier(name) &&
      (ts.isPropertySignature(node) ||
        ts.isVariableDeclaration(node) ||
        ts.isFunctionDeclaration(node) ||
        ts.isPropertyAssignment(node))
    ) {
      path.unshift(name.text);
    }
  }
  if (!named) {
    path[0] = `${relative(options.root, sf.fileName).replace(/^src\//, "")}#${path[0]}`;
  }
  const line = sf.getLineAndCharacterOfPosition(decl.getStart(sf)).line + 1;
  return { key: path.join("."), file: sf.fileName, line };
}
