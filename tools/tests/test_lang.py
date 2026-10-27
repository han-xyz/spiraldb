import os
import tempfile
import unittest

import client  # noqa: F401
from spiraltools.lang import lang_exists, parse_lang, quest_lang_keys, read_lang, zone_location_keys


def lang_bytes(entries):
    lines = ["header"] + [part for key, text in entries for part in (key, "", text)]
    return ("﻿" + "\r\n".join(lines)).encode("utf-16-le")


class LangTest(unittest.TestCase):
    def setUp(self):
        self.rootwad = tempfile.mkdtemp()
        self.locale = os.path.join(self.rootwad, "Locale", "en-US")
        os.makedirs(self.locale)

    def write(self, name, entries):
        with open(os.path.join(self.locale, name + ".lang"), "wb") as f:
            f.write(lang_bytes(entries))

    def test_parse_reads_key_and_text_of_each_triplet(self):
        data = lang_bytes([("00000001", "Gone Fishing"), ("00000002", "Celestia|Survey Camp")])
        self.assertEqual(parse_lang(data), {"00000001": "Gone Fishing", "00000002": "Celestia|Survey Camp"})

    def test_read_lang_and_lang_exists_find_the_file_under_the_locale(self):
        self.write("QuestTitle", [("371B8", "Gone Fishing")])
        self.assertTrue(lang_exists(self.rootwad, "QuestTitle"))
        self.assertFalse(lang_exists(self.rootwad, "WizardMobs"))
        self.assertEqual(read_lang(self.rootwad, "QuestTitle"), {"371B8": "Gone Fishing"})

    def test_quest_lang_keys_are_in_numeric_order(self):
        for key in ("1F", "A", "100"):
            self.write(f"WizQst{key}", [])
        self.write("QuestTitle", [])
        self.assertEqual(quest_lang_keys(self.rootwad), ["A", "1F", "100"])

    def test_zone_location_keys_keep_the_first_key_of_a_text(self):
        self.write("ZoneLocName", [("227135", "Celestia|Survey Camp"), ("227136", "Celestia|Survey Camp")])
        self.assertEqual(zone_location_keys(self.rootwad), {"Celestia|Survey Camp": "227135"})


if __name__ == "__main__":
    unittest.main()
