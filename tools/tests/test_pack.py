import json
import os
import tempfile
import unittest

import client  # noqa: F401
from spiraltools.pack import (append_items, append_teleports, duplicate_trigger_names, new_zone_file_path,
                              parse_tolerant, tolerant_load, write_unless_same)


def teleport(name, zone="WizardCity/WC_Hub"):
    return {"TriggerName": name, "Teleport": {"m_destinationLoc": "Start", "m_destinationZone": zone}}


class PackTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def path(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def text(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_parse_tolerant_accepts_trailing_commas(self):
        self.assertEqual(parse_tolerant('{"a": [1, 2,], "b": {"c": 3,},}'), {"a": [1, 2], "b": {"c": 3}})

    def test_append_teleports_keeps_a_file_without_trailing_commas_strict(self):
        doc = {"ZoneName": "Z", "Events": [], "Teleports": [teleport("A")]}
        path = self.path("z.json", json.dumps(doc, indent=2) + "\n")
        append_teleports(path, [teleport("B"), teleport("C")])
        loaded = json.loads(self.text(path))
        self.assertEqual([t["TriggerName"] for t in loaded["Teleports"]], ["A", "B", "C"])

    def test_append_teleports_follows_a_trailing_comma_file(self):
        path = self.path("z.json", '{\n  "ZoneName": "Z",\n  "Teleports": [\n    {"TriggerName": "A"},\n  ]\n}\n')
        append_teleports(path, [teleport("B")])
        text = self.text(path)
        self.assertTrue(text.rstrip().endswith("},\n  ]\n}"))
        self.assertEqual([t["TriggerName"] for t in tolerant_load(path)["Teleports"]], ["A", "B"])

    def test_append_teleports_fills_an_empty_list(self):
        path = self.path("z.json", '{\n  "ZoneName": "Z",\n  "Teleports": []\n}\n')
        append_teleports(path, [teleport("A")])
        self.assertEqual(json.loads(self.text(path))["Teleports"], [teleport("A")])

    def test_append_teleports_refuses_a_file_whose_last_key_is_not_a_list(self):
        path = self.path("z.json", '{\n  "Teleports": [],\n  "ZoneName": "Z"\n}\n')
        with self.assertRaises(SystemExit):
            append_teleports(path, [teleport("A")])

    def test_append_items_keeps_the_tail_of_the_tab(self):
        path = self.path("tab.json", '{\n  "items": [\n    {"templateId": 1}\n  ]\n}\n')
        append_items(path, [{"templateId": 2}])
        self.assertEqual(json.loads(self.text(path))["items"], [{"templateId": 1}, {"templateId": 2}])
        self.assertTrue(self.text(path).endswith("\n  ]\n}\n"))

    def test_write_unless_same_leaves_an_equal_file_alone(self):
        path = self.path("t.json", '{"Name": "Q", "CreatedAt": "then",}')
        self.assertFalse(write_unless_same(path, {"Name": "Q", "CreatedAt": "now"}, ignored=("CreatedAt",)))
        self.assertEqual(self.text(path), '{"Name": "Q", "CreatedAt": "then",}')
        self.assertTrue(write_unless_same(path, {"Name": "R"}))
        self.assertEqual(json.loads(self.text(path)), {"Name": "R"})

    def test_new_zone_file_path_widens_a_taken_name(self):
        self.path("WizardZoneDatas_GH_Hero_T2.json", "{}")
        self.assertEqual(os.path.basename(new_zone_file_path("Grizzleheim/Interiors/GH_Hero_T2", self.dir)),
                         "WizardZoneDatas_Interiors_GH_Hero_T2.json")

    def test_duplicate_trigger_names_lists_each_repeated_name_once(self):
        doc = {"ZoneName": "Z", "Teleports": [teleport("A"), teleport("B"), teleport("A"), teleport("A")]}
        repeated = self.path("WizardZoneDatas_Z.json", json.dumps(doc))
        self.path("WizardZoneDatas_Y.json", json.dumps({"ZoneName": "Y", "Teleports": [teleport("A")]}))
        self.assertEqual(duplicate_trigger_names(self.dir), {repeated: ["A"]})


if __name__ == "__main__":
    unittest.main()
