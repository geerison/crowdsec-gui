#!/usr/bin/env bash
set -euo pipefail

# Read IP from stdin (passed by the helper service, never from command-line args).
read -r IP

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/crowdsec-ip-validation.sh"

if ! IP="$(normalize_ip "$IP")"; then
  echo "ERROR: invalid IP address" >&2
  exit 1
fi

exec /usr/bin/docker exec crowdsec cscli decisions delete --ip "$IP"
