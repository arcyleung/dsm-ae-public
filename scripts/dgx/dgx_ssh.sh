#!/usr/bin/env bash
# Password-auth SSH wrapper for the DGX box. Reads host/user/port/pass from dgx.yaml
# (gitignored) via askpass.sh so the password never appears in argv, env dumps or logs.
#
# Usage:
#   scripts/dgx/dgx_ssh.sh 'remote command ...'
#   scripts/dgx/dgx_ssh.sh -- -N -L 8080:localhost:8080     # raw ssh args
#   DGX_SCP=1 scripts/dgx/dgx_ssh.sh <local> <remote>       # scp upload
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CRED="${DGX_CRED_FILE:-$REPO_ROOT/dgx.yaml}"

field() { awk -v k="$1" '/^bmc_dgx:/{f=1;next} f && /^[^[:space:]]/{f=0} f && $1==k":"{print $2;exit}' "$CRED"; }
DGX_USER="$(field user)"; DGX_IP="$(field ip)"; DGX_PORT="$(field port)"

export SSH_ASKPASS="$REPO_ROOT/scripts/dgx/askpass.sh"
export SSH_ASKPASS_REQUIRE=force
export DGX_CRED_FILE="$CRED"

# Multiplex over a single authenticated connection: the DGX sshd throttles
# concurrent password logins, so re-auth per command causes hangs.
CTL="${DGX_CTL_PATH:-$HOME/.ssh/dgx-ctl-%C}"
COMMON_OPTS=(
  -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile="$HOME/.ssh/known_hosts"
  -o PreferredAuthentications=password
  -o PubkeyAuthentication=no
  -o NumberOfPasswordPrompts=1
  -o ConnectTimeout=25
  -o ServerAliveInterval=30
  -o ControlMaster=auto
  -o ControlPath="$CTL"
  -o ControlPersist=10m
)

if [[ "${DGX_SCP:-0}" == "1" ]]; then
  exec setsid -w scp "${COMMON_OPTS[@]}" -P "$DGX_PORT" "$1" "${DGX_USER}@${DGX_IP}:$2"
fi

if [[ "${1:-}" == "--" ]]; then
  shift
  exec setsid -w ssh "${COMMON_OPTS[@]}" -p "$DGX_PORT" "$@" "${DGX_USER}@${DGX_IP}"
fi

exec setsid -w ssh "${COMMON_OPTS[@]}" -p "$DGX_PORT" "${DGX_USER}@${DGX_IP}" "$@"
