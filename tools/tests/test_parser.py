import os
import unittest

from client import needs_gamedata, needs_rootwad
from spiraltools import templates
from spiraltools.quests.archive import (ClientData, SpecBuilder, claimed_twice, item_entries, item_index, norm,
                                       predecessor_hand_in, preferred_lang, read_page, repository_entry,
                                       repository_fields, repository_matches, singular_forms)
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

    def usage_entries(self, name, zone=""):
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

    def test_a_giver_placed_in_an_unregistered_hub_does_not_block_the_spec(self):
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

    def test_a_misspelt_mob_name_reads_the_one_close_name(self):
        self.assertEqual(self.adjectives("Novus", "Abberant Marleybonian Dog"),
                         {"NV_Dog_AberrantNavy_A_01.AdjRef", "NV_Dog_AberrantNavy_A_02.AdjRef"})

    def test_a_mob_family_name_reads_no_mob(self):
        self.assertEqual(self.adjectives("Novus", "Cabal Bosses"), set())

    def adjectives(self, name, mob):
        return {entry["adjective"] for entry in ClientData(world(name)).mob_entries(mob)}


if __name__ == "__main__":
    unittest.main()
