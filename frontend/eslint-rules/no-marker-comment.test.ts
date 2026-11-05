import { createTester } from "./tester";
import { MARKERS, noMarkerComment } from "./no-marker-comment";

const tester = createTester();

tester.run("no-marker-comment", noMarkerComment, {
  valid: [
    // A word that only contains a marker, or a marker in another case.
    { code: `const todos = 1; // todos, TODO_LIST, hacker, XXXL, todo` },
    // Strings are data, never comments.
    { code: `const words = ["TODO", "FIXME"]; const s = \`HACK \${1}\`;` },
    { code: `const x = <p title="XXX">TODO</p>;` },
    // An allow with a reason, on the line or in the comments right above.
    { code: `// TODO is the format  lint: allow(marker) it names the word` },
    {
      code: [
        "// lint: allow(marker) the next line quotes the format",
        "// - FIXME: ...",
        "const x = 1;",
      ].join("\n"),
    },
    { code: "/**\n * lint: allow(marker) quoted below\n * TODO: ...\n */" },
  ],
  invalid: [
    ...MARKERS.map((marker) => ({
      code: `const x = 1; // ${marker}: tidy this`,
      errors: [{ messageId: "marker" as const, data: { marker } }],
    })),
    {
      code: "/**\n * Fine.\n * HACK: around the bug\n */",
      errors: [{ messageId: "marker" as const, line: 3 }],
    },
    {
      code: `const x = <div>{/* TODO */}</div>;`,
      errors: [{ messageId: "marker" as const }],
    },
    {
      // An allow needs a reason, and names this rule.
      code: "// TODO  lint: allow(marker)\n// XXX  lint: allow(other) why",
      errors: [
        { messageId: "marker" as const },
        { messageId: "marker" as const },
      ],
    },
    {
      // A line of code ends the run an allow covers.
      code: "// lint: allow(marker) a reason\nconst x = 1;\n// FIXME",
      errors: [{ messageId: "marker" as const, line: 3 }],
    },
  ],
});
