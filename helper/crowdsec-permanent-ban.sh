#!/usr/bin/env bash
set -euo pipefail

# Read IP from stdin (passed by the helper service, never from command-line args).
read -r IP

# Validate: only allow IPv4, IPv6, and CIDR notation.
if [[ ! "$IP" =~ ^[0-9a-fA-F.:/]+$ ]]; then
  echo "ERROR: invalid IP address" >&2
  exit 1
fi

# Additional strict check: must match IPv4 or IPv6 pattern.
if [[ ! "$IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?$ ]] && \
    [[ ! "$IP" =~ ^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}(/[0-9]{1,3})?$ ]]; then
  echo "ERROR: invalid IP address" >&2
  exit 1
fi

# CrowdSec decisions require an expiry. This 100-year horizon is effectively
# permanent while remaining explicitly reversible through the Unban control.
exec /usr/bin/docker exec crowdsec cscli decisions add \
  --ip "$IP" \
  --duration 876000h \
  --type ban \
  --reason manual_gui_permanent
