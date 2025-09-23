#!/usr/bin/env bash
# Usage:
#   ./setup-python-env.sh                  # use system default python3
#   ./setup-python-env.sh /usr/bin/python3.11   # use supplied python path

set -euo pipefail

# 1) pick interpreter: first argument if given, else "python3" from PATH
PY_BIN="${1:-python3}"

# 2) create virtualenv
"$PY_BIN" -m venv .venv

# 3) activate it
# shellcheck disable=SC1091
source .venv/bin/activate

# 4) upgrade pip + install requirements
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt