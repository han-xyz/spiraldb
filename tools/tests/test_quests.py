import glob
import json
import os
import re
import tempfile
import unittest

from client import needs_gamedata, needs_rootwad
from spiraltools.lang import ROOTWAD_DIR
from spiraltools.pack import QUEST_SPECS_DIR, quest_output_paths, tolerant_load, zone_transfer_files
from spiraltools.quests.generate import diff, quest_template, requirements, reward, steps
from spiraltools.quests.spec import SpecError, check_spec, load_specs, location_key, spell_id
from spiraltools.wad import GAMEDATA_DIR

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
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


def write_spec(directory, loaded):
    path = os.path.join(directory, f"{loaded['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in loaded.items() if not k.startswith("_")}, f)
    return path


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

    @needs_rootwad
    @needs_gamedata
    def test_check_finds_a_persona_placed_by_template_id(self):
        placed = load_specs(ROUNDTRIP[:1], ROOTWAD_DIR)[0]
        placed["giver"] = {"persona": "KR-Bastion-NPC23", "zone": "Khrysalis/KR_Z00_Hub"}
        problems = check_spec(placed, ROOTWAD_DIR, GAMEDATA_DIR, {}, {"Khrysalis/KR_Z00_Hub"})
        self.assertNotIn("persona KR-Bastion-NPC23 not placed in Khrysalis/KR_Z00_Hub", problems)

    @needs_rootwad
    @needs_gamedata
    def test_check_passes_the_round_trip_specs_whose_giver_has_no_zone(self):
        for loaded in load_specs(ROUNDTRIP, ROOTWAD_DIR):
            with self.subTest(loaded["id"]):
                self.assertEqual(check_spec(loaded, ROOTWAD_DIR, GAMEDATA_DIR, {}, set(zone_transfer_files())), [])

    @needs_rootwad
    def test_spell_names_resolve_by_file_or_display_name_and_an_ambiguous_one_names_its_candidates(self):
        spells = ["fire cat", "Blood Bat", "Pixie", {"spell": "No Such Spell", "school": "Fire"}]
        written = write_spec(tempfile.mkdtemp(), spec(reward={"spells": spells}))
        loaded = load_specs([written], ROOTWAD_DIR)[0]
        self.assertEqual(spell_id(loaded, "fire cat"), 103007158)
        self.assertEqual(spell_id(loaded, "Blood Bat"), 1067010286)
        with self.assertRaisesRegex(SpecError, "Spells/Pixie.xml, Spells/CastleMagic/Pixie.xml"):
            spell_id(loaded, "Pixie")
        with self.assertRaisesRegex(SpecError, "no spell template"):
            spell_id(loaded, "No Such Spell")

    @needs_rootwad
    @needs_gamedata
    def test_check_reports_an_unresolved_spell_reward(self):
        base = load_specs(ROUNDTRIP[:1], ROOTWAD_DIR)[0]
        base["reward"] = {**base.get("reward", {}), "spells": ["Fire Cat", "Pixie"]}
        loaded = load_specs([write_spec(tempfile.mkdtemp(), base)], ROOTWAD_DIR)[0]
        problems = check_spec(loaded, ROOTWAD_DIR, GAMEDATA_DIR, {}, set())
        self.assertEqual([p for p in problems if "spell" in p],
                         [f"{loaded['id']}: spell 'Pixie' matches several templates: "
                          "Spells/Pixie.xml, Spells/CastleMagic/Pixie.xml"])


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

    def test_spell_rewards_become_learn_spell_end_results_shaped_as_the_pack(self):
        spells = {"Spirit Shield": [("Spells/Spirit Shield.xml", 878360657)],
                  "Buoy Chests 1": [("Spells/Fishing Spells/BuoyChests1.xml", 766279669)]}
        built = quest_template(spec(goals=[{"type": "persona", "persona": "giver"}], _spell_ids=spells,
                                    reward={"spells": [{"spell": "Spirit Shield", "school": "Balance"},
                                                       "Buoy Chests 1"]}))
        pack = tolerant_load(os.path.join(FIXTURES, "questtemplates_WC-CYCLOPS-MAIN-005.json"))
        results = built["m_endResults"]["m_results"]
        self.assertEqual(results[1], pack["m_endResults"]["m_results"][1])
        self.assertEqual(results[2], {"$type": "Imcodec.ObjectProperty.TypeCache.ResLearnSpell, Imcodec.ObjectProperty",
                                      "m_templateID": 766279669, "m_requirements": None})

    def test_an_unresolved_spell_reward_blocks_generation(self):
        unresolved = spec(goals=[{"type": "persona", "persona": "giver"}], _spell_ids={"Pixie": []},
                          reward={"spells": ["Pixie"]})
        with self.assertRaises(SpecError):
            quest_template(unresolved)

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
