#!/bin/bash
# Run the test suite, print failures only, hard-cap the output at 60 lines.
#
# Why: a total failure (a broken fixture or migration) makes pytest print ~3,300 lines
# / 200 KB by default. This keeps the worst case under 5 KB without hiding which tests
# failed. A clean run prints the usual short summary.
#
# Usage:
#   scripts/test_summary.sh                    # whole suite
#   scripts/test_summary.sh tests/test_rules.py
#
# pipefail keeps pytest's exit code, so this stays usable as a gate.
set -o pipefail

if [ "$#" -eq 0 ]; then
    set -- tests/
fi

poetry run pytest "$@" -q --tb=short 2>&1 | tail -60
