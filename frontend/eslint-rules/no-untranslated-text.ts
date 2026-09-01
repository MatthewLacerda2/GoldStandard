import { type TSESTree } from "@typescript-eslint/utils";
import {
  createRule,
  getStaticAttributeString,
  isUiComponentFile,
} from "./utils";

// Attributes whose value is read by a user (or a screen reader). This is an
// allowlist on purpose: a denylist of className/id/htmlFor/… is wrong the first
// time someone adds a prop.
const USER_FACING_ATTRIBUTES = new Set([
  "placeholder",
  "title",
  "aria-label",
  "alt",
]);

// HTML entities (&nbsp;, &mdash;, &#8212;) are punctuation spelled with letters.
const HTML_ENTITY = /&(#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);/g;

/**
 * True when the text carries translatable content — at least one letter in any
 * script. Whitespace, digits, punctuation and symbols (`·`, `—`, `/`, `:`) are
 * separators, not copy, so they never need a translation key.
 */
function hasTranslatableContent(text: string): boolean {
  return /\p{L}/u.test(text.replace(HTML_ENTITY, ""));
}

/** Collapse whitespace and shorten, so the message stays one readable line. */
function summarize(text: string): string {
  const flat = text.trim().replace(/\s+/g, " ");
  return flat.length > 32 ? `${flat.slice(0, 32)}…` : flat;
}

export const noUntranslatedText = createRule({
  name: "no-untranslated-text",
  meta: {
    type: "problem",
    docs: {
      description:
        "Forbid hardcoded user-facing strings in JSX; route them through i18next.",
    },
    messages: {
      untranslatedText:
        "Hardcoded text '{{text}}' is not allowed. Add a key under src/i18n and render {t(\"…\")}.",
      untranslatedAttribute:
        "Hardcoded '{{attribute}}' text '{{text}}' is not allowed. Add a key under src/i18n and pass t(\"…\").",
    },
    schema: [],
  },
  defaultOptions: [],
  create(context) {
    // components/ui primitives are vendored shadcn code; exempt.
    if (isUiComponentFile(context.filename)) return {};

    return {
      // Only literal children are the target. Anything in an expression
      // container — {t("items.heading")} as much as {item.name} — is a
      // JSXExpressionContainer, never a JSXText, so it never reaches here.
      JSXText(node: TSESTree.JSXText) {
        if (!hasTranslatableContent(node.value)) return;
        context.report({
          node,
          messageId: "untranslatedText",
          data: { text: summarize(node.value) },
        });
      },
      JSXAttribute(node: TSESTree.JSXAttribute) {
        const attribute =
          node.name.type === "JSXIdentifier"
            ? node.name.name
            : `${node.name.namespace.name}:${node.name.name.name}`;
        if (!USER_FACING_ATTRIBUTES.has(attribute)) return;

        const value = getStaticAttributeString(node.value);
        // `undefined` means dynamic (placeholder={t("…")}); an empty or
        // letter-free value (alt="" on a decorative image) is not copy.
        if (!value || !hasTranslatableContent(value)) return;

        context.report({
          node,
          messageId: "untranslatedAttribute",
          data: { attribute, text: summarize(value) },
        });
      },
    };
  },
});
