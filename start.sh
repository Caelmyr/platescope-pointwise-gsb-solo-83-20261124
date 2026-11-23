#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ "${1:-}" == "stop" ]]; then
  exec docker compose down
fi
docker compose up -d --build --wait
printf 'PlateScope http://127.0.0.1:%s/\n' "${PLATESCOPE_PORT:-19886}"
