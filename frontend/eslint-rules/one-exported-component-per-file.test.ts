import { createTester } from "./tester";
import { oneExportedComponentPerFile } from "./one-exported-component-per-file";

const tester = createTester();

tester.run("one-exported-component-per-file", oneExportedComponentPerFile, {
  valid: [
    {
      code: `export function Widget() { return null; }`,
      filename: "src/components/widget.tsx",
    },
    {
      // helper + single component is fine (helper is not PascalCase exported fn)
      code: `function helper() {} export const Widget = () => null;`,
      filename: "src/components/widget.tsx",
    },
    {
      // components/ui is exempt
      code: `export const A = () => null; export const B = () => null;`,
      filename: "src/components/ui/thing.tsx",
    },
  ],
  invalid: [
    {
      code: `export const A = () => null; export const B = () => null;`,
      filename: "src/components/widget.tsx",
      errors: [{ messageId: "tooMany" }],
    },
    {
      code: `export function A() { return null; } export function B() { return null; }`,
      filename: "src/components/widget.tsx",
      errors: [{ messageId: "tooMany" }],
    },
  ],
});
