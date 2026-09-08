# BG3 save reader

Reads a Baldur's Gate 3 save and answers what each party member is actually
built out of: class and subclass, level, the feats taken at each level up,
abilities, every equipment slot with the item in it, and the whole spell
book. The point is to feed the `bg3` skill from the save file instead of from
a screen recording.

Anything nobody is wearing goes into one shared pool. Which member's bag it sits
in is not reported, because in play the party's bags are one pot; the only
ownership that changes a decision is what is on someone.

## Build and test

```
./scripts/verify.sh
```

That is the whole recipe; nothing else in the repository repeats it. It runs the
unit tests always, and the real extraction only when a save is present.

## Reading a save

```
python src/read_save.py path/to/QuickSave_418.lsv
```

A `.lsv` is unpacked next to itself; a directory that already holds `Globals.lsf`
(loose, or under `extracted/`) is read as it is. With no argument the script
falls back to `BG3_SAVE_DIR`, then to `.agent/saves`. Output goes to
`BG3_OUT_DIR` or beside the save:

| file | what it is |
|---|---|
| `party.md` | the build: class, feats, abilities, every slot, prepared spells, the whole book |
| `party.json` | the same, for a skill to read |
| `pool.md` | everything the party carries and nobody wears |
| `items_all.csv` | one row per item, with its slot when it is worn |

The ECS blob is not a separate file: it is one ScratchBuffer attribute named
`NewAge` inside `Globals.lsf`, and the reader pulls it out itself. Saves come out
of Steam Cloud (`store.steampowered.com/account/remotestorage`).

## Layout

| path | what it is |
|---|---|
| `src/lspk.py` | unpacks `.lsv` (LSPK v18, zstd) |
| `src/lsf.py` | reads LSF v7 and lifts a ScratchBuffer out of it |
| `src/blob.py` | the `NewAge` ECS blob (magic `LSMF`): components, entities, pointers |
| `src/party.py` | the game side: party, slots, spells, shared pool |
| `src/read_save.py` | the driver and the reports |
| `src/names.csv` | stat id to English and Russian name |
| `tests/fixture.py` | builds a miniature LSMF blob with a known layout |
| `tests/test_blob.py` | pins the reader against that blob |
| `tests/test_party.py` | pins the GUID text form and the name tables |

## Two things the save does not say

**Abilities are the final numbers, gear included.** `StatsComponent` holds one
value per ability with every equipped bonus already in it, and the character's
base score is nowhere in the file. Karlach reads DEX 18 while wearing Gloves of
Dexterity, which *set* Dexterity to 18: her base is 8, and nothing in the save
says so. Read a base score off the character sheet in game, not from here.

**A feat is stored as a GUID, not as a name.** The names come from the tables in
`src/party.py`, lifted from BG3-Community-Library. A GUID with no entry there
is reported as `guid:` plus its first eight hex characters, which means the
table needs a line, not that the save is unreadable.

## Saves are not in the repository

A save is 13 MB and is replaced every time the game is played, so committing one
would grow the history without ever testing anything: it would only prove the
reader still returns yesterday's answer, not that the answer is right.

The unit tests use a generated blob instead. Its layout is planted by
`tests/fixture.py`, so a test can check what came back against what went in, and
the cases are the mistakes actually made while reversing the format - an element
of skew, a mis-sized entity table, an index array claimed by the wrong
component, a pointer read without its bias.

## What the reader can and cannot do

Party, class, level, slots, the spell book and the prepared list are read out
of the blob. `Globals.lsf` supplies exactly two things: an item's stat id, which
the blob never spells out, and the coordinates that tie a character to their
`SaveInfo.json` record, which is where the race label comes from. Without
`SaveInfo.json` everything still comes out, with the race column blank.

Classes are GUIDs in the blob; eleven of the twelve are named in `src/party.py`
(Bard has not been seen in a save yet) and an unknown one is printed as its
first eight hex characters rather than dropped. Subclass names are known only
for the four this save carries.

Known gaps, with the evidence for each, are in `.agent/findings.md`, which is not
committed. The short version: the mods' items have no names anywhere; the
subclass table is four entries long; and four of the thirty-six index-array
segments are placed by a guess that `Blob.ambiguous` reports instead of hiding.
