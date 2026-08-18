#!/usr/bin/env bash

normalize_ip() {
  local value="$1"

  /usr/bin/python3 - "$value" <<'PY'
import ipaddress
import sys

try:
    value = sys.argv[1]
    address = (
        ipaddress.ip_network(value, strict=False)
        if "/" in value
        else ipaddress.ip_address(value)
    )
except ValueError:
    sys.exit(1)

print(address)
PY
}
