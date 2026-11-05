import { createRule } from "./utils";

/** The words a comment may not carry, as whole upper-case words. */
export const MARKERS = ["TODO", "FIXME", "XXX", "HACK"];
const MARKER_WORD = new RegExp(
  `(?<![A-Za-z0-9_])(?:${MARKERS.join("|")})(?![A-Za-z0-9_])`,
);
const ALLOW = /lint: allow\(marker\)[\s:—-]*\w/;
const COMMENT_LINE = /^\s*(\/\/|\/\*|\*)/;

/**
 * True if 1-based `line`, or the run of comment lines directly above it,
 * carries `lint: allow(marker) <why>` (the reason is required).
 */
function isAllowed(lines: readonly string[], line: number): boolean {
  if (ALLOW.test(lines[line - 1] ?? "")) return true;
  for (let i = line - 2; i >= 0 && COMMENT_LINE.test(lines[i] ?? ""); i--) {
    if (ALLOW.test(lines[i] ?? "")) return true;
  }
  return false;
}

export const noMarkerComment = createRule({
  name: "no-marker-comment",
  meta: {
    type: "problem",
    docs: {
      description:
        "Forbid comments promising work later; the work is done now or filed as an issue.",
    },
    messages: {
      marker:
        "'{{marker}}' comment: do it now, or file an issue and delete the comment.",
    },
    schema: [],
  },
  defaultOptions: [],
  create(context) {
    const { sourceCode } = context;
    return {
      // Only comments are read: a string holding the word is data.
      Program() {
        for (const comment of sourceCode.getAllComments()) {
          comment.value.split(/\r?\n/).forEach((text, offset) => {
            const match = MARKER_WORD.exec(text);
            const line = comment.loc.start.line + offset;
            if (!match || isAllowed(sourceCode.lines, line)) return;
            const end = sourceCode.lines[line - 1]?.length ?? 0;
            context.report({
              loc: { start: { line, column: 0 }, end: { line, column: end } },
              messageId: "marker",
              data: { marker: match[0] },
            });
          });
        }
      },
    };
  },
});
