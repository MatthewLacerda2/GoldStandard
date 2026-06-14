import { type TSESTree } from "@typescript-eslint/utils";
import { createRule, isUiComponentFile } from "./utils";

/** A name is component-like when it starts with an uppercase letter. */
function isComponentName(name: string): boolean {
  return /^[A-Z]/.test(name);
}

/**
 * Heuristic: does this initializer look like a React component (a function that
 * we treat as a component because its name is PascalCase)? We only gate on the
 * name; arrow/function initializers with a PascalCase id are candidates.
 */
function isFunctionLike(node: TSESTree.Node | null | undefined): boolean {
  return (
    !!node &&
    (node.type === "ArrowFunctionExpression" ||
      node.type === "FunctionExpression")
  );
}

export const oneExportedComponentPerFile = createRule({
  name: "one-exported-component-per-file",
  meta: {
    type: "problem",
    docs: {
      description: "Allow at most one exported React component per file.",
    },
    messages: {
      tooMany:
        "A file may export at most one React component (found another: '{{name}}').",
    },
    schema: [],
  },
  defaultOptions: [],
  create(context) {
    const filename = context.filename;
    // components/ui primitives and route files commonly export helpers; exempt.
    if (isUiComponentFile(filename)) return {};

    const exportedComponents: string[] = [];

    function record(name: string): void {
      if (isComponentName(name)) exportedComponents.push(name);
    }

    function flag(node: TSESTree.Node): void {
      if (exportedComponents.length > 1) {
        context.report({
          node,
          messageId: "tooMany",
          data: { name: exportedComponents[exportedComponents.length - 1] },
        });
      }
    }

    return {
      "ExportNamedDeclaration > FunctionDeclaration"(
        node: TSESTree.FunctionDeclaration,
      ) {
        if (node.id) record(node.id.name);
      },
      "ExportNamedDeclaration > VariableDeclaration"(
        node: TSESTree.VariableDeclaration,
      ) {
        for (const decl of node.declarations) {
          if (decl.id.type === "Identifier" && isFunctionLike(decl.init)) {
            record(decl.id.name);
          }
        }
      },
      ExportDefaultDeclaration(node: TSESTree.ExportDefaultDeclaration) {
        const decl = node.declaration;
        if (decl.type === "FunctionDeclaration" && decl.id) {
          record(decl.id.name);
        }
      },
      "Program:exit"(node: TSESTree.Program) {
        flag(node);
      },
    };
  },
});
