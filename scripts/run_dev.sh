#!/bin/bash
# 本地开发启动: cd ~/eios-geo && bash scripts/run_dev.sh
cd "$(dirname "$0")/.."

# 本地 GEO 也必须使用 Foundation 的开发身份签发出站票。缺少这些声明时，
# 企业资料同步会被知识库正确拒绝，并在 Client 里表现成整页不可用。
FOUNDATION="${EIOS_FOUNDATION_DIR:-/Users/tutu/eios-foundation}"
export EIOS_ENVIRONMENT="${EIOS_ENVIRONMENT:-development}"
export GEO_PRODUCT_DOOR="${GEO_PRODUCT_DOOR:-on}"
export GEO_AUTH_MODE="${GEO_AUTH_MODE:-auth_context}"
export EIOS_DEPLOYMENT_ID="${EIOS_DEPLOYMENT_ID:-dep_beichen_dev}"
export EIOS_ENTERPRISE_ID="${EIOS_ENTERPRISE_ID:-enterprise_beichen}"
export EIOS_AUTH_ISSUER="${EIOS_AUTH_ISSUER:-eios-dev-issuer}"
export EIOS_AUTH_KID="${EIOS_AUTH_KID:-dev-2026-08}"
export EIOS_AUTH_PRIVATE_KEY_PATH="${EIOS_AUTH_PRIVATE_KEY_PATH:-${FOUNDATION}/.dev-secrets/auth-private.pem}"
export EIOS_AUTH_PUBLIC_KEY_PATH="${EIOS_AUTH_PUBLIC_KEY_PATH:-${FOUNDATION}/.dev-secrets/auth-public.pem}"
export EIOS_KNOWLEDGE_URL="${EIOS_KNOWLEDGE_URL:-http://127.0.0.1:8040}"
export EIOS_SEMANTIC_URL="${EIOS_SEMANTIC_URL:-http://127.0.0.1:8010}"
export EIOS_DATA_URL="${EIOS_DATA_URL:-http://127.0.0.1:8020}"
export EIOS_PDP_MODE="${EIOS_PDP_MODE:-development_allow}"
export PYTHONPATH="${FOUNDATION}:${FOUNDATION}/packages/gateways:${FOUNDATION}/packages/auth:${FOUNDATION}/packages/clients:${FOUNDATION}/packages/common:${FOUNDATION}/packages/policy:${FOUNDATION}/packages/contracts/generated/python:${PWD}"

exec .venv/bin/python -m uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 3002
