import preact from "@preact/preset-vite";
import { defineConfig } from "vitest/config";
import { resolve } from "node:path";

// Builds an unpacked MV3 extension into dist/:
//   dist/manifest.json   (copied from public/)
//   dist/sidepanel.html  (Preact side panel UI)
//   dist/options.html    (first-run form / settings, opened on install)
//   dist/background.js   (service worker, stable name so the manifest can point at it)
export default defineConfig({
  plugins: [preact()],
  resolve: {
    alias: {
      // The card components live in the panel workstream; the extension hosts them.
      "~panel": resolve(__dirname, "../panel/src"),
      "~fixtures": resolve(__dirname, "../fixtures"),
    },
    // panel/src has no node_modules of its own: resolve preact from here, exactly once.
    dedupe: ["preact"],
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
    modulePreload: false,
    rollupOptions: {
      input: {
        sidepanel: resolve(__dirname, "sidepanel.html"),
        options: resolve(__dirname, "options.html"),
        background: resolve(__dirname, "src/background.ts"),
      },
      output: {
        entryFileNames: (chunk) => (chunk.name === "background" ? "background.js" : "assets/[name]-[hash].js"),
      },
    },
  },
  test: {
    environment: "node",
    include: ["test/**/*.test.ts"],
  },
});
