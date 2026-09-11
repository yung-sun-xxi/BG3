"""What counts as gear: the list of stat ids that can be worn, and how it grows.

The save never says whether an item is equippable.  There is no component for
it, and the stat id is the only handle a bag item carries.  So the answer is
kept in `gear.csv`, one row per stat id, and the reader grows it on every save:

    gear = yes   worn in a combat slot by somebody in some save - proof - or a
                 stat id whose prefix and last word both say gear (MAG_.._Gloves)
    gear = ?     only one of the two says gear; nobody has been seen wearing it
    gear = no    the owner looked and said it is not gear

The `source` column says which: `worn <save>`, `id <save>`, `seen <save>`.

A row is written once and never rewritten by the reader, so a `no` or a `yes`
set by hand stays.  Only `?` rows are upgraded to `yes` when a later save shows
the item worn.  The owner's job is to look at the `?` rows once, in `pool.md`
under "not yet checked", and flip them; nothing is checked twice.

The `kind` column is the slot family, read off the slot when worn and guessed
off the stat id's last token otherwise: MAG_Thunder_Reverberation_Gloves is
hands, UNI_MassHealRing is ring.
"""

import csv
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, 'gear.csv')

FIELDS = ('stats', 'kind', 'gear', 'source')

# Stat id prefixes under which Larian keeps wearable things.  MAG_ and UNI_
# also hold scrolls, grenades and quest objects, which is why a prefix hit is
# a `?` and not a `yes`.
PREFIXES = ('WPN_', 'ARM_', 'MAG_', 'UNI_')

# Slot family by word in the stat id's last token, first match wins.  The
# token is split on its capitals, so MassHealRing gives mass, heal, ring; a
# word has to match whole, except weapons, where compounds are the norm
# (Longsword, HeavyCrossbow, Quarterstaff) and a suffix match is enough.
# Substring matching was tried first and put Daggeroot under weapons and
# NightOrchid under torches.
KINDS = (
    ('shield', ('shield',)),
    ('cloak', ('cloak', 'cape', 'mantle')),
    ('head', ('helmet', 'helm', 'hat', 'circlet', 'hood', 'mask', 'cap', 'crown',
              'headband', 'wreath', 'diadem', 'tiara')),
    ('body', ('armor', 'armour', 'robe', 'garb', 'plate', 'mail', 'leather',
              'breastplate', 'vest', 'clothes', 'outfit', 'tunic', 'jacket',
              'coat', 'cuirass', 'hide', 'padded')),
    ('hands', ('gloves', 'gauntlets', 'bracers')),
    ('feet', ('boots', 'shoes', 'sandals', 'greaves')),
    ('amulet', ('amulet', 'necklace', 'pendant', 'periapt', 'talisman')),
    ('ring', ('ring',)),
    ('weapon', ('sword', 'rapier', 'scimitar', 'dagger', 'knife', 'axe', 'hammer',
                'maul', 'mace', 'morningstar', 'flail', 'club', 'staff', 'spear',
                'pike', 'halberd', 'glaive', 'trident', 'javelin', 'bow', 'crossbow',
                'sling', 'dart', 'scythe', 'sickle', 'torch')),
)

# A token anywhere in the stat id that settles it is not wearable, whatever
# the last token says: OBJ_Scroll_MageArmor is a scroll, ARM_Camp_Body_Minthara
# is camp clothing and never part of a build.
NOT_GEAR = ('scroll', 'potion', 'elixir', 'grenade', 'arrow', 'kit', 'ingredient',
            'herb', 'extract', 'food', 'book', 'note', 'letter', 'key', 'cont',
            'wand', 'underwear', 'camp', 'vanity')


def _words(token):
    """CamelCase token to lower-case words: HeavyCrossbow -> heavy, crossbow."""
    return [w.lower() for w in re.findall(r'[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])', token)] \
        or [token.lower()]


def _kind_by_word(sid):
    words = _words(sid.rsplit('_', 1)[-1])
    for kind, keys in KINDS:
        for w in words:
            if w in keys or (kind == 'weapon' and w.endswith(keys)):
                return kind
    return None


def _denied(sid):
    return any(t.lower() in NOT_GEAR for t in sid.split('_'))


# Slot number (party.SLOTS) to slot family.  4 is the off hand, which holds a
# shield or a weapon; the keyword decides.
SLOT_KIND = {0: 'head', 1: 'body', 2: 'cloak', 3: 'weapon', 4: 'weapon',
             5: 'weapon', 6: 'weapon', 7: 'ring', 9: 'feet', 10: 'hands',
             11: 'amulet', 12: 'ring'}

KIND_RU = {'weapon': 'Оружие', 'shield': 'Щиты', 'head': 'Головные уборы',
           'body': 'Броня', 'cloak': 'Плащи', 'hands': 'Перчатки',
           'feet': 'Обувь', 'amulet': 'Амулеты', 'ring': 'Кольца', '?': 'Не ясно'}
KIND_ORDER = ('weapon', 'shield', 'head', 'body', 'cloak', 'hands', 'feet',
              'amulet', 'ring', '?')


def kind_of(sid, slot=None):
    """Slot family of a stat id: from the slot if worn, else from its last token."""
    by_word = _kind_by_word(sid)
    if slot in SLOT_KIND:
        return 'shield' if slot == 4 and by_word == 'shield' else SLOT_KIND[slot]
    if by_word:
        return by_word
    if sid.startswith('WPN_'):
        return 'weapon'
    if sid.startswith('ARM_'):
        return 'body'
    return '?'


def looks_like_gear(sid):
    """True when the stat id alone suggests the item can be worn."""
    if _denied(sid):
        return False
    return sid.startswith(PREFIXES) or _kind_by_word(sid) is not None


def load(path=PATH):
    """stat id -> row dict, in file order."""
    rows = {}
    if os.path.exists(path):
        with open(path, newline='') as fh:
            for r in csv.DictReader(fh):
                rows[r['stats']] = r
    return rows


def save(rows, path=PATH):
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, FIELDS, lineterminator='\n')
        w.writeheader()
        for r in sorted(rows.values(), key=lambda r: (r['kind'], r['stats'])):
            w.writerow({k: r.get(k, '') for k in FIELDS})


def learn(rows, worn, pool, save_name):
    """Grow `rows` in place from one save; returns the stat ids added or upgraded.

    `worn` is {stat id: slot number} over every combat slot filled by anyone in
    the save - party or not, wearing it is proof.  `pool` is the stat ids the
    party carries unworn.  A `yes` or `no` already in the file is never touched.
    """
    changed = []
    for sid, slot in worn.items():
        if slot not in SLOT_KIND or not sid or _denied(sid):
            continue
        r = rows.get(sid)
        if r is None:
            rows[sid] = dict(stats=sid, kind=kind_of(sid, slot), gear='yes',
                             source='worn %s' % save_name)
            changed.append(sid)
        elif r['gear'] == '?':
            r.update(kind=kind_of(sid, slot), gear='yes', source='worn %s' % save_name)
            changed.append(sid)
    for sid in pool:
        if not sid or sid in rows or not looks_like_gear(sid):
            continue
        # Prefix and slot word agreeing (MAG_..._Gloves) is taken as gear
        # outright; either alone is a question for the owner.
        sure = sid.startswith(PREFIXES) and _kind_by_word(sid) is not None
        rows[sid] = dict(stats=sid, kind=kind_of(sid), gear='yes' if sure else '?',
                         source='%s %s' % ('id' if sure else 'seen', save_name))
        changed.append(sid)
    return changed
