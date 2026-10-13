import { readFileSync } from "node:fs";
import { join } from "node:path";

export function dataset(name) {
  return JSON.parse(readFileSync(join(process.cwd(), "_site", "data", "v1", `${name}.json`), "utf8"));
}
