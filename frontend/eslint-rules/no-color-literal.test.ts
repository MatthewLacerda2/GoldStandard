import { createTester } from "./tester";
import { noColorLiteral } from "./no-color-literal";

const tester = createTester();

tester.run("no-color-literal", noColorLiteral, {
  valid: [
    { code: `const x = <p className="bg-primary text-foreground">hi</p>;` },
    { code: `const x = <p style={{ padding: "4px" }}>hi</p>;` },
  ],
  invalid: [
    {
      code: `const x = <p className="text-[#ff0000]">hi</p>;`,
      errors: [{ messageId: "literal" }],
    },
    {
      code: `const x = <p style={{ color: "#fff" }}>hi</p>;`,
      errors: [{ messageId: "literal" }],
    },
    {
      code: `const x = <p style={{ color: "rgb(0,0,0)" }}>hi</p>;`,
      errors: [{ messageId: "literal" }],
    },
  ],
});
