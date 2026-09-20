#!/bin/bash
# 本地开发启动: cd ~/eios-geo && bash scripts/run_dev.sh
cd "$(dirname "$0")/.."
exec .venv/bin/python -m uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 3002
