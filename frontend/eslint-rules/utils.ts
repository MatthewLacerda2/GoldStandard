import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

/**
 * Factory for typed rules. The docs URL is a placeholder for this local plugin.
 */
export const createRule = ESLintUtils.RuleCreator(
  (name) => `https://internal/eslint-rules/${name}`,
);

/**
 * Extract a static string value from a JSX attribute value node, when it is a
 * plain string literal or a `{"..."}` expression container wrapping a literal.
 * Returns `undefined` when the value is dynamic (cannot be analysed statically).
 */
export function getStaticAttributeString(
  value: TSESTree.JSXAttribute["value"],
): string | undefined {
  if (!value) return undefined;
  if (value.type === "Literal" && typeof value.value === "string") {
    return value.value;
  }
  if (
    value.type === "JSXExpressionContainer" &&
    value.expression.type === "Literal" &&
    typeof value.expression.value === "string"
  ) {
    return value.expression.value;
  }
  return undefined;
}

/** Split a className string into its individual utility tokens. */
export function classTokens(value: string): string[] {
  return value.split(/\s+/).filter(Boolean);
}

/** True when the JSX element name is a lowercase intrinsic (e.g. `input`). */
export function isIntrinsicElement(
  name: TSESTree.JSXTagNameExpression,
): name is TSESTree.JSXIdentifier {
  return name.type === "JSXIdentifier" && /^[a-z]/.test(name.name);
}

/** True when the file path is inside a `components/ui` directory. */
export function isUiComponentFile(filename: string): boolean {
  return /[\\/]components[\\/]ui[\\/]/.test(filename);
}
