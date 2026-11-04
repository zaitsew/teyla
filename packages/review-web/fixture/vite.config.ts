import { defineConfig } from "vite";

// root is the fixture folder; `outDir` comes from the build script.
export default defineConfig({
  root: new URL(".", import.meta.url).pathname,
  logLevel: "warn",
  build: { emptyOutDir: true, minify: true, sourcemap: false, target: "es2022" },
});
