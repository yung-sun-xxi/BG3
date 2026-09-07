import struct, sys, os, zlib
import lz4.block, zstandard

def unpack(path, outdir):
    d = open(path,'rb').read()
    assert d[:4] == b'LSPK', 'not LSPK'
    ver, flo, fls, flags, prio = struct.unpack_from('<IQIBB', d, 4)
    nparts = struct.unpack_from('<H', d, 4+4+8+4+1+1+16)[0]
    print(f'LSPK v{ver} parts={nparts} listOffset={flo} listSize={fls}')
    nfiles, csize = struct.unpack_from('<II', d, flo)
    raw = lz4.block.decompress(d[flo+8:flo+8+csize], uncompressed_size=nfiles*272)
    os.makedirs(outdir, exist_ok=True)
    out=[]
    for i in range(nfiles):
        e = raw[i*272:(i+1)*272]
        name = e[:256].split(b'\0')[0].decode('utf-8')
        o1,o2,part,fl,disk,unc = struct.unpack_from('<IHBBII', e, 256)
        off = o1 | (o2<<32)
        blob = d[off:off+disk]
        m = fl & 0x0F
        if unc == 0 or m == 0: data = blob
        elif m == 1: data = zlib.decompress(blob)
        elif m == 2: data = lz4.block.decompress(blob, uncompressed_size=unc)
        elif m == 3: data = zstandard.ZstdDecompressor().decompress(blob, max_output_size=unc)
        else: raise Exception(f'compression {m}')
        p = os.path.join(outdir, name.replace('\\','/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p,'wb').write(data)
        out.append((name, len(data), m))
        print(f'  {name:40s} {len(data):>10,} bytes  (method {m})')
    return out

if __name__ == '__main__':
    unpack(sys.argv[1], sys.argv[2])
