"""The party as the save describes it: who is in it, what they wear, what they know.

Everything structural is read out of the ECS blob.  Globals.lsf is consulted for
one thing only - the stat id of an item, which the blob never spells out - and a
save whose Globals is missing still yields the party, the slots and the spells,
just with entity numbers where names would be.

The chain, each link measured rather than assumed:

    game.party.v0.MemberComponent       who is in the active party
    game.display_names.v2.Component     their name, as the player sees it
    game.stats.v3.StatsComponent        the six abilities and proficiency
    game.stats.v0.ClassesComponent      level, class and subclass GUIDs
    game.v0.SaveWithComponent           container -> the character it belongs to
    game.inventory.v3.Type              1 marks a container as worn equipment
    game.inventory.v1.ContainerComponent   that container's slot numbers
    game.inventory.v0.ContainerSlotData     and the item in each slot
    game.spell.v3.SpellBookComponent    the spell book, down to spell names

An item that nobody wears belongs to the shared pool: which of the four is
carrying it is not tracked, because in play it makes no difference.
"""

import collections
import os
import struct
import uuid

import blob
import lsf

# Equipment slot numbers, matching the ItemSlot enum of Norbyte/bg3se
# (BG3Extender/GameDefinitions/Enumerations/Stats.inl) one to one on the
# fifteen slots this save fills.  6, 13, 14 and 15 are named from that enum:
# RangedOffHand, Wings, Horns, Overhead.  19 MainHand and 20 OffHand are
# virtual and have no place in the container, which is why the container
# declares 19 slots.
SLOTS = {
    0: 'шлем', 1: 'нагрудник', 2: 'плащ', 3: 'основная рука',
    4: 'вторая рука', 5: 'дальний бой', 6: 'дальний бой, вторая рука',
    7: 'кольцо 1', 8: 'бельё', 9: 'сапоги', 10: 'перчатки', 11: 'амулет',
    12: 'кольцо 2', 13: 'крылья', 14: 'рога', 15: 'над головой',
    16: 'инструмент', 17: 'лагерная одежда', 18: 'лагерная обувь',
}
# The slots a build is actually made of; the rest is underwear and cosmetics.
GEAR = (0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12)

ABILITIES = ('СИЛ', 'ЛОВ', 'ВЫН', 'ИНТ', 'МДР', 'ХАР')

PARTY = 'game.party.v0.MemberComponent'
NAMES = 'game.display_names.v2.Component'
STATS = 'game.stats.v3.StatsComponent'
CLASSES = 'game.stats.v0.ClassesComponent'
SAVEWITH = 'game.v0.SaveWithComponent'
CONT_TYPE = 'game.inventory.v3.Type'
CONTAINER = 'game.inventory.v1.ContainerComponent'
MEMBER = 'game.inventory.v0.MemberComponent'
MEMBER_DATA = 'game.inventory.v0.MemberData'
SPELLBOOK = 'game.spell.v3.SpellBookComponent'
SPELL_DATA = 'game.spell.v3.SpellData'
PREPARES = 'game.spell.v0.SpellBookPrepares'
LEVEL = 'game.stats.v0.LevelComponent'

# The uniform +48 pointer bias holds everywhere in this file; nothing here is
# an exception.  Two record layouts looked like exceptions for a while, until
# they were read correctly:
#   ClassesComponent's span, at beg+48, holds 40 byte records - measured on
#   the nine named origin characters, whose classes the game itself names.
#   SpellBookComponent's span is also at beg+48, not the raw beg; the pointer
#   to each SpellId sits at record offset 0, not 48.  Measured on the share of
#   books that open on Projectile_Jump: 196 of 444 with this reading, 7 and 0
#   with the ones tried before it.
#   SpellBookPrepares was read the same way, checked by how many prepared
#   names turn up in the owner's own book: 2290 of 2297 at +48, 2160 and 2239
#   one record either side.
CLASS_REC = 40
SPELL_REC = 72
META_REC = 24

# Class GUIDs in Larian's .lsx text form (bg3se prints the last 8 bytes
# pairwise swapped, so compare by the first three groups when checking a GUID
# against the web).  Built from the nine named origin characters, whose class
# is public knowledge, plus this save's own SaveInfo.json.  Bard has never
# been observed in a save and is left out on purpose.
CLASS_NAMES = {
    'd8cadb42-0ff9-4049-afaf-d7e5068d99a3': 'Barbarian',
    '114e7aee-d1d4-4371-908d-208a5980af2f': 'Cleric',
    '457d0a6e-9da8-4f95-25a2-38180e2fb594': 'Druid',
    '721dfac3-92d4-41f5-73b7-07b7862a2f23': 'Fighter',
    'c4598bdb-fc07-40dd-2ca6-cc908b136fd7': 'Monk',
    'ff4d9497-023c-434a-14bd-fc827e361c99': 'Paladin',
    '36be18ba-23db-4dff-a6bf-10aee45c4431': 'Ranger',
    'e8b1eab0-ef11-40a2-0b8a-e8ce62d02abf': 'Rogue',
    '784001e2-c96d-4153-b6be-db2a5aef92bc': 'Sorcerer',
    'b4225a4b-4bbe-4d97-3c9e-1947d1db7c48': 'Warlock',
    'a865965f-501b-46e9-aa9e-4877c0e8094d': 'Wizard',
}

# Subclass GUIDs matched by position against SaveInfo.json of this save.
SUBCLASS_NAMES = {
    'd379fdae-b401-4731-508d-7c279173e39a': 'StormSorcery',
    '2a5e3097-384c-4d29-6e8d-4f05d2df806b': 'OpenHand',
    'f013d01b-3310-43f7-bf81-11a544305e2b': 'TrickeryDomain',
    '32eee7d8-1b2f-4de5-eeb9-fb7886d2efc6': 'BerserkerPath',
}


class Save:
    """A save opened for reading: the blob, and the stat ids if Globals is there."""

    def __init__(self, path):
        self.dir = path
        g = os.path.join(path, 'extracted', 'Globals.lsf')
        if not os.path.exists(g):
            g = os.path.join(path, 'Globals.lsf')
        self.globals_path = g if os.path.exists(g) else None
        if self.globals_path is None:
            raise IOError('no Globals.lsf under %s' % path)
        self.lsf = lsf.LSF(self.globals_path)
        self.blob = blob.Blob(data=lsf.scratch(self.lsf, 'NewAge'))
        self.stats = {}
        self.at = {}
        _, roots = lsf.build(self.lsf)
        root = {r.name: r for r in roots}
        for e, a in self._pairs(root, 'Items'):
            self.stats[e] = str(a.get('Stats', ('', ''))[1] or '')
        for e, a in self._pairs(root, 'Characters'):
            t = a.get('Translate')
            if t and isinstance(t[1], tuple) and len(t[1]) == 3:
                self.at[e] = t[1]

    def _pairs(self, root, kind):
        """(entity index, attribute dict) for each Creator/object pair of `kind`.

        Globals keeps two parallel child lists: one names the entity by GUID,
        the other carries its attributes.  The GUID is stored little endian, and
        the slot it lands on has to be folded onto the entity's first slot.
        """
        import uuid
        if kind not in root:
            return
        cre = root[kind].children[0].children[0].children
        obj = root[kind].children[0].children[1].children
        for c, o in zip(cre, obj):
            g = c.attrs.get('Entity')
            if not g or not g[1]:
                continue
            e = self.blob.of_guid(uuid.UUID(g[1]).bytes_le)
            if e is not None:
                yield e, o.attrs


class Character:
    __slots__ = ('entity', 'name', 'level', 'cls', 'sub', 'race', 'classes',
                 'abilities', 'proficiency', 'worn', 'spells', 'prepared',
                 'container')

    def __init__(self, entity):
        self.entity = entity
        self.name = str(entity)
        self.level = 0
        self.cls = self.sub = self.race = ''
        self.classes = []        # [{cls, sub, level, cls_guid, sub_guid}, ...]
        self.abilities = {}
        self.proficiency = 0
        self.worn = {}          # slot number -> (entity, stat id)
        self.spells = []
        self.prepared = []      # names, subset of spells, currently active
        self.container = None

    def gear(self):
        """(slot number, slot name, entity, stat id) for the build slots only."""
        return [(s, SLOTS[s]) + self.worn.get(s, (None, ''))
                for s in GEAR]


def display_name(b, e, pos=None):
    """Player-facing name of an entity, or None when it has no custom one.

    The component holds a span of 16 byte records - string pointer, length,
    flags - and only the records flagged 514 carry a literal.  The rest are
    localisation handles, which need files this reader does not have.
    """
    pos = pos if pos is not None else b.positions(NAMES)
    if e not in pos:
        return None
    beg, end = b.elem(NAMES, pos[e], '<2Q' + 'x' * (b.comps[NAMES]['elem'] - 16))[:2]
    got = None
    for p, ln, fl in b.pool(beg, max(0, (end - beg) // 16), '<QII'):
        if fl != 514 or ln == 0 or ln > 200:
            continue
        try:
            got = b.d[b.deref(p):b.deref(p) + ln].decode('utf-8')
        except UnicodeDecodeError:
            pass
    return got


def container_of(b):
    """Character entity -> the container holding what that character wears.

    Type 1 marks a container as an equipment container, and SaveWithComponent
    says whose it is.  In this save that is a bijection: 261 such containers,
    261 characters, no character with two and none with none.
    """
    ty = b.positions(CONT_TYPE)
    equip = {c for c, k in ty.items() if b.elem(CONT_TYPE, k, '<Q')[0] == 1}
    out = {}
    for c, k in b.positions(SAVEWITH).items():
        if c not in equip:
            continue
        owner = b.entity(b.elem(SAVEWITH, k, '<Q')[0])
        if owner is not None:
            out[owner] = c
    return out


def slots_of(b, container, pos=None):
    """Slot number -> item entity for one container.

    The container's record is two spans over one arena: m slot numbers as u16,
    then m pointers to ContainerSlotData records, parallel by index.  A bag uses
    the same field as a plain position and fills 0..m-1; an equipment container
    leaves gaps, which is how the two tell themselves apart without looking at
    what is inside them.
    """
    pos = pos if pos is not None else b.positions(CONTAINER)
    if container not in pos:
        return {}
    u16beg, u16end, ptrbeg, _ = b.elem(CONTAINER, pos[container], '<4Q')
    if u16beg == (1 << 64) - 1:
        return {}
    m = (u16end - u16beg) // 2
    nums = struct.unpack_from('<%dH' % m, b.d, b.deref(u16beg))
    out = {}
    for n, (p,) in zip(nums, b.pool(ptrbeg, m, '<Q')):
        e = b.entity(b.pool(p, 1, '<QII')[0][0])
        if e is not None:
            out[n] = e
    return out


def holders(b):
    """Item entity -> the container it sits in.

    MemberComponent is a plain 0..n-1 numbering; the payload is MemberData,
    element k, whose first field points at the item and whose second is its
    position inside the container.  Nothing here is skewed: the constant that
    used to sit in this function was the uniform pointer bias, applied twice.
    """
    out = {}
    for k, e in enumerate(b.entities(MEMBER)):
        ptr, _, _ = b.elem(MEMBER_DATA, k, '<QII')
        c = b.entity(ptr)
        if c is not None and e < b.nent:
            out[b.canon[e]] = c
    return out


def owners(b, hold=None, save_with=None):
    """Item entity -> the character whose inventory it is in, at any depth.

    A bag inside a backpack saves with the bag, not with the character, so the
    walk goes item -> its container -> what that container saves with -> and if
    that is itself an item, round again.  It stops on a character.
    """
    hold = hold if hold is not None else holders(b)
    if save_with is None:
        save_with = {}
        for c, k in b.positions(SAVEWITH).items():
            t = b.entity(b.elem(SAVEWITH, k, '<Q')[0])
            if t is not None:
                save_with[c] = t
    chars = set(b.positions(STATS))
    out = {}
    for e in hold:
        cur, seen = e, set()
        for _ in range(16):
            c = hold.get(cur)
            if c is None:
                break
            t = save_with.get(c)
            if t is None or t in seen:
                break
            if t in chars:
                out[e] = t
                break
            seen.add(t)
            cur = t
    return out


def classes_of(b, e, pos=None):
    """Every class record a character has, in file order.

    ClassesComponent is a span at beg+48, like every other span in this file,
    40 bytes a record: class GUID, subclass GUID, u32 level in that class, and
    a constant word that is not decoded.  Measured on the nine named origin
    characters, who each carry exactly one such record in this save.  An
    unrecognised GUID is reported as 'guid:' plus its first 8 hex characters
    rather than dropped; an all-zero subclass GUID means no subclass.
    """
    pos = pos if pos is not None else b.positions(CLASSES)
    if e not in pos:
        return []
    beg, end = b.elem(CLASSES, pos[e], '<2Q')
    out = []
    for k in range(max(0, (end - beg) // CLASS_REC)):
        cg, sg, level, _ = struct.unpack_from('<16s16sII', b.d,
                                               b.deref(beg) + k * CLASS_REC)
        cls_guid = str(uuid.UUID(bytes_le=cg))
        sub_guid = str(uuid.UUID(bytes_le=sg))
        cls = CLASS_NAMES.get(cls_guid, 'guid:' + cls_guid.replace('-', '')[:8])
        if sg == b'\x00' * 16:
            sub = ''
        else:
            sub = SUBCLASS_NAMES.get(sub_guid, 'guid:' + sub_guid.replace('-', '')[:8])
        out.append(dict(cls=cls, sub=sub, level=level,
                         cls_guid=cls_guid, sub_guid=sub_guid))
    return out


def spells_of(b, e, pos=None):
    """Every spell name in a character's book, common actions included.

    SpellBookComponent is a span at beg+48, like every other span in this
    file, over SpellData, 72 bytes a record.  At record offset 0 sits a
    pointer to a SpellId, and a SpellId holds a pointer and a length into the
    shared string arena - the names run together there with no separators, so
    the length is not optional.  Every pointer here is biased.
    """
    pos = pos if pos is not None else b.positions(SPELLBOOK)
    if e not in pos:
        return []
    beg, end = b.elem(SPELLBOOK, pos[e], '<2Q')
    out = []
    for k in range(max(0, (end - beg) // SPELL_REC)):
        rec = struct.unpack_from('<Q64x', b.d, b.deref(beg) + k * SPELL_REC)
        p, ln = b.pool(rec[0], 1, '<8xQI4x')[0]
        if ln == 0 or ln > 200:
            continue
        try:
            out.append(b.d[b.deref(p):b.deref(p) + ln].decode('utf-8'))
        except UnicodeDecodeError:
            pass
    return out


def prepared_of(b, e, pos=None):
    """Names in a character's currently prepared/active spells and actions.

    SpellBookPrepares holds five (begin, end) pairs; only the first carries
    anything here.  It spans MetaId, 24 bytes a record - string pointer,
    length, flag - and only records flagged 514 with a length in (0, 200]
    decode to a literal, the same filter display_name uses.  This is a subset
    of what spells_of returns, not a separate vocabulary.
    """
    pos = pos if pos is not None else b.positions(PREPARES)
    if e not in pos:
        return []
    beg, end = b.elem(PREPARES, pos[e],
                       '<2Q' + 'x' * (b.comps[PREPARES]['elem'] - 16))[:2]
    out = []
    for p, ln, fl in b.pool(beg, max(0, (end - beg) // META_REC), '<QII8x'):
        if fl != 514 or ln == 0 or ln > 200:
            continue
        try:
            out.append(b.d[b.deref(p):b.deref(p) + ln].decode('utf-8'))
        except UnicodeDecodeError:
            pass
    return out


def read(save, info=None):
    """(characters, shared pool) for the active party.

    The pool is a Counter of stat id over everything the party carries and
    nobody wears: which member's bag it is in is deliberately not kept.
    """
    b = save.blob
    members = [b.canon[e] for e in b.entities(PARTY)]
    conts = container_of(b)
    cpos = b.positions(CONTAINER)
    npos = b.positions(NAMES)
    spos = b.positions(SPELLBOOK)
    stpos = b.positions(STATS)
    clpos = b.positions(CLASSES)
    ppos = b.positions(PREPARES)
    lpos = b.positions(LEVEL)

    chars = []
    for e in members:
        ch = Character(e)
        ch.name = display_name(b, e, npos) or ('сущность %d' % e)
        if e in stpos:
            v = b.elem(STATS, stpos[e], '<9I')
            ch.abilities = dict(zip(ABILITIES, v[2:8]))
            ch.proficiency = v[8]
        if e in lpos:
            ch.level = b.elem(LEVEL, lpos[e], '<I')[0]
        ch.classes = classes_of(b, e, clpos)
        if ch.classes:
            ch.cls, ch.sub = ch.classes[0]['cls'], ch.classes[0]['sub']
        ch.container = conts.get(e)
        if ch.container is not None:
            for s, item in slots_of(b, ch.container, cpos).items():
                ch.worn[s] = (item, save.stats.get(item, ''))
        ch.spells = spells_of(b, e, spos)
        ch.prepared = prepared_of(b, e, ppos)
        chars.append(ch)

    hold = holders(b)
    own = owners(b, hold)
    worn = {it for c in chars for it, _ in c.worn.values()}
    party = set(members)
    pool = collections.Counter()
    for item, who in own.items():
        if who in party and item not in worn:
            pool[save.stats.get(item, '')] += 1
    pool.pop('', None)

    if info:
        _label(chars, info, save.at)
    return chars, pool


def _label(chars, info, at):
    """Attach race from SaveInfo.json, and name a subclass the blob couldn't.

    Class and subclass come from the blob (see classes_of); SaveInfo only
    decorates race here, plus a fallback subclass name when the blob's GUID
    is not yet in SUBCLASS_NAMES.  SaveInfo names no entity, and level does
    not identify a member - two of the four share one here, and matching on
    it put the monk's class on the barbarian.  The position does identify
    them: a character's coordinates in Globals equal the ones SaveInfo
    records, to well under a centimetre.  A record that finds no character is
    left off rather than guessed onto someone.
    """
    for r in info.get('Active Party', {}).get('Characters', []):
        p = r.get('Position')
        if not p:
            continue
        for ch in chars:
            q = at.get(ch.entity)
            if q and sum((x - y) ** 2 for x, y in zip(p, q)) < 1e-4:
                ch.race = r.get('Race', '')
                if ch.sub.startswith('guid:'):
                    cl = (r.get('Classes') or [{}])[0]
                    sub = cl.get('Sub', '')
                    if sub:
                        ch.sub = sub
                break
