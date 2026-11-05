// The one exception knip.ts declares: an export that stays though nothing
// imports it says why on itself, in a doc comment whose tag is `keep`
// followed by the reason. Knip only skips the tag. This holds it to its
// promise, reading the comments the way knip does: every `@word` in the run
// of comments right before an export is a tag of that export, in a line
// comment, a block comment or the prose of a doc comment alike. So:
//   - the keep tag is only ever a real doc-comment tag with a reason, and it
//     still excuses an export knip would report without it;
//   - `public`, `beta` and `alias` are refused: knip skips an export carrying
//     one whatever knip.ts says, with no reason and no way to go stale.
import ts from "typescript";

/** A source file's path (relative to the frontend) and its text. */
export interface Source {
  file: string;
  text: string;
}

/** An export with tags in the comments before it, as knip reads them. */
export interface Tagged {
  file: string;
  name: string;
  line: number;
  /** Every `@word` in those comments, as knip collects them. */
  tags: string[];
  /** How many keep tags open a line of a doc comment, the one place one
   *  is written, and the reasons TypeScript reads for them. */
  placed: number;
  reasons: string[];
}

const KEEP = "@keep";
const ALWAYS_SKIPPED = ["@public", "@beta", "@alias"];
const TAG = /@[A-Za-z0-9_]+/g;
// A keep tag opening a line of a doc comment: `/** @keep`, or ` * @keep`.
const PLACED = /^\s*(?:\/\*\*|\*)?\s*@keep\b/gm;
const REASON = /[^\s:—#*/-]/;

/** The names a top-level statement exports. */
function exportedNames(statement: ts.Statement): string[] {
  if (ts.isExportAssignment(statement)) return ["default"];
  const modifiers = ts.canHaveModifiers(statement)
    ? (ts.getModifiers(statement) ?? [])
    : [];
  const has = (kind: ts.SyntaxKind) => modifiers.some((m) => m.kind === kind);
  if (!has(ts.SyntaxKind.ExportKeyword)) return [];
  if (has(ts.SyntaxKind.DefaultKeyword)) return ["default"];
  if (ts.isVariableStatement(statement)) {
    return statement.declarationList.declarations.flatMap((d) =>
      ts.isIdentifier(d.name) ? [d.name.text] : [],
    );
  }
  const name = (statement as { name?: ts.Node }).name;
  return name && ts.isIdentifier(name) ? [name.text] : [];
}

/** Every export in `sources` with at least one tag in its comments. */
export function taggedExports(sources: Source[]): Tagged[] {
  return sources.flatMap(({ file, text }) => {
    const source = ts.createSourceFile(
      file,
      text,
      ts.ScriptTarget.Latest,
      true,
    );
    return source.statements.flatMap((statement) => {
      const comments = ts.getLeadingCommentRanges(text, statement.pos) ?? [];
      const texts = comments.map((c) => text.slice(c.pos, c.end));
      const tags = texts.flatMap((comment) => comment.match(TAG) ?? []);
      const placed = texts
        .filter((comment) => comment.startsWith("/**"))
        .flatMap((comment) => comment.match(PLACED) ?? []).length;
      if (tags.length === 0) return [];
      const reasons = ts
        .getJSDocTags(statement)
        .filter((tag) => `@${tag.tagName.text}` === KEEP)
        .map((tag) => ts.getTextOfJSDocComment(tag.comment)?.trim() ?? "");
      const line =
        source.getLineAndCharacterOfPosition(statement.getStart()).line + 1;
      return exportedNames(statement).map((name) => ({
        file,
        name,
        line,
        tags,
        placed,
        reasons,
      }));
    });
  });
}

/** What is wrong with the tags, as `file:line: message`. `excusing` holds
 *  `file#name` for each kept export knip still finds unused: what it
 *  reports when asked for the tagged exports only (`--tags +keep`). */
export function judgeTags(tagged: Tagged[], excusing: Set<string>): string[] {
  return tagged.flatMap(({ file, name, line, tags, placed, reasons }) => {
    const where = `${file}:${line}: ${name}`;
    const found = ALWAYS_SKIPPED.filter((tag) => tags.includes(tag)).map(
      (tag) =>
        `${where} carries ${tag}, which knip always skips: not allowed here`,
    );
    const keeps = tags.filter((tag) => tag === KEEP).length;
    if (keeps === 0) return found;
    if (keeps > 1 || placed !== 1 || reasons.length !== 1) {
      found.push(`${where}: a keep tag is written once, as /** @keep <why> */`);
    } else if (!REASON.test(reasons[0]!)) {
      found.push(`${where}: its keep tag gives no reason`);
    } else if (!excusing.has(`${file}#${name}`)) {
      found.push(
        `${where}: its keep tag excuses nothing, something imports it`,
      );
    }
    return found;
  });
}

/** `file#name` of every export in knip's JSON report, or why it is not one. */
export function reportedExports(json: string): Set<string> | string {
  try {
    const report = JSON.parse(json) as {
      issues: {
        file: string;
        exports: { name: string }[];
        types: { name: string }[];
      }[];
    };
    return new Set(
      report.issues.flatMap(({ file, exports, types }) =>
        [...exports, ...types].map(({ name }) => `${file}#${name}`),
      ),
    );
  } catch (error) {
    return `knip could not run: ${String(error)}`;
  }
}
