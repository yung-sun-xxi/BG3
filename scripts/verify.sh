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
EXPECT='персонажей=4 надето=52 снаряжения_в_пуле=56 не_проверено=3 заклинаний=95/28/293/30 подготовлено=61/28/92/30 черт=2/2/2/2'
fail=0

echo "== unit tests =="
for t in tests/test_blob.py tests/test_party.py tests/test_gear.py; do
    "$PY" "$t" 2>&1 | grep -v ResourceWarning
    [ "${PIPESTATUS[0]}" -eq 0 ] || fail=1
done

echo
echo "== integration: real save =="
if [ ! -f "$SAVES/extracted/Globals.lsf" ] && [ ! -f "$SAVES/Globals.lsf" ]; then
    echo "SKIPPED: no Globals.lsf under $SAVES (saves are never committed)"
else
    got=$("$PY" src/read_save.py "$SAVES" 2>&1 | tail -1)
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
