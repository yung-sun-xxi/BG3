#!/usr/bin/env bash
# Turn one save into the party's current build.
#
#   scripts/update_party.sh path/to/QuickSave_430.lsv
#
# The .lsv is moved under .agent/saves/<name>/ (never committed), read with
# src/read_save.py, and the three reports that matter - party.md, party.json,
# pool.md - are copied into current/, which is committed.  `git diff current/`
# then shows what changed since the last save: level, class, feats, what is
# worn, what the pool gained.  Getting the .lsv out of Steam Cloud is a browser
# step and lives in the bg3 skill, not here.
set -eu

cd "$(dirname "$0")/.."
PY=${PY:-python3}
[ -x .agent/venv/bin/python ] && PY=.agent/venv/bin/python

lsv=${1:?usage: scripts/update_party.sh <save.lsv>}
[ -f "$lsv" ] || { echo "no such file: $lsv" >&2; exit 1; }

name=$(basename "$lsv" .lsv)
dir=.agent/saves/$name
mkdir -p "$dir"
[ "$(cd "$(dirname "$lsv")" && pwd)/$(basename "$lsv")" = "$(pwd)/$dir/$name.lsv" ] \
    || mv "$lsv" "$dir/$name.lsv"

"$PY" src/read_save.py "$dir/$name.lsv" | tail -2

mkdir -p current
cp "$dir/party.md" "$dir/party.json" "$dir/pool.md" current/
echo
echo "== current/ against the last committed save =="
git --no-pager diff --stat -- current/ src/gear.csv
