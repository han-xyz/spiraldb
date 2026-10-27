import io
import json
import os
import tempfile
import unittest
import urllib.parse

import client  # noqa: F401
from spiraltools.quests.repository import Polite, fetch_world, read_quest
from spiraltools.worlds import world

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "repository", "Bam,_Zoom,_to_the_Doom.wikitext")


class ReadQuestTest(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE, encoding="utf-8") as f:
            self.quest = read_quest("Bam, Zoom, to the Doom", f.read())

    def test_the_infobox_gives_the_first_lang_key_type_and_chain(self):
        self.assertEqual(self.quest["name"], "Bam, Zoom, to the Doom")
        self.assertEqual(self.quest["lang_hex"], "188A1E")
        self.assertEqual(self.quest["type"], "storyline")
        self.assertEqual(self.quest["prev"], ["Heroes of Old"])
        self.assertEqual(self.quest["next"], ["The Man on the Moon is the Engineer", "Moon Magic!"])

    def test_goals_are_plain_text_without_icons(self):
        self.assertEqual(len(self.quest["goals"]), 7)
        self.assertEqual(self.quest["goals"][0], "Go To Rocket")
        self.assertEqual(self.quest["goals"][3], "Talk To Stallion Quartermane")

    def test_dialogue_lines_carry_speaker_text_and_audio(self):
        self.assertEqual(len(self.quest["dialogue"]), 3)
        self.assertEqual(self.quest["dialogue"][1], {"speaker": "Stallion Quartermane", "text": "Stop right there, fiends!",
                                                     "audio": "Stallion Quartermane NV-PostWL 006.mp3"})


VARIANTS = """{{Quest
|type=Mainline Quest<br>Instance Quest
|id=WizQst17D8A0
}}
==Quest Goals==
#Catch a Drop Bear Drop Bear {{Sic}}

==Dialogue==
:[[File:Portrait Dromel Wizard A NPC.png|28px|Sandiago]] {{D|Sandiago AR-PreWL 001.mp3}} '''[[Sandiago]]''': Wizard, return to the Arcanum.
"""


class ReadVariantsTest(unittest.TestCase):
    def setUp(self):
        self.quest = read_quest("The Little Prince (Wizard101)", VARIANTS)

    def test_the_game_qualifier_is_dropped_from_the_name(self):
        self.assertEqual(self.quest["name"], "The Little Prince")

    def test_a_quest_of_two_kinds_has_both_types(self):
        self.assertEqual(self.quest["type"], "instance/storyline")

    def test_templates_are_dropped_from_goals(self):
        self.assertEqual(self.quest["goals"], ["Catch a Drop Bear Drop Bear"])

    def test_the_colon_after_the_bold_speaker_is_read(self):
        self.assertEqual(self.quest["dialogue"][0]["speaker"], "Sandiago")
        self.assertEqual(self.quest["dialogue"][0]["text"], "Wizard, return to the Arcanum.")


class FakeApi:
    def __init__(self):
        self.urls = []

    def __call__(self, request, timeout):
        self.urls.append(request.full_url)
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(request.full_url).query))
        if query.get("list") == "categorymembers":
            members = [{"title": "Bank Run"}] if "Mainline" in query["cmtitle"] else []
            answer = {"query": {"categorymembers": members}}
        elif query.get("meta") == "siteinfo":
            answer = {"query": {"rightsinfo": {"url": "https://www.fandom.com/licensing", "text": "CC-BY-SA"}}}
        else:
            answer = {"parse": {"title": query["page"], "wikitext": "{{Quest\n|id=WizQst17D8A0\n}}"}}
        return io.BytesIO(json.dumps(answer).encode())


class FetchWorldTest(unittest.TestCase):
    def test_a_second_fetch_asks_nothing_already_cached(self):
        api = FakeApi()
        with tempfile.TemporaryDirectory() as cache:
            fetch_world(Polite(api, interval=0), cache, world("Wallaru"))
            first = len(api.urls)
            fetch_world(Polite(api, interval=0), cache, world("Wallaru"))
            self.assertTrue(os.path.exists(os.path.join(cache, "repository", "wallaru", "Bank_Run.wikitext")))
        self.assertEqual(first, 5)
        self.assertEqual(len(api.urls), first)
