// A knip reporter that only says what to do: `bun run deadcode` runs it after
// knip's own list (`--reporter symbols --reporter <this file>`).
import type { Reporter } from "knip";

const knipHint: Reporter = ({ counters }) => {
  // `processed` and `total` count the files read, not the issues found.
  const found = Object.entries(counters).some(
    ([kind, count]) => kind !== "processed" && kind !== "total" && count > 0,
  );
  if (!found) return;
  console.error(
    "\nDelete what knip names: the file, the `export` (or the whole symbol, if nothing in" +
      " its file uses it either), or the dependency (`bun remove <name>`). An export that" +
      " stays on purpose says why on itself: `/** @keep <why> */`. A file a tool reaches" +
      " that knip does not see is an entry in knip.ts, with the reason.",
  );
};

export default knipHint;
