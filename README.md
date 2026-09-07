# BG3 save reader

Reads a Baldur's Gate 3 save and answers who in the party is carrying what, and
what each of them is actually wearing. The point is to feed the `bg3` skill from
the save file instead of from a screen recording.

## Build and test

```
./scripts/verify.sh
```

That is the whole recipe; nothing else in the repository repeats it. It runs the
unit tests always, and the real extraction only when a save is present.

## Layout

| path | what it is |
|---|---|
| `src/lspk.py` | unpacks `.lsv` (LSPK v18, zstd) |
| `src/lsf.py` | reads LSF v7 (`Globals.lsf`, `SaveInfo.json` neighbours) |
| `src/blob.py` | reads the `NewAge` ECS blob (magic `LSMF`) |
| `src/extract_items.py` | per-character inventory, worn versus stowed |
| `src/names.csv` | stat id to English and Russian name, 1221 rows |
| `tests/fixture.py` | builds a miniature LSMF blob with a known layout |
| `tests/test_blob.py` | pins the reader against that blob |

## Saves are not in the repository

A save is 13 MB and is replaced every time the game is played, so committing one
would grow the history without ever testing anything: it would only prove the
reader still returns yesterday's answer, not that the answer is right.

The unit tests use a generated blob instead. Its layout is planted by
`tests/fixture.py`, so a test can check what came back against what went in, and
the cases are the mistakes actually made while reversing the format - an element
of skew, a mis-sized entity table, an index array claimed by the wrong
component.

To run the integration stage, put a save's extracted files where the script
looks:

```
BG3_SAVE_DIR=/path/to/saves ./scripts/verify.sh
```

That directory needs `newage.bin` and an `extracted/` holding `Globals.lsf` and
`SaveInfo.json`. Saves come out of Steam Cloud
(`store.steampowered.com/account/remotestorage`); `src/lspk.py` unpacks the
`.lsv`.

## What the reader can and cannot do

Owner and worn-versus-stowed are read out of the ECS blob, not guessed from
distance. Known gaps, with the evidence for each, are in `.agent/findings.md`,
which is not committed. The short version: the equipment slot number (helmet,
ring 1, ring 2) has not been located, spells are not where `LearnedSpells`
suggests, and four of the thirty-six index-array segments are placed by a guess
that `Blob.ambiguous` now reports instead of hiding.
