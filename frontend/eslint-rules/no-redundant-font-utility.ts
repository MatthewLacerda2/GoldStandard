import { type TSESTree } from "@typescript-eslint/utils";
import { classTokens, createRule, getStaticAttributeString } from "./utils";

// Typography tokens that already carry a font-weight.
const TYPOGRAPHY_TOKENS = new Set([
  "text-display",
  "text-h1",
  "text-h2",
  "text-h3",
  "text-body",
  "text-caption",
  "text-kpi-lg",
  "text-kpi-sm",
]);

// font-weight utilities that are redundant next to a typography token.
const FONT_WEIGHT =
  /^font-(thin|extralight|light|normal|medium|semibold|bold|extrabold|black)$/;

export const noRedundantFontUtility = createRule({
  name: "no-redundant-font-utility",
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Flag a font-weight utility used alongside a typography token that already carries weight.",
    },
    messages: {
      redundant:
        "Font utility '{{token}}' is redundant next to typography token '{{tokenName}}'.",
    },
    schema: [],
  },
  defaultOptions: [],
  create(context) {
    return {
      JSXAttribute(node: TSESTree.JSXAttribute) {
        if (node.name.name !== "className") return;
        const raw = getStaticAttributeString(node.value);
        if (!raw) return;

        const tokens = classTokens(raw);
        const typographyToken = tokens.find((t) => TYPOGRAPHY_TOKENS.has(t));
        if (!typographyToken) return;

        const redundant = tokens.find((t) => FONT_WEIGHT.test(t));
        if (!redundant) return;

        context.report({
          node,
          messageId: "redundant",
          data: { token: redundant, tokenName: typographyToken },
          fix(fixer) {
            const kept = tokens.filter((t) => t !== redundant).join(" ");
            const valueNode = node.value;
            if (!valueNode) return null;
            // Preserve the original quote/expression style by replacing the
            // inner string range only.
            if (
              valueNode.type === "Literal" &&
              typeof valueNode.value === "string"
            ) {
              return fixer.replaceText(valueNode, `"${kept}"`);
            }
            if (
              valueNode.type === "JSXExpressionContainer" &&
              valueNode.expression.type === "Literal"
            ) {
              return fixer.replaceText(valueNode.expression, `"${kept}"`);
            }
            return null;
          },
        });
      },
    };
  },
});
