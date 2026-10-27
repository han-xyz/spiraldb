import io
import json
import os
import tempfile
import unittest
import urllib.error

import client  # noqa: F401
from spiraltools.quests.archive import USER_AGENT, LiveWiki, cached, fetch_quest, match_by_proper_nouns


class Lines:
    def __init__(self, files):
        self.files = files

    def quest_lines(self, key):
        return {"00000001": self.files.get(key, "")}


def page(goals, giver=None, location=None):
    return {"goals": goals, "giver": giver, "hand_in": None, "giver_location": location}


FILES = {
    "100": "Talk to Kala Kono in the Coruscade.",
    "105": "Tupa Taua waits in the Coruscade. Bring the bark to Tupa.",
    "106": "Tupa Taua thanks you.",
    "107": "Tupa Taua and Kala Kono argue at the Coruscade.",
    "140": "Tupa Taua lives far away in the Coruscade.",
}


class ProperNounTest(unittest.TestCase):
    def match(self, pages, langs, free, files=FILES):
        zones = {name: "Floating Land" for name in list(pages) + list(langs)}
        return match_by_proper_nouns(Lines(files), pages, zones, langs, free, common=set())

    def test_the_unique_best_key_of_the_zone_run_is_matched_with_its_nouns(self):
        pages = {"Q:Bark": page(["Collect bark for Tupa Taua in the Coruscade"])}
        found = self.match(pages, {"Q:Known": "100"}, ["105", "106"])
        key, evidence = found["Q:Bark"]
        self.assertEqual(key, "105")
        self.assertIn("Coruscade, Taua, Tupa", evidence)

    def test_a_tie_or_a_single_shared_noun_is_not_matched(self):
        pages = {"Q:Bark": page(["Talk to Tupa Taua"])}
        self.assertEqual(self.match(pages, {"Q:Known": "100"}, ["105", "106"]), {})
        pages = {"Q:Kono": page(["Talk to Kono"])}
        self.assertEqual(self.match(pages, {"Q:Known": "100"}, ["107"]), {})

    def test_a_key_outside_the_zone_run_is_not_a_candidate(self):
        pages = {"Q:Far": page(["Collect bark for Tupa Taua in the Coruscade"])}
        self.assertEqual(self.match(pages, {"Q:Known": "100"}, ["140"]), {})

    def test_two_pages_wanting_one_key_go_to_the_higher_score(self):
        pages = {"Q:Bark": page(["Collect bark for Tupa Taua in the Coruscade"]),
                 "Q:Taua": page(["Talk to Tupa Taua"])}
        found = self.match(pages, {"Q:Known": "100"}, ["105"])
        self.assertEqual(found, {"Q:Bark": found["Q:Bark"]})


QUEST_HTML = '<span id="Quest_Information"></span>Given By: someone'
ROBOTS = "https://wiki.wizard101central.com/robots.txt"
API = "https://wiki.wizard101central.com/api.php?"
PAGE = "https://wiki.wizard101central.com/wiki/Quest:Bark"


class Response(io.BytesIO):
    def __init__(self, url, body):
        super().__init__(body)
        self.url = url


class FakeWeb:
    """urlopen over a table of URL prefix -> (status, body, headers); records each request."""

    def __init__(self, answers):
        self.answers = answers
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        url = request.full_url
        status, body, headers = next(a for prefix, a in self.answers.items() if url.startswith(prefix))
        if status != 200:
            raise urllib.error.HTTPError(url, status, "", headers, io.BytesIO(body))
        return Response(url, body)

    def urls(self):
        return [r.full_url for r in self.requests]


class FakeArchive:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return "https://web.archive.org/web/20250101000000id_/" + PAGE, b"archived page"


ALLOW_ALL = (200, b"User-agent: *\nDisallow:\n", {})
API_PAGE = (200, json.dumps({"parse": {"text": {"*": QUEST_HTML}}}).encode(), {})


class FetchOrderTest(unittest.TestCase):
    def fetch(self, answers):
        web, archive = FakeWeb(answers), FakeArchive()
        with tempfile.TemporaryDirectory() as cache:
            found = fetch_quest(LiveWiki(urlopen=web, interval=0), archive, cache, {"page": "Quest:Bark"})
            hit = cached(cache, "Quest:Bark")
            with open(hit.path, encoding="utf-8") as f:
                text = f.read()
            return found, hit, text, web, archive

    def test_a_live_api_answer_is_used_and_the_archive_is_not_asked(self):
        found, hit, text, web, archive = self.fetch({ROBOTS: ALLOW_ALL, API: API_PAGE})
        self.assertEqual(found, "live")
        self.assertEqual(hit.source, "live")
        self.assertEqual(text, QUEST_HTML)
        self.assertEqual(archive.urls, [])
        self.assertTrue(all(r.get_header("User-agent") == USER_AGENT for r in web.requests))
        self.assertIn("action=parse", web.urls()[-1])

    def test_the_plain_page_is_tried_when_the_api_has_no_such_page(self):
        missing = (200, json.dumps({"error": {"code": "missingtitle"}}).encode(), {})
        found, hit, text, _, archive = self.fetch({ROBOTS: ALLOW_ALL, API: missing,
                                                   PAGE: (200, QUEST_HTML.encode(), {})})
        self.assertEqual((found, hit.source, text), ("live", "live", QUEST_HTML))
        self.assertEqual(archive.urls, [])

    def test_a_403_falls_back_to_the_archive_after_one_attempt(self):
        found, hit, text, web, archive = self.fetch({ROBOTS: ALLOW_ALL, API: (403, b"Forbidden", {}),
                                                     PAGE: (403, b"Forbidden", {})})
        self.assertEqual((found, hit.source, text), ("archive", "archive", "archived page"))
        self.assertEqual(web.urls(), [ROBOTS, web.urls()[1]])
        self.assertEqual(len(archive.urls), 1)

    def test_a_challenge_page_is_not_retried(self):
        challenge = (503, b"<title>Just a moment...</title>", {"cf-mitigated": "challenge"})
        found, hit, _, web, _ = self.fetch({ROBOTS: ALLOW_ALL, API: challenge, PAGE: challenge})
        self.assertEqual((found, hit.source), ("archive", "archive"))
        self.assertEqual(len(web.requests), 2)

    def test_a_path_robots_txt_disallows_is_not_requested(self):
        robots = (200, b"User-agent: *\nDisallow: /api.php\n", {})
        found, _, _, web, _ = self.fetch({ROBOTS: robots, API: API_PAGE, PAGE: (200, QUEST_HTML.encode(), {})})
        self.assertEqual(found, "live")
        self.assertEqual(web.urls(), [ROBOTS, PAGE])


if __name__ == "__main__":
    unittest.main()
