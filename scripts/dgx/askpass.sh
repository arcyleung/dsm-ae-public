#!/usr/bin/env bash
# SSH_ASKPASS helper: emits the DGX password read at runtime from dgx.yaml.
# The secret is NEVER stored in this file, in argv, or in any log.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
awk '/^bmc_dgx:/{f=1;next} f && /^[^[:space:]]/{f=0} f && /pass:/{sub(/^[[:space:]]*pass:[[:space:]]*/,"");print;exit}' \
  "${DGX_CRED_FILE:-$REPO_ROOT/dgx.yaml}"
