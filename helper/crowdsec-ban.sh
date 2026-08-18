#!/usr/bin/env bash
set -euo pipefail

# Read IP and the duration preset from stdin (never from command-line args).
read -r IP
read -r DURATION

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/crowdsec-ip-validation.sh"

if ! IP="$(normalize_ip "$IP")"; then
  echo "ERROR: invalid IP address" >&2
  exit 1
fi

case "$DURATION" in
  15m|4h|24h|168h) ;;
  *)
    echo "ERROR: invalid ban duration" >&2
    exit 1
    ;;
esac

# The duration comes from a fixed allowlist; the UI cannot provide CLI arguments.
exec /usr/bin/docker exec crowdsec cscli decisions add \
  --ip "$IP" \
  --duration "$DURATION" \
  --type ban \
  --reason manual_gui
