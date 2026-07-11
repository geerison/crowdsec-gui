#!/usr/bin/env bash
set -euo pipefail

IP="${1:-}"

# Validate: only allow IPv4, IPv6, and CIDR notation
if [[ ! "$IP" =~ ^[0-9a-fA-F.:/]+$ ]]; then
  echo "ERROR: invalid IP address: $IP" >&2
  exit 1
fi

# Additional strict check: must match IPv4 or IPv6 pattern
if [[ ! "$IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?$ ]] && \
   [[ ! "$IP" =~ ^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}(/[0-9]{1,3})?$ ]]; then
  echo "ERROR: invalid IP address: $IP" >&2
  exit 1
fi

exec /usr/bin/docker exec crowdsec cscli decisions delete --ip "$IP"
