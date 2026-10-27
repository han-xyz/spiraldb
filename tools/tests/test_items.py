import contextlib
import io
import unittest

from client import needs_rootwad
from spiraltools import cli, templates
from spiraltools.lang import ROOTWAD_DIR
from spiraltools.quests.archive import item_entries, item_index


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


if __name__ == "__main__":
    unittest.main()
