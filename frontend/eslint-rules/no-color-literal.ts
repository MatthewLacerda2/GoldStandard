import { type TSESTree } from "@typescript-eslint/utils";
import { createRule, getStaticAttributeString } from "./utils";

// Hex colors (#abc / #aabbcc / #aabbccdd) and rgb()/hsl()/rgba()/hsla() calls.
const COLOR_LITERAL = /#[0-9a-fA-F]{3,8}\b|\b(rgb|rgba|hsl|hsla)\s*\(/;

export const noColorLiteral = createRule({
  name: "no-color-literal",
  meta: {
    type: "problem",
    docs: {
      description:
        "Forbid hex / rgb() / hsl() color literals in className and style.",
    },
    messages: {
      literal:
        "Color literal '{{value}}' is not allowed. Use a semantic color token.",
    },
    schema: [],
  },
  defaultOptions: [],
  create(context) {
    function check(node: TSESTree.Node, text: string): void {
      const match = COLOR_LITERAL.exec(text);
      if (match) {
        context.report({
          node,
          messageId: "literal",
          data: { value: match[0] },
        });
      }
    }

    return {
      JSXAttribute(node: TSESTree.JSXAttribute) {
        const attr = node.name.name;
        if (attr !== "className" && attr !== "style") return;
        const value = getStaticAttributeString(node.value);
        if (value) check(node, value);
      },
      // Catch literals inside style objects: style={{ color: "#fff" }}.
      Property(node: TSESTree.Property) {
        if (
          node.value.type === "Literal" &&
          typeof node.value.value === "string"
        ) {
          check(node.value, node.value.value);
        }
      },
    };
  },
});
