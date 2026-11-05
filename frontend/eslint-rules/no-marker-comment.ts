import { createRule } from "./utils";

/** The words a comment may not carry, as whole upper-case words. */
export const MARKERS = ["TODO", "FIXME", "XXX", "HACK"];
const MARKER_WORD = new RegExp(
  `(?<![A-Za-z0-9_])(?:${MARKERS.join("|")})(?![A-Za-z0-9_])`,
);
// The reason starts at the first character that is not a separator, so it
// may open with a backtick, quote or bracket.
const ALLOW = /lint: allow\(marker\)[\s:—-]*[^\s:—-]/;

/**
 * True if the comment text on `line`, or on the line directly above it,
 * carries `lint: allow(marker) <why>` (the reason is required).
 */
function isAllowed(comments: Map<number, string>, line: number): boolean {
  return [line, line - 1].some((at) => ALLOW.test(comments.get(at) ?? ""));
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
      // Only comment text is read, for the marker and the allow alike: a
      // string holding either is data.
      Program() {
        const comments = new Map<number, string>();
        for (const comment of sourceCode.getAllComments()) {
          comment.value.split(/\r?\n/).forEach((text, offset) => {
            const line = comment.loc.start.line + offset;
            comments.set(line, `${comments.get(line) ?? ""} ${text}`);
          });
        }
        for (const [line, text] of comments) {
          const match = MARKER_WORD.exec(text);
          if (!match || isAllowed(comments, line)) continue;
          const end = sourceCode.lines[line - 1]?.length ?? 0;
          context.report({
            loc: { start: { line, column: 0 }, end: { line, column: end } },
            messageId: "marker",
            data: { marker: match[0] },
          });
        }
      },
    };
  },
});
