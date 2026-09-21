"""Read a save and write everything a build discussion needs.

    python src/read_save.py [save]

`save` is either a `.lsv` straight out of Steam Cloud, which is unpacked next to
itself, or a directory that already holds `Globals.lsf` (loose or under
`extracted/`).  With no argument it falls back to `BG3_SAVE_DIR`, and then to
`.agent/saves`.

Four files come out, into `BG3_OUT_DIR` or beside the save:

    party.md      the build: abilities, feats, every equipment slot, spells
    party.json    the same, for the bg3 skill to read instead of a screenshot
    pool.md       the gear the party carries and nobody wears
    items_all.csv one row per item, with its slot when it is worn

Who carries an unworn item is deliberately not reported.  In play the party's
bags are one pot, so the only ownership that matters is what is on someone.
Only gear is reported at all: weapons, armour and accessories that can be
worn.  Potions, scrolls, food and quest objects are dropped, and what counts
as gear is the list in `gear.csv`, which this script grows - see gear.py.
"""

import collections
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gear
import lspk
import party

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.environ.get('BG3_SAVE_DIR', os.path.join(HERE, '..', '.agent', 'saves'))

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


def feats_line(c):
    """Feats as `Name (level 4)`, in level order; empty when none were picked."""
    return ', '.join('%s (ур. %d)' % (f['feat'], f['level']) for f in c.feats)


def dc_line(c):
    """`СЛ заклинаний: 20 = 8 + 4 мастерство + ...`, or why there is none."""
    dc = c.spell_dc()
    if dc is None:
        return 'СЛ заклинаний: нет, класс не заклинатель'
    total, parts = dc
    return 'СЛ заклинаний: **%d** = %s' % (
        total, ' + '.join('%d %s' % (v, name_of(k) if k in NAMES else k)
                          for k, v in parts))


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
    L.append('Всё ниже прочитано из ECS-блоба: состав партии, класс, уровень, '
             'черты, слоты экипировки, подготовленные заклинания, книга и '
             'выборы на каждом уровне. Раса — из `SaveInfo.json`. СЛ заклинаний '
             'в сейве нет, она считается: 8 + мастерство + модификатор '
             'заклинательной характеристики + надетое, что её поднимает.\n')
    L.append('Характеристики — итоговые, вместе с надетым. Предмет, который '
             'ставит или поднимает характеристику, уже учтён в числе, и базы '
             'персонажа в сейве нет.\n')
    L.append('| Персонаж | Класс | Ур. | ' + ' | '.join(party.ABILITIES)
             + ' | Владение | Черты |')
    L.append('|---|---|---|' + '---|' * 8)
    for c in chars:
        L.append('| %s | %s | %d | %s | +%d | %s |'
                 % (c.name, ', '.join(x for x in (c.cls, c.sub) if x), c.level,
                    ' | '.join(str(c.abilities.get(a, '—')) for a in party.ABILITIES),
                    c.proficiency, feats_line(c) or '—'))
    for c in chars:
        L.append('\n## %s — %s %d\n' % (c.name, c.cls or '?', c.level))
        L.append('Черты: %s\n' % (feats_line(c) or '—'))
        L.append(dc_line(c) + '\n')
        L.append('| Слот | Предмет |')
        L.append('|---|---|')
        for num, slot, ent, sid in c.gear():
            L.append('| %s | %s |' % (slot, name_of(sid) if ent is not None else '— пусто —'))
        extra = [(n, c.worn[n]) for n in sorted(c.worn) if n not in party.GEAR]
        if extra:
            L.append('\nВне боевых слотов: '
                     + ', '.join('%s — %s' % (party.SLOTS.get(n, n), name_of(s))
                                 for n, (_, s) in extra))
        picked = [lv for lv in c.choices
                  if lv['spells'] or lv['replaced'] or lv['passives']]
        if picked:
            L.append('\n### Выборы при повышении уровня\n')
            L.append('| Ур. | Заклинания и фокусы | Заменено | Пассивки |')
            L.append('|---|---|---|---|')
            for lv in picked:
                L.append('| %d | %s | %s | %s |' % (
                    lv['level'],
                    ', '.join('`%s`' % x for x in lv['spells']) or '—',
                    ', '.join('`%s` → `%s`' % ab for ab in lv['replaced']) or '—',
                    ', '.join('`%s`' % x for x in lv['passives']) or '—'))
        L.append('\n### Подготовлено и активно (%d)\n' % len(c.prepared))
        L.append(', '.join('`%s`' % s for s in sorted(c.prepared)) or '—')
        L.append('\n### Книга заклинаний и действий (%d)\n' % len(c.spells))
        L.append(', '.join('`%s`' % s for s in sorted(c.spells)) or '—')
    return '\n'.join(L) + '\n'


def pool_md(pool, known):
    """The shared pool, gear only, grouped by slot family.

    `known` is the gear table.  Rows marked `?` go into their own section for
    the owner to check once; rows marked `no` and stat ids the table does not
    hold are not gear and do not appear.
    """
    yes = {s: n for s, n in pool.items() if known.get(s, {}).get('gear') == 'yes'}
    ask = {s: n for s, n in pool.items() if known.get(s, {}).get('gear') == '?'}
    L = ['# Общий пул снаряжения\n',
         'Оружие, броня и аксессуары, которые партия несёт и никто не носит: '
         '%d предметов, %d наименований. Зелья, свитки, еда и квестовые вещи '
         'не показаны.\n' % (sum(yes.values()), len(yes)),
         'У кого именно в сумке — не отслеживается: в игре это один котёл.\n']
    for kind in gear.KIND_ORDER:
        g = sorted(s for s in yes if known[s]['kind'] == kind)
        if not g:
            continue
        L.append('## %s\n' % gear.KIND_RU[kind])
        for s in g:
            L.append('- %s%s' % (name_of(s), ' ×%d' % yes[s] if yes[s] > 1 else ''))
        L.append('')
    if ask:
        L.append('## Не проверено (%d)\n' % len(ask))
        L.append('Похожи на снаряжение по stat id, но никто в сейве их не носил. '
                 'Проверить один раз и проставить `yes` или `no` в `src/gear.csv`.\n')
        for s in sorted(ask):
            L.append('- %s — `%s`, похоже на %s'
                     % (name_of(s), s, gear.KIND_RU[known[s]['kind']].lower()))
        L.append('')
    return '\n'.join(L) + '\n'


def world_worn(save, b):
    """{stat id: slot} over every combat slot anyone in the save has filled."""
    out = {}
    cpos = b.positions(party.CONTAINER)
    for e, c in party.container_of(b).items():
        for slot, item in party.slots_of(b, c, cpos).items():
            sid = save.stats.get(item, '')
            if sid and slot in gear.SLOT_KIND:
                out.setdefault(sid, slot)
    return out


def main(argv):
    src = argv[1] if len(argv) > 1 else DEFAULT
    save = open_save(src)
    info = info_of(save)
    chars, pool = party.read(save, info)
    out = os.environ.get('BG3_OUT_DIR', save.dir)

    known = gear.load()
    learned = gear.learn(known, world_worn(save, save.blob), pool,
                         (info or {}).get('Save Name', '?'))
    if learned:
        gear.save(known)
    is_gear = lambda s: known.get(s, {}).get('gear') == 'yes'
    unsure = sorted(s for s in pool if known.get(s, {}).get('gear') == '?')

    with open(os.path.join(out, 'party.md'), 'w') as fh:
        fh.write(party_md(chars, info))
    with open(os.path.join(out, 'pool.md'), 'w') as fh:
        fh.write(pool_md(pool, known))

    doc = dict(save=(info or {}).get('Save Name', ''),
               level=(info or {}).get('Current Level', ''),
               pool={s: n for s, n in pool.most_common() if is_gear(s)},
               pool_unchecked=unsure,
               characters=[dict(
                   name=c.name, entity=c.entity, level=c.level, cls=c.cls,
                   sub=c.sub, race=c.race, classes=c.classes, feats=c.feats,
                   abilities=c.abilities, proficiency=c.proficiency,
                   spells=sorted(c.spells), prepared=sorted(c.prepared),
                   choices=c.choices,
                   spell_dc=(c.spell_dc() or (None, []))[0],
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

    print('персонажей=%d надето=%d снаряжения_в_пуле=%d не_проверено=%d '
          'заклинаний=%s подготовлено=%s черт=%s сл=%s'
          % (len(chars), sum(len(c.worn) for c in chars),
             sum(n for s, n in pool.items() if is_gear(s)), len(unsure),
             '/'.join(str(len(c.spells)) for c in chars),
             '/'.join(str(len(c.prepared)) for c in chars),
             '/'.join(str(len(c.feats)) for c in chars),
             '/'.join(str((c.spell_dc() or ('-',))[0]) for c in chars)))
    if learned:
        print('gear.csv: %d новых строк' % len(learned))


if __name__ == '__main__':
    main(sys.argv)
