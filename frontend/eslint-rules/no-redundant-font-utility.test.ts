import { createTester } from "./tester";
import { noRedundantFontUtility } from "./no-redundant-font-utility";

const tester = createTester();

tester.run("no-redundant-font-utility", noRedundantFontUtility, {
  valid: [
    { code: `const x = <p className="text-h1">hi</p>;` },
    // font utility without a typography token is fine.
    { code: `const x = <p className="font-bold">hi</p>;` },
  ],
  invalid: [
    {
      code: `const x = <p className="text-h1 font-bold">hi</p>;`,
      output: `const x = <p className="text-h1">hi</p>;`,
      errors: [{ messageId: "redundant" }],
    },
    {
      code: `const x = <p className="font-semibold text-caption">hi</p>;`,
      output: `const x = <p className="text-caption">hi</p>;`,
      errors: [{ messageId: "redundant" }],
    },
  ],
});
