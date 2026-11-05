// Small questions about TypeScript types and symbols that every part of the
// contract gate asks the same way.
import ts from "typescript";

/** The checker's own id for a type: a cache key that two equal types share. */
export const typeId = (type: ts.Type) => (type as unknown as { id: number }).id;

/** An array's or a tuple's element type; `undefined` for anything else. */
export function elementOf(
  checker: ts.TypeChecker,
  type: ts.Type,
): ts.Type | undefined {
  return checker.isArrayType(type) || checker.isTupleType(type)
    ? checker.getIndexTypeOfType(type, ts.IndexKind.Number)
    : undefined;
}

/** The declarations a property was written in, back through a `Pick`, an
 *  `Omit`, a mapped type, a union or an intersection; the symbol itself when
 *  it is one. */
export function rootsOf(
  checker: ts.TypeChecker,
  symbol: ts.Symbol,
): readonly ts.Symbol[] {
  const roots = checker.getRootSymbols(symbol);
  return roots.length > 0 ? roots : [symbol];
}

/** The declaration an expression names, through an import alias. */
export function declarationOf(
  checker: ts.TypeChecker,
  expr: ts.Expression,
): ts.Declaration | undefined {
  let symbol = checker.getSymbolAtLocation(expr);
  if (symbol && symbol.flags & ts.SymbolFlags.Alias)
    symbol = checker.getAliasedSymbol(symbol);
  return symbol?.valueDeclaration ?? symbol?.declarations?.[0];
}

/** What a `const` an expression names was initialized with. */
export function constInitializer(
  checker: ts.TypeChecker,
  expr: ts.Expression,
): ts.Expression | undefined {
  const decl = declarationOf(checker, expr);
  return decl &&
    ts.isVariableDeclaration(decl) &&
    decl.initializer &&
    ts.getCombinedNodeFlags(decl) & ts.NodeFlags.Const
    ? decl.initializer
    : undefined;
}
