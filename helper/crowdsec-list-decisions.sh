#!/usr/bin/env bash
set -euo pipefail
exec /usr/bin/docker exec crowdsec cscli decisions list -o json
