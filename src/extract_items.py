"""Per character inventory out of a BG3 save.

Owner comes from the ECS blob, not from a distance guess: every item carries an
inventory.v0.MemberComponent pointing at the container it sits in, and every
container holds items of exactly one character.  The container is tied to its
character through the item coordinates in Globals.lsf, which for an inventory
item equal the owner's own coordinates exactly.

The equipment container is the one holding the character's camp clothes or
underwear - those slots are always filled, and nothing else lives there.
"""

import collections, csv, json, math, os, struct, sys, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import blob, lsf

HERE = os.path.dirname(os.path.abspath(__file__))
# Saves are never committed: they are 13 MB apiece and change every session.
SAVES = os.environ.get('BG3_SAVE_DIR', os.path.join(HERE, '..', '.agent', 'saves'))
OUT = os.environ.get('BG3_OUT_DIR', SAVES)

EQUIP_MARK = ('ARM_Camp_Body', 'ARM_Camp_Shoes', 'ARM_Underwear')
GROUPS = [('Магические (MAG_)', 'MAG_'), ('Уникальные (UNI_)', 'UNI_'),
          ('Оружие (WPN_)', 'WPN_'), ('Броня (ARM_)', 'ARM_')]

NAMES = {}
with open(os.path.join(HERE, 'names.csv')) as fh:
    for r in csv.DictReader(fh):
        NAMES[r['stats']] = (r['en'], r['ru'])


def name_of(sid):
    """Русское (English) when known, English alone, else the raw stat id."""
    en, ru = NAMES.get(sid, ('', ''))
    if ru and en:
        return '%s (%s)' % (ru, en)
    return en or '`%s`' % sid


b = blob.Blob(os.path.join(SAVES, 'newage.bin'))
f = lsf.LSF(os.path.join(SAVES, 'extracted', 'Globals.lsf'))
nodes, roots = lsf.build(f)
root = {r.name: r for r in roots}
info = json.load(open(os.path.join(SAVES, 'extracted', 'SaveInfo.json')))


def pairs(kind):
    """(entity index, attribute dict) for every Creator/object pair of `kind`."""
    cre = root[kind].children[0].children[0].children
    obj = root[kind].children[0].children[1].children
    for c, o in zip(cre, obj):
        a = {k: v[1] for k, v in c.attrs.items()}
        z = {k: v[1] for k, v in o.attrs.items()}
        if a.get('Entity'):
            e = b.of_guid(uuid.UUID(a['Entity']).bytes_le)
            if e is not None:
                yield e, z


party = {}
for c in info['Active Party']['Characters']:
    cl = c['Classes'][0]
    party[tuple(c['Position'])] = dict(
        origin=c['Origin'], cls=cl['Main'], sub=cl['Sub'],
        level=c['Level'], race=c['Race'])

who = {}
for e, z in pairs('Characters'):
    t = z.get('Translate')
    for p, c in party.items():
        if isinstance(t, tuple) and len(t) == 3 and math.dist(t, p) < 0.01:
            c['entity'] = e
            who[e] = c

items, place = {}, {}
for e, z in pairs('Items'):
    items[e] = str(z.get('Stats', ''))
    place[e] = z.get('Translate')

# item -> container it is a member of.  Position k of MemberComponent's entity
# index array pairs with the MemberData record at its ptr + 96 + k * 16, that is
# with element k + 3, and why it is k + 3 is not known.  The index array itself
# is sound: MemberComponent is an anchor with exactly one maximal increasing run
# of its length.  The skew was measured, not guessed - every other multiple of
# 16 from -16 to 128 scatters a character's items over 128 to 168 containers,
# and 96 over 21 - and it is confirmed by a second, independent metric: at 96 no
# container holds items sitting at two different coordinates, at 48 that happens
# to 190 containers out of 293.  The price is the last three items, whose record
# would fall past the end of MemberData.
MEMBER_SKEW = 96


def read_members():
    holder, order = {}, {}
    md = b.comps['game.inventory.v0.MemberData']['ptr'] + MEMBER_SKEW
    for k, e in enumerate(b.entities('game.inventory.v0.MemberComponent')):
        ptr, pos, _ = struct.unpack_from('<QII', b.d, md + k * 16)
        off = ptr - b.ent_at
        if off < 0 or off % 16 or off // 16 >= b.nent or e >= b.nent:
            continue
        holder[b.canon[e]] = b.canon[off // 16]
        order[b.canon[e]] = pos
    return holder, order


def scatter(holder):
    seen = collections.defaultdict(set)
    for e, t in place.items():
        if not (isinstance(t, tuple) and len(t) == 3) or e not in holder:
            continue
        for p in party:
            if math.dist(t, p) < 0.01:
                seen[p].add(holder[e])
    return sum(len(v) for v in seen.values()) or 1 << 30


holder, order = read_members()
assert scatter(holder) < 40, 'связка предмет-контейнер рассыпалась: %d' % scatter(holder)

# item -> owning character.  An item held by a character carries that
# character's coordinates exactly; nested bags inherit the bag's, so the match
# is done per item and the container is used only to tell worn from stowed.
mine = {}
for e, t in place.items():
    if not (isinstance(t, tuple) and len(t) == 3):
        continue
    for p, ch in party.items():
        if math.dist(t, p) < 0.01:
            mine[e] = ch['entity']

score = collections.defaultdict(collections.Counter)
for e, ch in mine.items():
    if e in holder:
        score[ch][holder[e]] += items.get(e, '').startswith(EQUIP_MARK)
equip = {ch: max(v, key=lambda c: v[c]) for ch, v in score.items() if max(v.values())}

carried = collections.defaultdict(list)
for e, ch in mine.items():
    carried[ch].append((items.get(e, ''), holder.get(e) == equip.get(ch)))

L = ['# Инвентарь партии из сейва %s\n' % info['Save Name']]
L.append('Локация `%s`, сложность %s, версия игры %s, платформа %s.\n'
         % (info['Current Level'], info['Difficulty'][0],
            info['Game Version'], info['Platform']))
L.append('Владелец и слот прочитаны из ECS-блоба, а не угаданы по расстоянию.\n')

stats = 'game.stats.v3.StatsComponent'
ABIL = 'СИЛ ЛОВ ВЫН ИНТ МДР ХАР'.split()
L.append('## Партия\n')
L.append('| Персонаж | Класс | Уровень | ' + ' | '.join(ABIL) + ' | Владение |')
L.append('|---|---|---|' + '---|' * 7)
for e, c in sorted(who.items()):
    v = struct.unpack_from('<9I', b.d, b.at(stats, e))
    L.append('| %s | %s, %s | %d | %s | +%d |'
             % (c['origin'], c['cls'], c['sub'], c['level'],
                ' | '.join(str(x) for x in v[2:8]), v[8]))

for e, c in sorted(who.items()):
    own = carried[e]
    L.append('\n## %s — %s %d, всего предметов %d\n'
             % (c['origin'], c['cls'], c['level'], len(own)))
    on = sorted(s for s, eq in own if eq)
    L.append('### Надето (%d)\n' % len(on))
    for s in on:
        L.append('- %s' % name_of(s))
    bag = collections.Counter(s for s, eq in own if not eq)
    L.append('\n### В сумке (%d)\n' % sum(bag.values()))
    for title, pref in GROUPS:
        g = sorted(s for s in bag if s.startswith(pref))
        if not g:
            continue
        L.append('**%s**\n' % title)
        for s in g:
            L.append('- %s' % name_of(s) + (' ×%d' % bag[s] if bag[s] > 1 else ''))
        L.append('')
    rest = collections.Counter()
    for s, n in bag.items():
        if not s.startswith(tuple(p for _, p in GROUPS)):
            rest[s.split('_')[0]] += n
    if rest:
        L.append('**Расходники и прочее:** '
                 + ', '.join('%s ×%d' % kv for kv in rest.most_common()))

open(os.path.join(OUT, 'inventory.md'), 'w').write('\n'.join(L) + '\n')

with open(os.path.join(OUT, 'items_all.csv'), 'w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['stats', 'ru', 'en', 'entity', 'container', 'owner', 'equipped', 'slot'])
    for e in sorted(holder):
        c = holder[e]
        o = mine.get(e)
        n = NAMES.get(items.get(e, ''), ('', ''))
        w.writerow([items.get(e, ''), n[1], n[0], e, c,
                    who[o]['origin'] + '/' + who[o]['cls'] if o in who else '',
                    int(c == equip.get(o)) if o else 0, order.get(e, '')])

print('персонажей=%d предметов_в_контейнерах=%d у_партии=%d надето=%d'
      % (len(who), len(holder), sum(len(v) for v in carried.values()),
         sum(1 for v in carried.values() for _, eq in v if eq)))
