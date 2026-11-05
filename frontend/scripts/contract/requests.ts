// Where the frontend asks the API for JSON: every call of a fetcher of the
// API client (`request<T>`, `CLIENT` in `config.ts`), the paths it can ask for as far as the code
// spells them, its methods, and the type it reads the answer as.
import ts from "typescript";
import { DYNAMIC, HTTP_METHODS } from "./openapi";

export interface Request {
  /** `lib/api/items.ts#createItem` — the call site, line-free. */
  site: string;
  /** Every path the call can ask for, run-time pieces as `DYNAMIC` and the
   *  query cut off (`id ? `${BASE}/${id}` : BASE` is two). Empty when the code
   *  builds it out of sight — a callback's answer. */
  paths: string[];
  /** Lower case, every one the call can use. Empty when the code decides it
   *  out of sight. */
  methods: string[];
  /** What the answer is read as (`T`, awaited). */
  type: ts.Type;
}

/** The API client: its module's file name, and the functions there that fetch. */
export interface Client {
  file: string;
  fetchers: readonly string[];
}

/** More alternatives than this and the path is not worth spelling out. */
const MAX_ALTERNATIVES = 16;

export function findRequests(
  program: ts.Program,
  client: Client,
  isReaderFile: (fileName: string) => boolean,
  siteOf: (node: ts.Node) => string,
): Request[] {
  const checker = program.getTypeChecker();
  const requests: Request[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isCallExpression(node) && isFetch(checker, client, node)) {
      const signature = checker.getResolvedSignature(node);
      const type =
        signature && checker.getAwaitedType(signature.getReturnType());
      const [pathArg, initArg] = node.arguments;
      if (type && pathArg) {
        const methods = initArg ? methodsOf(checker, initArg) : ["get"];
        requests.push({
          site: siteOf(node),
          paths: pathsOf(checker, pathArg),
          methods,
          type,
        });
      }
    }
    ts.forEachChild(node, visit);
  };
  for (const sf of program.getSourceFiles()) {
    if (!sf.isDeclarationFile && isReaderFile(sf.fileName)) visit(sf);
  }
  return requests;
}

// Whether a call is of one of the client's fetchers, however it was imported.
function isFetch(
  checker: ts.TypeChecker,
  client: Client,
  call: ts.CallExpression,
): boolean {
  const decl = declarationOf(checker, call.expression);
  if (!decl || !ts.isFunctionDeclaration(decl) || !decl.name) return false;
  return (
    decl.getSourceFile().fileName === client.file &&
    client.fetchers.includes(decl.name.text)
  );
}

/** The paths an expression can spell: literals, constants, string-literal
 *  unions, both sides of a choice and every return of a helper spelled out,
 *  anything else as `DYNAMIC`, the query string cut off. */
export function pathsOf(
  checker: ts.TypeChecker,
  expr: ts.Expression,
): string[] {
  const texts = evaluate(checker, expr, 0);
  if (texts.length > MAX_ALTERNATIVES) return [];
  const paths = texts.flatMap((text) => normalize(text) ?? []);
  return paths.length === texts.length ? [...new Set(paths)] : [];
}

// A dynamic piece that does not start a segment is the query string's
// (`/items${query ? `?${query}` : ""}`), so the path ends there.
function normalize(text: string): string | undefined {
  if (!text.startsWith("/")) return undefined;
  let path = text.split("?")[0];
  const cut = [...path].findIndex(
    (ch, i) => ch === DYNAMIC && i > 0 && path[i - 1] !== "/",
  );
  if (cut !== -1) path = path.slice(0, cut);
  return path
    .replace(new RegExp(`${DYNAMIC}+`, "g"), DYNAMIC)
    .replace(/(.)\/$/, "$1");
}

const product = (heads: string[], tails: string[]) =>
  heads
    .flatMap((head) => tails.map((tail) => head + tail))
    .slice(0, MAX_ALTERNATIVES + 1);

// Every text the expression can be; `[DYNAMIC]` for a piece computed at run
// time, and nothing at all (`[]`) when the whole path is.
function evaluate(
  checker: ts.TypeChecker,
  expr: ts.Expression,
  depth: number,
  env?: Bindings,
): string[] {
  const dynamic = depth === 0 ? [] : [DYNAMIC];
  if (depth > 6) return dynamic;
  if (ts.isStringLiteralLike(expr)) return [expr.text];
  if (ts.isParenthesizedExpression(expr))
    return evaluate(checker, expr.expression, depth, env);
  if (ts.isTemplateExpression(expr)) {
    let texts = [expr.head.text];
    for (const span of expr.templateSpans) {
      texts = product(
        texts,
        evaluate(checker, span.expression, depth + 1, env),
      );
      texts = product(texts, [span.literal.text]);
    }
    return texts;
  }
  if (
    ts.isBinaryExpression(expr) &&
    expr.operatorToken.kind === ts.SyntaxKind.PlusToken
  ) {
    return product(
      evaluate(checker, expr.left, depth + 1, env),
      evaluate(checker, expr.right, depth + 1, env),
    );
  }
  if (ts.isConditionalExpression(expr)) {
    const branches = [expr.whenTrue, expr.whenFalse].map((e) =>
      evaluate(checker, e, depth + 1, env),
    );
    return branches.some((b) => b.length === 0) ? dynamic : branches.flat();
  }
  if (ts.isCallExpression(expr)) {
    const decl = declarationOf(checker, expr.expression);
    const fn = decl && functionOf(decl);
    if (!fn?.body) return dynamic;
    // The helper's parameters are what this call passes (`p("a")` is `/api/a`,
    // not every member of `k: "a" | "b"`).
    const bound: Bindings = new Map();
    fn.parameters.forEach((param, i) => {
      const arg = expr.arguments[i];
      const symbol = ts.isIdentifier(param.name)
        ? checker.getSymbolAtLocation(param.name)
        : undefined;
      if (arg && symbol && !param.dotDotDotToken)
        bound.set(symbol, { expr: arg, env });
    });
    const returns = returnsOf(fn.body).map((e) =>
      evaluate(checker, e, depth + 1, bound),
    );
    return returns.length === 0 || returns.some((r) => r.length === 0)
      ? dynamic
      : returns.flat();
  }
  if (ts.isIdentifier(expr) && env) {
    const symbol = checker.getSymbolAtLocation(expr);
    const arg = symbol && env.get(symbol);
    if (arg) return evaluate(checker, arg.expr, depth + 1, arg.env);
  }
  const literals = stringLiterals(checker.getTypeAtLocation(expr));
  if (literals) return literals;
  if (ts.isIdentifier(expr) || ts.isPropertyAccessExpression(expr)) {
    const decl = declarationOf(checker, expr);
    if (
      decl &&
      ts.isVariableDeclaration(decl) &&
      decl.initializer &&
      ts.getCombinedNodeFlags(decl) & ts.NodeFlags.Const
    ) {
      return evaluate(checker, decl.initializer, depth + 1);
    }
  }
  return dynamic;
}

// The values of a string literal type or a union of them (`kind: "a" | "b"`).
function stringLiterals(type: ts.Type): string[] | undefined {
  const members = type.isUnion() ? type.types : [type];
  const values = members.flatMap((m) => (m.isStringLiteral() ? [m.value] : []));
  return values.length > 0 && values.length === members.length
    ? values
    : undefined;
}

function declarationOf(
  checker: ts.TypeChecker,
  expr: ts.Expression,
): ts.Declaration | undefined {
  let symbol = checker.getSymbolAtLocation(expr);
  if (symbol && symbol.flags & ts.SymbolFlags.Alias)
    symbol = checker.getAliasedSymbol(symbol);
  return symbol?.valueDeclaration ?? symbol?.declarations?.[0];
}

/** Each parameter of a helper a call evaluates, with what the call passes. */
type Bindings = Map<
  ts.Symbol,
  { expr: ts.Expression; env: Bindings | undefined }
>;

function functionOf(
  decl: ts.Declaration,
):
  | ts.FunctionDeclaration
  | ts.ArrowFunction
  | ts.FunctionExpression
  | undefined {
  if (ts.isFunctionDeclaration(decl)) return decl;
  if (ts.isVariableDeclaration(decl) && decl.initializer) {
    const init = decl.initializer;
    if (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) return init;
  }
  return undefined;
}

const functionBody = (decl: ts.Declaration) => functionOf(decl)?.body;

// What a body returns: a concise arrow's expression, or each `return` that is
// not inside a nested function.
function returnsOf(body: ts.ConciseBody): ts.Expression[] {
  if (!ts.isBlock(body)) return [body];
  const found: ts.Expression[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isFunctionLike(node)) return;
    if (ts.isReturnStatement(node) && node.expression)
      found.push(node.expression);
    ts.forEachChild(node, visit);
  };
  ts.forEachChild(body, visit);
  return found;
}

// The methods an init can ask for: its `method` (written out or shorthand),
// spelled out like a path; a constant's initializer; or the one the helper
// that builds it names (`put(body)`, `json("PATCH", body)`). An init whose
// type has no `method` is a GET. Empty when the code decides it out of sight —
// never guessed: the request is then unpaired.
function methodsOf(
  checker: ts.TypeChecker,
  init: ts.Expression,
  depth = 0,
): string[] {
  if (depth > 3) return [];
  if (
    ts.isParenthesizedExpression(init) ||
    ts.isAsExpression(init) ||
    ts.isSatisfiesExpression(init)
  ) {
    return methodsOf(checker, init.expression, depth);
  }
  if (ts.isObjectLiteralExpression(init)) {
    // As at run time, a later property wins: `{ method: "POST", ...init }`
    // takes `init`'s method when it can carry one.
    let methods = ["get"];
    for (const prop of init.properties) {
      if (ts.isSpreadAssignment(prop)) {
        const spread = checker.getNonNullableType(
          checker.getTypeAtLocation(prop.expression),
        );
        if (spread.getProperty("method"))
          methods = methodsOf(checker, prop.expression, depth + 1);
        continue;
      }
      const key = prop.name;
      const name =
        key && (ts.isIdentifier(key) || ts.isStringLiteral(key))
          ? key.text
          : undefined;
      if (name !== "method") continue;
      methods = ts.isPropertyAssignment(prop)
        ? methodNames(evaluate(checker, prop.initializer, 0))
        : ts.isShorthandPropertyAssignment(prop)
          ? methodNames(evaluate(checker, prop.name, 0))
          : [];
    }
    return methods;
  }
  if (ts.isIdentifier(init)) {
    const decl = declarationOf(checker, init);
    if (
      decl &&
      ts.isVariableDeclaration(decl) &&
      decl.initializer &&
      ts.getCombinedNodeFlags(decl) & ts.NodeFlags.Const
    ) {
      return methodsOf(checker, decl.initializer, depth + 1);
    }
  }
  if (ts.isCallExpression(init)) {
    for (const arg of init.arguments) {
      if (ts.isStringLiteralLike(arg) && isMethodName(arg.text))
        return [arg.text.toLowerCase()];
    }
    const decl = declarationOf(checker, init.expression);
    const body = decl && functionBody(decl);
    const returns = body ? returnsOf(body) : [];
    if (returns.length > 0) {
      return [
        ...new Set(returns.flatMap((r) => methodsOf(checker, r, depth + 1))),
      ];
    }
  }
  return checker.getTypeAtLocation(init).getProperty("method") ? [] : ["get"];
}

const methodNames = (texts: string[]) =>
  texts.every(isMethodName)
    ? [...new Set(texts.map((t) => t.toLowerCase()))]
    : [];

const isMethodName = (text: string) =>
  (HTTP_METHODS as readonly string[]).includes(text.toLowerCase());
