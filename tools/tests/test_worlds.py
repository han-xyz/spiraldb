import unittest

from client import needs_rootwad
from spiraltools.lang import ROOTWAD_DIR
from spiraltools.worlds import WORLDS, UnknownWorld, lang_cluster, world


class WorldsTest(unittest.TestCase):
    def test_world_ignores_case_and_spaces(self):
        self.assertEqual(world("wizard city").prefix, "WC")

    def test_an_unknown_world_lists_the_registry(self):
        with self.assertRaises(UnknownWorld) as raised:
            world("Atlantis")
        self.assertIn("Celestia, Zafaria", str(raised.exception))

    @needs_rootwad
    def test_every_world_resolves_a_lang_cluster(self):
        for registered in WORLDS:
            with self.subTest(registered.name):
                first, last = lang_cluster(registered, ROOTWAD_DIR)
                self.assertLessEqual(first, last)

    @needs_rootwad
    def test_celestia_cluster_is_the_one_its_quests_were_matched_in(self):
        self.assertEqual(lang_cluster(world("Celestia"), ROOTWAD_DIR), (0x371A8, 0x3780E))

    @needs_rootwad
    def test_a_declared_range_wins_over_an_anchor_outside_the_worlds_quests(self):
        self.assertEqual(lang_cluster(world("Lemuria"), ROOTWAD_DIR), (0x170115, 0x1744C6))
    def test_a_declared_range_wins_over_the_anchored_cluster(self):
        self.assertEqual(lang_cluster(world("Karamelle"), ROOTWAD_DIR), (0x16B48E, 0x1716FA))


if __name__ == "__main__":
    unittest.main()
