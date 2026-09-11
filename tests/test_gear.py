"""Tests for what counts as gear, and for how the gear table grows.

The save never marks an item as wearable, so gear.py decides from the stat id
and from who is seen wearing what.  These pin the mistakes already made while
getting there - substring matching filed Daggeroot under weapons and
NightOrchid under torches - and the one promise the table makes: a `yes` or a
`no` written by hand is never overwritten by the reader.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

import gear


class KindFromStatId(unittest.TestCase):

    def test_last_word_names_the_slot(self):
        self.assertEqual(gear.kind_of('MAG_Thunder_Reverberation_Gloves'), 'hands')
        self.assertEqual(gear.kind_of('UNI_MassHealRing'), 'ring')
        self.assertEqual(gear.kind_of('ACT1_HAG_HagMask'), 'head')
        self.assertEqual(gear.kind_of('ARM_TalismanOfJergal'), 'amulet')

    def test_weapon_compounds_match_on_their_suffix(self):
        self.assertEqual(gear.kind_of('MAG_Drowelf_SpiderSnare_Longsword'), 'weapon')
        self.assertEqual(gear.kind_of('MAG_BG_Harold_HeavyCrossbow'), 'weapon')
        self.assertEqual(gear.kind_of('MAG_Duergar_Sword_KingsKnife'), 'weapon')

    def test_words_match_whole_not_as_substrings(self):
        # Daggeroot is not a dagger, Bonecap is not a cap, NightOrchid holds
        # no torch and ThievesTools no vest.
        for sid in ('ALCH_Extract_Daggeroot', 'ALCH_Extract_Bonecap',
                    'ALCH_Ingredient_Herb_NightOrchid', 'OBJ_Kit_ThievesTools'):
            self.assertFalse(gear.looks_like_gear(sid), sid)

    def test_a_scroll_of_mage_armor_is_not_armor(self):
        self.assertFalse(gear.looks_like_gear('OBJ_Scroll_MageArmor'))

    def test_camp_clothes_and_underwear_are_not_gear(self):
        for sid in ('ARM_Camp_Body_Minthara', 'ARM_Underwear_Tieflings',
                    'ARM_Vanity_Body_Citizen_B_Teal'):
            self.assertFalse(gear.looks_like_gear(sid), sid)

    def test_prefix_alone_is_a_candidate(self):
        self.assertTrue(gear.looks_like_gear('WPN_Salami'))
        self.assertEqual(gear.kind_of('WPN_Salami'), 'weapon')

    def test_the_slot_wins_over_the_word(self):
        # Worn in the off hand, a "Shield" is a shield and anything else a weapon.
        self.assertEqual(gear.kind_of('MAG_Ketheric_Shield', slot=4), 'shield')
        self.assertEqual(gear.kind_of('WPN_Dagger', slot=4), 'weapon')
        self.assertEqual(gear.kind_of('WPN_Torch', slot=3), 'weapon')


class Learning(unittest.TestCase):

    def test_worn_is_proof_and_prefix_with_word_is_taken(self):
        rows = {}
        got = gear.learn(rows, {'ACT1_HAG_HagMask': 0}, ['MAG_Monk_Fire_Gloves'], 'S')
        self.assertEqual(sorted(got), ['ACT1_HAG_HagMask', 'MAG_Monk_Fire_Gloves'])
        self.assertEqual(rows['ACT1_HAG_HagMask']['gear'], 'yes')
        self.assertEqual(rows['ACT1_HAG_HagMask']['source'], 'worn S')
        self.assertEqual(rows['MAG_Monk_Fire_Gloves']['gear'], 'yes')
        self.assertEqual(rows['MAG_Monk_Fire_Gloves']['source'], 'id S')

    def test_one_signal_alone_is_a_question(self):
        rows = {}
        gear.learn(rows, {}, ['WPN_Salami', 'GOB_Priest_Amulet', 'OBJ_Potion'], 'S')
        self.assertEqual(rows['WPN_Salami']['gear'], '?')
        self.assertEqual(rows['GOB_Priest_Amulet']['gear'], '?')
        self.assertNotIn('OBJ_Potion', rows)

    def test_a_question_becomes_yes_once_seen_worn(self):
        rows = {'WPN_Salami': dict(stats='WPN_Salami', kind='weapon', gear='?', source='seen A')}
        got = gear.learn(rows, {'WPN_Salami': 3}, [], 'B')
        self.assertEqual(got, ['WPN_Salami'])
        self.assertEqual(rows['WPN_Salami']['gear'], 'yes')
        self.assertEqual(rows['WPN_Salami']['source'], 'worn B')

    def test_a_hand_written_answer_is_never_touched(self):
        rows = {'OBJ_InfernalPlate': dict(stats='OBJ_InfernalPlate', kind='body',
                                          gear='no', source='checked'),
                'WPN_Torch': dict(stats='WPN_Torch', kind='weapon',
                                  gear='no', source='checked')}
        got = gear.learn(rows, {'WPN_Torch': 3}, ['OBJ_InfernalPlate'], 'S')
        self.assertEqual(got, [])
        self.assertEqual(rows['WPN_Torch']['gear'], 'no')
        self.assertEqual(rows['OBJ_InfernalPlate']['gear'], 'no')

    def test_camp_slots_are_not_proof(self):
        rows = {}
        gear.learn(rows, {'ARM_Camp_Body_Minthara': 17, 'ARM_Underwear_X': 8}, [], 'S')
        self.assertEqual(rows, {})


class TableOnDisk(unittest.TestCase):

    def test_every_row_is_well_formed(self):
        rows = gear.load()
        self.assertGreater(len(rows), 100)
        for sid, r in rows.items():
            self.assertIn(r['gear'], ('yes', 'no', '?'), sid)
            self.assertIn(r['kind'], gear.KIND_ORDER, sid)
            self.assertTrue(r['source'], sid)

    def test_camp_clothes_never_reach_the_table(self):
        for sid in gear.load():
            self.assertFalse(gear._denied(sid), sid)


if __name__ == '__main__':
    unittest.main(verbosity=2)
