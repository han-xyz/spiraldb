"""Quest pages of The Repository (therepository.fandom.com, CC-BY-SA) into the cache, and an index per world of
what they add to the archive: each quest's lang key, type, chain, goals and dialogue."""
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request

from .archive import DEFAULT_CACHE, file_name

API = "https://therepository.fandom.com/api.php?"
USER_AGENT = "spiraltools (quest data for a private Wizard101 data pack; one request per 3 s)"
REQUEST_INTERVAL = 3.0


class Polite:
    """GET requests one every REQUEST_INTERVAL seconds, with USER_AGENT; nothing is retried."""

    def __init__(self, urlopen=urllib.request.urlopen, interval=REQUEST_INTERVAL):
        self.urlopen, self.interval, self.last = urlopen, interval, 0.0

    def get(self, url):
        time.sleep(max(0.0, self.last + self.interval - time.monotonic()))
        try:
            with self.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=60) as response:
                return response.read().decode("utf-8")
        finally:
            self.last = time.monotonic()

    def api(self, **query):
        return json.loads(self.get(API + urllib.parse.urlencode({**query, "format": "json", "formatversion": "2"})))


SITE = "https://therepository.fandom.com/wiki/"
# The Repository's category kinds, in the order asked; a world whose Mainline category is empty has no pages.
CATEGORY_TYPES = {"Mainline": "storyline", "Instance": "instance", "Side": "side"}
QUEST_TYPE = re.compile(r"^(\w+) Quest$")
LANG_ID = re.compile(r"WizQst([0-9A-F]+)")
LINK = re.compile(r"\[\[([^\]|#]*)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
FILE_LINK = re.compile(r"\[\[File:[^\]]*\]\]")
AUDIO = re.compile(r"\{\{D\|([^}]*)\}\}")
SPEAKER = re.compile(r"'''(.+?):'''")
TAG = re.compile(r"<[^>]+>")


def world_dir(cache, registered):
    return os.path.join(cache, "repository", registered.name.lower())


def index_path(cache, registered):
    return os.path.join(cache, "repository", f"index-repository-{registered.name.lower()}.json")


def category(registered, kind):
    return f"Category:Wizard101 {registered.wiki.replace('_', ' ')} {kind} Quests"


def cached_json(path, fetch):
    """The JSON at path; fetched and written there when the cache lacks it."""
    if not os.path.exists(path):
        answer = fetch()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(answer, f, indent=1, ensure_ascii=False)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def category_members(client, folder, title):
    def fetch():
        query = {"action": "query", "list": "categorymembers", "cmtitle": title, "cmlimit": "500", "cmnamespace": "0"}
        members = []
        while True:
            answer = client.api(**query)
            members += [member["title"] for member in answer["query"]["categorymembers"]]
            if "continue" not in answer:
                return members
            query.update(answer["continue"])
    return cached_json(os.path.join(folder, file_name(title) + ".json"), fetch)


def fetch_world(client, cache, registered):
    """The world's category listings and quest pages into the cache, each asked once."""
    folder = world_dir(cache, registered)
    os.makedirs(folder, exist_ok=True)
    cached_json(os.path.join(cache, "repository", "siteinfo.json"),
                lambda: client.api(action="query", meta="siteinfo", siprop="rightsinfo")["query"])
    counts = {"fetched": 0, "cached": 0}
    for kind in CATEGORY_TYPES:
        titles = category_members(client, folder, category(registered, kind))
        if not titles and kind == "Mainline":
            print(f"{registered.name}: {category(registered, kind)} is empty; no pages")
            return
        for title in titles:
            path = os.path.join(folder, file_name(title) + ".wikitext")
            if os.path.exists(path):
                counts["cached"] += 1
                continue
            text = client.api(action="parse", page=title, prop="wikitext")["parse"]["wikitext"]
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            counts["fetched"] += 1
        print(f"{registered.name}: {category(registered, kind)}: {len(titles)} pages")
    print(f"{registered.name}: {counts['fetched']} fetched, {counts['cached']} already cached")


def plain(text):
    text = FILE_LINK.sub("", text)
    text = LINK.sub(lambda m: m.group(2) or m.group(1), text)
    text = TAG.sub(" ", text).replace("'''", "").replace("''", "")
    return html.unescape(" ".join(text.split()))


def infobox(wikitext):
    fields = {}
    body = wikitext.split("{{Quest", 1)[1].split("\n}}", 1)[0] if "{{Quest" in wikitext else ""
    for line in body.split("\n"):
        if line.startswith("|") and "=" in line:
            key, value = line[1:].split("=", 1)
            fields[key.strip()] = value.strip()
    return fields


def section(wikitext, heading):
    match = re.search(rf"^=={re.escape(heading)}==\s*$(.*?)(?=^==[^=]|\Z)", wikitext, re.M | re.S)
    return match.group(1).split("\n") if match else []


def linked_titles(value):
    return [m.group(1).strip() for m in LINK.finditer(value) if not m.group(1).startswith("File:")]


def quest_type(value):
    match = QUEST_TYPE.match(plain(value))
    return CATEGORY_TYPES.get(match.group(1), match.group(1).lower()) if match else None


def dialogue_line(line):
    speaker = SPEAKER.search(line)
    audio = AUDIO.search(line)
    text = line[speaker.end():] if speaker else AUDIO.sub("", line.lstrip(":"))
    return {"speaker": plain(speaker.group(1)) if speaker else None, "text": plain(text),
            "audio": audio.group(1).strip() if audio else None}


def read_quest(title, wikitext):
    """A quest page's wikitext as an index entry: lang key, type, chain, goals and dialogue."""
    fields = infobox(wikitext)
    lang = LANG_ID.search(fields.get("id", ""))
    return {
        "name": title,
        "wiki_page": SITE + urllib.parse.quote(title.replace(" ", "_")),
        "lang_hex": lang.group(1) if lang else None,
        "type": quest_type(fields.get("type", "")),
        "prev": linked_titles(fields.get("prev", "")),
        "next": linked_titles(fields.get("next", "")),
        "goals": [plain(line[1:]) for line in section(wikitext, "Quest Goals") if line.startswith("#")],
        "dialogue": [dialogue_line(line) for line in section(wikitext, "Dialogue") if line.startswith(":")],
    }


def parse_world(cache, registered):
    """index-repository-<world>.json from the cached pages, with the licence of the text."""
    folder = world_dir(cache, registered)
    titles = []
    for kind in CATEGORY_TYPES:
        path = os.path.join(folder, file_name(category(registered, kind)) + ".json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                titles += [t for t in json.load(f) if t not in titles]
    quests = []
    for title in titles:
        with open(os.path.join(folder, file_name(title) + ".wikitext"), encoding="utf-8") as f:
            quests.append(read_quest(title, f.read()))
    with open(os.path.join(cache, "repository", "siteinfo.json"), encoding="utf-8") as f:
        rights = json.load(f)["rightsinfo"]
    index = {"source": "The Repository (https://therepository.fandom.com)", "licence": rights["text"],
             "licence_url": rights["url"], "quests": quests}
    with open(index_path(cache, registered), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    keyed = sum(1 for q in quests if q["lang_hex"])
    print(f"{registered.name}: {len(quests)} quests, {keyed} with a lang key")
    print(f"index: {index_path(cache, registered)}")
