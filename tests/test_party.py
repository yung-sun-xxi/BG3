"""Tests for the game side of the reader that need no save.

test_blob.py pins the container format; this file pins the two things above it
that a save cannot teach us and that have already been got wrong once: how a
GUID turns into text, and that the name tables are keyed in that same text.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

import party


# The Sorcerer class GUID as this save stores it, byte for byte.
SORCERER_RAW = bytes.fromhex('e20140786dc95341b6bedb2a5aef92bc')
SORCERER_TEXT = '784001e2-c96d-4153-beb6-2adbef5abc92'


class GuidText(unittest.TestCase):

    def test_larian_form_swaps_the_tail_as_well(self):
        self.assertEqual(party.guid_text(SORCERER_RAW), SORCERER_TEXT)

    def test_bytes_le_is_not_the_larian_form(self):
        # The old rendering. It differs only in the last eight bytes, which is
        # exactly why it went unnoticed and matched nothing outside this repo.
        import uuid
        self.assertNotEqual(str(uuid.UUID(bytes_le=SORCERER_RAW)), SORCERER_TEXT)

    def test_a_guid_of_zeroes_stays_zeroes(self):
        self.assertEqual(party.guid_text(b'\x00' * 16),
                         '00000000-0000-0000-0000-000000000000')


class NameTables(unittest.TestCase):

    def test_class_table_is_keyed_in_the_larian_form(self):
        self.assertEqual(party.CLASS_NAMES[SORCERER_TEXT], 'Sorcerer')

    def test_every_key_is_a_well_formed_guid(self):
        import uuid
        for table in (party.CLASS_NAMES, party.SUBCLASS_NAMES, party.FEAT_NAMES):
            for k in table:
                uuid.UUID(k)

    def test_all_twelve_classes_are_named(self):
        self.assertEqual(len(party.CLASS_NAMES), 12)
        self.assertIn('Bard', party.CLASS_NAMES.values())

    def test_no_table_lost_lines(self):
        # Sizes as lifted from BG3-Community-Library. A table that shrinks has
        # been truncated by an edit, and the loss is silent: a missing GUID
        # comes out as 'guid:xxxxxxxx', which reads like an unknown feat rather
        # than like a broken table.
        self.assertEqual(len(party.SUBCLASS_NAMES), 45)
        self.assertEqual(len(party.FEAT_NAMES), 41)

    def test_the_ability_improvement_is_a_feat_like_any_other(self):
        # A character who spent a level-up on ability scores rather than on a
        # named feat shows ASI here, so 'no feat' and 'stats instead' are
        # distinguishable without opening the game.
        self.assertIn('ASI', party.FEAT_NAMES.values())

    def test_this_saves_four_subclasses_are_named(self):
        for name in ('StormSorcery', 'OpenHand', 'TrickeryDomain', 'BerserkerPath'):
            self.assertIn(name, party.SUBCLASS_NAMES.values())


if __name__ == '__main__':
    unittest.main(verbosity=2)
