#!/usr/bin/env bash
# Build the DSM-AE blog as a static bundle and stage it into the personal site
# so it is served at https://arcyleung.com/dsm-ae/ .
#
# Why this shape: the site is a Nuxt 4 SPA (`ssr: false`, `nuxt generate`), and
# Nuxt copies `public/` into the generated output verbatim, without routing or
# transforming it. Dropping a self-contained bundle at `public/dsm-ae/`
# therefore needs NO change to nuxt.config.ts, no new route, and no new
# dependency -- the site build does not even know the blog is there.
#
# The blog is a plain Vite SPA whose runtime inputs are all under reports/, so a
# static copy is complete. Two things have to line up:
#   1. Vite `base` must be /dsm-ae/ (the dev default is /dsm-ae-blog/), or every
#      asset URL 404s once the page is served from the new prefix.
#   2. Everything the app fetches from reports/ must be copied in. In dev a Vite
#      middleware (web/vite.config.ts, "serve-reports") serves that whole tree
#      off disk; in a static build the middleware does not exist, so anything
#      not copied here 404s. Two inputs fetch at runtime:
#        - reports/matrix/vue-data.json        (useMatrix.ts) -> the matrix
#        - reports/blog/trajectories/          (TrajectoryViewer.vue) -> viewer
#      Miss the first and the page renders its shell without the matrix; miss
#      the second and the Trajectories tab reports "trajectories not available".
#
# Usage:
#   scripts/deploy_blog_to_site.sh            # build + stage, leaves git to you
#   scripts/deploy_blog_to_site.sh --check    # verify a previous stage, no build
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE="${DSM_AE_SITE_DIR:-$HOME/Projects/arcyleung.github.io}"
BASE_PATH="/dsm-ae/"
DEST="$SITE/public/dsm-ae"

red()  { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
grn()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }

[ -d "$SITE" ] || { red "site not found: $SITE (set DSM_AE_SITE_DIR)"; exit 1; }
[ -d "$SITE/public" ] || { red "no public/ in $SITE -- is this the Nuxt site?"; exit 1; }

check() {
  local fail=0
  [ -f "$DEST/index.html" ] || { red "missing $DEST/index.html"; fail=1; }
  [ -f "$DEST/reports/matrix/vue-data.json" ] || { red "missing vue-data.json"; fail=1; }
  # Trajectory viewer: the index must be present AND every .jsonl it names must
  # have been copied, or the tab loads and then fails on a per-session fetch.
  local idx="$DEST/reports/blog/trajectories/index.json"
  if [ ! -f "$idx" ]; then
    red "missing reports/blog/trajectories/index.json"; fail=1
  else
    while read -r f; do
      [ -f "$DEST/reports/blog/trajectories/$f" ] || { red "trajectory missing: $f"; fail=1; }
    done < <(grep -oE '"file"[[:space:]]*:[[:space:]]*"[^"]+"' "$idx" | sed -E 's/.*"([^"]+)"$/\1/')
  fi
  # every asset URL must carry the /dsm-ae/ prefix, or it breaks once deployed
  if grep -qoE '(src|href)="/(assets|dsm-ae-blog)/' "$DEST/index.html" 2>/dev/null; then
    red "index.html references the wrong base path (expected ${BASE_PATH})"
    fail=1
  fi
  local n
  n=$(grep -oE 'href="/dsm-ae/assets/[^"]+"|src="/dsm-ae/assets/[^"]+"' "$DEST/index.html" | wc -l)
  [ "$n" -gt 0 ] || { red "index.html has no /dsm-ae/assets references"; fail=1; }
  # referenced assets must actually exist
  while read -r a; do
    [ -f "$DEST/${a#/dsm-ae/}" ] || { red "referenced asset missing: $a"; fail=1; }
  done < <(grep -oE '/dsm-ae/assets/[^"]+' "$DEST/index.html" | sort -u)
  return $fail
}

if [ "${1:-}" = "--check" ]; then
  check && grn "staged bundle looks correct" || exit 1
  exit 0
fi

info "building blog with base=${BASE_PATH}"
( cd "$REPO/web" && npx vite build --base="$BASE_PATH" --outDir dist-site --emptyOutDir >/dev/null )

info "staging into $DEST"
rm -rf "$DEST"
mkdir -p "$DEST/reports/matrix"
cp -r "$REPO/web/dist-site/." "$DEST/"
cp "$REPO/reports/matrix/vue-data.json" "$DEST/reports/matrix/vue-data.json"
# Trajectory viewer payload: index.json plus the .jsonl it names.
mkdir -p "$DEST/reports/blog/trajectories"
cp -r "$REPO/reports/blog/trajectories/." "$DEST/reports/blog/trajectories/"
rm -rf "$REPO/web/dist-site"

check || { red "staged bundle failed verification"; exit 1; }

grn "staged $(du -sh "$DEST" | cut -f1) at $DEST"
cat <<EOF

Next steps (in $SITE):

  git add public/dsm-ae
  git commit -m "Add DSM-AE blog at /dsm-ae"
  git push

No change to nuxt.config.ts or any route is needed -- Nuxt copies public/
through untouched. Verify locally first with:

  cd $SITE && npm run generate && npx serve .output/public
  # then open http://localhost:3000/dsm-ae/
EOF
