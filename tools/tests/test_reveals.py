import os
import tempfile
import unittest

import client  # noqa: F401
from spiraltools.pack import render, tolerant_load
from spiraltools.reveals import persona_cases, persona_fix
from spiraltools.twins import PlacedObject, Template, apply_fixes

ZONE = "WizardCity/WC_Streets/WC_Triton"
TEMPLATES = {1: Template("WC-TRITON-NPC05", "", "", "WC-TRITON-NPC05_Persona", True),
             2: Template("WC-TRITON-NPC05-B", "", "", "WC-TRITON-NPC05_Persona", True),
             3: Template("WC-Lamp", "", "", None, False)}


def placed(tag, template_id, undetectable):
    return PlacedObject(tag, template_id, (0.0, 0.0, 0.0), undetectable, "", False)


def quest():
    return {"m_questName": "Q", "m_goals": [
        {"m_goalName": "Goal", "m_goalType": "GOAL_TYPE_WAYPOINT", "m_destinationZone": ZONE,
         "m_activateResults": {"m_results": []}, "m_completeResults": {"m_results": []}},
        {"m_goalName": "Goal 1", "m_goalType": "GOAL_TYPE_PERSONA", "m_destinationZone": "",
         "m_personaName": "WC-TRITON-NPC05", "m_activateResults": {"m_results": []},
         "m_completeResults": {"m_results": []}}]}


class PersonaFixTest(unittest.TestCase):
    def setUp(self):
        [self.case] = persona_cases(quest())

    def test_the_persona_goal_takes_the_earlier_zone(self):
        self.assertEqual((self.case.goal, self.case.zone, self.case.persona), ("Goal 1", ZONE, "WC-TRITON-NPC05"))

    def test_a_persona_name_with_the_suffix_reads_as_the_persona(self):
        q = quest()
        q["m_goals"][1]["m_personaName"] = "WC-TRITON-NPC05_Persona"
        self.assertEqual(persona_cases(q)[0].persona, "WC-TRITON-NPC05")

    def test_a_visible_placement_needs_no_reveal(self):
        objects = [placed("NPC05", 1, False), placed("NPC05-B", 2, True)]
        verdict, fix = persona_fix(self.case, objects, TEMPLATES, set())
        self.assertIsNone(fix)
        self.assertEqual(verdict, "visible")

    def test_only_hidden_placements_are_revealed_on_activate(self):
        objects = [placed("NPC05-B", 2, True), placed("Lamp", 3, True)]
        _, fix = persona_fix(self.case, objects, TEMPLATES, set())
        self.assertEqual(fix, ("Goal 1", "m_activateResults", ZONE, ["NPC05-B"]))

    def test_a_placement_another_quest_shows_is_left_to_it(self):
        objects = [placed("NPC05-B", 2, True)]
        verdict, fix = persona_fix(self.case, objects, TEMPLATES, {(ZONE, "NPC05-B")})
        self.assertIsNone(fix)
        self.assertEqual(verdict, "shown by a quest")

    def test_the_reveal_is_written_once(self):
        path = os.path.join(tempfile.mkdtemp(), "questtemplates_Q.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(render(quest()))
        _, fix = persona_fix(self.case, [placed("NPC05-B", 2, True)], TEMPLATES, set())
        self.assertEqual(apply_fixes(path, [fix]), ["NPC05-B"])
        with open(path, encoding="utf-8") as f:
            first = f.read()
        self.assertEqual(apply_fixes(path, [fix]), [])
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), first)
        [shown] = tolerant_load(path)["m_goals"][1]["m_activateResults"]["m_results"]
        self.assertEqual(
            (shown["m_dynaModClientTag"], shown["m_bShowsObject"], shown["m_persist"], shown["m_zoneName"]),
            ("NPC05-B", True, True, ZONE))


if __name__ == "__main__":
    unittest.main()
