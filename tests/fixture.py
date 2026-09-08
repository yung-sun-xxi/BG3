"""Build a miniature LSMF blob whose layout is known exactly.

The real save is 5.7 MB and is never committed, so the reader is pinned against
a blob generated here instead.  Everything the reader has to infer - where the
name table is, how many entity slots there are, which components own an index
array and where each one starts - is planted deliberately, so a test can compare
what came back against what went in.

Layout is the one `blob.py` documents: every `ptr` in the component index is
48 bytes below the data it names, blocks sit back to back at ptr + cnt * elem,
and the index arrays begin where the last block ends.
"""

import struct

TAG = 0x6b
HEADER = 56          # LSMF header plus filler; the first block starts here
NAME_PAD = 5         # junk between the name table and the component index

# name, elem, cnt, index array (None when the component owns none).
# Order is the order of the records in the component index, which is the order
# the index arrays are laid out in.
PLAN = [
    ('core.v0.EntityId',             16, 12, None),
    ('game.test.v0.AlphaComponent',   8,  5, (0, 1, 2, 3, 4)),
    ('game.test.v2.NoIndexComponent', 8,  7, None),
    ('game.test.v0.Gamma',            4,  2, (2, 4)),
    ('game.test.v1.BetaComponent',    4,  3, (1, 3, 5)),
    ('game.test.v0.DeltaComponent',  16,  4, (0, 2, 4, 6)),
    # Pointers to entity slots, biased like every pointer in the file, and
    # aimed at repeated slots so folding onto the first slot is exercised.
    ('game.test.v0.RefComponent',     8,  6, (0, 1, 2, 3, 4, 5)),
    # A begin/end pair over DeltaComponent's block, so a span can be read back
    # and compared with what was planted in it.
    ('game.test.v0.SpanComponent',   16,  8, (0, 1, 2, 3, 4, 5, 6, 7)),
]

# Entity slot each RefComponent element points at.  8 and 10 repeat slot 0.
REFS = (0, 2, 4, 6, 8, 10)

# Entity slots 8..11 repeat the GUIDs of slots 0, 3, 0 and 7, the way the real
# table repeats a GUID once per reference to it.
GUID_SOURCE = [0, 1, 2, 3, 4, 5, 6, 7, 0, 3, 0, 7]

NENT = len(GUID_SOURCE)


def guid(n):
    return bytes([0xE0 + n]) + b'\xab\xcd\xef' + struct.pack('<12B', *range(n, n + 12))


def element(cid, k, elem):
    """Recognisable payload: first u32 names the component and the element."""
    return struct.pack('<I', cid * 1000 + k).ljust(elem, b'\x5a')[:elem]


def build():
    """Return (blob bytes, dict of everything a test needs to check against)."""
    blocks, ptrs, off = {}, {}, HEADER
    for cid, (name, elem, cnt, _) in enumerate(PLAN):
        if name == 'core.v0.EntityId':
            body = b''.join(guid(GUID_SOURCE[k]) for k in range(cnt))
        elif name == 'game.test.v0.RefComponent':
            base = ptrs['core.v0.EntityId']
            body = b''.join(struct.pack('<Q', base + s * 16) for s in REFS)
        elif name == 'game.test.v0.SpanComponent':
            d0 = ptrs['game.test.v0.DeltaComponent']
            body = struct.pack('<2Q', d0, d0 + 4 * 16)
            body += b'\xff' * (cnt * elem - len(body))
        else:
            body = b''.join(element(cid, k, elem) for k in range(cnt))
        assert len(body) == cnt * elem
        blocks[name], ptrs[name] = body, off - 48
        off += cnt * elem

    index_at = off
    index_off, idx = {}, b''
    for name, _, _, arr in PLAN:
        if arr is None:
            continue
        index_off[name] = index_at + len(idx)
        idx += struct.pack('<%dI' % len(arr), *arr)

    names_at = index_at + len(idx)
    table, name_off = b'', {}
    for name, _, _, _ in PLAN:
        name_off[name] = len(table)
        table += name.encode()

    records = b''
    for name, elem, cnt, _ in PLAN:
        records += struct.pack('<QIIQIIQQ', name_off[name], len(name), TAG, 0,
                               elem, 0, cnt, ptrs[name])

    d = b'LSMF' + bytes([1, 1, 0, 8]) + b'\x00' * 32 + b'\x00' * (HEADER - 40)
    d += b''.join(blocks[name] for name, _, _, _ in PLAN)
    d += idx + table + b'\x00' * NAME_PAD + records
    assert len(d) - len(records) - NAME_PAD - len(table) == names_at

    canon = [GUID_SOURCE.index(g) for g in GUID_SOURCE]
    return d, dict(plan=PLAN, ptrs=ptrs, index_at=index_at, names_at=names_at,
                   index_off=index_off, nent=NENT, canon=canon,
                   refs=[canon[s] for s in REFS],
                   span=[5 * 1000 + k for k in range(4)])


if __name__ == '__main__':
    d, _ = build()
    print(len(d), 'bytes')
