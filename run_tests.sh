#!/usr/bin/env bash
# Run unit tests + coverage for the Autonoma Sublime plugin.
# Fails if coverage falls below 80%.

set -euo pipefail

cd "$(dirname "$0")"

if ! command -v coverage >/dev/null 2>&1; then
    echo "coverage.py not found — running tests without coverage gate."
    python3 -m unittest discover -s tests -v
    exit $?
fi

coverage erase
coverage run --source=a6s_client,a6s_commands,a6s_ui,Autonoma -m unittest discover -s tests -v
coverage report -m --fail-under=80
