import { oneExportedComponentPerFile } from "./one-exported-component-per-file";
import { noArbitraryText } from "./no-arbitrary-text";
import { noLegacyTextScale } from "./no-legacy-text-scale";
import { noColorLiteral } from "./no-color-literal";
import { noMarkerComment } from "./no-marker-comment";
import { noHandRolledFormControl } from "./no-hand-rolled-form-control";
import { noRedundantFontUtility } from "./no-redundant-font-utility";
import { noUntranslatedText } from "./no-untranslated-text";

/** The local ESLint plugin exposing the house rules. */
const plugin = {
  meta: { name: "local", version: "0.1.0" },
  rules: {
    "one-exported-component-per-file": oneExportedComponentPerFile,
    "no-arbitrary-text": noArbitraryText,
    "no-legacy-text-scale": noLegacyTextScale,
    "no-color-literal": noColorLiteral,
    "no-hand-rolled-form-control": noHandRolledFormControl,
    "no-redundant-font-utility": noRedundantFontUtility,
    "no-untranslated-text": noUntranslatedText,
    "no-marker-comment": noMarkerComment,
  },
};

export default plugin;
