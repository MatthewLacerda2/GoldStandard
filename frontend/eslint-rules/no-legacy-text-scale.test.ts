import { createTester } from "./tester";
import { noLegacyTextScale } from "./no-legacy-text-scale";

const tester = createTester();

tester.run("no-legacy-text-scale", noLegacyTextScale, {
  valid: [
    { code: `const x = <p className="text-h1">hi</p>;` },
    { code: `const x = <p className="text-caption">hi</p>;` },
    { code: `const x = <p className="text-kpi-lg">hi</p>;` },
    // text-center is alignment, not a size — must be allowed.
    { code: `const x = <p className="text-center">hi</p>;` },
  ],
  invalid: [
    {
      code: `const x = <p className="text-sm">hi</p>;`,
      errors: [{ messageId: "legacy" }],
    },
    {
      code: `const x = <p className="md:text-2xl">hi</p>;`,
      errors: [{ messageId: "legacy" }],
    },
  ],
});
