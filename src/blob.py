"""Reader for the NewAge ECS blob (magic LSMF) found inside a BG3 save.

Layout, established empirically on QuickSave_418 and validated against
Globals.lsf and SaveInfo.json:

    0                    40 byte header: b'LSMF', version, hash
    40 .. dataEnd        component data arrays, packed back to back
    dataEnd .. names     per component: entity index arrays (u32 each)
    names                component name table, concatenated, no separators
    names+len .. EOF     component index, one 48 byte record per component

Every pointer in the file is 48 bytes lower than the byte it names.  That holds
for `ptr` in the component index, so element k of a component lives at
ptr + 48 + k * elem and `cnt` is the exact element count; and it holds just the
same for a pointer stored inside a record, which is why `deref` and `entity`
exist and why nothing here carries a per-component fudge factor.  The bias is
uniform, not a per-array header: consecutive blocks sit at ptr + cnt * elem
(measured on 321 of 355 neighbouring pairs, the rest separated only by padding
to an 8 byte boundary), and the last block ends where the index region begins.

No component is an exception. Two looked like one for a while -
ClassesComponent seemed to need +80 and SpellBookComponent seemed to take a
raw offset - and both turned out to be misread record layouts; the layouts
live in party.py.
"""

import re
import struct

REC = 48
TAG = 0x6b
BIAS = 48


class Blob:
    def __init__(self, path=None, data=None):
        if data is None:
            with open(path, 'rb') as fh:
                data = fh.read()
        self.d = d = data
        assert d[:4] == b'LSMF', 'not an LSMF blob'
        self.version = struct.unpack_from('<4B', d, 4)
        self._read_index()
        self._read_entities()
        self._build_canon()
        self._runs = None
        self._layout = None
        self.ambiguous = None

    # --- component index -------------------------------------------------

    def _read_index(self):
        d = self.d
        n = len(d)
        count = 0
        while struct.unpack_from('<I', d, n - (count + 1) * REC + 12)[0] == TAG:
            count += 1
        start = n - count * REC
        raw = []
        for k in range(count):
            raw.append(struct.unpack_from('<QIIQIIQQ', d, start + k * REC))
        total = sum(r[1] for r in raw)
        ok = re.compile(r'[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+\.[A-Za-z][A-Za-z0-9_]*$')
        for pad in range(16):
            nt = start - total - pad
            names = [d[nt + r[0]:nt + r[0] + r[1]].decode('latin1', 'replace') for r in raw]
            if all(ok.match(x) for x in names):
                break
        else:
            raise ValueError('name table not found')
        self.names_at = nt
        self.comps = {}
        self.order = []
        for r, nm in zip(raw, names):
            self.comps[nm] = dict(name=nm, elem=r[4], ver=r[5], cnt=r[6], ptr=r[7])
            self.order.append(nm)

    # --- entities --------------------------------------------------------

    def _read_entities(self):
        e = self.comps['core.v0.EntityId']
        self.ent_at = e['ptr'] + BIAS
        self.nent = e['cnt']
        self.data_end = max(c['ptr'] + c['cnt'] * c['elem'] for c in self.comps.values())
        self.index_at = self.data_end + 48

    def guid(self, i):
        """Raw 16 byte GUID of entity `i`, little endian as stored."""
        return self.d[self.ent_at + i * 16:self.ent_at + (i + 1) * 16]

    def _build_canon(self):
        # The entity table holds one slot per reference, so the same GUID
        # appears many times.  Fold every slot onto the first one that carries
        # its GUID; that first slot is the entity id everything else keys on.
        self._first = {}
        self.canon = [0] * self.nent
        for i in range(self.nent):
            g = self.guid(i)
            self.canon[i] = self._first.setdefault(g, i)

    def of_guid(self, g):
        """Canonical entity index for a raw little endian GUID, or None."""
        return self._first.get(g)

    # --- component data --------------------------------------------------

    def at(self, name, k=0):
        c = self.comps[name]
        return c['ptr'] + BIAS + k * c['elem']

    def elem(self, name, k, fmt):
        """Element k of `name` unpacked with `fmt`."""
        return struct.unpack_from(fmt, self.d, self.at(name, k))

    def deref(self, p):
        """File offset named by a pointer stored inside a record."""
        return p + BIAS

    def rows(self, name, fmt):
        """Unpack every element of `name` with struct format `fmt`."""
        c = self.comps[name]
        assert struct.calcsize(fmt) == c['elem'], (fmt, c['elem'])
        base = c['ptr'] + BIAS
        return [struct.unpack_from(fmt, self.d, base + k * c['elem'])
                for k in range(c['cnt'])]

    def pool(self, p, n, fmt):
        """`n` records of `fmt` from a pointer stored inside a record."""
        sz = struct.calcsize(fmt)
        a = self.deref(p)
        return [struct.unpack_from(fmt, self.d, a + k * sz) for k in range(n)]

    def entity(self, p):
        """Canonical entity index a stored pointer names, or None.

        Every reference between components is a pointer into core.v0.EntityId,
        biased like every other pointer, and lands on a slot that has to be
        folded onto the first slot carrying the same GUID.
        """
        off = self.deref(p) - self.ent_at
        if off < 0 or off % 16:
            return None
        i = off // 16
        return self.canon[i] if i < self.nent else None

    # --- entity index arrays ---------------------------------------------

    def _build_runs(self):
        d, a, b = self.d, self.index_at, self.names_at
        arr = struct.unpack_from('<%dI' % ((b - a) // 4), d, a)
        run = [0] * len(arr)
        for i in range(len(arr) - 2, -1, -1):
            run[i] = run[i + 1] + 1 if arr[i] < arr[i + 1] < self.nent else 0
        # Only maximal runs are candidates: a window cut out of a longer
        # increasing stretch has the right length by accident, not by layout.
        starts = {}
        for i, r in enumerate(run):
            if i and run[i - 1]:
                continue
            starts.setdefault(r + 1, []).append(i)
        self._arr, self._run, self._starts = arr, run, starts

    # --- layout of the index region ---------------------------------------

    def _build_layout(self):
        """Work out where every component's entity index array starts.

        The arrays sit back to back from `index_at`, in component order, but
        only components that actually carry one take space, and the file says
        nowhere which those are.  The layout is recovered in two steps:
        components whose element count matches exactly one maximal increasing
        run are taken as anchors, and the components between two anchors are
        resolved by the only selection whose lengths add up to the gap and
        whose blocks are all increasing.
        """
        import collections
        if self._runs is None:
            self._build_runs()
            self._runs = True
        bylen = collections.defaultdict(list)
        for L, ii in self._starts.items():
            for i in ii:
                bylen[L].append(self.index_at + i * 4)
        comps = [n for n in self.order if not n.startswith('core.')]
        cnt = {n: self.comps[n]['cnt'] for n in comps}
        anchors = [(i, n, bylen[cnt[n]][0]) for i, n in enumerate(comps)
                   if n.endswith('Component') and len(bylen.get(cnt[n], ())) == 1]
        chain = []
        for i in range(len(anchors)):
            c = [anchors[i]]
            for j in range(i + 1, len(anchors)):
                if anchors[j][2] > c[-1][2]:
                    c.append(anchors[j])
            if len(c) > len(chain):
                chain = c
        layout = {n: o for _, n, o in chain}
        segs = [(0, chain[0][0], self.index_at, (chain[0][2] - self.index_at) // 4)]
        for (i1, n1, o1), (i2, _, o2) in zip(chain, chain[1:]):
            end = o1 + cnt[n1] * 4
            segs.append((i1 + 1, i2, end, (o2 - end) // 4))
        self.ambiguous = []
        for lo, hi, off, target in segs:
            memo = {}

            def fit(i, rem):
                """Up to two ways to fill [i, hi) with `rem` u32 of index array."""
                if (i, rem) in memo:
                    return memo[(i, rem)]
                if i == hi:
                    r = [[]] if rem == 0 else []
                else:
                    o = off + (target - rem) * 4
                    c = cnt[comps[i]]
                    r = []
                    if c <= rem and self._increasing(o, c):
                        for tail in fit(i + 1, rem - c):
                            r.append([(comps[i], o)] + tail)
                            if len(r) > 1:
                                break
                    if len(r) < 2:
                        for tail in fit(i + 1, rem):
                            r.append(tail)
                            if len(r) > 1:
                                break
                memo[(i, rem)] = r[:2]
                return memo[(i, rem)]

            got = fit(lo, target)
            if len(got) > 1:
                # Two selections fill the gap equally well, so the placement of
                # the components they disagree on is a guess, not a reading.
                self.ambiguous.append(sorted(set(dict(got[0])) ^ set(dict(got[1]))))
            if got:
                layout.update(dict(got[0]))
        self._layout = layout

    def _increasing(self, off, n):
        if n <= 1:
            return True
        v = struct.unpack_from('<%dI' % n, self.d, off)
        return all(v[k] < v[k + 1] for k in range(n - 1)) and v[-1] < self.nent

    def index_of(self, name):
        """Offset of `name`'s entity index array, or None when it has none."""
        if self._layout is None:
            self._build_layout()
        return self._layout.get(name)

    def entities(self, name):
        """Entity indices carrying `name`, from the recovered layout."""
        off = self.index_of(name)
        if off is None:
            raise LookupError('no index array for %s' % name)
        cnt = self.comps[name]['cnt']
        return struct.unpack_from('<%dI' % cnt, self.d, off)

    def positions(self, name):
        """Canonical entity index -> position of its element in `name`.

        Indexing a component by the entity index itself only works when the
        index array happens to be the identity, which is true of
        StatsComponent and of nothing else.
        """
        return {self.canon[e]: k for k, e in enumerate(self.entities(name))}
