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

import blob
import lsf

# Equipment slot numbers, read off the save rather than guessed: a container
# marked Type 1 declares 19 slots, and the items sitting in them line up with
# what the number has to mean.  13, 14 and 15 are never filled in this save;
# they are the cosmetic wings, horns and overhead slots.
SLOTS = {
    0: 'шлем', 1: 'нагрудник', 2: 'плащ', 3: 'основная рука',
    4: 'вторая рука', 5: 'дальний бой', 6: 'дальний бой, вторая рука',
    7: 'кольцо 1', 8: 'бельё', 9: 'сапоги', 10: 'перчатки', 11: 'амулет',
    12: 'кольцо 2', 16: 'инструмент', 17: 'лагерная одежда',
    18: 'лагерная обувь',
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

# Two spans in this file do not take the uniform pointer bias, and both were
# measured rather than assumed.
#   ClassesComponent needs +80 from the raw begin, not +48.  Why has never been
#   established; the record is 40 bytes and every character in this save has
#   exactly one, so "+80 bytes" and "+2 records" cannot be told apart.
#   SpellBookComponent's begin is a plain file offset, +0.  With the uniform
#   +48 nothing decodes at all; with +-72, one record either way, the share of
#   books that open on Projectile_Jump falls from 196 of 444 to 7 and 0.
# The pointers stored *inside* those pools are biased like everything else.
CLASS_SKEW = 80
CLASS_REC = 40
SPELL_REC = 72


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
    __slots__ = ('entity', 'name', 'level', 'cls', 'sub', 'race',
                 'abilities', 'proficiency', 'worn', 'spells', 'container')

    def __init__(self, entity):
        self.entity = entity
        self.name = str(entity)
        self.level = 0
        self.cls = self.sub = self.race = ''
        self.abilities = {}
        self.proficiency = 0
        self.worn = {}          # slot number -> (entity, stat id)
        self.spells = []
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


def spells_of(b, e, pos=None):
    """Every spell name in a character's book, common actions included.

    SpellBookComponent is a span over SpellData, 72 bytes a record, and that
    span is a plain file offset.  At offset 48 of a record sits a pointer to a
    SpellId, and a SpellId holds a pointer and a length into the shared string
    arena - the names run together there with no separators, so the length is
    not optional.  Both of those pointers are biased.
    """
    pos = pos if pos is not None else b.positions(SPELLBOOK)
    if e not in pos:
        return []
    beg, end = b.elem(SPELLBOOK, pos[e], '<2Q')
    out = []
    for k in range(max(0, (end - beg) // SPELL_REC)):
        rec = struct.unpack_from('<48xQ16x', b.d, beg + k * SPELL_REC)
        p, ln = b.pool(rec[0], 1, '<8xQI4x')[0]
        if ln == 0 or ln > 200:
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

    chars = []
    for e in members:
        ch = Character(e)
        ch.name = display_name(b, e, npos) or ('сущность %d' % e)
        if e in stpos:
            v = b.elem(STATS, stpos[e], '<9I')
            ch.abilities = dict(zip(ABILITIES, v[2:8]))
            ch.proficiency = v[8]
        if e in clpos:
            beg, end = b.elem(CLASSES, clpos[e], '<2Q')
            if end > beg:
                ch.level = struct.unpack_from('<I', b.d, beg + CLASS_SKEW)[0]
        ch.container = conts.get(e)
        if ch.container is not None:
            for s, item in slots_of(b, ch.container, cpos).items():
                ch.worn[s] = (item, save.stats.get(item, ''))
        ch.spells = spells_of(b, e, spos)
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
    """Attach class, subclass and race from SaveInfo.json.

    SaveInfo names no entity, and level does not identify a member - two of the
    four share one here, and matching on it put the monk's class on the
    barbarian.  The position does identify them: a character's coordinates in
    Globals equal the ones SaveInfo records, to well under a centimetre.  A
    record that finds no character is left off rather than guessed onto someone.
    """
    for r in info.get('Active Party', {}).get('Characters', []):
        p = r.get('Position')
        if not p:
            continue
        for ch in chars:
            q = at.get(ch.entity)
            if q and sum((x - y) ** 2 for x, y in zip(p, q)) < 1e-4:
                cl = (r.get('Classes') or [{}])[0]
                ch.cls, ch.sub = cl.get('Main', ''), cl.get('Sub', '')
                ch.race = r.get('Race', '')
                break
