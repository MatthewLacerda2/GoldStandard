import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// CI installs the Bun named by `packageManager`; the production image builds on
// the `oven/bun` tag in the Dockerfile. Dependabot bumps only the tag, so this
// test is what keeps the two one version: its PR stays red until
// `packageManager` moves with it.
const frontend = resolve(import.meta.dirname, "..");
const read = (file: string) => readFileSync(resolve(frontend, file), "utf8");

test("the Docker image builds on the Bun version CI tests with", () => {
  const { packageManager } = JSON.parse(read("package.json")) as {
    packageManager: string;
  };
  const ciBun = /^bun@(.+)$/.exec(packageManager)?.[1];
  const imageBun = /^FROM oven\/bun:([^\s-]+)/m.exec(read("Dockerfile"))?.[1];

  expect(ciBun, "packageManager should be bun@<version>").toBeDefined();
  expect(
    imageBun,
    "Dockerfile should build FROM oven/bun:<version>",
  ).toBeDefined();
  expect(
    imageBun,
    "the Dockerfile's oven/bun tag and package.json's packageManager must move together",
  ).toBe(ciBun);
});
