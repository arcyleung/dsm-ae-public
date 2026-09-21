#!/usr/bin/env bash
# Publish the Vue blog publicly via Tailscale Funnel.
#
# The production preview must already be listening on 127.0.0.1:4174
# (web/scripts/preview.sh). Needs operator rights once:
#   sudo tailscale set --operator="$USER"
# Then this script, or without operator:
#   sudo bash web/scripts/tailscale-serve.sh
#
# WHY A DEDICATED PORT, NOT :443
#
# Funnel is enabled per host:port, not per path. `tailscale funnel` on the
# default :443 would make every path already mounted there public, and this
# host currently has twelve, including:
#
#     /mongo, /mongodb  ->  127.0.0.1:27017   (MongoDB)
#     /netcat           ->  127.0.0.1:65534
#     /dsm-ae           ->  127.0.0.1:8765    (eval queue UI + its token)
#
# Exposing those to the public internet to publish a blog is not a trade worth
# making. Funnel allows exactly three ports -- 443, 8443, 10000 -- so the blog
# gets its own, serving a single path and nothing else. 8443 is already taken
# by another service, so this uses 10000.
#
# The tailnet-only mapping at https://<host>/dsm-ae-blog is left untouched, so
# both continue to work:
#     tailnet : https://arcyleung-ubuntu.tailb940e6.ts.net/dsm-ae-blog/
#     public  : https://arcyleung-ubuntu.tailb940e6.ts.net:10000/
set -euo pipefail

PORT="${DSM_AE_FUNNEL_PORT:-10000}"
BACKEND="http://127.0.0.1:4174"

if ! curl -fsS -o /dev/null --max-time 5 "$BACKEND/dsm-ae-blog/"; then
  echo "backend not responding at $BACKEND -- start it first:" >&2
  echo "  bash web/scripts/preview.sh" >&2
  exit 1
fi

# Funnel on a dedicated port serving one path. `--bg` persists across reboots;
# only this port is touched, so the other mappings on :443 are unaffected.
tailscale funnel --bg --https="$PORT" --yes "$BACKEND"

host="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
echo "public : https://${host}:${PORT}/"
echo "tailnet: https://${host}/dsm-ae-blog/"
echo
echo "Verify (may take a few seconds for the funnel to come up):"
echo "  curl -sI https://${host}:${PORT}/ | head -1"
