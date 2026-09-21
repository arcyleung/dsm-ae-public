import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vue from "@vitejs/plugin-vue";
import type { Plugin } from "vite";
import { defineConfig } from "vite";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)));
const repo = path.resolve(root, "..");
const blogMd = path.resolve(repo, "docs/blog_post.md");
const VIRTUAL = "virtual:blog.md";
const PUBLIC_BASE = "/dsm-ae-blog/";

function reportsMiddleware(reports: string) {
  return (req: { url?: string }, res: any, next: () => void) => {
    const rel = decodeURIComponent((req.url || "/").split("?")[0]);
    const abs = path.resolve(reports, "." + rel);
    if (abs !== reports && !abs.startsWith(reports + path.sep)) {
      res.statusCode = 403;
      res.end("forbidden");
      return;
    }
    fs.stat(abs, (err, st) => {
      if (err) {
        next();
        return;
      }
      const file = st.isDirectory() ? path.join(abs, "index.html") : abs;
      fs.readFile(file, (e2: NodeJS.ErrnoException | null, data: Buffer) => {
        if (e2) {
          next();
          return;
        }
        const ext = path.extname(file);
        const types: Record<string, string> = {
          ".html": "text/html; charset=utf-8",
          ".json": "application/json; charset=utf-8",
          ".jsonl": "application/jsonl; charset=utf-8",
          ".css": "text/css; charset=utf-8",
          ".js": "text/javascript; charset=utf-8",
          ".md": "text/markdown; charset=utf-8",
        };
        res.setHeader("Content-Type", types[ext] || "application/octet-stream");
        res.end(data);
      });
    });
  };
}

function serveReports(): Plugin {
  const reports = path.resolve(repo, "reports");
  const mount = (server: { middlewares: { use: Function } }) => {
    const handler = reportsMiddleware(reports);
    server.middlewares.use("/reports", handler);
    server.middlewares.use(`${PUBLIC_BASE}reports`, handler);
  };
  return {
    name: "serve-reports",
    configureServer: mount,
    configurePreviewServer: mount,
  };
}

/** Tailscale Serve --set-path strips /dsm-ae-blog before proxying. Accept both. */
function rewriteStrippedPrefix(): Plugin {
  const prefix = PUBLIC_BASE.replace(/\/$/, "");
  const rewrite = (req: { url?: string }) => {
    const raw = req.url || "/";
    const q = raw.indexOf("?");
    const pathname = q >= 0 ? raw.slice(0, q) : raw;
    if (pathname === prefix || pathname.startsWith(prefix + "/")) return;
    const search = q >= 0 ? raw.slice(q) : "";
    req.url = prefix + (pathname.startsWith("/") ? pathname : `/${pathname}`) + search;
  };
  const mount = (server: { middlewares: { use: Function } }) => {
    server.middlewares.use((req: { url?: string }, _res: unknown, next: () => void) => {
      rewrite(req);
      next();
    });
  };
  return {
    name: "rewrite-stripped-blog-prefix",
    configureServer: mount,
    configurePreviewServer: mount,
  };
}

function watchBlogMarkdown(): Plugin {
  const absBlog = path.resolve(blogMd);
  return {
    name: "watch-blog-md",
    configureServer(server) {
      server.watcher.add(absBlog);
      server.watcher.add(path.dirname(absBlog));
    },
    resolveId(id) {
      if (id === VIRTUAL) return "\0" + VIRTUAL;
    },
    load(id) {
      if (id === "\0" + VIRTUAL) {
        const text = fs.existsSync(absBlog) ? fs.readFileSync(absBlog, "utf8") : "";
        return `export default ${JSON.stringify(text)}`;
      }
    },
    handleHotUpdate({ file, server }) {
      if (path.resolve(file) !== absBlog) return;
      const mod = server.moduleGraph.getModuleById("\0" + VIRTUAL);
      if (mod) server.moduleGraph.invalidateModule(mod);
      server.ws.send({ type: "full-reload" });
      return [];
    },
  };
}

export default defineConfig({
  root,
  base: PUBLIC_BASE,
  plugins: [rewriteStrippedPrefix(), vue(), watchBlogMarkdown(), serveReports()],
  resolve: {
    alias: { "@": path.join(root, "src") },
  },
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    allowedHosts: true,
    fs: { allow: [repo] },
    watch: { ignored: ["**/reports/**", "**/node_modules/**"] },
    hmr: { overlay: true },
  },
  preview: {
    host: "127.0.0.1",
    port: 4174,
    strictPort: true,
    allowedHosts: true,
  },
});
