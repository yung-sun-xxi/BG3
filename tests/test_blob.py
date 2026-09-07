"""What the LSMF reader must get right, checked against a planted blob.

Every case here corresponds to a mistake that was actually made while the format
was being reversed, so a green run means those mistakes have not come back.
"""

import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import blob
import fixture


class BlobTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d, cls.want = fixture.build()
        fh = tempfile.NamedTemporaryFile(suffix='.bin', delete=False)
        fh.write(d)
        fh.close()
        cls.path = fh.name
        cls.b = blob.Blob(cls.path)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.path)

    def test_index_records(self):
        for name, elem, cnt, _ in self.want['plan']:
            c = self.b.comps[name]
            self.assertEqual((c['elem'], c['cnt'], c['ptr']),
                             (elem, cnt, self.want['ptrs'][name]), name)
        self.assertEqual(self.b.order, [p[0] for p in self.want['plan']])

    def test_name_table_survives_padding(self):
        self.assertEqual(self.b.names_at, self.want['names_at'])

    def test_entity_count_is_the_element_count(self):
        # `cnt` is exact.  Treating the uniform 48 byte pointer bias as a
        # per-array header cost three entity slots for a while.
        self.assertEqual(self.b.nent, self.want['nent'])
        self.assertEqual(self.b.ent_at, self.want['ptrs']['core.v0.EntityId'] + 48)

    def test_repeated_guids_fold_onto_the_first_slot(self):
        self.assertEqual(list(self.b.canon), self.want['canon'])
        for i, c in enumerate(self.want['canon']):
            self.assertEqual(self.b.of_guid(self.b.guid(i)), c, i)

    def test_element_addressing(self):
        # Off by one element and off by 48 bytes both land on a neighbour, so
        # every element of every component is compared, not just the first.
        for cid, (name, elem, cnt, _) in enumerate(self.want['plan']):
            if name == 'core.v0.EntityId':
                continue
            for k in range(cnt):
                got = self.b.d[self.b.at(name, k):self.b.at(name, k) + elem]
                self.assertEqual(got, fixture.element(cid, k, elem), (name, k))
            rows = self.b.rows(name, '<I' + 'B' * (elem - 4))
            self.assertEqual([r[0] for r in rows],
                             [cid * 1000 + k for k in range(cnt)], name)

    def test_blocks_are_packed_without_a_header(self):
        # The invariant the docstring rests on: the last element of a block ends
        # exactly where the next block's first element begins.
        cs = sorted(self.b.comps.values(), key=lambda c: c['ptr'])
        for c, n in zip(cs, cs[1:]):
            self.assertEqual(c['ptr'] + 48 + c['cnt'] * c['elem'], n['ptr'] + 48,
                             (c['name'], n['name']))
        self.assertEqual(self.b.index_at, self.want['index_at'])

    def test_index_arrays_are_recovered(self):
        for name, _, _, arr in self.want['plan']:
            if arr is None:
                continue
            self.assertEqual(self.b.index_of(name), self.want['index_off'][name], name)
            self.assertEqual(self.b.entities(name), arr, name)

    def test_components_without_an_index_array_stay_empty(self):
        # NoIndexComponent sits between an anchor and the component the gap
        # actually belongs to; claiming a slice for it would shift everything
        # after it.
        self.assertIsNone(self.b.index_of('game.test.v2.NoIndexComponent'))
        with self.assertRaises(LookupError):
            self.b.entities('game.test.v2.NoIndexComponent')

    def test_layout_reports_no_guesses(self):
        self.b.index_of('game.test.v0.Gamma')
        self.assertEqual(self.b.ambiguous, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
