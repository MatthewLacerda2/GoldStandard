// The verdict, apart from the analysis: today's findings against the
// baseline (the findings that stood the day the gate was born, which only
// shrinks) and the allowlist (fields read in a way no analysis can see, each
// with its reason).
import type { Finding } from "./collect";

/** `unread Item.owner_id` — how a finding is named in both lists. */
export const findingId = (f: Pick<Finding, "kind" | "key">) =>
  `${f.kind} ${f.key}`;

/** The baseline file: its lines, and the renames some of them declare
 *  (`unread New.x  # was unread Old.x`), new line to old. */
export interface Baseline {
  lines: string[];
  renamed: Map<string, string>;
}

export interface Verdict {
  /** Findings neither list names: what the change under review introduced. */
  fresh: Finding[];
  /** Baseline lines no finding matches any more: fixed, so the line goes. */
  staleBaseline: string[];
  /** Allowlist entries no finding matches any more: read plainly now, or gone. */
  staleAllowed: string[];
  /** Baseline lines the base branch did not have, and that rename none it had:
   *  the baseline only shrinks. */
  grown: string[];
}

export function judge(
  findings: Finding[],
  baseline: Baseline,
  allowed: Readonly<Record<string, string>>,
  /** The baseline's lines on the base branch; `undefined` when there is none to compare. */
  base?: readonly string[],
): Verdict {
  const ids = new Set(findings.map(findingId));
  const inBaseline = new Set(baseline.lines);
  return {
    fresh: findings.filter(
      (f) => !inBaseline.has(findingId(f)) && !(findingId(f) in allowed),
    ),
    staleBaseline: baseline.lines.filter(
      (line) => !ids.has(line) || line in allowed,
    ),
    staleAllowed: Object.keys(allowed).filter((id) => !ids.has(id)),
    grown: base ? grownLines(baseline, new Set(base)) : [],
  };
}

// A line the base did not have is growth, unless it renames one the base had
// and this baseline no longer has: the same kind of finding about the same
// field, under another type or file (`unread A.x` → `unread B.x`), and the
// old type is gone from the baseline — a rename moves all its lines, so `A`
// keeping one says `A` was not renamed. Each old line is claimed once, so a
// rename never lets the count grow, and fixing one field never buys room for
// another. What this cannot tell (an old type whose only line was this one)
// is left to the diff, where every added line shows.
function grownLines(baseline: Baseline, base: ReadonlySet<string>): string[] {
  const kept = new Set(baseline.lines);
  const owners = new Set(baseline.lines.map(ownerOf));
  const claimed = new Set<string>();
  return baseline.lines.filter((line) => {
    if (base.has(line)) return false;
    const old = baseline.renamed.get(line);
    if (!old || !base.has(old) || kept.has(old) || claimed.has(old))
      return true;
    if (sameField(old) !== sameField(line) || owners.has(ownerOf(old)))
      return true;
    claimed.add(old);
    return false;
  });
}

// The kind and the type a line is about: everything before the field.
const ownerOf = (line: string) => line.slice(0, line.lastIndexOf("."));

// What a rename keeps: the kind, and the field's own name after the last dot.
const sameField = (line: string) =>
  `${line.slice(0, line.indexOf(" "))} ${line.slice(line.lastIndexOf(".") + 1)}`;

const HEADER = `# The contract gate's baseline (frontend/scripts/check-contract.ts): the
# findings that stood on the day the gate was born. It only shrinks — a line
# the gate no longer finds is reported, and one the base branch did not have
# is refused. Fix a line by reading the field, declaring it, or removing it
# from the backend's answer (then \`make openapi\`) and the frontend's type;
# then delete the line.
#
# A rename (of a type, a file, a schema) turns its lines into new ones: say so
# on each, \`unread New.field  # was unread Old.field\` — same kind, same field —
# and the old line it replaces does not count as growth. A different field is
# never a rename. \`--write-baseline\` keeps those notes.
`;

const RENAME = "  # was ";

export function parseBaseline(text: string): Baseline {
  const lines: string[] = [];
  const renamed = new Map<string, string>();
  for (const raw of text.split("\n")) {
    const trimmed = raw.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const at = trimmed.indexOf(RENAME.trim());
    const line = at === -1 ? trimmed : trimmed.slice(0, at).trim();
    if (at !== -1)
      renamed.set(line, trimmed.slice(at + RENAME.trim().length).trim());
    lines.push(line);
  }
  return { lines, renamed };
}

/** The file for these lines, each keeping the rename it declared in `renamed`. */
export function formatBaseline(
  lines: readonly string[],
  renamed: ReadonlyMap<string, string> = new Map(),
): string {
  const body = [...new Set(lines)].sort().map((line) => {
    const old = renamed.get(line);
    return old ? `${line}${RENAME}${old}` : line;
  });
  return HEADER + body.join("\n") + "\n";
}
