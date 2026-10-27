import os
import unittest

from client import needs_gamedata, needs_rootwad
from spiraltools import templates
from spiraltools.quests.archive import (ClientData, SpecBuilder, item_entries, item_index, norm, read_page,
                                       singular_forms)
from spiraltools.wad import GAMEDATA_DIR
from spiraltools.worlds import world

PAGES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "pages")
ZONE = "W/Z_Quest"


def fields_of(name):
    with open(os.path.join(PAGES, f"Quest_{name}.html"), encoding="utf-8") as f:
        return read_page(f.read())


class Data:
    """The client lookups a spec needs, over a handful of names."""
    folder = "W"
    level = 1

    def __init__(self, personas=(), mobs=(), items=(), places=None):
        self.personas = {norm(name): name for name in personas}
        self.mobs = {norm(name): name for name in mobs}
        self.objects = item_index([{"template": f"W-{norm(name)}", "name": name, "name_key": f"Items_{i}",
                                    "icon": "", "adjectives": [f"W-{norm(name)}.AdjRef"]}
                                   for i, name in enumerate(items)], "W")
        self.places = places or {}

    def persona(self, name, zone):
        found = self.personas.get(norm(name))
        return found and {"name": found, "persona": found, "folder": "W", "portrait": "", "template_id": 1,
                          "zones": [ZONE]}

    def mob_entries(self, name):
        found = next((self.mobs[form] for form in singular_forms(name) if form in self.mobs), None)
        return [{"adjective": f"{found}.AdjRef", "target": "", "folder": "W"}] if found else []

    def object_entries(self, name):
        return item_entries(self.objects, name)

    def usage_entries(self, name):
        return self.object_entries(name)

    def zone_by_place(self, place):
        return self.places.get(place)

    def has_persona(self, name):
        return norm(name) in self.personas

    def location(self, place):
        return None

    def quest_lines(self, key):
        return {}

    def title_keys(self, title):
        return []

    def internal_name(self, key):
        return None


def build(name, data, known_zones=(ZONE,), fields=None, predecessor_hand_in=None):
    fields = fields or fields_of(name)
    entry = {"name": name, "page": f"Quest:{name}", "zones": ["Quest Zone"], "fetched": "20250101000000",
             "fetched_from": "archive"}
    builder = SpecBuilder(data, entry, fields, {"Quest Zone": ZONE}, {}, set(known_zones), predecessor_hand_in)
    return builder.build("ABC", "T-1")


def blocking(spec):
    return [(item["field"], item["value"]) for item in spec["needs_review"] if item["blocking"]]


def summary(goal):
    return (goal["type"], goal.get("persona") or goal.get("mobs") or goal.get("items") or goal.get("zone"),
            goal.get("count"), goal.get("with_previous", False))


class GoalLineTest(unittest.TestCase):
    def test_a_talk_to_header_is_one_step_of_its_npcs(self):
        data = Data(personas=["Edgar Ableton", "Mackenzie Trowel", "Peter Cheswick", "Dalton Prescott"])
        spec = build("Survivors", data)
        self.assertEqual([summary(goal) for goal in spec["goals"]],
                         [("persona", "Edgar Ableton", None, False), ("persona", "Mackenzie Trowel", None, True),
                          ("persona", "Peter Cheswick", None, True), ("persona", "giver", None, False)])

    def test_repeated_lines_count_and_a_collect_hint_reads_as_an_item(self):
        data = Data(mobs=["Stellar Protector", "Selenor"],
                    items=["Stellar Protector", "Crystal Pylon", "Moon Relic"])
        spec = build("Pylon_Raiders", data)
        self.assertEqual([summary(goal) for goal in spec["goals"]],
                         [("usage", ["W-stellarprotector.AdjRef"], 1, False),
                          ("usage", ["W-crystalpylon.AdjRef"], 3, False),
                          ("bounty", ["Stellar Protector.AdjRef"], 2, False),
                          ("bounty", ["Selenor.AdjRef"], 1, False),
                          ("usage", ["W-moonrelic.AdjRef"], 1, False)])
        self.assertIsNone(fields_of("Pylon_Raiders")["hand_in"])

    def test_a_repeated_talk_line_stays_two_goals(self):
        fields = {**fields_of("Survivors"), "goals": ["@Talk to Edgar Ableton", "@Talk to Edgar Ableton"]}
        spec = build("Talk_Twice", Data(personas=["Edgar Ableton", "Dalton Prescott"]), fields=fields)
        self.assertEqual([summary(goal)[:2] for goal in spec["goals"]],
                         [("persona", "Edgar Ableton"), ("persona", "Edgar Ableton"), ("persona", "giver")])

    def test_school_and_rank_tags_are_not_part_of_a_creature_name(self):
        data = Data(mobs=["Pingouin Revolutionary", "Principe Guard", "Aberrant Valencian",
                          "Governor Rottingham Weiler"])
        spec = build("Battle_of_the_Three_Armies", data)
        self.assertEqual([goal["mobs"] for goal in spec["goals"]],
                         [["Pingouin Revolutionary.AdjRef"], ["Principe Guard.AdjRef"],
                          ["Aberrant Valencian.AdjRef"], ["Governor Rottingham Weiler.AdjRef"]])

    def test_place_lines_are_waypoints_or_left_out_never_items(self):
        spec = build("Battle_of_the_Three_Armies", Data(mobs=["Pingouin Revolutionary", "Principe Guard",
                                                              "Aberrant Valencian", "Governor Rottingham Weiler"]))
        self.assertNotIn("goal.items", [field for field, _ in blocking(spec)])
        data = Data(personas=["Queen Elissa"], mobs=["Grey Ogre Spider"], items=["Spider Web", "Drum"],
                    places={"Drum House": "W/Interiors/Z_Drum_House"})
        spec = build("Drum_House", data, known_zones=(ZONE, "W/Interiors/Z_Drum_House"))
        self.assertEqual([summary(goal) for goal in spec["goals"]],
                         [("usage", ["W-spiderweb.AdjRef"], 1, False),
                          ("waypoint", "W/Interiors/Z_Drum_House", None, False),
                          ("bounty", ["Grey Ogre Spider.AdjRef"], 2, False),
                          ("usage", ["W-drum.AdjRef"], 4, False),
                          ("persona", "giver", None, False)])

    def test_a_list_of_places_is_one_step_of_waypoints_and_an_unknown_place_is_left_out(self):
        fields = {**fields_of("Survivors"), "goals": ["@Explore:", "@@[Location:Last Wood]", "@@[Location:Stone Town]",
                                                     "@Find the [Location:Councilor's House]"]}
        data = Data(personas=["Dalton Prescott"], places={"Last Wood": "W/Last_Wood", "Stone Town": "W/Stone_Town"})
        spec = build("Places", data, known_zones=(ZONE, "W/Last_Wood", "W/Stone_Town"), fields=fields)
        self.assertEqual([summary(goal) for goal in spec["goals"]],
                         [("waypoint", "W/Last_Wood", None, False), ("waypoint", "W/Stone_Town", None, True),
                          ("persona", "giver", None, False)])
        self.assertEqual(blocking(spec), [])

    def test_a_defeat_in_another_zone_sends_the_player_there(self):
        data = Data(personas=["Old Cob"], mobs=["Morganthe"], places={"Morganthe's Chamber": "W/Boss_Room"})
        spec = build("Final_Challenge", data, known_zones=(ZONE, "W/Boss_Room"))
        self.assertEqual((spec["goals"][0]["type"], spec["goals"][0]["zone"]), ("bounty", "W/Boss_Room"))
        spec = build("Final_Challenge", data)
        self.assertEqual(spec["goals"][0]["zone"], ZONE)

    def test_a_task_list_header_reads_each_task_as_its_own_goal(self):
        data = Data(personas=["Doctor Witch"], mobs=["Wight Rhino"], items=["Wisp Speck"])
        spec = build("Apothecary_Now", data)
        self.assertEqual([summary(goal) for goal in spec["goals"]],
                         [("bountycollect", ["Wight Rhino.AdjRef"], 3, False),
                          ("usage", ["W-wispspeck.AdjRef"], 4, True),
                          ("persona", "giver", None, False)])
        data = Data(personas=["Don Leonardo"], mobs=["Banana Spider"], items=["Vale of Perfection"])
        spec = build("Dye_For_Art", data)
        self.assertEqual([summary(goal) for goal in spec["goals"]],
                         [("usage", ["W-valeofperfection.AdjRef"], 1, False),
                          ("bountycollect", ["Banana Spider.AdjRef"], 1, True),
                          ("persona", "giver", None, False)])

    def test_an_npc_link_naming_only_an_item_is_a_usage_goal(self):
        fields = {**fields_of("Survivors"), "goals": ["@Find [NPC:Raleigh Waterson]", "@Find [NPC:Edgar Ableton]"]}
        spec = build("Like_Dockwork", Data(personas=["Edgar Ableton", "Dalton Prescott"], items=["Raleigh Waterson"]),
                     fields=fields)
        self.assertEqual([summary(goal)[:2] for goal in spec["goals"]],
                         [("usage", ["W-raleighwaterson.AdjRef"]), ("persona", "Edgar Ableton"), ("persona", "giver")])

    def test_a_person_verb_naming_an_npc_without_a_link_is_a_persona_goal(self):
        fields = {**fields_of("Survivors"), "goals": ["@Follow Dog Tracy", "@Find Edgar Ableton in the Camp"]}
        data = Data(personas=["Dog Tracy", "Edgar Ableton", "Dalton Prescott"], items=["Dog Tracy", "Edgar Ableton"])
        spec = build("Crime_and_Punishment", data, fields=fields)
        self.assertEqual([summary(goal)[:2] for goal in spec["goals"]],
                         [("persona", "Dog Tracy"), ("persona", "Edgar Ableton"), ("persona", "giver")])

    def test_a_persona_name_an_item_reads_only_without_its_place_stays_a_persona(self):
        fields = {**fields_of("Survivors"), "goals": ["@Talk to [NPC:Dasein on High]"]}
        spec = build("Like_Dockwork", Data(personas=["Dalton Prescott"], items=["Dasein"]), fields=fields)
        self.assertIn(("goal.persona", "Dasein on High"), blocking(spec))

    def test_a_quest_that_starts_automatically_is_given_by_its_prerequisite_hand_in_npc(self):
        fields = {**fields_of("Survivors"), "giver": None, "auto_start": True}
        spec = build("Like_Dockwork", Data(personas=["Dalton Prescott", "Edgar Ableton"]), fields=fields,
                     predecessor_hand_in="Edgar Ableton")
        self.assertEqual(spec["giver"], {"persona": "Edgar Ableton", "zone": ZONE})
        self.assertTrue(spec["auto_start"])
        self.assertNotIn("giver", [field for field, _ in blocking(spec)])

    def test_a_quest_that_starts_automatically_without_a_predecessor_hand_in_stays_blocked(self):
        fields = {**fields_of("Survivors"), "giver": None, "auto_start": True}
        spec = build("Like_Dockwork", Data(personas=["Dalton Prescott"]), fields=fields, predecessor_hand_in="Nobody")
        self.assertIn("giver (auto-start, no predecessor hand-in)", [field for field, _ in blocking(spec)])
        self.assertNotIn("giver", spec)

    def test_a_person_followed_to_a_place_is_a_persona_goal(self):
        fields = {**fields_of("Survivors"), "goals": ["@Follow Josiah into [Location:Town]"]}
        spec = build("Crime_and_Punishment", Data(personas=["Josiah", "Dalton Prescott"]), fields=fields)
        self.assertEqual(summary(spec["goals"][0])[:2], ("persona", "Josiah"))

    def test_npc_verbs_and_notes_on_npc_names(self):
        data = Data(personas=["Fernanda Maregellan", "Dasein", "Dasein on High", "Dasein Anomaly"],
                    mobs=["Banana Spider"], items=["Firefly", "Frame of Mind"])
        spec = build("Monkey_Business_(Novus)", data)
        self.assertEqual([summary(goal)[:2] for goal in spec["goals"]],
                         [("persona", "giver"), ("persona", "Dasein"), ("bounty", ["Banana Spider.AdjRef"]),
                          ("usage", ["W-firefly.AdjRef"]), ("persona", "Dasein on High"), ("persona", "Dasein Anomaly"),
                          ("usage", ["W-frameofmind.AdjRef"]), ("usage", ["W-frameofmind.AdjRef"]),
                          ("persona", "Dasein")])

    def test_a_persona_name_only_an_item_reads_is_a_usage_goal(self):
        fields = {**fields_of("Survivors"), "goals": ["@Talk to [NPC:Statue of Artorius]"]}
        spec = build("Like_Dockwork", Data(personas=["Dalton Prescott"], items=["Statue of Artorius"]), fields=fields)
        self.assertEqual([summary(goal)[:2] for goal in spec["goals"]][0], ("usage", ["W-statueofartorius.AdjRef"]))
        self.assertNotIn("goal.persona", [field for field, _ in blocking(spec)])


@needs_rootwad
@needs_gamedata
class ClientLookupTest(unittest.TestCase):
    def test_an_npc_placed_by_template_id_has_its_zone(self):
        placed = templates.zone_placements(GAMEDATA_DIR, "Khrysalis", {"KR-Bastion-NPC23": 1223156})
        self.assertEqual(placed["KR-Bastion-NPC23"], ["Khrysalis/KR_Z00_Hub"])

    def test_a_mob_the_world_lacks_comes_from_the_nearest_world_only(self):
        data = ClientData(world("Karamelle"))
        self.assertEqual({entry["folder"] for entry in data.mob_entries("Vexxor")}, {"NV"})

    def test_a_place_resolves_to_the_world_zone_of_that_name(self):
        data = ClientData(world("Zafaria"))
        self.assertEqual(data.zone_by_place("the Drum House"), "Zafaria/Interiors/ZF_Z10_I03_Drum_House")
        self.assertIsNone(data.zone_by_place("Nowhere At All"))

    def test_a_title_with_the_wiki_world_tag_matches_the_title(self):
        data = ClientData(world("Novus"))
        self.assertIn("17D615", data.title_keys("Monkey Business (Novus)"))

    def test_a_title_read_only_outside_the_declared_range_has_no_lang(self):
        self.assertIsNone(ClientData(world("Avalon")).title_lang("Plant Life"))

    def test_a_title_read_inside_and_outside_the_declared_range_takes_the_key_inside(self):
        self.assertEqual(ClientData(world("Avalon")).title_lang("Running Free"), "908F3")

    def test_a_title_spelled_slightly_differently_matches_one_close_title_in_the_range(self):
        self.assertEqual(ClientData(world("Empyrea")).title_lang("'Til Wizard Voices Wake Us"), "16434E")

    def test_a_mob_name_reads_with_its_article_and_each_word_singular(self):
        self.assertTrue(ClientData(world("Mirage")).mob_entries("The Scorpion"))
        self.assertTrue(ClientData(world("Azteca")).mob_entries("Left Talons of the Sky"))
        karamelle = ClientData(world("Karamelle"))
        self.assertEqual({entry["folder"] for entry in karamelle.mob_entries("The Quake Charmer")}, {"KM"})


if __name__ == "__main__":
    unittest.main()
