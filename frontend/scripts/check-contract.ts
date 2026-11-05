// The contract gate: holds the frontend's hand-written types
// (`src/lib/schemas/`) to what the backend sends. Run by `make front-contract`,
// so by `make frontend` and CI.
//
// It finds every request the app makes through the API client (`CLIENT` in
// `contract/config.ts`), pairs the type it reads the answer as with the
// endpoint's answer in the backend's contract (`frontend/openapi.json`,
// written by `make openapi`; `make back-build` fails when it is stale), and
// reports five kinds of finding:
//
//   unread      a field a response type declares that no code reads (the
//               schema modules, tests and mocks are not readers);
//   undeclared  a field a paired backend answer sends that no frontend type
//               declares — so nothing reads it either;
//   phantom     a field a frontend type declares that its endpoint never sends;
//   mismatched  a value read as another kind than it is sent: a list read as
//               one object, an object read as a list or a string, and so on;
//   unpaired    a request whose answer cannot be matched to an endpoint: the
//               path is built out of sight. Give the type it reads the
//               answer as a `/** @backend SchemaName */` tag.
//
// So it compares field names and what kind each value is (list, object,
// scalar), nesting included; it does not compare a scalar's type (string or
// number), nullability, or request bodies, and an endpoint no request calls
// is not looked at. How a read is told from a declaration or a write, and how
// a read through a parameter of another type counts, is in
// `contract/analyze.ts`; how a request is matched to its operation, in
// `contract/requests.ts`.
//
// Today's findings are held against the baseline (`contract/baseline.txt`,
// only shrinks: a line no longer found is reported, a line the base branch
// did not have is refused unless it declares the line it renames) and the
// allowlist (`ALLOWED` in `contract/config.ts`, each entry with its reason).
// `--write-baseline` rewrites the baseline to today's findings, keeping the
// renames it declared — to drop fixed lines; a line it adds is still refused.
import ts from "typescript";
import { readFileSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { baseBaseline, baseCommit } from "./contract/baseline-base";
import { collect } from "./contract/collect";
import { ALLOWED, CLIENT, isExcludedReader } from "./contract/config";
import {
  findingId,
  formatBaseline,
  judge,
  parseBaseline,
} from "./contract/gate";
import type { OpenApi } from "./contract/openapi";

const NAME = "check-contract";
const FRONTEND = join(import.meta.dirname, "..");
const REPO = join(FRONTEND, "..");
const BASELINE = join(FRONTEND, "scripts/contract/baseline.txt");
const SRC = join(FRONTEND, "src") + "/";

const started = Date.now();
const config = ts.getParsedCommandLineOfConfigFile(
  join(FRONTEND, "tsconfig.json"),
  {},
  { ...ts.sys, onUnRecoverableConfigFileDiagnostic: () => {} },
);
if (!config) throw new Error(`${NAME}: tsconfig.json could not be read`);
const program = ts.createProgram(config.fileNames, config.options);
const spec = JSON.parse(
  readFileSync(join(FRONTEND, "openapi.json"), "utf8"),
) as OpenApi;
const { findings, stats } = collect(program, spec, {
  root: FRONTEND,
  isProjectFile: (fileName) => fileName.startsWith(SRC),
  isExcludedReader,
  client: CLIENT,
});

if (process.argv.includes("--write-baseline")) {
  const lines = findings.map(findingId).filter((id) => !(id in ALLOWED));
  const { renamed } = parseBaseline(readFileSync(BASELINE, "utf8"));
  writeFileSync(BASELINE, formatBaseline(lines, renamed));
  console.log(
    `${NAME}: wrote ${lines.length} lines to ${relative(REPO, BASELINE)}.`,
  );
}

const baseline = parseBaseline(readFileSync(BASELINE, "utf8"));
const verdict = judge(findings, baseline, ALLOWED, baseLines());
const seconds = ((Date.now() - started) / 1000).toFixed(1);
const problems =
  verdict.fresh.length +
  verdict.staleBaseline.length +
  verdict.staleAllowed.length +
  verdict.grown.length;

for (const f of verdict.fresh) {
  const where = f.where ? ` (${f.where})` : "";
  const detail = f.detail ? ` — ${f.detail}` : "";
  console.error(`${NAME}: ${findingId(f)}${where}${detail}`);
}
for (const line of verdict.staleBaseline) {
  console.error(
    `${NAME}: baseline line "${line}" is no longer found — delete it.`,
  );
}
for (const id of verdict.staleAllowed) {
  console.error(
    `${NAME}: ALLOWED names "${id}", which is no longer found — delete it.`,
  );
}
for (const line of verdict.grown) {
  console.error(
    `${NAME}: baseline line "${line}" is new — the baseline only shrinks; fix the finding or allow it with its reason. Only when it is the same field renamed (same kind and field, another type or file) does the line say so: "${line}  # was <the old line>".`,
  );
}
if (problems > 0) {
  console.error(
    "\nThe frontend's types and the backend's answers must agree, and a field nobody reads is" +
      " not sent: declare and read it, or remove it from the backend's response model (then" +
      " `make openapi`) and from the frontend's type. A value read as another kind than it is sent" +
      " (a list read as one object) is fixed in the frontend's type or the request. A field read in a way the analysis cannot" +
      " see (a string accessor, Object.entries, a whole-row export) goes in ALLOWED" +
      " (scripts/contract/config.ts) with the reason. A request it cannot pair takes a" +
      " `/** @backend SchemaName */` tag on the type it reads the answer as.",
  );
  process.exit(1);
}
console.log(
  `${NAME}: ${stats.fields} fields of ${stats.requests} requests (${stats.paired} paired with the contract), ` +
    `${baseline.lines.length} in the baseline, ${Object.keys(ALLOWED).length} allowed — ${seconds}s.`,
);

// The baseline as the base branch has it, to refuse a line it did not have.
function baseLines(): string[] | undefined {
  const gate = {
    name: NAME,
    repo: REPO,
    baseline: relative(REPO, BASELINE),
    script: relative(REPO, import.meta.filename),
  };
  const text = baseBaseline(gate, baseCommit(gate));
  return text === undefined ? undefined : parseBaseline(text).lines;
}
