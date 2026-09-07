import struct, sys, lz4.block, lz4.frame, zstandard, zlib

def decomp(blob, unc, flags):
    m = flags & 0x0F
    if m == 0 or unc == 0: return blob
    if blob[:4] == b'\x04\x22\x4d\x18': return lz4.frame.decompress(blob)
    if m == 1: return zlib.decompress(blob)
    if m == 2: return lz4.block.decompress(blob, uncompressed_size=unc)
    if m == 3: return zstandard.ZstdDecompressor().decompress(blob, max_output_size=unc)
    raise Exception(m)

class LSF:
    def __init__(self, path):
        d = open(path,'rb').read()
        assert d[:4] == b'LSOF'
        self.ver = struct.unpack_from('<I', d, 4)[0]
        o = 8
        eng = struct.unpack_from('<Q', d, o)[0]; o += 8
        (su, sd, ku, kd, nu, nd, au, ad, vu, vd) = struct.unpack_from('<10I', d, o); o += 40
        flags = d[o]; o += 4
        meta_fmt = struct.unpack_from('<I', d, o)[0]; o += 4
        self.meta_fmt = meta_fmt
        p = o
        def take(n): 
            nonlocal p
            b = d[p:p+n]; p += n; return b
        strings = decomp(take(sd), su, flags)
        keys    = decomp(take(kd), ku, flags)
        nodes   = decomp(take(nd), nu, flags)
        attrs   = decomp(take(ad), au, flags)
        self.values = decomp(take(vd), vu, flags)
        self.hdr = dict(ver=self.ver, meta_fmt=meta_fmt, flags=hex(flags),
                        nodes_sz=len(nodes), attrs_sz=len(attrs), vals_sz=len(self.values))
        # --- string hash table ---
        self.names = []
        q = 0
        nbuckets = struct.unpack_from('<I', strings, q)[0]; q += 4
        for _ in range(nbuckets):
            cnt = struct.unpack_from('<H', strings, q)[0]; q += 2
            bucket = []
            for _ in range(cnt):
                l = struct.unpack_from('<H', strings, q)[0]; q += 2
                bucket.append(strings[q:q+l].decode('utf-8','replace')); q += l
            self.names.append(bucket)
        self.nodes_raw, self.attrs_raw = nodes, attrs
        self.node_sz = 12 if len(nodes) % 12 == 0 and len(nodes) % 16 else (16 if len(nodes) % 16 == 0 else 12)
        self.attr_sz = 12 if len(attrs) % 12 == 0 and len(attrs) % 16 else (16 if len(attrs) % 16 == 0 else 12)

    def name(self, idx):
        b, e = idx >> 16, idx & 0xFFFF
        try: return self.names[b][e]
        except: return f'<bad {b}/{e}>'

if __name__ == '__main__':
    f = LSF(sys.argv[1])
    print(f.hdr)
    print('buckets:', len(f.names), 'strings:', sum(len(b) for b in f.names))
    print('node entry size guess:', f.node_sz, 'count', len(f.nodes_raw)//f.node_sz)
    print('attr entry size guess:', f.attr_sz, 'count', len(f.attrs_raw)//f.attr_sz)
    print('sample strings:', [s for b in f.names for s in b][:25])
    for sz in (12,16):
        if len(f.nodes_raw) % sz: continue
        ok = 0; n = len(f.nodes_raw)//sz
        for i in range(min(n, 400)):
            ni = struct.unpack_from('<I', f.nodes_raw, i*sz)[0]
            if not f.name(ni).startswith('<bad'): ok += 1
        print(f'  nodes as {sz}B: {ok}/{min(n,400)} valid names')

# ---------------- full tree reader ----------------
TYPES = {0:'None',1:'Byte',2:'Short',3:'UShort',4:'Int',5:'UInt',6:'Float',7:'Double',
 8:'IVec2',9:'IVec3',10:'IVec4',11:'Vec2',12:'Vec3',13:'Vec4',14:'Mat2',15:'Mat3',16:'Mat3x4',
 17:'Mat4x3',18:'Mat4',19:'Bool',20:'String',21:'Path',22:'FixedString',23:'LSString',
 24:'ULongLong',25:'ScratchBuffer',26:'Long',27:'Int8',28:'TranslatedString',29:'WString',
 30:'LSWString',31:'UUID',32:'Int64',33:'TranslatedFSString'}

def read_value(buf, off, t, ln):
    b = buf[off:off+ln]
    if t == 1:  return b[0]
    if t == 2:  return struct.unpack('<h', b)[0]
    if t == 3:  return struct.unpack('<H', b)[0]
    if t == 4:  return struct.unpack('<i', b)[0]
    if t == 5:  return struct.unpack('<I', b)[0]
    if t == 6:  return struct.unpack('<f', b)[0]
    if t == 7:  return struct.unpack('<d', b)[0]
    if t == 19: return bool(b[0])
    if t == 24 or t == 32 or t == 26: return struct.unpack('<q', b[:8])[0]
    if t == 27: return struct.unpack('<b', b)[0]
    if t == 31 and ln == 16:
        a,bb,c = struct.unpack('<IHH', b[:8]); d = b[8:]
        return f'{a:08x}-{bb:04x}-{c:04x}-{d[:2].hex()}-{d[2:].hex()}'
    if t in (20,21,22,23,29,30): return b.split(b'\0')[0].decode('utf-8','replace')
    if t in (28,33):
        try: return b[6:].split(b'\0')[0].decode('utf-8','replace')
        except: return b.hex()
    if t in (11,12,13): return struct.unpack('<%df'%(ln//4), b)
    if t in (8,9,10):   return struct.unpack('<%di'%(ln//4), b)
    return b.hex()

class Node:
    __slots__=('name','attrs','children','parent')
    def __init__(s,name,parent): s.name=name; s.attrs={}; s.children=[]; s.parent=parent

def build(f):
    n = len(f.nodes_raw)//12
    nodes = []
    for i in range(n):
        ni, first_attr, parent = struct.unpack_from('<Iii', f.nodes_raw, i*12)
        nodes.append(Node(f.name(ni), parent))
    for i,nd in enumerate(nodes):
        if nd.parent >= 0 and nd.parent < n: nodes[nd.parent].children.append(nd)
    # attributes, 12-byte V3: nameIdx, typeAndLength, nodeIndex ; values sequential
    a = len(f.attrs_raw)//12
    off = 0
    for i in range(a):
        ni, tl, node_i = struct.unpack_from('<IIi', f.attrs_raw, i*12)
        t, ln = tl & 0x3F, tl >> 6
        if 0 <= node_i < n:
            nodes[node_i].attrs[f.name(ni)] = (TYPES.get(t,t), read_value(f.values, off, t, ln))
        off += ln
    roots = [nd for nd in nodes if nd.parent < 0]
    return nodes, roots

def dump(nd, d=0, maxd=6, out=None):
    pad = '  '*d
    out.append(f'{pad}<{nd.name}> ' + ', '.join(f'{k}={v[1]!r}' for k,v in list(nd.attrs.items())[:8]))
    if d < maxd:
        for c in nd.children[:12]: dump(c, d+1, maxd, out)
