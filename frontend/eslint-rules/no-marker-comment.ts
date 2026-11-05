import { createRule } from "./utils";

/** The words a comment may not carry, as whole upper-case words. */
export const MARKERS = ["TODO", "FIXME", "XXX", "HACK"];
const MARKER_PATTERN = `(?<![A-Za-z0-9_])(?:${MARKERS.join("|")})(?![A-Za-z0-9_])`;
const MARKER_WORD = new RegExp(MARKER_PATTERN);
const MARKER_WORDS = new RegExp(MARKER_PATTERN, "g");
const ALLOW = /lint: allow\(marker\)(.*)/;
// A reason is any character that is not a separator, so it may open with a
// backtick, quote or bracket.
const REASON = /[^\s:—#*/-]/;
// The line breaks ESLint itself counts lines by.
const LINE_BREAK = /\r\n|[\r\n\u2028\u2029]/;

/**
 * True if `comment` carries `lint: allow(marker) <why>`, whose reason is
 * something besides separators and markers: it may quote the word, but
 * `// lint: allow(marker) // TODO` gives no reason.
 */
function grants(comment: string): boolean {
  const allow = ALLOW.exec(comment);
  return !!allow && REASON.test((allow[1] ?? "").replace(MARKER_WORDS, ""));
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
      // Only comment text is read, for the marker and the allow alike, each
      // comment on its own: a string holding either is data.
      Program() {
        const comments = new Map<number, string[]>();
        for (const comment of sourceCode.getAllComments()) {
          comment.value.split(LINE_BREAK).forEach((text, offset) => {
            const line = comment.loc.start.line + offset;
            comments.set(line, [...(comments.get(line) ?? []), text]);
          });
        }
        for (const [line, texts] of comments) {
          const match = texts.map((t) => MARKER_WORD.exec(t)).find(Boolean);
          const near = [line, line - 1].flatMap((at) => comments.get(at) ?? []);
          if (!match || near.some(grants)) continue;
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
