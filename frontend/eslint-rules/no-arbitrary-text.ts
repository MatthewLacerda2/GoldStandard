import { type TSESTree } from "@typescript-eslint/utils";
import { classTokens, createRule, getStaticAttributeString } from "./utils";

// Matches arbitrary text-size utilities like `text-[14px]` / `text-[1.2rem]`.
const ARBITRARY_TEXT = /^text-\[[\d.]+(px|rem|em|pt)\]$/;

export const noArbitraryText = createRule({
  name: "no-arbitrary-text",
  meta: {
    type: "problem",
    docs: {
      description:
        "Forbid arbitrary text-size classes (text-[Npx]); use typography tokens.",
    },
    messages: {
      arbitrary:
        "Arbitrary text size '{{token}}' is not allowed. Use a typography token (text-h1, text-body, …).",
    },
    schema: [],
  },
  defaultOptions: [],
  create(context) {
    return {
      JSXAttribute(node: TSESTree.JSXAttribute) {
        if (node.name.name !== "className") return;
        const value = getStaticAttributeString(node.value);
        if (!value) return;
        for (const token of classTokens(value)) {
          if (ARBITRARY_TEXT.test(token)) {
            context.report({
              node,
              messageId: "arbitrary",
              data: { token },
            });
          }
        }
      },
    };
  },
});
