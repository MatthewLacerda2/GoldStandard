// What the contract gate reads, what it skips, and what it lets through.

/** How the app asks the API for JSON: the module `lib/api/` goes through, the
 *  functions there that fetch, and the prefix they put in front of a path
 *  (`request("/items")` asks for `/api/v1/items`). A prefix that drifts from
 *  the client's turns every request unpaired, so the gate says so itself. */
export const CLIENT = {
  file: "src/lib/api/client.ts",
  fetchers: ["request"],
  prefix: "/api/v1",
} as const;

/** Not a read, wherever it happens: the schema modules declare the fields,
 *  tests and mocks build and assert them. */
export function isExcludedReader(fileName: string): boolean {
  return (
    fileName.includes("/src/lib/schemas/") ||
    /\.test\.tsx?$/.test(fileName) ||
    /\/mock-[^/]*\.tsx?$/.test(fileName)
  );
}

/** Findings that are not findings: a field read by a name no code spells (a
 *  column's string accessor, `Object.entries`, an export of the whole row),
 *  or one a standard makes the backend send. Keyed as the gate prints it
 *  (`unread Type.field`), each with its reason. An entry nothing matches any
 *  more is reported, so the list stays true. */
export const ALLOWED: Readonly<Record<string, string>> = {
  "unread TokenResponse.token_type":
    "OAuth 2.0 (RFC 6749, section 5.1) makes a token response carry it; the client only speaks bearer",
};
