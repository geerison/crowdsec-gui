#!/usr/bin/env bash
set -euo pipefail
exec /usr/bin/docker exec crowdsec cscli alerts list -o json
