"""Read a save and write everything a build discussion needs.

    python src/read_save.py [save]

`save` is either a `.lsv` straight out of Steam Cloud, which is unpacked next to
itself, or a directory that already holds `Globals.lsf` (loose or under
`extracted/`).  With no argument it falls back to `BG3_SAVE_DIR`, and then to
`.agent/saves`.

Four files come out, into `BG3_OUT_DIR` or beside the save:

    party.md      the build: abilities, every equipment slot, spells
    party.json    the same, for the bg3 skill to read instead of a screenshot
    pool.md       everything the party carries and nobody wears
    items_all.csv one row per item, with its slot when it is worn

Who carries an unworn item is deliberately not reported.  In play the party's
bags are one pot, so the only ownership that matters is what is on someone.
"""

import collections
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lspk
import party

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.environ.get('BG3_SAVE_DIR', os.path.join(HERE, '..', '.agent', 'saves'))

GROUPS = [('Магические (MAG_)', 'MAG_'), ('Уникальные (UNI_)', 'UNI_'),
          ('Оружие (WPN_)', 'WPN_'), ('Броня (ARM_)', 'ARM_')]

NAMES = {}
with open(os.path.join(HERE, 'names.csv')) as fh:
    for r in csv.DictReader(fh):
        NAMES[r['stats']] = (r['en'], r['ru'])


def name_of(sid):
    """Русское (English) when known, English alone, else the raw stat id."""
    if not sid:
        return '—'
    en, ru = NAMES.get(sid, ('', ''))
    if ru and en:
        return '%s (%s)' % (ru, en)
    return en or '`%s`' % sid


def open_save(path):
    """A Save from a .lsv or from a directory, unpacking the .lsv if need be."""
    if os.path.isfile(path) and path.lower().endswith('.lsv'):
        out = os.path.join(os.path.dirname(os.path.abspath(path)), 'extracted')
        lspk.unpack(path, out)
        path = os.path.dirname(os.path.abspath(path))
    return party.Save(path)


def info_of(save):
    """SaveInfo.json if the save carries one; it only decorates the report."""
    for p in (os.path.join(save.dir, 'extracted', 'SaveInfo.json'),
              os.path.join(save.dir, 'SaveInfo.json')):
        if os.path.exists(p):
            with open(p) as fh:
                return json.load(fh)
    return None


def party_md(chars, info):
    L = ['# Партия из сейва %s\n' % ((info or {}).get('Save Name', '?'))]
    if info:
        L.append('Локация `%s`, сложность %s, версия игры %s.\n'
                 % (info.get('Current Level'), (info.get('Difficulty') or ['?'])[0],
                    info.get('Game Version')))
    L.append('Всё ниже прочитано из ECS-блоба: состав партии, слоты экипировки '
             'и книга заклинаний. Класс и раса — из `SaveInfo.json`.\n')
    L.append('| Персонаж | Класс | Ур. | ' + ' | '.join(party.ABILITIES) + ' | Владение |')
    L.append('|---|---|---|' + '---|' * 7)
    for c in chars:
        L.append('| %s | %s | %d | %s | +%d |'
                 % (c.name, ', '.join(x for x in (c.cls, c.sub) if x), c.level,
                    ' | '.join(str(c.abilities.get(a, '—')) for a in party.ABILITIES),
                    c.proficiency))
    for c in chars:
        L.append('\n## %s — %s %d\n' % (c.name, c.cls or '?', c.level))
        L.append('| Слот | Предмет |')
        L.append('|---|---|')
        for num, slot, ent, sid in c.gear():
            L.append('| %s | %s |' % (slot, name_of(sid) if ent is not None else '— пусто —'))
        extra = [(n, c.worn[n]) for n in sorted(c.worn) if n not in party.GEAR]
        if extra:
            L.append('\nВне боевых слотов: '
                     + ', '.join('%s — %s' % (party.SLOTS.get(n, n), name_of(s))
                                 for n, (_, s) in extra))
        L.append('\n### Книга заклинаний и действий (%d)\n' % len(c.spells))
        L.append(', '.join('`%s`' % s for s in sorted(c.spells)) or '—')
    return '\n'.join(L) + '\n'


def pool_md(pool):
    L = ['# Общий пул партии\n',
         'Всё, что партия несёт и никто не носит: %d предметов, %d наименований.\n'
         % (sum(pool.values()), len(pool)),
         'У кого именно в сумке — не отслеживается: в игре это один котёл.\n']
    rest = collections.Counter()
    for title, pref in GROUPS:
        g = sorted(s for s in pool if s.startswith(pref))
        if not g:
            continue
        L.append('## %s\n' % title)
        for s in g:
            L.append('- %s%s' % (name_of(s), ' ×%d' % pool[s] if pool[s] > 1 else ''))
        L.append('')
    for s, n in pool.items():
        if not s.startswith(tuple(p for _, p in GROUPS)):
            rest[s.split('_')[0]] += n
    if rest:
        L.append('## Расходники и прочее\n')
        L.append(', '.join('%s ×%d' % kv for kv in rest.most_common()))
    return '\n'.join(L) + '\n'


def main(argv):
    src = argv[1] if len(argv) > 1 else DEFAULT
    save = open_save(src)
    info = info_of(save)
    chars, pool = party.read(save, info)
    out = os.environ.get('BG3_OUT_DIR', save.dir)

    with open(os.path.join(out, 'party.md'), 'w') as fh:
        fh.write(party_md(chars, info))
    with open(os.path.join(out, 'pool.md'), 'w') as fh:
        fh.write(pool_md(pool))

    doc = dict(save=(info or {}).get('Save Name', ''),
               level=(info or {}).get('Current Level', ''),
               pool={s: n for s, n in pool.most_common()},
               characters=[dict(
                   name=c.name, entity=c.entity, level=c.level, cls=c.cls,
                   sub=c.sub, race=c.race, abilities=c.abilities,
                   proficiency=c.proficiency, spells=sorted(c.spells),
                   worn={party.SLOTS.get(n, str(n)): s
                         for n, (_, s) in sorted(c.worn.items())})
                   for c in chars])
    with open(os.path.join(out, 'party.json'), 'w') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)

    b = save.blob
    hold = party.holders(b)
    own = party.owners(b, hold)
    members = {c.entity: c for c in chars}
    worn = {it: (c, n) for c in chars for n, (it, _) in c.worn.items()}
    with open(os.path.join(out, 'items_all.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['stats', 'ru', 'en', 'entity', 'container', 'worn_by', 'slot'])
        for e in sorted(hold):
            if own.get(e) not in members and e not in worn:
                continue
            sid = save.stats.get(e, '')
            en, ru = NAMES.get(sid, ('', ''))
            c, n = worn.get(e, (None, None))
            w.writerow([sid, ru, en, e, hold[e], c.name if c else '',
                        party.SLOTS.get(n, '') if c else ''])

    print('персонажей=%d надето=%d в_пуле=%d заклинаний=%s'
          % (len(chars), sum(len(c.worn) for c in chars), sum(pool.values()),
             '/'.join(str(len(c.spells)) for c in chars)))


if __name__ == '__main__':
    main(sys.argv)
