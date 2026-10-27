import os
import tempfile
import unittest

import client  # noqa: F401
from spiraltools.pack import render, tolerant_load
from spiraltools.twins import Fix, LayoutError, PlacedObject, Template, apply_fixes, bounty_cases, find_twins

ZONE = "WizardCity/WC_Streets/Interiors/WC_Cyclops_T2"
MOB_KEY = "WizardMobs_00000025"
AKILLES_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures",
                               "questtemplates_WC-CYCLOPS-MAIN-005.json")


def goal(name, goal_type, zone="", mob_key=""):
    return {"m_goalName": name, "m_goalType": goal_type, "m_destinationZone": zone,
            "m_activateResults": {"m_results": []}, "m_completeResults": {"m_results": []},
            "m_tallyCounter": {"m_descriptor2": mob_key}, "m_npcAdjectives": ["General_Akilles"]}


def quest():
    return {"m_questName": "Q", "m_goals": [goal("Goal", "GOAL_TYPE_WAYPOINT", ZONE),
                                            goal("Goal 1", "GOAL_TYPE_BOUNTY", mob_key=MOB_KEY)]}


def placed(tag, template_id, location=(0.0, 0.0, 0.0), undetectable=True):
    return PlacedObject(tag, template_id, location, undetectable, "", False)


class BountyCaseTest(unittest.TestCase):
    def test_a_bounty_without_a_zone_takes_the_earlier_waypoint_zone(self):
        [case] = bounty_cases(quest())
        self.assertEqual((case.goal, case.zone, case.mob_key), ("Goal 1", ZONE, MOB_KEY))

    def test_a_bounty_with_no_zone_before_it_has_none(self):
        q = quest()
        q["m_goals"].reverse()
        self.assertIsNone(bounty_cases(q)[0].zone)


class FindTwinsTest(unittest.TestCase):
    templates = {1: Template("WC-ST03-AkilliesNPC", MOB_KEY, "General Akilles", "WC-ST03-AkilliesNPC_Persona", True),
                 2: Template("WC-AkillesPet-GreatOne", "NPCs_00000099", "The Great One", "WC-AkillesPet_Persona", True),
                 3: Template("WC-Cyclops-Mob", MOB_KEY, "General Akilles", None, False),
                 4: Template("WC-Other-NPC", "NPCs_00000077", "Private Quinn", "WC-Other_Persona", True),
                 5: Template("WC-Lamp", "", "", None, False)}

    def test_the_twin_is_the_npc_with_the_mob_display_name_and_companions_are_hidden_npc_neighbours(self):
        objects = [placed("Akilles", 1), placed("Pet", 2, (100.0, 0.0, 0.0)), placed("Mob", 3, undetectable=False),
                   placed("Far", 2, (5000.0, 0.0, 0.0)), placed("Other", 4, undetectable=False), placed("Lamp", 5)]
        twins, companions = find_twins(objects, self.templates, MOB_KEY, "", ["General_Akilles"])
        self.assertEqual([o.tag for o in twins], ["Akilles"])
        self.assertEqual([o.tag for o in companions], ["Pet"])

    def test_no_npc_with_the_mob_display_name_is_no_twin(self):
        self.assertEqual(find_twins([placed("Mob", 3)], self.templates, MOB_KEY, "", []), ([], []))

    def test_an_npc_whose_display_text_is_the_mob_name_is_a_twin_under_another_key(self):
        twins, _ = find_twins([placed("Quinn", 4)], self.templates, "WizardMobs_00000500", "Private Quinn", [])
        self.assertEqual([o.tag for o in twins], ["Quinn"])


class ApplyFixesTest(unittest.TestCase):
    def write(self, text):
        path = os.path.join(tempfile.mkdtemp(), "questtemplates_Q.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def dynamods(self, path):
        return [(g["m_goalName"], key, r["m_dynaModClientTag"], r["m_bShowsObject"], r["m_dynaModRemove"],
                 r["m_persist"], r["m_zoneName"])
                for g in tolerant_load(path)["m_goals"] for key in ("m_activateResults", "m_completeResults")
                for r in (g[key] or {}).get("m_results") or [] if "DynaMod" in r["$type"]]

    def test_apply_reveals_on_the_kill_once(self):
        path = self.write(render(quest()).rstrip("\n"))
        fix = Fix("Goal 1", "m_completeResults", ZONE, ["Akilles"], True)
        self.assertEqual(apply_fixes(path, [fix]), ["Akilles"])
        first = self.read(path)
        self.assertEqual(apply_fixes(path, [fix]), [])
        self.assertEqual(self.read(path), first)
        self.assertFalse(first.endswith("\n"))
        self.assertEqual(self.dynamods(path), [("Goal 1", "m_completeResults", "Akilles", True, False, True, ZONE)])

    def test_the_akilles_hide_rows_become_reveals_and_stay_so(self):
        with open(AKILLES_FIXTURE, encoding="utf-8") as f:
            path = self.write(f.read())
        fix = Fix("Goal 1", "m_completeResults", ZONE, ["WC-ST03-AkilliesNPC", "WC-AkillesPet-GreatOne"], True)
        self.assertEqual(apply_fixes(path, [fix]), ["WC-ST03-AkilliesNPC", "WC-AkillesPet-GreatOne"])
        first = self.read(path)
        self.assertEqual(apply_fixes(path, [fix]), [])
        self.assertEqual(self.read(path), first)
        self.assertEqual(self.dynamods(path),
                         [("Goal 1", "m_completeResults", tag, True, False, True, ZONE) for tag in fix.tags])

    def test_reformat_writes_a_trailing_comma_file(self):
        path = self.write(render(quest()).rstrip()[:-1].rstrip() + ",\n}\n")
        fix = Fix("Goal 1", "m_completeResults", ZONE, ["Akilles"], True)
        self.assertEqual(apply_fixes(path, [fix], reformat=True), ["Akilles"])
        self.assertEqual(self.read(path), render(tolerant_load(path)))

    def test_a_trailing_comma_file_that_would_change_is_refused(self):
        path = self.write(render(quest()).rstrip()[:-1].rstrip() + ",\n}\n")
        with self.assertRaises(LayoutError):
            apply_fixes(path, [Fix("Goal 1", "m_completeResults", ZONE, ["Akilles"], True)])


if __name__ == "__main__":
    unittest.main()
