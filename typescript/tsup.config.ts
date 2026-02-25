import { defineConfig } from "tsup";

export default defineConfig({
  entry: {
    index: "typescript/src/index.ts",
    cli: "typescript/src/cli.ts",
  },
  format: ["cjs", "esm"],
  dts: true,
  sourcemap: true,
  clean: true,
  outDir: "dist",
  target: "es2020",
  shims: true,
});
