#!/bin/bash
set -euo pipefail

source /module/venv/bin/activate
chmod +x /workspace/python/build_modules.sh
/workspace/python/build_modules.sh
