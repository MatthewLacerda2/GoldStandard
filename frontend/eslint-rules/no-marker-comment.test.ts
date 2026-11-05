import { createTester } from "./tester";
import { MARKERS, noMarkerComment } from "./no-marker-comment";

const tester = createTester();
const marker = { messageId: "marker" as const };

tester.run("no-marker-comment", noMarkerComment, {
  valid: [
    // A word that only contains a marker, or a marker in another case.
    { code: `const todos = 1; // todos, TODO_LIST, hacker, XXXL, todo` },
    // Strings are data, never comments.
    { code: `const words = ["TODO", "FIXME"]; const s = \`HACK \${1}\`;` },
    { code: `const x = <p title="XXX">TODO</p>;` },
    // An allow with a reason, on the line or directly above it.
    { code: `// TODO is the format  lint: allow(marker) it names the word` },
    { code: "// lint: allow(marker) `FIXME` is quoted below\n// - FIXME: ..." },
    // A reason may open with any non-separator, a non-ASCII letter included.
    { code: "// TODO  lint: allow(marker) été" },
    { code: "/**\n * lint: allow(marker) (quoted below)\n * TODO: ...\n */" },
  ],
  invalid: [
    ...MARKERS.map((word) => ({
      code: `const x = 1; // ${word}: tidy this`,
      errors: [{ ...marker, data: { marker: word } }],
    })),
    {
      code: "/**\n * Fine.\n * HACK: around the bug\n */",
      errors: [{ ...marker, line: 3 }],
    },
    { code: `const x = <div>{/* TODO */}</div>;`, errors: [marker] },
    {
      // An allow needs a reason, and names this rule.
      code: "// TODO  lint: allow(marker) -- \n\n// XXX  lint: allow(other) why",
      errors: [marker, marker],
    },
    {
      // An allow excuses its own line and the one below, nothing further.
      code: "// lint: allow(marker) a reason\n// TODO\n// XXX\nconst x = 1; // FIXME",
      errors: [
        { ...marker, line: 3 },
        { ...marker, line: 4 },
      ],
    },
    {
      // An allow inside a string is not in a comment.
      code: `const s = "lint: allow(marker) a reason"; // FIXME`,
      errors: [marker],
    },
    {
      // A separator alone is no reason.
      code: "// TODO  lint: allow(marker) —",
      errors: [marker],
    },
  ],
});
