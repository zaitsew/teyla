// Writes capture.json and capture.png the way the web package builds them, for the Python tests that
// validate the JSON against templates/review/capture.schema.json and upload it to the real channel
// service:  node scripts/emit-sample-capture.ts <outDir> <product>
import { mkdirSync, writeFileSync } from "node:fs";
import { encodeCapture } from "../src/format.ts";
import { recordFor } from "../src/session.ts";
import { sha256Hex } from "../src/sha256.ts";

const [outDir, product = "fixture-app"] = process.argv.slice(2);
if (!outDir) { console.error("usage: emit-sample-capture.ts <outDir> [product]"); process.exit(2); }

// A 1x1 PNG.
const png = Uint8Array.from(Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64"));
const anchors = [
  { id: "app.home.card", screen: "app.home", role: "container" as const, bounds: { x: 8, y: 80, width: 600, height: 120 } },
  { id: "app.home.addButton", screen: "app.home", parent: "app.home.card", role: "button" as const, bounds: { x: 500, y: 100, width: 80, height: 40 }, strings: ["home.add"], source: { file: "src/Home.tsx", line: 41 } },
];
const rec = recordFor({
  id: "3b9f1d2e-6a41-4c7e-9d0a-5e2f8b7c1a64", hostname: "test.example.com", product, name: "Sample App", version: "1.4.0", build: "212", commit: "3f9c2ab",
  environment: { os: "macOS 15.1", model: "Chrome 130", locale: "es-ES", language: "es", appearance: "dark", dynamic_type: "unspecified", screen: { width: 1000, height: 700, scale: 2 } },
  anchors, frames: [{ x: 8, y: 300, width: 200, height: 40 }], sha256: await sha256Hex(png), pixelWidth: 2000, pixelHeight: 1400, scale: 2,
}, { tap: { x: 530, y: 120 }, text: "The add button is too small.", input: "text" }, new Date());
mkdirSync(outDir, { recursive: true });
writeFileSync(`${outDir}/capture.png`, png);
writeFileSync(`${outDir}/capture.json`, encodeCapture(rec));
