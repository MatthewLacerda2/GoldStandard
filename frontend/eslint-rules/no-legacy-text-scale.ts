import { type TSESTree } from "@typescript-eslint/utils";
import { classTokens, createRule, getStaticAttributeString } from "./utils";

// Legacy Tailwind text-size scale that is banned in favour of typography tokens.
const LEGACY_SIZES = new Set([
  "xs",
  "sm",
  "base",
  "lg",
  "xl",
  "2xl",
  "3xl",
  "4xl",
  "5xl",
  "6xl",
  "7xl",
  "8xl",
  "9xl",
]);

/** Strip a responsive/state prefix (e.g. `md:`, `hover:`) from a token. */
function bareToken(token: string): string {
  const idx = token.lastIndexOf(":");
  return idx === -1 ? token : token.slice(idx + 1);
}

export const noLegacyTextScale = createRule({
  name: "no-legacy-text-scale",
  meta: {
    type: "problem",
    docs: {
      description:
        "Forbid the legacy text-xs…9xl scale; only typography tokens are allowed.",
    },
    messages: {
      legacy:
        "Legacy text scale '{{token}}' is not allowed. Use a typography token (text-display, text-h1…text-caption, text-kpi-*).",
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
          const bare = bareToken(token);
          if (!bare.startsWith("text-")) continue;
          const size = bare.slice("text-".length);
          if (LEGACY_SIZES.has(size)) {
            context.report({
              node,
              messageId: "legacy",
              data: { token },
            });
          }
        }
      },
    };
  },
});
