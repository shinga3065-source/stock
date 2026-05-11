#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p .tmp reports/us_low_price_volume

PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "$PYTHON_BIN" tools/daily_us_stock_report.py --limit 20 --news-days 5
