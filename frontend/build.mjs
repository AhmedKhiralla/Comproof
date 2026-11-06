// Builds the web app into dist/ with esbuild. `node build.mjs --watch` rebuilds on change.
import * as esbuild from "esbuild";
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const dist = join(root, "dist");
const watch = process.argv.includes("--watch");

const options = {
  entryPoints: { app: join(root, "src/main.tsx") },
  bundle: true,
  outdir: join(dist, "assets"),
  format: "esm",
  target: ["es2022", "chrome110", "firefox115", "safari16"],
  minify: !watch,
  sourcemap: watch ? "inline" : false,
  jsx: "automatic",
  loader: { ".png": "file", ".svg": "file" },
  define: { "process.env.NODE_ENV": JSON.stringify(watch ? "development" : "production") },
  metafile: true,
  logLevel: "info",
};

function writeIndex(metafile) {
  const outputs = Object.keys(metafile.outputs);
  const js = outputs.find((f) => f.endsWith("app.js"));
  const css = outputs.find((f) => f.endsWith("app.css"));
  const ver = (f) => createHash("sha256").update(readFileSync(join(root, f))).digest("hex").slice(0, 10);
  const html = readFileSync(join(root, "index.html"), "utf8")
    .replace("%CSS%", css ? `/assets/app.css?v=${ver(css)}` : "")
    .replace("%JS%", `/assets/app.js?v=${ver(js)}`);
  writeFileSync(join(dist, "index.html"), html);
}

rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });
cpSync(join(root, "public"), dist, { recursive: true });

if (watch) {
  const ctx = await esbuild.context({
    ...options,
    plugins: [{ name: "index", setup(b) { b.onEnd((r) => r.metafile && writeIndex(r.metafile)); } }],
  });
  await ctx.watch();
} else {
  const result = await esbuild.build(options);
  writeIndex(result.metafile);
}
