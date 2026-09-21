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

## New save, in three steps

1. Steam Cloud, `store.steampowered.com/account/remotestorage`, Baldur's Gate 3
   (appid 1086940). The list is paged, 50 rows a page, with no page links:
   `remotestorageapp/?appid=1086940&index=0`, `&index=50`, `&index=100`.
   Take the newest `.lsv` by date; its "Download" link points at
   `cdn.steamusercontent.com/filedownload/<id>` and needs no login.
2. ```
   scripts/update_party.sh path/to/QuickSave_430.lsv
   ```
   moves the file under `.agent/saves/<name>/`, reads it, and copies the three
   reports into `current/`.
3. `git diff current/` is the change since the last save: level, class, feats,
   what is worn, what the pool gained.

`current/` is committed, so the `bg3` skill always reads the same three files
and the history of the party's builds is the history of that directory. The
`.lsv` itself is never committed.

## Reading a save by hand

```
python src/read_save.py path/to/QuickSave_418.lsv
```

A `.lsv` is unpacked next to itself; a directory that already holds `Globals.lsf`
(loose, or under `extracted/`) is read as it is. With no argument the script
falls back to `BG3_SAVE_DIR`, then to `.agent/saves`. Output goes to
`BG3_OUT_DIR` or beside the save:

| file | what it is |
|---|---|
| `party.md` | the build: class, feats, abilities, every slot, prepared spells, the whole book, what was picked at each level (spells, cantrips, metamagic, swaps), and the spell save DC with its terms |
| `party.json` | the same, for a skill to read |
| `pool.md` | the gear the party carries and nobody wears, by slot family |
| `items_all.csv` | one row per item, with its slot when it is worn |

The ECS blob is not a separate file: it is one ScratchBuffer attribute named
`NewAge` inside `Globals.lsf`, and the reader pulls it out itself. Saves come out
of Steam Cloud (`store.steampowered.com/account/remotestorage`).

## What counts as gear

The save does not say whether an item can be worn: there is no component for
it, and a bag item carries nothing but its stat id. So the answer is a table,
`src/gear.csv`, one row per stat id with `gear` = `yes`, `no` or `?`, and the
reader grows it on every save:

- worn in a combat slot by anyone in the save, party or not, is proof: `yes`;
- a stat id whose prefix (`WPN_`, `ARM_`, `MAG_`, `UNI_`) and last word
  (`_Gloves`, `_Amulet`, `_Longsword`) both say gear is taken as `yes`;
- only one of the two, and nobody seen wearing it, is a `?` for the owner to
  settle once — they are listed at the end of `pool.md`;
- a `yes` or `no` written by hand is never overwritten.

Potions, scrolls, food, quest objects, camp clothes and underwear are not gear
and never appear in the pool. A row's `source` says how it got there.

## Layout

| path | what it is |
|---|---|
| `src/lspk.py` | unpacks `.lsv` (LSPK v18, zstd) |
| `src/lsf.py` | reads LSF v7 and lifts a ScratchBuffer out of it |
| `src/blob.py` | the `NewAge` ECS blob (magic `LSMF`): components, entities, pointers |
| `src/party.py` | the game side: party, slots, spells, shared pool |
| `src/read_save.py` | the driver and the reports |
| `src/gear.py` | what counts as gear, and how `gear.csv` grows |
| `src/gear.csv` | every stat id ever seen as gear, with the evidence |
| `src/names.csv` | stat id to English and Russian name |
| `scripts/update_party.sh` | one save in, `current/` out |
| `current/` | the party as of the last save: `party.md`, `party.json`, `pool.md` |
| `tests/fixture.py` | builds a miniature LSMF blob with a known layout |
| `tests/test_blob.py` | pins the reader against that blob |
| `tests/test_party.py` | pins the GUID text form and the name tables |
| `tests/test_gear.py` | pins the gear rules and the promise that hand-written rows stay |

## Two numbers that change from save to save

Every record in the blob's component index carries one u32 at offset 12, and
every string record in `display_names` and `SpellBookPrepares` carries one
flag. Both are the same across a save and different between saves:
QuickSave_418 has `0x6b` and 514, QuickSave_430 has `0xa3` and 675. Neither is
hard-coded any more; both are read off the file. When a new save fails, check
these two before suspecting a layout.

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
