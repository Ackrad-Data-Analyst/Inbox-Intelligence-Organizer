#!/usr/bin/env bash
set -euo pipefail

if [[ ! -x .venv/bin/python ]]; then
  echo "Virtual environment missing. Run: bash setup.sh"
  exit 1
fi

.venv/bin/python -m streamlit run app.py
