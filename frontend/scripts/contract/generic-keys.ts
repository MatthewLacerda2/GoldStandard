// A read by a key a call passes: `get(row, "name")`, `sortBy(rows, "name")`,
// where the helper is generic over the object and its key
// (`<T, K extends keyof T>(o: T, k: K)` or `(o: T, k: keyof T)`). Inside the
// helper `o[k]` names nothing; at the call the literal names the field.
import ts from "typescript";
import { elementOf } from "./types";

/** The properties a call reads through a generic key parameter. */
export function genericKeyReads(
  checker: ts.TypeChecker,
  call: ts.CallExpression,
): ts.Symbol[] {
  const decl = checker.getResolvedSignature(call)?.declaration;
  if (!decl || ts.isJSDocSignature(decl) || !decl.typeParameters) return [];
  const reads: ts.Symbol[] = [];
  decl.parameters.forEach((param, i) => {
    const owner = keyOwner(decl, param.type);
    const arg = call.arguments[i];
    if (!owner || !arg) return;
    const names = literalsOf(checker.getTypeAtLocation(arg));
    decl.parameters.forEach((other, j) => {
      const value = call.arguments[j];
      if (j === i || !value || !holds(other.type, owner)) return;
      for (const type of objectsOf(checker, checker.getTypeAtLocation(value))) {
        for (const name of names) {
          const prop = checker.getPropertyOfType(type, name);
          if (prop) reads.push(prop);
        }
      }
    });
  });
  return reads;
}

// `T` when the parameter is typed `keyof T`, or `K` with `K extends keyof T`.
function keyOwner(
  decl: ts.SignatureDeclaration,
  type: ts.TypeNode | undefined,
): string | undefined {
  if (!type) return undefined;
  if (
    ts.isTypeOperatorNode(type) &&
    type.operator === ts.SyntaxKind.KeyOfKeyword
  ) {
    return ts.isTypeReferenceNode(type.type)
      ? type.type.typeName.getText()
      : undefined;
  }
  if (!ts.isTypeReferenceNode(type)) return undefined;
  const name = type.typeName.getText();
  const param = decl.typeParameters?.find((p) => p.name.text === name);
  return param?.constraint ? keyOwner(decl, param.constraint) : undefined;
}

// Whether a parameter holds values of `T`: `T`, `T[]`, `readonly T[]`, `Array<T>`.
function holds(type: ts.TypeNode | undefined, owner: string): boolean {
  if (!type) return false;
  if (ts.isTypeOperatorNode(type)) return holds(type.type, owner);
  if (ts.isArrayTypeNode(type)) return holds(type.elementType, owner);
  if (!ts.isTypeReferenceNode(type)) return false;
  const name = type.typeName.getText();
  if (name === owner) return true;
  const [element] = type.typeArguments ?? [];
  return (
    (name === "Array" || name === "ReadonlyArray") && holds(element, owner)
  );
}

function literalsOf(type: ts.Type): string[] {
  const members = type.isUnion() ? type.types : [type];
  return members.flatMap((m) => (m.isStringLiteral() ? [m.value] : []));
}

function objectsOf(checker: ts.TypeChecker, type: ts.Type): ts.Type[] {
  const members = type.isUnion() ? type.types : [type];
  return members.flatMap((m) => {
    const element = elementOf(checker, m);
    return element
      ? objectsOf(checker, element)
      : m.flags & ts.TypeFlags.Object
        ? [m]
        : [];
  });
}
