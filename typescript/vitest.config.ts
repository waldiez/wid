import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    root: "typescript",
    include: ["test/**/*.test.ts"],
  },
});
