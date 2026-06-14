import { oneExportedComponentPerFile } from "./one-exported-component-per-file";
import { noArbitraryText } from "./no-arbitrary-text";
import { noLegacyTextScale } from "./no-legacy-text-scale";
import { noColorLiteral } from "./no-color-literal";
import { noHandRolledFormControl } from "./no-hand-rolled-form-control";
import { noRedundantFontUtility } from "./no-redundant-font-utility";

/** The local ESLint plugin exposing the design-system rules. */
const plugin = {
  meta: { name: "local", version: "0.1.0" },
  rules: {
    "one-exported-component-per-file": oneExportedComponentPerFile,
    "no-arbitrary-text": noArbitraryText,
    "no-legacy-text-scale": noLegacyTextScale,
    "no-color-literal": noColorLiteral,
    "no-hand-rolled-form-control": noHandRolledFormControl,
    "no-redundant-font-utility": noRedundantFontUtility,
  },
};

export default plugin;
