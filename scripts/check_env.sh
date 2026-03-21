#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -f "${SKILL_ROOT}/project/main.py" ]]; then
  PROJECT_DIR="${SKILL_ROOT}/project"
elif [[ -f "${SKILL_ROOT}/main.py" ]]; then
  PROJECT_DIR="${SKILL_ROOT}"
else
  echo "Could not locate project directory from ${SKILL_ROOT}" >&2
  exit 1
fi

ENV_FILE="${PROJECT_DIR}/.env"
VENV_PYTHON="${SKILL_ROOT}/.venv/bin/python"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing environment file: ${ENV_FILE}" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

required_vars=(
  TAVILY_API_KEY
  R2_ACCOUNT_ID
  R2_ACCESS_KEY_ID
  R2_SECRET_ACCESS_KEY
  R2_PUBLIC_URL
)

missing=0
for var_name in "${required_vars[@]}"; do
  if ! grep -Eq "^${var_name}=.+" "${ENV_FILE}"; then
    echo "Missing required variable in .env: ${var_name}" >&2
    missing=1
  fi
done

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "Missing virtualenv Python: ${VENV_PYTHON}" >&2
  missing=1
fi

if [[ ${missing} -ne 0 ]]; then
  exit 1
fi

cd "${PROJECT_DIR}"

"${VENV_PYTHON}" - <<'PY'
from pathlib import Path
from src.config_loader import load_config
cfg = load_config(Path("config.yaml"))
print(f"config_ok model={cfg['openclaw']['model']}")
PY

"${VENV_PYTHON}" - <<'PY'
import os
from pathlib import Path
required = [
    "edge_tts",
    "requests",
    "readability",
    "lxml",
    "boto3",
    "feedgen",
    "yaml",
    "httpx",
    "tenacity",
    "mutagen",
    "dotenv",
]
for name in required:
    __import__(name)
print("python_imports_ok")
PY

gateway_url="$("${VENV_PYTHON}" - <<'PY'
from pathlib import Path
from src.config_loader import load_config
cfg = load_config(Path("config.yaml"))
print(cfg["openclaw"]["gateway_url"].rstrip("/"))
PY
)"

auth_header=()
if grep -Eq '^OPENCLAW_GATEWAY_TOKEN=.+' "${ENV_FILE}"; then
  token="${OPENCLAW_GATEWAY_TOKEN:-}"
  auth_header=(-H "Authorization: Bearer ${token}")
fi

status="$(curl -sS -o /dev/null -w "%{http_code}" "${auth_header[@]}" \
  -H "Content-Type: application/json" \
  -d '{"model":"openclaw","messages":[{"role":"user","content":"ping"}]}' \
  "${gateway_url}/v1/chat/completions" || true)"

if [[ "${status}" != "200" && "${status}" != "400" && "${status}" != "401" ]]; then
  echo "OpenClaw gateway check failed with status ${status:-unknown}" >&2
  exit 1
fi

mkdir -p "${PROJECT_DIR}/output"
echo "gateway_check_status=${status}"
echo "env_check_ok"
