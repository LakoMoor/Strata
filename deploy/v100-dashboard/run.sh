#!/bin/sh
set -eu
DASHBOARD_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
STRATA_ROOT=${STRATA_ROOT:-/workspace/strata-v100}
exec "$STRATA_ROOT/runtime/terminal/0.1.55/python/bin/python3.12" "$DASHBOARD_DIR/server.py" \
  --config "$STRATA_ROOT/dashboard-state/engine.json" \
  --python "$STRATA_ROOT/runtime/terminal/0.1.55/python/bin/python3.12" \
  --host 0.0.0.0 --port 8000
