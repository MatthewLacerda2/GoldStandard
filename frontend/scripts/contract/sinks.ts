// Where in the syntax a value can hand fields on (`analyze.ts`, A FLOW): the
// expressions that carry an object, the places that expect a type of it, and
// the places that take any object and name none of its fields.
import ts from "typescript";

/** A place that takes any object and names none of its fields: `unknown`,
 *  `object`, `Record<string, unknown>` — a snapshot, a serializer, an export. */
export function isOpenSink(type: ts.Type): boolean {
  if (
    type.flags &
    (ts.TypeFlags.Unknown | ts.TypeFlags.Any | ts.TypeFlags.NonPrimitive)
  ) {
    return true;
  }
  const values = type.getStringIndexType();
  return (
    !!values &&
    type.getProperties().length === 0 &&
    !!(values.flags & (ts.TypeFlags.Unknown | ts.TypeFlags.Any))
  );
}

/** An expression that can carry an object a field could flow out of. */
export function isCarrier(node: ts.Node): node is ts.Expression {
  return (
    ts.isIdentifier(node) ||
    ts.isPropertyAccessExpression(node) ||
    ts.isElementAccessExpression(node) ||
    ts.isCallExpression(node) ||
    ts.isAwaitExpression(node) ||
    ts.isNonNullExpression(node) ||
    ts.isObjectLiteralExpression(node) ||
    ts.isArrayLiteralExpression(node)
  );
}

/** Whether a value lands here where a type is expected: an argument, a typed
 *  initializer, a return, an arrow's body, a property of a literal, a JSX
 *  attribute, an array element, the right side of `=`, a spread — looking
 *  through parentheses, `cond ? a : b` and `a ?? b`, which hand the expected
 *  type down to their operands. */
export function isSink(node: ts.Node): boolean {
  let child: ts.Node = node;
  let parent = node.parent;
  while (
    ts.isParenthesizedExpression(parent) ||
    (ts.isConditionalExpression(parent) && child !== parent.condition) ||
    (ts.isBinaryExpression(parent) && isPassThrough(parent.operatorToken.kind))
  ) {
    child = parent;
    parent = parent.parent;
  }
  if (ts.isCallExpression(parent) || ts.isNewExpression(parent))
    return child !== parent.expression;
  if (ts.isVariableDeclaration(parent))
    return child === parent.initializer && !!parent.type;
  if (ts.isPropertyAssignment(parent)) return child === parent.initializer;
  if (ts.isArrowFunction(parent)) return child === parent.body;
  if (ts.isBinaryExpression(parent)) {
    return (
      child === parent.right &&
      parent.operatorToken.kind === ts.SyntaxKind.EqualsToken
    );
  }
  return (
    ts.isReturnStatement(parent) ||
    ts.isJsxExpression(parent) ||
    ts.isArrayLiteralExpression(parent) ||
    ts.isSpreadAssignment(parent) ||
    ts.isSpreadElement(parent) ||
    ts.isJsxSpreadAttribute(parent)
  );
}

/** A spread onto a DOM element's attributes (`<div {...row} />`), not onto a
 *  component's props. */
export function isIntrinsicSpread(expr: ts.Expression): boolean {
  const spread = expr.parent;
  if (!ts.isJsxSpreadAttribute(spread)) return false;
  const tag = spread.parent.parent.tagName;
  return ts.isIdentifier(tag) && /^[a-z]/.test(tag.text);
}

const isPassThrough = (kind: ts.SyntaxKind) =>
  kind === ts.SyntaxKind.QuestionQuestionToken ||
  kind === ts.SyntaxKind.BarBarToken ||
  kind === ts.SyntaxKind.AmpersandAmpersandToken;
