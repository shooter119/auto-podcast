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

VENV_PYTHON="${SKILL_ROOT}/.venv/bin/python"
if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "Virtual environment not found: ${VENV_PYTHON}" >&2
  echo "Create it with: python3 -m venv ${SKILL_ROOT}/.venv && ${SKILL_ROOT}/.venv/bin/pip install -r ${PROJECT_DIR}/requirements.txt" >&2
  exit 1
fi

cd "${PROJECT_DIR}"
exec "${VENV_PYTHON}" main.py "$@"
