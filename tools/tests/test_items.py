import contextlib
import io
import unittest

from client import needs_rootwad
from spiraltools import cli, templates
from spiraltools.lang import ROOTWAD_DIR
from spiraltools.quests.archive import ClientData, item_entries, item_index
from spiraltools.worlds import world


@needs_rootwad
class ItemsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = {row["template"]: row for row in templates.items(ROOTWAD_DIR, "CL")}
        cls.index = item_index(cls.rows.values(), "CL")

    def adjectives(self, phrase):
        return {entry["adjective"] for entry in item_entries(self.index, phrase)}

    def test_items_name_objects_by_display_name_and_quest_icon(self):
        self.assertEqual(self.rows["CL-TeslaTower2"]["name"], "Galvanic Tower")
        self.assertEqual(self.rows["CL-KrakenObject"]["icon"], "kraken statue")
        self.assertEqual(self.rows["CL-KrakenObject"]["adjectives"], ["CL-KrakenObject.AdjRef"])

    def test_items_keep_interactable_objects_named_like_mobs(self):
        self.assertEqual(self.rows["CL_Protector01"]["name"], "Stellar Protector")
        self.assertNotIn("CL-Protector-Gold-R9-1", self.rows)

    def test_a_goal_phrase_resolves_to_the_item_adjectives(self):
        self.assertIn("CL-TeslaTower2.AdjRef", self.adjectives("Galvanic Tower 2"))
        self.assertEqual(self.adjectives("Kraken Statue in Stormriven Hall"), {"CL-KrakenObject.AdjRef"})
        self.assertEqual(self.adjectives("final Piece of Ancient Tablet"), {"CL-AncientTablet.AdjRef"})
        self.assertEqual(self.adjectives("Pieces of Coral"), {"CL-Coral-Object.AdjRef"})
        self.assertEqual(self.adjectives("Stellar Protector in The Lunarium"), {"CL_DormantProtector01.AdjRef"})
        self.assertEqual(self.adjectives("Research Notes"), {"CL-ResearchNotes.AdjRef"})

    def test_a_place_resolves_to_no_item(self):
        self.assertEqual(self.adjectives("Survey Camp"), set())

    def test_items_command_lists_the_world_folder(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["items", "Celestia"])
        self.assertIn("Galvanic Tower\tgalvanic tower\tCL-TeslaTower2\t", out.getvalue())


@needs_rootwad
class ItemWordsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = ClientData(world("Zafaria"))

    def adjectives(self, phrase):
        return {entry["adjective"] for entry in self.data.usage_entries(phrase)}

    def test_a_phrase_matches_the_words_of_a_template_name_in_any_order(self):
        self.assertEqual(self.adjectives("Horn on Pedestal"), {"ZF-Grave-HornPedestal.AdjRef"})
        self.assertEqual(self.adjectives("Moon Gardens Gate"), {"ZF_Gate_Moon.AdjRef"})

    def test_every_plural_word_and_inner_preposition_is_read(self):
        self.assertEqual(self.adjectives("Bundles of Sticks"), {"ZF_Bundle_of_Sticks.AdjRef"})
        self.assertEqual(self.adjectives("Hole-In-The-Wall"), {"ZF_Hole-in-Wall.AdjRef"})

    def test_the_object_after_a_preposition_is_the_item_when_it_alone_resolves(self):
        self.assertEqual(self.adjectives("seeds in Soil"), {"ZF_Soil.AdjRef"})

    def test_a_template_only_the_editor_places_is_no_item(self):
        lemuria = ClientData(world("Lemuria"))
        self.assertEqual({entry["adjective"] for entry in lemuria.usage_entries("Virtual Old One")},
                         {"LM-WILD-NPC03.AdjRef"})

    def test_a_phrase_several_templates_read_resolves_to_none(self):
        self.assertEqual(self.adjectives("Book"), set())
        self.assertEqual(self.adjectives("Cage"), set())
        self.assertEqual(self.adjectives("Drum Near King's Cage"), set())

    def test_a_teleporter_the_quest_helper_skips_is_no_item(self):
        mirage = ClientData(world("Mirage"))
        self.assertEqual({entry["adjective"] for entry in mirage.usage_entries("Barrows")}, set())

    def test_the_place_after_a_preposition_is_the_item_only_by_its_own_words(self):
        mirage = ClientData(world("Mirage"))
        self.assertEqual({entry["adjective"] for entry in mirage.usage_entries("Tetrus Solitary Block in Istanboa")},
                         set())


if __name__ == "__main__":
    unittest.main()
