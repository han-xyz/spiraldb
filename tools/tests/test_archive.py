import unittest

import client  # noqa: F401
from spiraltools.quests.archive import match_by_proper_nouns


class Lines:
    def __init__(self, files):
        self.files = files

    def quest_lines(self, key):
        return {"00000001": self.files.get(key, "")}


def page(goals, giver=None, location=None):
    return {"goals": goals, "giver": giver, "hand_in": None, "giver_location": location}


FILES = {
    "100": "Talk to Kala Kono in the Coruscade.",
    "105": "Tupa Taua waits in the Coruscade. Bring the bark to Tupa.",
    "106": "Tupa Taua thanks you.",
    "107": "Tupa Taua and Kala Kono argue at the Coruscade.",
    "140": "Tupa Taua lives far away in the Coruscade.",
}


class ProperNounTest(unittest.TestCase):
    def match(self, pages, langs, free, files=FILES):
        zones = {name: "Floating Land" for name in list(pages) + list(langs)}
        return match_by_proper_nouns(Lines(files), pages, zones, langs, free, common=set())

    def test_the_unique_best_key_of_the_zone_run_is_matched_with_its_nouns(self):
        pages = {"Q:Bark": page(["Collect bark for Tupa Taua in the Coruscade"])}
        found = self.match(pages, {"Q:Known": "100"}, ["105", "106"])
        key, evidence = found["Q:Bark"]
        self.assertEqual(key, "105")
        self.assertIn("Coruscade, Taua, Tupa", evidence)

    def test_a_tie_or_a_single_shared_noun_is_not_matched(self):
        pages = {"Q:Bark": page(["Talk to Tupa Taua"])}
        self.assertEqual(self.match(pages, {"Q:Known": "100"}, ["105", "106"]), {})
        pages = {"Q:Kono": page(["Talk to Kono"])}
        self.assertEqual(self.match(pages, {"Q:Known": "100"}, ["107"]), {})

    def test_a_key_outside_the_zone_run_is_not_a_candidate(self):
        pages = {"Q:Far": page(["Collect bark for Tupa Taua in the Coruscade"])}
        self.assertEqual(self.match(pages, {"Q:Known": "100"}, ["140"]), {})

    def test_two_pages_wanting_one_key_go_to_the_higher_score(self):
        pages = {"Q:Bark": page(["Collect bark for Tupa Taua in the Coruscade"]),
                 "Q:Taua": page(["Talk to Tupa Taua"])}
        found = self.match(pages, {"Q:Known": "100"}, ["105"])
        self.assertEqual(found, {"Q:Bark": found["Q:Bark"]})


if __name__ == "__main__":
    unittest.main()
