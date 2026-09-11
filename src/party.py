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
LEVELUP = 'game.progression.v3.LevelUpComponent'

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
# LevelUpComponent is a span of 8 byte entries, one per character level;
# each entry points at a 96 byte progression record.  Measured on the four
# party members, whose levels are 8/9/8/9 and whose entry counts are the
# same four numbers.
LEVELUP_REC = 8
PROGRESS_REC = 96

def guid_text(raw):
    """The 16 stored bytes as the GUID string Larian itself writes.

    Every group is little endian, the last eight bytes included, and that last
    part is the trap: `uuid.UUID(bytes_le=raw)` swaps only the first three
    groups and leaves the tail as stored.  The result round-trips inside this
    repository and matches nothing outside it, which is why class GUIDs used to
    be named by guesswork and feat GUIDs could not be named at all.

        stored bytes    e2014078 6dc9 5341 b6be db2a5aef92bc
        bytes_le        784001e2-c96d-4153-b6be-db2a5aef92bc   ours, wrong
        Larian          784001e2-c96d-4153-beb6-2adbef5abc92   Sorcerer

    Checked against three sources that agree on the second form: the
    BG3-Community-Library dictionaries, the Feats.lsx of published mods, and
    this save itself, where Tav's two feats come out WarCaster and Actor,
    exactly as his sheet reads.

    `lsf.read_value` still prints the first form for type 31 and `Save._pairs`
    converts it straight back with `bytes_le`; that pair round-trips and is
    left alone.  Everything meant for human eyes, or for comparison with any
    source outside this repository, goes through this function.
    """
    tail = bytes(x for i in range(8, 16, 2) for x in (raw[i + 1], raw[i]))
    return str(uuid.UUID(bytes=raw[3::-1] + raw[5:3:-1] + raw[7:5:-1] + tail))


# Class, subclass and feat GUIDs, in the text form guid_text produces.  Taken
# whole from BG3-Community-Library (ScriptExtender/Lua/IdDictionary/StaticData)
# rather than from this save: a table covering only what one save happens to
# hold has to be extended every time somebody respecs.  The four subclasses
# this save does hold agree with it exactly.
CLASS_NAMES = {
    'd8cadb42-0ff9-4049-afaf-e5d78d06a399': 'Barbarian',
    '92cd50b6-eb1b-4824-8adb-853e90c34c90': 'Bard',
    '114e7aee-d1d4-4371-8d90-8a2080592faf': 'Cleric',
    '457d0a6e-9da8-4f95-a225-18382f0e94b5': 'Druid',
    '721dfac3-92d4-41f5-b773-b7072a86232f': 'Fighter',
    'c4598bdb-fc07-40dd-a62c-90cc138bd76f': 'Monk',
    'ff4d9497-023c-434a-bd14-82fc367e991c': 'Paladin',
    '36be18ba-23db-4dff-bfa6-ae105ce43144': 'Ranger',
    'e8b1eab0-ef11-40a2-8a0b-cee8d062bf2a': 'Rogue',
    '784001e2-c96d-4153-beb6-2adbef5abc92': 'Sorcerer',
    'b4225a4b-4bbe-4d97-9e3c-4719dbd1487c': 'Warlock',
    'a865965f-501b-46e9-9eaa-7748e8c04d09': 'Wizard',
}

SUBCLASS_NAMES = {
    'e6a0eb75-7a01-4f40-8563-24ba2615e99b': 'AbjurationSchool',
    'b36d247e-d39f-4ae9-9476-3ec315c55789': 'Ancients',
    'ede4778e-7602-440f-9075-b4bc8dc31cea': 'ArcaneTricker',
    '733ddf8c-9ec4-4c5a-85e3-c70fd3df3c24': 'Archfey',
    'b53a8061-f31d-4985-adfe-d4d691a918d9': 'Assassin',
    'e668c6f1-5149-4b10-ab7e-3637ed444066': 'BattleMaster',
    '6fd9547d-cc28-400e-bfa9-3a85baa70f24': 'BeastMaster',
    '32eee7d8-1b2f-4de5-b9ee-78fbd286c6ef': 'BerserkerPath',
    '0a01dc6b-ab1a-4c0e-8a5e-4787fe1f2caf': 'Champion',
    '7458da78-34b7-4150-a42f-37197ab04510': 'CircleOfTheLand',
    '3eab0689-e51b-4634-a690-0375d3cb2716': 'CircleOfTheMoon',
    '4b61af6c-4a44-436e-aa0a-0d11a2d6b8ee': 'CircleOfTheSpores',
    '7a3feb8d-dda7-46ec-9029-1f302f537432': 'ConjurationSchool',
    '1c761ad0-6f5f-409e-ac1d-ddf6f85c1fc4': 'Devotion',
    '7577b0e1-a517-4f82-8f72-05a227dc5e88': 'DivinationSchool',
    '36286b0a-26f9-4b4e-9311-fd1404301d20': 'DragonicBloodline',
    'b722614a-303f-411a-bb19-a1882ad1f4cc': 'EldritchKnight',
    '46d31950-6917-444e-ac87-706702825215': 'EnchantmentSchool',
    'c059dca1-c17d-4dce-8260-83ede5070eac': 'EvocationSchool',
    '8866db28-7dda-4fd6-93ed-20eca16314f0': 'Fiend',
    '22894c32-54cf-49ea-b366-44bfcf01bb2a': 'FourElements',
    'd5f10e55-84e3-409b-aa64-2098c9550319': 'GloomStalker',
    'e1e4a21f-9405-46ec-81a0-ccc8d58d9736': 'GreatOldOne',
    '0aa1cff9-c45f-4d00-a95b-99a7aa96dd06': 'Hunter',
    '436c9e1a-3a39-48dd-b753-7cee1bd19c00': 'IllusionSchool',
    'ebe18794-b5e1-41c4-befa-4b9d6922b0ec': 'KnowledgeDomain',
    '4b5da2f5-b999-4623-8bff-a63df5560fb3': 'LifeDomain',
    'c54d7591-b305-4f22-b2a7-1bf5c4a3470a': 'LightDomain',
    'd21368ac-c776-465c-9dcf-6123dd52734f': 'LoreCollege',
    '6dec76d0-df22-411c-8a78-3d6fb843ae50': 'NatureDomain',
    'fbb8347b-20e3-4846-ba91-0552cd12fc5f': 'NecromancySchool',
    '2a5e3097-384c-4d29-8d6e-054fdfd26b80': 'OpenHand',
    'bf46d73f-d406-4cb8-9a1d-e6e758ca02c7': 'Shadow',
    'd379fdae-b401-4731-8d50-277c73919ae3': 'StormSorcery',
    'c4bd5252-d68a-4330-9431-5e8ab24c5f29': 'SwordsCollege',
    '89bacf1b-8f15-4972-ada7-bf59c7c78441': 'TempestDomain',
    '32c7b8df-a6ec-4848-a9db-c0dce781beb9': 'Thief',
    '2e585948-d775-451d-b58b-15b75321d11e': 'TotemWarriorPath',
    'a12f2924-30b4-4185-9db9-2c5b383ff449': 'TransmutationSchool',
    'f013d01b-3310-43f7-81bf-a51130442b5e': 'TrickeryDomain',
    '2b46330d-0ada-4eb5-a131-3d250a41ca6a': 'ValorCollege',
    '3cc3d397-c47d-4966-87ae-88827f73f645': 'Vengeance',
    'b9ccf90e-b35b-4b73-b896-8ed2d32ae8c6': 'WarDomain',
    '14374d37-a70e-41a8-9dc5-85a23f8b5dd2': 'WildMagic',
    'd6bf00fc-3518-4d63-ba8b-03532c1abc4d': 'WildMagicPath',
}

# ASI is the ability improvement; a character who took one shows it here.
FEAT_NAMES = {
    '010f717e-c6e2-45cf-bbf9-298a72db4cad': 'Sharpshooter',
    '019564a0-f136-4139-94ea-040f94bbaf19': 'Skilled',
    '0a3b07bf-a806-4c77-9c8f-6e7c0965f9dd': 'Mobile',
    '0de08fff-ab18-442f-a0b1-f53e7be04c03': 'HeavyArmorMaster',
    '17ac3605-9a8a-41f3-9504-ffc17fffa03e': 'MediumArmorMaster',
    '1e0ac3c4-5bb5-42d7-941c-9de58d919732': 'MagicInitiateWarlock',
    '1e1a9a4d-38f4-4a05-b080-d32c2b872250': 'MagicInitiateDruid',
    '26c6990b-d9f0-41a2-8108-209789fafc18': 'MagicInitiateWizard',
    '28e5fed3-bd41-4b74-ab48-b8e824ad3443': 'MagicInitiateCleric',
    '3fe71254-d1b2-44c7-886c-927552fe5f2e': 'ShieldMaster',
    '455fc2d5-1c77-40e7-a010-0b51044ae74b': 'MartialAdept',
    '4f744a6e-8589-4a46-89ab-a95415a73245': 'MagicInitiateBard',
    '56c3c247-35cf-4ffd-86dd-7d249cc1808f': 'Durable',
    '60dfd716-3ba8-4611-90ee-018b59775b1d': 'Performer',
    '661eee63-ff91-4f29-9f21-3a974c9d6fe5': 'DefensiveDuelist',
    '681d5307-f0ed-4c94-8cf0-db0c51116f56': 'ModeratelyArmored',
    '71b65667-0eac-4e62-b878-fa862e88ebbf': 'DungeonDelver',
    '7bc235ac-7eeb-49d3-8249-c3313d87af75': 'HeavilyArmored',
    '816b1554-9384-49e9-aaa0-05dd622e60f7': 'Sentinel',
    '93d41226-d7af-495c-b023-08a6af077962': 'MagicInitiateSorcerer',
    '94a78b4c-a8f2-404f-8cdc-2d454c13cb97': 'CrossbowExpert',
    'a533fde7-ee0a-46ce-92e2-9763201a54d2': 'MageSlayer',
    'b13c4744-1d45-42da-b92c-e09f598ab1c3': 'Resilient',
    'b153e75c-27a2-4412-95cd-60b477121679': 'WeaponMaster',
    'b441c722-e4d4-4702-861a-039bfd77c124': 'LightlyArmored',
    'be0889d2-f9aa-472d-b942-592bff0f1ef3': 'TavernBrawler',
    'c02f22c9-9a06-4001-b917-4d5cf09be399': 'SpellSniper',
    'c09815f7-282b-4ccf-bd89-a51caa1b550f': 'GreatWeaponMaster',
    'cdcbc538-883b-401c-a8ed-1373fb6d1720': 'Actor',
    'cec2d95b-451c-40f8-8e17-9e547d363e8e': 'ElementalAdept',
    'd215b9ad-9753-4d74-8ff9-24bf1dce53d6': 'ASI',
    'd674aa33-8633-4b67-8623-b6788f0d5fc4': 'Athlete',
    'd84c7f36-8c5b-4b17-b95a-e1da725f9004': 'Lucky',
    'e061a323-3430-4cff-88d3-5eae7a1779a4': 'SavageAttacker',
    'e8d1e7f6-d841-48ff-a83c-f1aaa16597ff': 'Tough',
    'eab25714-15d6-4e26-b809-3fad832d0484': 'Charger',
    'ed4e367d-d136-4285-abac-077147e84cf2': 'WarCaster',
    'f3370916-6b35-4c5b-af36-19ca888cb43e': 'RitualCaster',
    'f57bd72c-be64-4855-9e3a-bb7d7665e656': 'Alert',
    'f692f7b5-ffd5-4942-91a1-a71ebb2f5e7c': 'DualWielder',
    'fdf0be80-cc1e-4501-bd2e-7a1ea737362c': 'PolearmMaster',
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
                 'abilities', 'proficiency', 'worn', 'spells', 'prepared', 'feats',
                 'container')

    def __init__(self, entity):
        self.entity = entity
        self.name = str(entity)
        self.level = 0
        self.cls = self.sub = self.race = ''
        self.classes = []        # [{cls, sub, level, cls_guid, sub_guid}, ...]
        self.feats = []          # [{level, feat, feat_guid}, ...], levels 4 and 8
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


def literal_flag(b):
    """The flag value that marks a string record as a literal in this save.

    Records in display_names and in SpellBookPrepares alternate: a localisation
    handle flagged 0, then a literal flagged with one save-wide number.  That
    number is not a constant - QuickSave_418 used 514 and QuickSave_430 uses
    675 - so it is read off the file: the only non-zero flag display_names
    carries.  Cached on the blob, because every character asks for it.
    """
    got = getattr(b, '_literal_flag', None)
    if got is not None:
        return got
    seen = collections.Counter()
    for e, k in b.positions(NAMES).items():
        beg, end = b.elem(NAMES, k, '<2Q' + 'x' * (b.comps[NAMES]['elem'] - 16))[:2]
        for _, _, fl in b.pool(beg, max(0, (end - beg) // 16), '<QII'):
            if fl:
                seen[fl] += 1
    if not seen:
        raise ValueError('display_names carries no non-zero string flag')
    b._literal_flag = seen.most_common(1)[0][0]
    return b._literal_flag


def display_name(b, e, pos=None):
    """Player-facing name of an entity, or None when it has no custom one.

    The component holds a span of 16 byte records - string pointer, length,
    flags - and only the records carrying the save's literal flag hold a
    literal.  The rest are localisation handles, which need files this reader
    does not have.  The flag is per save, not a constant: see `literal_flag`.
    """
    pos = pos if pos is not None else b.positions(NAMES)
    if e not in pos:
        return None
    lit = literal_flag(b)
    beg, end = b.elem(NAMES, pos[e], '<2Q' + 'x' * (b.comps[NAMES]['elem'] - 16))[:2]
    got = None
    for p, ln, fl in b.pool(beg, max(0, (end - beg) // 16), '<QII'):
        if fl != lit or ln == 0 or ln > 200:
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
        cls_guid = guid_text(cg)
        sub_guid = guid_text(sg)
        cls = CLASS_NAMES.get(cls_guid, 'guid:' + cls_guid.replace('-', '')[:8])
        if sg == b'\x00' * 16:
            sub = ''
        else:
            sub = SUBCLASS_NAMES.get(sub_guid, 'guid:' + sub_guid.replace('-', '')[:8])
        out.append(dict(cls=cls, sub=sub, level=level,
                         cls_guid=cls_guid, sub_guid=sub_guid))
    return out


def feats_of(b, e, pos=None):
    """(level, feat name) for every feat a character picked, in level order.

    LevelUpComponent is a span at beg+48 over 8 byte entries, one per level.
    Each entry is a pointer to a 96 byte progression record laid out as four
    GUIDs and then bookkeeping: class at offset 0, subclass at 16 on the level
    the subclass is chosen, and the feat at 32 on the levels that grant one.
    An all-zero GUID means the slot is empty, which is every level but 4 and 8.

    Measured on the four party members: entry counts come out 8/9/8/9, the same
    as their levels, the class GUID repeats on every level and equals the one
    ClassesComponent reports, and Tav's two feats resolve to the two his sheet
    names.  A feat GUID with no entry in FEAT_NAMES is reported as 'guid:' plus
    its first 8 hex characters rather than dropped.
    """
    pos = pos if pos is not None else b.positions(LEVELUP)
    if e not in pos:
        return []
    beg, end = b.elem(LEVELUP, pos[e], '<2Q')
    out = []
    for k in range(max(0, (end - beg) // LEVELUP_REC)):
        ptr, = struct.unpack_from('<I', b.d, b.deref(beg) + k * LEVELUP_REC)
        rec = b.deref(ptr)
        g = b.d[rec + 32:rec + 48]
        if g == b'\x00' * 16:
            continue
        t = guid_text(g)
        out.append(dict(level=k + 1, feat=FEAT_NAMES.get(t, 'guid:' + t.replace('-', '')[:8]),
                        feat_guid=t))
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
    length, flag - and only records carrying the save's literal flag with a
    length in (0, 200] decode to a literal, the same filter display_name uses.
    This is a subset of what spells_of returns, not a separate vocabulary.
    """
    pos = pos if pos is not None else b.positions(PREPARES)
    if e not in pos:
        return []
    lit = literal_flag(b)
    beg, end = b.elem(PREPARES, pos[e],
                       '<2Q' + 'x' * (b.comps[PREPARES]['elem'] - 16))[:2]
    out = []
    for p, ln, fl in b.pool(beg, max(0, (end - beg) // META_REC), '<QII8x'):
        if fl != lit or ln == 0 or ln > 200:
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
    fpos = b.positions(LEVELUP)

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
        ch.feats = feats_of(b, e, fpos)
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
