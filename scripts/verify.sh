#!/usr/bin/env bash
# The one build-and-test recipe for this repository.  Nothing else may hold a
# copy of it: README, CI and any handoff call this script instead.
#
# Exit 0 means green.  Two stages:
#   1. unit tests against a generated blob - always run, no save needed;
#   2. the real extraction - run only when a save is present, skipped otherwise.
set -u

cd "$(dirname "$0")/.."
PY=${PY:-python3}
[ -x .agent/venv/bin/python ] && PY=.agent/venv/bin/python

SAVES=${BG3_SAVE_DIR:-.agent/saves}
EXPECT='персонажей=4 предметов_в_контейнерах=2351 у_партии=549 надето=52'
fail=0

echo "== unit tests =="
"$PY" tests/test_blob.py 2>&1 | grep -v ResourceWarning
[ "${PIPESTATUS[0]}" -eq 0 ] || fail=1

echo
echo "== integration: real save =="
if [ ! -f "$SAVES/newage.bin" ]; then
    echo "SKIPPED: no $SAVES/newage.bin (saves are never committed)"
else
    got=$("$PY" src/extract_items.py 2>&1 | tail -1)
    echo "$got"
    if [ "$got" = "$EXPECT" ]; then
        echo "control line matches"
    else
        echo "MISMATCH, expected: $EXPECT"
        fail=1
    fi
fi

echo
[ "$fail" -eq 0 ] && echo "VERIFY OK" || echo "VERIFY FAILED"
exit "$fail"
