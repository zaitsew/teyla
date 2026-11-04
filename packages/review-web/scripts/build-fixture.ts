// Builds fixture/ with Vite, once with the review flag and once without:
//   node scripts/build-fixture.ts <outDir> on|off [--key=<channel key>] [--url=<channel url>]
// The flag-on build holds the overlay chunk and the channel key; the flag-off build must hold neither.
import { build } from "vite";
import { fileURLToPath } from "node:url";

const [outDir, mode, ...rest] = process.argv.slice(2);
if (!outDir || (mode !== "on" && mode !== "off")) {
  console.error("usage: build-fixture.ts <outDir> on|off [--key=K] [--url=U]");
  process.exit(2);
}
const arg = (name: string) => rest.find((a) => a.startsWith(`--${name}=`))?.slice(name.length + 3);
const root = fileURLToPath(new URL("../fixture", import.meta.url));

// In both builds the channel address and key are in the environment, the way a CI job has them:
// the flag decides whether they reach the output.
process.env.VITE_TEYLA_REVIEW_KEY = arg("key") ?? "fixture-write-only-key-0123456789";
process.env.VITE_TEYLA_REVIEW_URL = arg("url") ?? "http://localhost:8099";
if (mode === "on") process.env.VITE_TEYLA_REVIEW = "1";
else delete process.env.VITE_TEYLA_REVIEW;

await build({ configFile: false, root, logLevel: "warn", envDir: root, build: { outDir, emptyOutDir: true, minify: true, target: "es2022" } });
