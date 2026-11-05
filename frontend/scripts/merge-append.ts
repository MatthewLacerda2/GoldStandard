// The "append" half of the git merge driver (merge-driver.ts), for the
// TypeScript registries two branches grow at the same spot and nothing else:
// the house-rule plugin's index (`eslint-rules/index.ts`) and
// `eslint.config.ts`, where every new house rule adds an import, a `rules`
// entry, its severity and its exemptions right where the last one did. Git's
// line merge calls two insertions at one spot a conflict although the answer
// is plainly "both".
//
// Given git's diff3 output (`git merge-file -p --diff3`), every conflict whose
// base side is EMPTY (both branches only inserted lines there) is resolved as
// ours then theirs: on a rebase, the upstream's lines first and the replayed
// branch's after. Where both sides bring a blank line at the seam, one is
// kept, so the result stays Prettier-clean. A conflict where either side
// changed or deleted a base line is not this driver's: the whole file falls
// back to git's own conflict.
//
// That is stricter than git's `merge=union`, which keeps both sides of ANY
// conflict, edits included, and checks nothing. Even so, "both" is right only
// where the file is a list of independent entries, so each insertion must
// stand alone (`insertionRefusal`: a bracket-balanced block, and the two not
// opening or closing with the same line), and the merged file is checked
// before it is taken (`refusal`): it must still parse, the two insertions must
// not set the same key of a `rules` object, and it must not hold the same
// import, top-level name or object key twice (two branches adding the same
// entry beside different ones).
//
// Every check here runs only on a merge git could not make alone. Insertions
// at DIFFERENT spots are git's ordinary clean merge, taken as git wrote it: two
// branches adding the same entry at different spots both land, and the gates
// (tsc, eslint) are what catch that.
//
// Never route generated code, JSON (the last entry has no comma) or a file
// whose order or adjacency carries meaning (a function body, a sequence of
// statements) through this driver: two insertions there are not two entries.
// `eslint.config.ts` is a last-wins list of blocks; two blocks configuring
// the same rule at one spot are refused, since a rebase and a merge would put
// them in opposite orders.

/** Markers wide enough that no line of these files can be mistaken for one. */
export const PARSE_MARKER_SIZE = 64;

/** Where one conflict's two insertions landed: 0-based line ranges, end excluded. */
export type Seam = { ours: [number, number]; theirs: [number, number] };

export type AppendMerge = { text: string; seams: Seam[] } | { refused: string };

const blank = (line: string | undefined) =>
  line !== undefined && line.trim() === "";

/**
 * An empty base says both insertions sit after the same LINE, not at the same
 * place in the file's structure: xdiff slides an insertion up or down past
 * lines equal to its own edges. So each side's block must be bracket-balanced,
 * never closing what it did not open; a block xdiff slid into a neighbouring
 * one whose first lines match it is not, and the other side's lines would end
 * up inside it.
 *
 * Two insertions that open (or close) with the same line, one with a word in
 * it (a comment, an entry), both wrote it: "both" would keep it twice.
 * Shared brackets alone are two blocks' own edges, and fine.
 */
function insertionRefusal(ours: string[], theirs: string[]): string | null {
  if (!balanced(ours) || !balanced(theirs))
    return "an insertion is not a balanced block";
  const edges = (lines: string[]) => {
    const filled = lines.filter((line) => !blank(line));
    return [filled[0], filled.at(-1)];
  };
  const [ourEdges, theirEdges] = [edges(ours), edges(theirs)];
  for (const [at, where] of [
    [0, "open"],
    [1, "close"],
  ] as const) {
    const line = ourEdges[at];
    if (
      line !== undefined &&
      line === theirEdges[at] &&
      /[\p{L}\p{N}]/u.test(line)
    )
      return `both insertions ${where} with the line ${JSON.stringify(line.trim())}`;
  }
  return null;
}

/** Brackets outside strings and comments open and close within `lines`, in order. */
function balanced(lines: string[]): boolean {
  const pairs: Record<string, string> = { ")": "(", "]": "[", "}": "{" };
  const open: string[] = [];
  let comment = false;
  for (const line of lines) {
    let quote = "";
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (comment) {
        if (c === "*" && line[i + 1] === "/") [comment, i] = [false, i + 1];
      } else if (quote) {
        if (c === "\\") i++;
        else if (c === quote) quote = "";
      } else if (c === "/" && line[i + 1] === "/") break;
      else if (c === "/" && line[i + 1] === "*") [comment, i] = [true, i + 1];
      else if (c === '"' || c === "'" || c === "`") quote = c;
      else if ("([{".includes(c)) open.push(c);
      else if (c in pairs && open.pop() !== pairs[c]) return false;
    }
    if (quote && quote !== "`") return false; // a string cannot span lines
  }
  return open.length === 0 && !comment;
}

/**
 * Where ours ends and theirs begins is the one adjacency neither branch wrote
 * (each side's own edges keep the neighbours they had). Two blank lines there
 * become one, which Prettier would demand: the one line of either side this
 * driver drops.
 */
function joined(ours: string[], theirs: string[]): string[] {
  if (blank(ours.at(-1)) && blank(theirs[0]))
    return [...ours, ...theirs.slice(1)];
  return [...ours, ...theirs];
}

/**
 * Resolve the insert-only conflicts of git's diff3 output (`markerSize`-wide
 * markers), or say why the file is not a pure double insertion.
 */
export function resolveInsertions(
  diff3: string,
  markerSize = PARSE_MARKER_SIZE,
): AppendMerge {
  const [open, baseMark, middle, close] = ["<", "|", "=", ">"].map((c) =>
    c.repeat(markerSize),
  );
  const isMarker = (line: string, mark: string) =>
    line === mark || line.startsWith(`${mark} `);

  const out: string[] = [];
  const seams: Seam[] = [];
  const lines = diff3.split("\n");
  let i = 0;
  while (i < lines.length) {
    if (!isMarker(lines[i], open)) {
      out.push(lines[i++]);
      continue;
    }
    const at = i + 1;
    const sides: Record<"ours" | "base" | "theirs", string[]> = {
      ours: [],
      base: [],
      theirs: [],
    };
    let side = sides.ours;
    let sawBase = false;
    for (i += 1; i < lines.length && !isMarker(lines[i], close); i++) {
      if (isMarker(lines[i], baseMark)) [side, sawBase] = [sides.base, true];
      else if (isMarker(lines[i], middle)) side = sides.theirs;
      else side.push(lines[i]);
    }
    if (i === lines.length || !sawBase)
      return { refused: `unreadable conflict at line ${at}` };
    if (sides.base.length > 0) {
      return {
        refused: `line ${at}: a side changed or removed a line, not only added`,
      };
    }
    const why = insertionRefusal(sides.ours, sides.theirs);
    if (why !== null) return { refused: `line ${at}: ${why}` };
    const start = out.length;
    const both = joined(sides.ours, sides.theirs);
    const seam = start + sides.ours.length;
    seams.push({ ours: [start, seam], theirs: [seam, start + both.length] });
    out.push(...both);
    i += 1;
  }
  return { text: out.join("\n"), seams };
}

/**
 * Why `text`, the merged TypeScript file `path`, must not be taken as is, or
 * `null` when it may: it no longer parses; the two insertions of one of the
 * `seams` set the same key of a `rules` object (in a last-wins list like the
 * ESLint config, a rebase and a merge would order them oppositely); or it
 * holds the same import, top-level name or object key twice.
 */
export async function refusal(
  path: string,
  text: string,
  seams: Seam[] = [],
): Promise<string | null> {
  const ts = (await import("typescript")).default;
  const parsed = ts.transpileModule(text, {
    fileName: path,
    reportDiagnostics: true,
  });
  const broken = parsed.diagnostics?.[0];
  if (broken) {
    return `it no longer parses: ${ts.flattenDiagnosticMessageText(broken.messageText, " ")}`;
  }
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true);
  // Top-level names: two branches each adding `const OWNERS = …` parse fine.
  // A function's overload signatures share its name, so only bodies count.
  const names = source.statements.flatMap((statement) => {
    if (ts.isVariableStatement(statement)) {
      return statement.declarationList.declarations.flatMap((d) =>
        ts.isIdentifier(d.name) ? [d.name.text] : [],
      );
    }
    if (
      ts.isFunctionDeclaration(statement) &&
      statement.body &&
      statement.name
    ) {
      return [statement.name.text];
    }
    if (ts.isClassDeclaration(statement) && statement.name)
      return [statement.name.text];
    return [];
  });
  let duplicateKey: string | null = null;
  // Each key set in a `rules` object, quoted or not, with its 0-based line.
  const ruleKeys: { key: string; line: number }[] = [];
  const visit = (node: import("typescript").Node) => {
    if (
      ts.isPropertyAssignment(node) &&
      propertyKey(ts, node.name) === "rules" &&
      ts.isObjectLiteralExpression(node.initializer)
    ) {
      for (const p of node.initializer.properties) {
        const named =
          ts.isPropertyAssignment(p) || ts.isShorthandPropertyAssignment(p);
        const key = named ? propertyKey(ts, p.name) : null;
        const { line } = source.getLineAndCharacterOfPosition(p.getStart());
        if (key !== null) ruleKeys.push({ key, line });
      }
    }
    if (ts.isImportDeclaration(node) && node.importClause) {
      const { name, namedBindings } = node.importClause;
      if (name) names.push(name.text);
      if (namedBindings && ts.isNamespaceImport(namedBindings)) {
        names.push(namedBindings.name.text);
      } else if (namedBindings)
        names.push(...namedBindings.elements.map((e) => e.name.text));
    }
    if (ts.isObjectLiteralExpression(node) && duplicateKey === null) {
      // A getter and its setter share a name on purpose; only values count.
      const keys = node.properties.flatMap((p) => {
        const named =
          ts.isPropertyAssignment(p) ||
          ts.isShorthandPropertyAssignment(p) ||
          ts.isMethodDeclaration(p);
        const key = named ? propertyKey(ts, p.name) : null;
        return key === null ? [] : [key];
      });
      duplicateKey = repeated(keys, "key");
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  const setIn = ([start, end]: [number, number]) =>
    new Set(
      ruleKeys
        .filter(({ line }) => line >= start && line < end)
        .map(({ key }) => key),
    );
  for (const seam of seams) {
    const theirs = setIn(seam.theirs);
    const shared = [...setIn(seam.ours)].find((key) => theirs.has(key));
    if (shared !== undefined)
      return `both insertions configure ${JSON.stringify(shared)}`;
  }
  return repeated(names, "name") ?? duplicateKey;
}

function propertyKey(
  ts: typeof import("typescript"),
  name: import("typescript").PropertyName,
): string | null {
  if (
    ts.isIdentifier(name) ||
    ts.isStringLiteral(name) ||
    ts.isNumericLiteral(name)
  ) {
    return name.text;
  }
  return null; // a computed key cannot be compared by its text
}

function repeated(items: string[], what: string): string | null {
  const seen = new Set<string>();
  for (const item of items) {
    if (seen.has(item))
      return `the ${what} ${JSON.stringify(item)} would appear twice`;
    seen.add(item);
  }
  return null;
}
