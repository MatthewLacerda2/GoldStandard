import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

// Wire @typescript-eslint's RuleTester into Vitest's lifecycle hooks so the
// rule fixtures run as part of `vitest run`.
RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

/** A RuleTester preconfigured for JSX/TSX rule fixtures. */
export function createTester(): RuleTester {
  return new RuleTester({
    languageOptions: {
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
  });
}
