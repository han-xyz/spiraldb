import glob
import json
import os
import re
import tempfile
import unittest

from client import needs_gamedata, needs_rootwad
from spiraltools.lang import ROOTWAD_DIR
from spiraltools.pack import QUEST_SPECS_DIR, quest_output_paths, tolerant_load
from spiraltools.quests.generate import diff, quest_template, requirements, reward, steps
from spiraltools.quests.spec import SpecError, check_spec, load_specs, location_key
from spiraltools.wad import GAMEDATA_DIR

ROUNDTRIP = sorted(glob.glob(os.path.join(QUEST_SPECS_DIR, "roundtrip", "*.json")))
# What the client keeps nowhere a tool can read, and the known shape differences (tools/README.md, "Not generated").
KNOWN_DIFFERENCES = {
    "WC-FIRECAT-MAIN-004": {".m_goals[0].m_bountyTotal: only generated", ".m_goals[0].m_bountyType: only generated",
                            ".m_goals[3].m_bountyType: only generated",
                            ".m_goals[1].m_activateResults.m_results: differs"},
    "WC-TRITON-MAIN-002": {".m_goals[1].m_bountyTotal: only generated", ".m_goals[1].m_bountyType: only generated",
                           ".m_goals[0].m_activateResults.m_results: differs"},
    "WC-UNICORN-MAIN-002": {".m_requirements.$type: only generated", ".m_dialogList.m_dialogs: differs",
                            ".m_goals[0].m_dialogList: differs"},
}


def spec(**fields):
    base = {"id": "T-1", "lang": "ABC", "giver": {"persona": "NPC", "zone": "W/Z"}, "goals": [],
            "_zone_locations": {"Celestia|Survey Camp": "227135"}}
    return {**base, **fields}


class SpecTest(unittest.TestCase):
    def test_location_key_passes_keys_and_looks_up_place_text(self):
        s = spec()
        self.assertEqual(location_key(s, "ZoneLocName_1"), "ZoneLocName_1")
        self.assertEqual(location_key(s, "WizQst1_00000002"), "WizQst1_00000002")
        self.assertEqual(location_key(s, "Celestia|Survey Camp"), "ZoneLocName_227135")
        with self.assertRaises(SpecError):
            location_key(s, "Celestia|Nowhere")

    @needs_rootwad
    def test_load_specs_gives_each_spec_the_successors_that_require_it(self):
        directory = tempfile.mkdtemp()
        paths = []
        for quest, requires in (("A", []), ("B", ["A"]), ("C", ["A"])):
            paths.append(os.path.join(directory, f"{quest}.json"))
            with open(paths[-1], "w", encoding="utf-8") as f:
                json.dump(spec(id=quest, requires=requires), f)
        loaded = {s["id"]: s for s in load_specs(paths, ROOTWAD_DIR)}
        self.assertEqual(loaded["A"]["successors"], ["B", "C"])
        self.assertEqual(loaded["B"]["successors"], [])

    @needs_rootwad
    @needs_gamedata
    def test_check_reports_a_missing_lang_and_an_unknown_line(self):
        rootwad, gamedata = ROOTWAD_DIR, GAMEDATA_DIR
        self.assertEqual(check_spec(spec(lang="FFFFFFF"), rootwad, gamedata, {}, set()), ["no WizQstFFFFFFF.lang"])
        broken = load_specs(ROUNDTRIP[:1], rootwad)[0]
        broken["dialogs"]["prep"][0]["line"] = "99999999"
        problems = check_spec(broken, rootwad, gamedata, {}, set())
        self.assertIn(f"line 99999999 not in WizQst{broken['lang']}.lang", problems)


class GenerateTest(unittest.TestCase):
    def test_a_goal_with_previous_joins_the_step_before(self):
        goals = [{}, {"with_previous": True}, {}]
        self.assertEqual(steps(["1", "2", "3"], goals), [["1", "2"], ["3"]])

    def test_requirements_cover_prerequisites_level_and_successors(self):
        reqs = requirements(spec(requires=["P"], min_level=48, successors=["S"]))["m_requirements"]
        self.assertEqual([(r["$type"].split(",")[0].split(".")[-1], r.get("m_questName"), r["m_applyNOT"])
                          for r in reqs],
                         [("ReqHasEntry", "P", False), ("ReqMagicLevel", None, False), ("ReqHasEntry", "S", True)])
        self.assertIsNone(requirements(spec()))

    def test_reward_falls_back_to_the_level_band(self):
        self.assertEqual(reward(spec(level=48)), (3805, 103))
        self.assertEqual(reward(spec(level=12, reward={"xp": 7})), (7, 43))

    @needs_rootwad
    def test_round_trip_specs_differ_from_the_pack_only_in_presentation(self):
        for loaded in load_specs(ROUNDTRIP, ROOTWAD_DIR):
            with self.subTest(loaded["id"]):
                pack = tolerant_load(quest_output_paths(loaded["id"])[0])
                generated = quest_template(loaded)
                logic = {re.sub(r": generated .*", ": differs", line) for line in diff(generated, pack)
                         if ".m_dialogEntries[" not in line and ".m_madlibs" not in line}
                self.assertEqual(logic, KNOWN_DIFFERENCES[loaded["id"]])
                self.assertEqual(generated["m_goalLogic"], pack["m_goalLogic"])
                for built, captured in zip(generated["m_dialogList"]["m_dialogs"], pack["m_dialogList"]["m_dialogs"]):
                    self.assertEqual([e["m_dialog"] for e in built["m_dialogEntries"]],
                                     [e["m_dialog"] for e in captured["m_dialogEntries"]])


if __name__ == "__main__":
    unittest.main()
