#!/usr/bin/env bash
# Build and serve the Vue blog for Tailscale at http://127.0.0.1:4174/dsm-ae-blog/
set -euo pipefail
cd "$(dirname "$0")/.."
npm run build
exec npm run preview
