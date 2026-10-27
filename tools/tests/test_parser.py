import os
import unittest

from client import needs_gamedata, needs_rootwad
from spiraltools import templates
from spiraltools.quests.archive import (ClientData, SpecBuilder, claimed_twice, item_entries, item_index, norm,
                                       predecessor_hand_in, preferred_lang, read_page, repository_entry,
                                       repository_fields, repository_matches, rewire_requires, singular_forms,
                                       captured_ids, mark_captured)
from spiraltools.wad import GAMEDATA_DIR
from spiraltools.worlds import world

PAGES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "pages")
ZONE = "W/Z_Quest"


def fields_of(name):
    with open(os.path.join(PAGES, f"Quest_{name}.html"), encoding="utf-8") as f:
        return read_page(f.read())


class Data:
    """The client lookups a spec needs, over a handful of names."""
    world = "W"
    folder = "W"
    level = 1
    titles = {"ABC": "Quest", "834ED": ""}

    def __init__(self, personas=(), mobs=(), items=(), places=None, volumes=None, cantrips=()):
        self.personas = {norm(name): name for name in personas}
        self.mobs = {norm(name): name for name in mobs}
        self.objects = item_index([{"template": f"W-{norm(name)}", "name": name, "name_key": f"Items_{i}",
                                    "icon": "", "adjectives": [f"W-{norm(name)}.AdjRef"]}
                                   for i, name in enumerate(items)], "W")
        self.places = places or {}
        self.volumes = volumes or {}
        self.cantrips = set(cantrips)

    def persona(self, name, zone):
        found = self.personas.get(norm(name))
        return found and {"name": found, "persona": found, "folder": "W", "portrait": "", "template_id": 1,
                          "zones": [ZONE]}

    def zones_at(self, zone):
        return [zone]

    def volumes_named(self, name):
        return [(zone, name) for zone in self.volumes.get(name, [])]

    def is_cantrip(self, name):
        return name in self.cantrips

    def mob_entries(self, name):
        found = next((self.mobs[form] for form in singular_forms(name) if form in self.mobs), None)
        return [{"adjective": f"{found}.AdjRef", "target": "", "folder": "W"}] if found else []

    def object_entries(self, name):
        return item_entries(self.objects, name)

    def usage_entries(self, name, zone="", count=1):
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


class GiverPlacedIn(Data):
    """Every persona placed in one zone, for a world of the registry."""
    world = "Polaris"

    def __init__(self, zone, **kwargs):
        super().__init__(**kwargs)
        self.zone = zone

    def persona(self, name, zone):
        found = super().persona(name, zone)
        return found and dict(found, zones=[self.zone])


class PlacedIn(Data):
    """Every persona placed in the same zones."""

    def __init__(self, zones, **kwargs):
        super().__init__(**kwargs)
        self.zones = zones

    def persona(self, name, zone):
        found = super().persona(name, zone)
        return found and dict(found, zones=self.zones)


class ItemWords(Data):
    """Items a usage goal reads by their words though no item goes by the name."""

    def __init__(self, words, **kwargs):
        super().__init__(**kwargs)
        self.words = words

    def usage_entries(self, name, zone="", count=1):
        return self.object_entries(name) or self.object_entries(self.words.get(name, ""))


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
    def test_a_giver_placed_in_another_registered_world_blocks_the_spec(self):
        personas = ["Edgar Ableton", "Mackenzie Trowel", "Peter Cheswick", "Dalton Prescott"]
        spec = build("Survivors", GiverPlacedIn("Avalon/AV_Z03_CaerLyon", personas=personas))
        self.assertIn("giver (other world)", [field for field, _ in blocking(spec)])

    def test_a_giver_placed_in_the_arcanum_hub_does_not_block_the_spec(self):
        personas = ["Edgar Ableton", "Mackenzie Trowel", "Peter Cheswick", "Dalton Prescott"]
        spec = build("Survivors", GiverPlacedIn("Arcanum/AR_Z01_Hub", personas=personas))
        self.assertEqual(spec["giver"]["zone"], "Arcanum/AR_Z01_Hub")
        self.assertNotIn("giver (other world)", [field for field, _ in blocking(spec)])

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

    def test_a_predecessor_without_a_hand_in_gives_its_giver(self):
        pages = {"P1": {"hand_in": None, "giver": "Hierarch of Purpose"}, "P2": {"hand_in": "Mellori", "giver": "X"}}
        by_title = {"looneyattunes": "P1", "savingtheskyanchor": "P2"}
        self.assertEqual(predecessor_hand_in(pages, by_title, {"prequests": ["Looney Attunes"]}), "Hierarch of Purpose")
        self.assertEqual(predecessor_hand_in(pages, by_title, {"prequests": ["Looney Attunes", "Saving the Sky Anchor"]}),
                         "Mellori")

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

    def goals_of(self, lines, data, known_zones=(ZONE,)):
        fields = {**fields_of("Survivors"), "goals": lines}
        spec = build("Like_Dockwork", data, known_zones=known_zones, fields=fields)
        return [summary(goal)[:2] for goal in spec["goals"]][:-1], blocking(spec)

    def test_a_line_with_a_note_entering_a_place_is_a_waypoint_there(self):
        data = Data(personas=["Dalton Prescott"], places={"Rage Dream": "W/Rage", "Sanctum": "W/Sanctum"})
        goals, _ = self.goals_of(["@Rest by the fire (Enter [Location:Rage Dream])",
                                  "@Follow Lemurs (into [Location:Sanctum])"], data, (ZONE, "W/Rage", "W/Sanctum"))
        self.assertEqual(goals, [("waypoint", "W/Rage"), ("waypoint", "W/Sanctum")])

    def test_a_line_leading_someone_to_a_place_or_an_npc_ends_there(self):
        data = Data(personas=["Dalton Prescott", "Dasein"], places={"Next Room": "W/Next"})
        goals, _ = self.goals_of(["@Lead the Nobles to Dasein", "@Follow Freddie to the Next Room"], data,
                                 (ZONE, "W/Next"))
        self.assertEqual(goals, [("persona", "Dasein"), ("waypoint", "W/Next")])

    def test_a_line_whose_whole_target_is_a_place_is_a_waypoint_there(self):
        data = Data(personas=["Dalton Prescott"], places={"Cabin": "W/Cabin", "Imperial Palace": "W/Palace"})
        goals, _ = self.goals_of(["@Clear out [Location:Cabin]", "@Assault the Imperial Palace"], data,
                                 (ZONE, "W/Cabin", "W/Palace"))
        self.assertEqual(goals, [("waypoint", "W/Cabin"), ("waypoint", "W/Palace")])

    def test_an_item_verb_does_not_go_to_the_place_its_item_stands_in(self):
        data = Data(personas=["Dalton Prescott"], places={"Library": "W/Library"})
        goals, blocked = self.goals_of(["@Use the Way of Itz (in the [Location:Library])"], data, (ZONE, "W/Library"))
        self.assertEqual((goals, blocked), ([], [("goal.usage", "Use the Way of Itz (in the Library)")]))

    def test_a_pet_mode_line_reads_as_what_the_pet_does(self):
        data = Data(personas=["Dalton Prescott", "Wally"], items=["Key"], places={"Outback": "W/Outback"})
        goals, blocked = self.goals_of(["@Use Pet Mode to find Wally in [Location:Outback]",
                                        "@Use Pet Mode to find Key"], data, (ZONE, "W/Outback"))
        self.assertEqual((goals, blocked), ([("persona", "Wally"), ("usage", ["W-key.AdjRef"])], []))

    def test_a_take_line_nothing_reads_is_a_waypoint_into_the_current_zone_to_review(self):
        goals, blocked = self.goals_of(["@Take a Few Steps Back", "@Take Tour"], Data(personas=["Dalton Prescott"]))
        self.assertEqual((goals, blocked), ([("waypoint", ZONE)] * 2, []))

    def test_a_person_line_nothing_reads_is_a_waypoint_to_the_place_it_links(self):
        data = Data(personas=["Dalton Prescott"], places={"Glockenspiel": "W/Glock"})
        goals, blocked = self.goals_of(["@Rescue Trapped Singers in the [Location:Glockenspiel]"], data,
                                       (ZONE, "W/Glock"))
        self.assertEqual((goals, blocked), ([("waypoint", "W/Glock")], []))

    def test_a_name_no_npc_has_that_an_item_reads_by_its_words_is_a_usage_goal(self):
        data = ItemWords({"Star Obelisk": "Obelisk Star", "Sweet Baby Sister": "Baby Sister"},
                         personas=["Dalton Prescott"], items=["Obelisk Star", "Baby Sister"])
        goals, blocked = self.goals_of(["@Talk to [NPC:Star Obelisk]", "@Free [NPC:Sweet Baby Sister]"], data)
        self.assertEqual((goals, blocked), ([("usage", ["W-obeliskstar.AdjRef"]), ("usage", ["W-babysister.AdjRef"])],
                                            []))

    def test_update_is_a_talk_verb(self):
        goals, _ = self.goals_of(["@Update the Villagers"], Data(personas=["Dalton Prescott", "Villagers"]))
        self.assertEqual(goals, [("persona", "Villagers")])

    def test_a_line_read_as_nothing_blocks_under_the_field_its_verb_asks_for(self):
        lines = ["@Celebrate Your Victory", "@Open Cell Door", "@Collect 5 Comestibles", "@Rescue Principe Mario"]
        _, blocked = self.goals_of(lines, Data(personas=["Dalton Prescott"]))
        self.assertEqual(blocked, [("goal.unknown-verb", "Celebrate Your Victory"),
                                   ("goal.usage", "Open Cell Door"),
                                   ("goal.items", "Comestibles"),
                                   ("goal.persona", "Rescue Principe Mario")])

    def test_study_break_and_smoosh_read_as_item_and_kill_verbs(self):
        data = Data(personas=["Dalton Prescott"], items=["Tome of Insight", "Vine Barrier"], mobs=["Common House Spider"])
        goals, blocked = self.goals_of(["@Study Tome of Insight", "@Break the Vine Barrier",
                                        "@Smoosh 2 Common House Spiders", "@Pick up the Vine Barrier"], data)
        self.assertEqual((goals, blocked), ([("usage", ["W-tomeofinsight.AdjRef"]), ("usage", ["W-vinebarrier.AdjRef"]),
                                             ("bounty", ["Common House Spider.AdjRef"]),
                                             ("usage", ["W-vinebarrier.AdjRef"])], []))

    def test_creature_links_in_a_note_qualify_the_creature_named_before_it(self):
        data = Data(personas=["Dalton Prescott"], mobs=["Spearfang Slasher"])
        goals, blocked = self.goals_of(["@Defeat 3 Spearfang Slashers ([Creature:Male] or [Creature:Female])"], data)
        self.assertEqual((goals, blocked), ([("bounty", ["Spearfang Slasher.AdjRef"])], []))
        data = Data(personas=["Dalton Prescott"], mobs=["Piscean Centurion", "Piscean"])
        goals, blocked = self.goals_of(["@Defeat 4 Pisceans ([Creature:Piscean Centurions])"], data)
        self.assertEqual((goals, blocked), ([("bounty", ["Piscean Centurion.AdjRef"])], []))

    def test_a_defeat_header_ending_in_collect_reads_its_lines_as_the_drops(self):
        data = Data(personas=["Dalton Prescott"], mobs=["Hobgoblin Plunderer"])
        goals, blocked = self.goals_of(["@Defeat [Creature:Hobgoblin Plunderers] and Collect:", "@@Sir Brennan's Armor",
                                        "@@4 Patolli Pieces"], data)
        self.assertEqual((goals, blocked), ([("bountycollect", ["Hobgoblin Plunderer.AdjRef"])] * 2, []))
        fields = {**fields_of("Survivors"), "goals": ["@Defeat [Creature:Hobgoblin Plunderers] and Collect:",
                                                     "@@4 Patolli Pieces"]}
        self.assertEqual(build("Like_Dockwork", data, fields=fields)["goals"][0]["count"], 4)

    def test_creature_links_in_a_note_of_a_defeat_header_line_qualify_the_creature_before_it(self):
        data = Data(personas=["Dalton Prescott"], mobs=["Inzinebu Bandit"])
        goals, blocked = self.goals_of(["@Defeat", "@@Inzinebu Bandit ([Creature:Female] or [Creature:Male]) in "
                                                   "[Location:Baobab Market] and Collect Spices"], data)
        self.assertEqual((goals, blocked), ([("bountycollect", ["Inzinebu Bandit.AdjRef"])], []))

    def test_a_latin_plural_creature_reads_its_singular(self):
        goals, blocked = self.goals_of(["@Defeat the [Creature:Death Fungi]"],
                                       Data(personas=["Dalton Prescott"], mobs=["Death Fungus"]))
        self.assertEqual((goals, blocked), ([("bounty", ["Death Fungus.AdjRef"])], []))

    def test_a_movement_line_read_as_nothing_is_a_waypoint_into_the_current_zone_to_review(self):
        lines = ["@Make Your Way Up", "@Investigate Strange Noise", "@Follow the Ox Alarm to Dark Cloud Base",
                 "@Follow the Trail of Papers", "@Approach Duck's Camp"]
        goals, blocked = self.goals_of(lines, Data(personas=["Dalton Prescott"]))
        self.assertEqual((goals, blocked), ([("waypoint", ZONE)] * 5, []))

    def test_a_movement_header_over_names_no_item_reads_is_one_step_of_waypoints(self):
        data = Data(personas=["Dalton Prescott"], places={"Test of Vision": "W/Vision"})
        goals, blocked = self.goals_of(["@Go to:", "@@Test of Vision", "@@Test of Constellation"], data,
                                       (ZONE, "W/Vision"))
        self.assertEqual((goals, blocked), ([("waypoint", "W/Vision"), ("waypoint", ZONE)], []))

    def test_an_item_header_over_places_is_that_item_in_each_place(self):
        data = Data(personas=["Dalton Prescott"], items=["Hero Flower", "Tapestry"],
                    places={"Telos": "W/Telos", "Heap": "W/Heap", "Nosebiter's Hideout": "W/Hideout"})
        zones = (ZONE, "W/Telos", "W/Heap", "W/Hideout")
        goals, blocked = self.goals_of(["@Find Hero Flower", "@@in [Location:Telos]", "@@in [Location:Heap]"], data,
                                       zones)
        self.assertEqual((goals, blocked), ([("usage", ["W-heroflower.AdjRef"])] * 2, []))
        fields = {**fields_of("Survivors"), "goals": [
            "@Collect Tapestry from:", "@@[Location:Caer Lyon] (in [Location:Nosebiter's Hideout])"]}
        spec = build("Like_Dockwork", data, known_zones=zones, fields=fields)
        self.assertEqual((spec["goals"][0]["items"], spec["goals"][0]["zone"]), (["W-tapestry.AdjRef"], "W/Hideout"))


class SchoolQuestTest(unittest.TestCase):
    def test_the_level_and_school_notes_are_read_in_both_wordings(self):
        fields = fields_of("Introduction_to_Fire")
        self.assertEqual((fields["level"], fields["school"]), (7, "Fire"))
        with open(os.path.join(PAGES, "Quest_Introduction_to_Fire.html"), encoding="utf-8") as f:
            page = f.read().replace("Level 7 is", "Level 12+ is").replace(
                "Wizards must be in the School of Fire", "your wizard must be in the school of storm")
        self.assertEqual((read_page(page)["level"], read_page(page)["school"]), (12, "Storm"))

    def test_the_level_note_sets_level_and_min_level_and_the_school_note_a_school_requirement(self):
        spec = build("Introduction_to_Fire", Data(personas=["Dalia Falmea"]))
        self.assertEqual((spec["level"], spec["min_level"], spec["requires"]), (7, 7, [{"school": "Fire"}]))

    def test_rewired_prerequisites_keep_the_school_and_the_page_level(self):
        fields = {**fields_of("Introduction_to_Fire"), "prequests": ["Gone Quest"]}
        spec = build("Introduction_to_Fire", Data(personas=["Dalia Falmea"]), fields=fields)
        rewire_requires([(fields, spec)], {}, {}, {}, set(), 1)
        self.assertEqual((spec["requires"], spec["min_level"]), ([{"school": "Fire"}], 7))

    def test_locate_and_go_to_a_named_volume_are_waypoints_into_its_zone(self):
        data = Data(personas=["Dalia Falmea"], volumes={"Dragon's Mouth Cave": ["W/Golem"], "Living Flame": ["W/Cave"]})
        spec = build("Introduction_to_Fire", data, known_zones=(ZONE, "W/Golem", "W/Cave"))
        self.assertEqual([(goal["type"], goal["zone"], goal.get("volume")) for goal in spec["goals"]],
                         [("waypoint", "W/Golem", "Dragon's Mouth Cave"), ("waypoint", "W/Cave", "Living Flame"),
                          ("persona", ZONE, None)])
        self.assertEqual(spec["goals"][2]["persona"], "giver")

    def test_go_to_a_thing_no_zone_places_is_a_waypoint_into_the_current_zone_to_review(self):
        spec = build("Introduction_to_Fire", Data(personas=["Dalia Falmea"]))
        self.assertEqual([(goal["type"], goal["zone"]) for goal in spec["goals"]],
                         [("waypoint", ZONE), ("waypoint", ZONE), ("persona", ZONE)])
        self.assertEqual(blocking(spec), [])
        self.assertIn(("goal.waypoint (current zone)", "Living Flame", False),
                      [(item["field"], item["value"], item["blocking"]) for item in spec["needs_review"]])

    def test_the_giver_stands_in_the_zone_its_giver_location_names(self):
        fields = {**fields_of("Introduction_to_Fire"), "giver_location": "Ravenwood"}
        data = PlacedIn(["W/PartyRoom", "W/Ravenwood"], personas=["Dalia Falmea"], places={"Ravenwood": "W/Ravenwood"})
        spec = build("Introduction_to_Fire", data, known_zones=(ZONE, "W/PartyRoom", "W/Ravenwood"), fields=fields)
        self.assertEqual(spec["giver"]["zone"], "W/Ravenwood")

    def test_a_cantrip_reward_is_left_out_for_review(self):
        fields = {**fields_of("Introduction_to_Fire"), "reward_spells": ["Fire Prism", "To Buttersfield"]}
        spec = build("Introduction_to_Fire", Data(personas=["Dalia Falmea"], cantrips=["To Buttersfield"]),
                     fields=fields)
        self.assertEqual(spec["reward"]["spells"], ["Fire Prism"])
        self.assertIn(("reward.spells (cantrip)", "To Buttersfield", False),
                      [(item["field"], item["value"], item["blocking"]) for item in spec["needs_review"]])


class CapturedTest(unittest.TestCase):
    def test_a_spec_with_a_captured_quests_title_is_marked_and_prerequisites_point_at_the_captured_quest(self):
        specs = [{"id": "WC-Q-9958", "lang": "9958", "requires": []},
                 {"id": "WC-Q-1410C", "lang": "1410C", "requires": [{"school": "Fire"}, "WC-Q-9958"]},
                 {"id": "WC-Q-2", "lang": "2", "title": "QuestTitle_00000103", "requires": []},
                 {"id": "WC-Q-unmatched", "requires": []}]
        ids = captured_ids(specs, {"9958": "WC-FIRE-C01-001", "00000103": "WC-OTHER-001"})
        self.assertEqual(ids, {"WC-Q-9958": "WC-FIRE-C01-001", "WC-Q-2": "WC-OTHER-001"})
        mark_captured(specs, ids)
        self.assertEqual([spec.get("captured") for spec in specs], ["WC-FIRE-C01-001", None, "WC-OTHER-001", None])
        self.assertEqual(specs[1]["requires"], [{"school": "Fire"}, "WC-FIRE-C01-001"])


class Langs:
    """Quest lang files by key."""

    def __init__(self, files):
        self.files = files

    def has_quest_lang(self, key):
        return key in self.files

    def quest_lines(self, key):
        return dict(enumerate(self.files.get(key, [])))


def repository_quest(lang_hex, *lines):
    return {"name": "Q", "lang_hex": lang_hex, "dialogue": [{"speaker": "A", "text": line} for line in lines]}


class RepositoryLangTest(unittest.TestCase):
    def test_the_repository_key_wins_when_its_file_holds_the_dialogue(self):
        data = Langs({"A1": ["Something else entirely."], "B2": ["Hello there, young Wizard!", "Off you go."]})
        quest = repository_quest("B2", "Hello there, young wizard!", "Off you go.")
        self.assertEqual(preferred_lang(data, "A1", quest), "B2")

    def test_the_title_key_stays_when_the_repository_file_lacks_the_dialogue(self):
        data = Langs({"A1": ["Hello there, young Wizard!"], "B2": ["A neighbouring quest's line."]})
        self.assertEqual(preferred_lang(data, "A1", repository_quest("B2", "Hello there, young Wizard!")), "A1")

    def test_a_repository_key_without_a_lang_file_is_not_taken(self):
        self.assertEqual(preferred_lang(Langs({}), None, repository_quest("B2", "Hello")), None)
        self.assertEqual(preferred_lang(Langs({"B2": ["Hello"]}), None, repository_quest("B2", "Hello")), "B2")

    def test_a_key_two_pages_hold_stays_with_the_page_whose_dialogue_it_holds(self):
        data = Langs({"B2": ["Hello there, young Wizard!"]})
        quests = {"Quest:Mine": repository_quest("B2", "Hello there, young Wizard!"),
                  "Quest:Other": repository_quest("B2", "Something else entirely.")}
        langs = {"Quest:Mine": "B2", "Quest:Other": "B2"}
        self.assertEqual(claimed_twice(data, langs, quests, {"Quest:Other": "evidence"}), ["Quest:Other"])

    def test_a_title_the_repository_spells_closely_finds_its_page_unless_another_title_reads_it(self):
        repository = {"allswellthatcleanseswells": "wells", "lostcity": "city"}
        index = [{"name": "All's Well that Cleanses Well", "page": "P1"}, {"name": "Lost City", "page": "P2"},
                 {"name": "Lost Citys", "page": "P3"}]
        self.assertEqual(repository_matches(repository, index), {"P1": "wells", "P2": "city", "P3": None})


REPOSITORY_QUEST = {
    "name": "Around Here Someplace", "wiki_page": "https://therepository.fandom.com/wiki/Around_Here_Someplace",
    "lang_hex": "834ED", "type": "storyline", "prev": ["Fool's Knight"], "next": ["Broken Signs"],
    "goals": ["Defeat Hobgoblin Plunderer and Collect Sir Brennan's Armor", "Defeat 2 Hart Lancer",
              "Talk To Steward Kay in Caer Lyon"],
    "characters": ["Steward Kay"], "dialogue": []}
LICENCE = {"licence": "CC-BY-SA", "licence_url": "https://www.fandom.com/licensing"}


def build_from_repository(data, quest=REPOSITORY_QUEST, tracked=None):
    entry = repository_entry({"name": quest["name"], "page": f"Quest:{quest['name']}", "zones": []}, quest, LICENCE)
    fields = repository_fields(data, quest, tracked)
    builder = SpecBuilder(data, entry, fields, {"Quest Zone": ZONE}, {"foolsknight": "T-0"}, {ZONE})
    return fields, builder.build("834ED", "T-1")


class RepositorySpecTest(unittest.TestCase):
    def setUp(self):
        self.data = Data(personas=["Steward Kay"], mobs=["Hobgoblin Plunderer", "Hart Lancer"])
        self.fields, self.spec = build_from_repository(self.data, tracked={"area": "Quest Zone", "xp": 4380,
                                                                           "gold": 285})

    def test_goals_are_read_from_the_quest_goals_list(self):
        self.assertEqual([summary(goal) for goal in self.spec["goals"]],
                         [("bountycollect", ["Hobgoblin Plunderer.AdjRef"], 1, False),
                          ("bounty", ["Hart Lancer.AdjRef"], 2, False), ("persona", "giver", None, False)])

    def test_the_first_character_gives_the_quest_and_the_last_talk_is_the_hand_in(self):
        self.assertEqual(self.spec["giver"], {"persona": "Steward Kay", "zone": ZONE})
        self.assertEqual(self.fields["hand_in"], "Steward Kay")

    def test_chain_reward_and_zone_come_from_the_infobox_and_spiraltracker(self):
        self.assertEqual(self.spec["requires"], ["T-0"])
        self.assertEqual(self.fields["leads_to"], ["Broken Signs"])
        self.assertEqual(self.spec["reward"], {"xp": 4380, "gold": 285})
        self.assertTrue(self.spec["mainline"])
        self.assertEqual(self.spec["goals"][0]["zone"], ZONE)

    def test_the_spec_names_the_repository_page_and_its_licence(self):
        self.assertEqual(self.spec["source"], {"page": REPOSITORY_QUEST["wiki_page"], "from": "repository",
                                               **LICENCE})

    def test_without_a_zone_name_the_goals_take_the_giver_zone(self):
        _, spec = build_from_repository(self.data, tracked={"area": "Elsewhere"})
        self.assertEqual([goal["zone"] for goal in spec["goals"][:2]], [ZONE, ZONE])

    def test_a_key_quest_title_lacks_takes_the_title_key_that_reads_the_name(self):
        data = Data(personas=["Steward Kay"])
        data.titles = {"00000150": "Around Here Someplace"}
        data.title_keys = lambda title: ["00000150"]
        _, spec = build_from_repository(data)
        self.assertEqual(spec["title"], "QuestTitle_00000150")
        data.title_keys = lambda title: []
        _, spec = build_from_repository(data)
        self.assertIn(("title", "Around Here Someplace"), blocking(spec))

    def test_a_first_character_no_zone_places_gives_no_giver(self):
        quest = dict(REPOSITORY_QUEST, characters=["Narrator", "Steward Kay"])
        fields, spec = build_from_repository(self.data, quest)
        self.assertIsNone(fields["giver"])
        self.assertNotIn("reward", spec)


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

    def test_a_place_resolves_without_its_possessive(self):
        data = ClientData(world("Lemuria"))
        self.assertEqual(data.zone_by_place("Centaurzan's Cabin"), "Lemuria/Interiors/LM_Z01_CentaurzanCabin")

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

    def test_a_mob_named_without_its_article_or_epithet_reads_the_one_mob_named_so(self):
        self.assertIn("LM_Chicken_Hero_A_01.AdjRef", self.adjectives("Lemuria", "Bantam"))
        self.assertIn("AV-Ogre-Boss-R12-02.AdjRef", self.adjectives("Avalon", "Eurgh"))

    def test_a_mob_named_without_the_words_before_its_name_reads_the_one_mob_named_so(self):
        self.assertEqual(self.adjectives("Azteca", "Yaxche"), {"AZ-Treant-Flower-B.AdjRef"})

    def test_a_misspelt_mob_name_reads_the_one_close_name(self):
        self.assertEqual(self.adjectives("Novus", "Abberant Marleybonian Dog"),
                         {"NV_Dog_AberrantNavy_A_01.AdjRef", "NV_Dog_AberrantNavy_A_02.AdjRef"})

    def test_a_professor_given_in_ravenwood_is_the_one_in_the_school_off_it(self):
        data = ClientData(world("WizardCity"))
        row = data.persona("Dalia Falmea", "WizardCity/WC_Ravenwood")
        self.assertEqual(row["template"], "WC-RAV-NPC04")
        self.assertIn("WizardCity/Interiors/WC_SchoolFire", data.zones_at("WizardCity/WC_Ravenwood"))

    def test_of_several_templates_at_the_zone_the_one_that_offers_quests_then_the_unsuffixed_one_gives(self):
        data = ClientData(world("WizardCity"))
        self.assertEqual(data.persona("Moolinda Wu", "WizardCity/WC_Ravenwood")["template"], "WC-RAV-NPC01")
        self.assertEqual(data.persona("Malorn Ashthorn", "WizardCity/WC_Ravenwood_Lite")["template"], "WC-RAV-NPC08")

    def test_an_item_the_world_lacks_comes_from_the_nearest_folder_that_has_it(self):
        entries = ClientData(world("WizardCity")).usage_entries("the Stone of Mazzaroth", "")
        self.assertEqual([(entry["adjective"], entry["folder"]) for entry in entries],
                         [("DS_Mazzaroth_Stone.AdjRef", "DS")])

    def test_a_counted_item_reads_the_as_many_items_one_zone_places_under_its_head_word(self):
        entries = ClientData(world("Avalon")).usage_entries("Unlit Lanterns", "", 6)
        self.assertEqual({entry["adjective"] for entry in entries},
                         {"AV-CRYS-Lanterns.AdjRef"} | {f"AV-CRYS-Lanterns{i}.AdjRef" for i in range(2, 7)})
        entries = ClientData(world("Wysteria")).usage_entries("Topiary", "", 3)
        self.assertEqual(len(entries), 3)
        self.assertEqual(ClientData(world("Wysteria")).usage_entries("Topiary", "", 2), [])

    def test_a_mob_and_an_npc_of_a_nested_object_folder_are_found(self):
        data = ClientData(world("WizardCity"))
        self.assertEqual({entry["folder"] for entry in data.mob_entries("Satharilith")}, {"Gauntlet/Catacombs"})
        self.assertEqual(data.persona("Jack Straw", "")["template"], "HO-Halloween02")

    def test_a_volume_name_reads_the_zones_that_hold_it(self):
        data = ClientData(world("WizardCity"))
        self.assertEqual(data.volumes_named("the Living Flame"),
                         [("WizardCity/Interiors/WC_Fire_Cave", "Living Flame")])
        self.assertEqual(data.volumes_named("Dragon's Mouth Cave"),
                         [("WizardCity/WC_Golem_Tower", "Dragon's Mouth Cave")])

    def test_a_mob_family_name_reads_no_mob(self):
        self.assertEqual(self.adjectives("Novus", "Cabal Bosses"), set())

    def adjectives(self, name, mob):
        return {entry["adjective"] for entry in ClientData(world(name)).mob_entries(mob)}


if __name__ == "__main__":
    unittest.main()
