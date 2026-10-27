import os
import unittest

import client  # noqa: F401
from spiraltools.quests.tracker import quest_list

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "tracker", "khrysalis.html")


class QuestListTest(unittest.TestCase):
    def test_the_quest_array_is_read_across_the_page_flight_chunks(self):
        with open(FIXTURE, encoding="utf-8") as f:
            quests = quest_list(f.read())
        self.assertEqual([q["name"] for q in quests], ["Letters of Light", "Calling the Council"])
        self.assertEqual(quests[0]["nerothon"]["nextQuests"], ["Calling the Council"])
        self.assertEqual(quests[1]["wikiName"], "Calling the Council")
