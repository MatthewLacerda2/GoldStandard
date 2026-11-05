// The `@keep` exception knip.ts declares: an export that stays though nothing
// imports it says why on itself, `/** @keep <why> */`. Knip only skips the
// tag; this holds it to its promise: every `@keep` carries a reason, and
// excuses an export knip would report without it.
import ts from "typescript";

/** A source file's path (relative to the frontend) and its text. */
export interface Source {
  file: string;
  text: string;
}

/** An exported declaration tagged `@keep`, and the reason it gives. */
export interface Keep {
  file: string;
  name: string;
  line: number;
  reason: string;
}

const TAG = "keep";

/** The names a top-level statement exports, with the node its JSDoc is on. */
function exported(statement: ts.Statement): [string, ts.Node][] {
  const modifiers = ts.canHaveModifiers(statement)
    ? ts.getModifiers(statement)
    : undefined;
  if (!modifiers?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword)) {
    return [];
  }
  if (ts.isVariableStatement(statement)) {
    // The JSDoc is on the statement, for each name it declares.
    return statement.declarationList.declarations.flatMap((d) =>
      ts.isIdentifier(d.name)
        ? [[d.name.text, statement] as [string, ts.Node]]
        : [],
    );
  }
  const name = (statement as { name?: ts.Node }).name;
  return name && ts.isIdentifier(name) ? [[name.text, statement]] : [];
}

/** Every exported declaration tagged `@keep` in `sources`. */
export function keepTags(sources: Source[]): Keep[] {
  return sources.flatMap(({ file, text }) => {
    const source = ts.createSourceFile(
      file,
      text,
      ts.ScriptTarget.Latest,
      true,
    );
    return source.statements.flatMap((statement) =>
      exported(statement).flatMap(([name, node]) =>
        ts
          .getJSDocTags(node)
          .filter((tag) => tag.tagName.text === TAG)
          .map((tag) => ({
            file,
            name,
            line: source.getLineAndCharacterOfPosition(tag.pos).line + 1,
            reason: ts.getTextOfJSDocComment(tag.comment)?.trim() ?? "",
          })),
      ),
    );
  });
}

/** The `@keep` tags that are wrong, as `file:line: message`: no reason, or
 *  nothing to excuse. `excusing` holds `file#name` for each tagged export
 *  knip still finds unused, which is what it reports when asked for the
 *  tagged ones only (`--tags +keep`). */
export function judgeKeeps(keeps: Keep[], excusing: Set<string>): string[] {
  return keeps.flatMap(({ file, name, line, reason }) => {
    const where = `${file}:${line}: @keep on ${name}`;
    if (!/\w/.test(reason)) return [`${where} gives no reason`];
    if (!excusing.has(`${file}#${name}`)) {
      return [`${where} excuses nothing: something imports it now`];
    }
    return [];
  });
}
