# DSM-AE Vue blog

Vite + Vue 3. Serves `docs/blog_post.md` and reloads when that file changes.

Local editing:

```bash
cd web
npm install
python3 scripts/extract_matrix_data.py   # refresh reports/matrix/vue-data.json
npm run dev
```

Open http://127.0.0.1:5174/dsm-ae-blog/ for editing (Vite live reload).

Detached preview (survives the CLI session; no hot-reload):

```bash
bash web/scripts/serve.sh          # build + setsid on :4174
bash web/scripts/serve.sh status
bash web/scripts/serve.sh stop
```

Foreground snapshot: `npm run build && npm run preview` (or `bash web/scripts/preview.sh`).

Tailscale / Funnel (`/dsm-ae-blog` on this machine):

```bash
bash web/scripts/serve.sh
sudo tailscale serve --bg --https=443 --yes --set-path=/dsm-ae-blog http://127.0.0.1:4174
```

Or, after `sudo tailscale set --operator="$USER"`, run `bash web/scripts/tailscale-serve.sh`.

Public URL: https://arcyleung-ubuntu.tailb940e6.ts.net/dsm-ae-blog/

- **Blog**: markdown, mermaid pipelines, trajectory viewer at §1.5 / Appendix A
- **Matrix**: Vue sections: syndrome matrix, decision trees, metric results
- **Trajectories**: `TrajectoryViewer` over `reports/blog/trajectories/`

Refresh matrix JSON after regenerating `reports/dsm-ae-matrix.html`. Rebuild the preview after editing the markdown.
