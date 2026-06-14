import { type TSESTree } from "@typescript-eslint/utils";
import { createRule, isUiComponentFile } from "./utils";

const BANNED = new Set(["input", "select", "textarea"]);

export const noHandRolledFormControl = createRule({
  name: "no-hand-rolled-form-control",
  meta: {
    type: "problem",
    docs: {
      description:
        "Forbid raw <input>/<select>/<textarea>; compose shadcn primitives instead.",
    },
    messages: {
      handRolled:
        "Raw <{{tag}}> is not allowed. Use the shadcn primitive from components/ui.",
    },
    schema: [],
  },
  defaultOptions: [],
  create(context) {
    // components/ui is where the primitives themselves live; exempt.
    if (isUiComponentFile(context.filename)) return {};

    return {
      JSXOpeningElement(node: TSESTree.JSXOpeningElement) {
        const name = node.name;
        if (name.type !== "JSXIdentifier") return;
        if (BANNED.has(name.name)) {
          context.report({
            node,
            messageId: "handRolled",
            data: { tag: name.name },
          });
        }
      },
    };
  },
});
