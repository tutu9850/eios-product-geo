#!/usr/bin/env bash
# GEO 回归体检包装：cd ~/eios-geo && bash scripts/geo_regression.sh [--live] [--unit] ...
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec .venv/bin/python scripts/geo_regression.py "$@"
