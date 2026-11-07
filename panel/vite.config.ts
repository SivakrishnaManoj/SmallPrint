import preact from "@preact/preset-vite";
import { defineConfig } from "vite";
import path from "path";

export default defineConfig({
  plugins: [preact()],
  build: {
    outDir: "dist",
  },
  resolve: {
    alias: {
      "~fixtures": path.resolve(__dirname, "../fixtures"),
    },
  },
});
