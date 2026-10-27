"""Questgen specs for a world, built from the Wizard101 Central wiki, live or the Internet Archive's copies: enumerate
the world's quest pages, fetch them, parse them into specs."""
import argparse
import difflib
import glob
import gzip
import html
import json
import math
import os
import re
import sys
from typing import NamedTuple
import time
import urllib.robotparser
import urllib.error
import urllib.parse
import urllib.request

from .. import templates
from ..lang import LANG_SUBDIR, ROOTWAD_DIR, read_lang
from ..pack import PACK, QUEST_SPECS_DIR, quest_template_paths, zone_transfer_files
from ..wad import GAMEDATA_DIR, zone_of_wad
from ..worlds import WORLDS, lang_cluster, world
from .generate import diff
from .goal_lines import (COLLECT_VERBS, FIND_VERBS, ITEM_VERBS, MOVE_VERBS, PERSON_VERBS, TALK_VERBS, destinations,
                         goal_kind, is_goal_line, place_readings, repeated, strip_notes, target_text, unread_field,
                         verb_of)

DESCRIPTION = ("Build questgen specs for a world from the Wizard101 Central wiki, live first, else the Internet "
               "Archive's copies.")
DEFAULT_CACHE = os.path.join(PACK, ".scratch", "friends-server", "task-A1", "cache")
SITE = "https://wiki.wizard101central.com/"
WIKI = SITE + "wiki/"
API = SITE + "api.php?"
ARCHIVE = "https://web.archive.org/web/"
CDX = ("https://web.archive.org/cdx/search/cdx?url=wiki.wizard101central.com/wiki/Quest:*"
       "&fl=original,timestamp,statuscode&filter=statuscode:200&collapse=urlkey")
CATEGORY_CDX = ("https://web.archive.org/cdx/search/cdx?url=wiki.wizard101central.com/wiki/{}"
                "&fl=timestamp,statuscode&filter=statuscode:200")
# A partial timestamp redirects to the capture nearest to it, so this year asks for the newest capture.
NEWEST = "2026"
USER_AGENT = "spiraltools/1.0 (+https://github.com/han-xyz/spiraldb)"
REQUEST_INTERVAL = 1.0
LIVE_INTERVAL = 2.0
RETRY_STATUSES = {429, 500, 502, 503, 504}
LIVE_RETRY_STATUSES = {429, 503}
CHALLENGE = re.compile(rb"<title>Just a moment|challenge-platform|cf-chl-|cf_chl_", re.I)
LIVE, ARCHIVED = "live", "archive"
BACKOFF_START, BACKOFF_CAP, BACKOFF_TOTAL = 2.0, 60.0, 300.0
QUEST_TYPES = ("storyline", "side", "instance")
MIN_SHARED_WEIGHT, CLEAR_MARGIN = 4.0, 1.5
CHAIN_WINDOW = 16
NAME_CUTOFF = 0.8
MOB_NAME_CUTOFF = 0.9
TITLE_CUTOFF = 0.95
DIALOGUE_CUTOFF = 0.85
# Goals without a count: a line repeated on consecutive lines is that many goals.
UNCOUNTED_GOALS = ("persona", "waypoint")
ZONE_PREFIX = re.compile(r"^[A-Z]{2}_(?:Z\d+[A-Za-z]?_)?(?:I\d+_)?(?:the_)?", re.I)


class ArchiveUnavailable(Exception):
    pass


class Archive:
    """GET requests to the Wayback Machine, one a second, with exponential backoff on throttling and outages."""

    def __init__(self):
        self.last = 0.0

    def get(self, url):
        delay, waited = BACKOFF_START, 0.0
        while True:
            time.sleep(max(0.0, self.last + REQUEST_INTERVAL - time.monotonic()))
            self.last = time.monotonic()
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    data = response.read()
                    return response.url, gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
            except urllib.error.HTTPError as e:
                if e.code not in RETRY_STATUSES:
                    raise
                reason = f"HTTP {e.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                reason = str(e)
            if waited >= BACKOFF_TOTAL:
                raise ArchiveUnavailable(f"{url}: {reason}, gave up after {waited:.0f}s")
            print(f"  {reason}; retrying in {delay:.0f}s", file=sys.stderr)
            time.sleep(delay)
            waited += delay
            delay = min(delay * 2, BACKOFF_CAP)


class LiveUnavailable(Exception):
    pass


def is_challenge(headers, body):
    return headers.get("cf-mitigated") == "challenge" or bool(CHALLENGE.search(body[:20000]))


class LiveWiki:
    """GET requests to the live wiki: an honest User-Agent, robots.txt obeyed, one request every LIVE_INTERVAL
    seconds, exponential backoff on 429 and 503. A 403, a challenge page or an outage ends live fetching for the run,
    after one attempt: nothing here retries past a refusal."""

    def __init__(self, urlopen=urllib.request.urlopen, interval=LIVE_INTERVAL):
        self.urlopen, self.interval, self.last = urlopen, interval, 0.0
        self.robots = None
        self.stopped = None

    def page(self, key):
        """A quest page's HTML from the API's parse, else the page itself; None when neither answers."""
        query = {"action": "parse", "page": page_key(key), "prop": "text", "format": "json"}
        answer = self.attempt(lambda: self.json(API + urllib.parse.urlencode(query)))
        text = (answer or {}).get("parse", {}).get("text", {}).get("*")
        if text is None:
            data = self.attempt(lambda: self.get(WIKI + urllib.parse.quote(page_key(key), safe=":_()/,!")))
            text = data.decode("utf-8", errors="replace") if data is not None else None
        return text

    def category(self, category):
        """The subcategories and the Quest: pages of a category, by page key, from the API; None when it does not
        answer."""
        query = {"action": "query", "list": "categorymembers", "cmtitle": category, "cmlimit": "500",
                 "format": "json"}
        titles = []
        while True:
            answer = self.attempt(lambda: self.json(API + urllib.parse.urlencode(query)))
            if not answer or "query" not in answer:
                return None
            titles += [page_key(member["title"]) for member in answer["query"]["categorymembers"]]
            if "continue" not in answer:
                break
            query.update(answer["continue"])
        return ([t for t in titles if t.startswith("Category:")], [t for t in titles if t.startswith("Quest:")])

    def attempt(self, request):
        if self.stopped:
            return None
        try:
            return request()
        except LiveUnavailable as e:
            self.stopped = str(e)
            print(f"live wiki: {e}; using the Internet Archive from here on", file=sys.stderr)
            return None

    def json(self, url):
        data = self.get(url)
        return json.loads(data) if data is not None else None

    def get(self, url):
        """The body of a GET, or None on 404 and other refusals of this URL alone, and for a URL robots.txt
        disallows."""
        if self.robots is None:
            self.robots = urllib.robotparser.RobotFileParser()
            self.robots.parse((self.request(SITE + "robots.txt") or b"").decode("utf-8", errors="replace").splitlines())
            self.interval = max(self.interval, float(self.robots.crawl_delay(USER_AGENT) or 0))
        if not self.robots.can_fetch(USER_AGENT, url):
            return None
        return self.request(url)

    def request(self, url):
        delay, waited = BACKOFF_START, 0.0
        while True:
            time.sleep(max(0.0, self.last + self.interval - time.monotonic()))
            self.last = time.monotonic()
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with self.urlopen(request, timeout=60) as response:
                    data = response.read()
                if is_challenge({}, data):
                    raise LiveUnavailable(f"{url}: a challenge page")
                return data
            except urllib.error.HTTPError as e:
                with e:
                    body = e.read()
                if e.code == 403 or is_challenge(e.headers, body):
                    raise LiveUnavailable(f"{url}: HTTP {e.code}{' (challenge)' if e.code != 403 else ''}")
                if e.code not in LIVE_RETRY_STATUSES:
                    return None
                reason = f"HTTP {e.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                raise LiveUnavailable(f"{url}: {e}")
            if waited >= BACKOFF_TOTAL:
                raise LiveUnavailable(f"{url}: {reason}, gave up after {waited:.0f}s")
            print(f"  {reason}; retrying in {delay:.0f}s", file=sys.stderr)
            time.sleep(delay)
            waited += delay
            delay = min(delay * 2, BACKOFF_CAP)


def page_key(title):
    """A wiki page title as the archive's URL path writes it: underscores, no percent escapes."""
    return urllib.parse.unquote(title).replace(" ", "_")


def file_name(key):
    return re.sub(r"[^A-Za-z0-9_.()'-]", "_", key)


class Cached(NamedTuple):
    stamp: str
    source: str
    path: str


# <timestamp>_<live|archive>_<page>.html; the pages cached before the live wiki was asked have no source and are
# archive captures.
CACHED_NAME = re.compile(r"(\d{14})_(?:(live|archive)_)?(.+)\.html")


def cached_copies(cache, key):
    """The cached copies of a page, live before archived and newest first."""
    name = file_name(key)
    hits = []
    for path in glob.glob(os.path.join(cache, f"[0-9]*_{glob.escape(name)}.html")):
        match = CACHED_NAME.fullmatch(os.path.basename(path))
        if match and match.group(3) == name:
            hits.append(Cached(match.group(1), match.group(2) or ARCHIVED, path))
    return sorted(hits, key=lambda hit: (hit.source == LIVE, hit.stamp), reverse=True)


def cached(cache, key):
    """The preferred cached copy of a page, or None."""
    return next(iter(cached_copies(cache, key)), None)


def save_page(cache, key, stamp, source, text):
    with open(os.path.join(cache, f"{stamp}_{source}_{file_name(key)}.html"), "w", encoding="utf-8") as f:
        f.write(text)


def fetch_page(archive, cache, key, raw=True, at=NEWEST):
    """A wiki page's newest capture, from the cache or the archive."""
    hit = cached(cache, key)
    if hit:
        with open(hit.path, encoding="utf-8") as f:
            return hit.stamp, f.read()
    return download_page(archive, cache, key, raw, at)


def download_page(archive, cache, key, raw, at):
    url, data = archive.get(f"{ARCHIVE}{at}{'id_' if raw else ''}/{WIKI}{urllib.parse.quote(key, safe=':_()/,!')}")
    stamp = re.search(r"/web/(\d{14})", url).group(1)
    text = data.decode("utf-8", errors="replace")
    save_page(cache, key, stamp, ARCHIVED, text)
    return stamp, text


def fetch_quest(live, archive, cache, entry):
    """Fetches a quest page from the live wiki, else from the archive unless an archived copy is cached or none
    exists; the source fetched from, or None."""
    text = live.page(entry["page"])
    if text is not None:
        save_page(cache, entry["page"], time.strftime("%Y%m%d%H%M%S", time.gmtime()), LIVE, text)
        return LIVE
    if cached(cache, entry["page"]) or entry.get("missing_snapshot"):
        return None
    try:
        fetch_page(archive, cache, entry["page"])
    except urllib.error.HTTPError as e:
        if e.code not in (403, 404):
            raise
        # The newest capture can be an error page or refused; the CDX timestamp is a capture with status 200.
        fetch_page(archive, cache, entry["page"], at=entry["timestamp"])
    return ARCHIVED


def category_members(page):
    """The subcategories and the Quest: pages a category page lists, by page key."""
    start = page.find('id="mw-subcategories"')
    end = page.find('id="mw-pages"')
    block = page[start:end] if 0 <= start < end else ""
    subcategories = [page_key(m) for m in re.findall(r'href="[^"]*/wiki/(Category:[^"#?]+)"', block)]
    pages_block = page[end:page.find('class="printfooter"', end)] if end >= 0 else ""
    quests = [page_key(m) for m in re.findall(r'href="[^"]*/wiki/(Quest:[^"#?]+)"', pages_block)]
    return list(dict.fromkeys(subcategories)), list(dict.fromkeys(quests))


def quest_type_of(category):
    match = re.search(rf"_({'|'.join(t.title() for t in QUEST_TYPES)})_Quests$", category)
    return match.group(1).lower() if match else None


def is_category_page(page):
    return 'id="mw-pages"' in page or 'id="mw-subcategories"' in page


def fetch_category(archive, cache, category):
    """A category page from the newest cached or archived capture with status 200 that lists members, or None."""
    return fetch_capture(archive, cache, category, is_category_page)


def fetch_capture(archive, cache, key, is_usable):
    """A page from the newest cached or archived capture with status 200 that is_usable accepts, or None. The newest
    captures can be recorded refusals, which the archive serves as a page of its own."""
    stamps = set()
    for hit in cached_copies(cache, key):
        stamps.add(hit.stamp)
        with open(hit.path, encoding="utf-8") as f:
            page = f.read()
        if is_usable(page):
            return page
    _, data = archive.get(CATEGORY_CDX.format(urllib.parse.quote(key, safe=":_()/,!")))
    captures = [line.split() for line in data.decode().splitlines()]
    for stamp in reversed([fields[0] for fields in captures if fields[1:2] == ["200"]]):
        if stamp in stamps:
            continue
        try:
            page = download_page(archive, cache, key, raw=False, at=stamp)[1]
        except urllib.error.HTTPError as e:
            if e.code not in (403, 404):
                raise
            continue
        if is_usable(page):
            return page
    return None


def category_listing(live, archive, cache, category):
    """(subcategories, quest pages) of a category, from the live wiki else the archive; None when neither lists
    any."""
    found = live.category(category)
    if found is None:
        page = fetch_category(archive, cache, category)
        found = category_members(page) if page is not None else None
    return found if found and any(found) else None


def content_quests(page, key):
    """The Quest: pages the content of a page links to, without the page itself and other quest trees."""
    start = page.find('id="mw-content-text"')
    end = page.find('class="printfooter"', max(start, 0))
    block = page[max(start, 0):end if end >= 0 else None]
    found = [page_key(m) for m in re.findall(r'href="[^"]*/wiki/(Quest:[^"#?]+)"', block)]
    return list(dict.fromkeys(q for q in found if q != key and not q.endswith("_Quest_Tree")))


def tree_quests(live, archive, cache, registered):
    """The quest pages the world's Quest Tree page links to; none when it is neither live nor archived."""
    key = f"Quest:{registered.wiki}_Quest_Tree"
    page = live.page(key) or fetch_capture(archive, cache, key, lambda text: bool(content_quests(text, key)))
    return content_quests(page, key) if page else []


def walk_categories(live, archive, cache, registered):
    """quest page key -> {"zones": set, "types": set}, from the world's category tree."""
    root = registered.category
    quests = {}
    queue = [(root, None)]
    seen = set()
    while queue:
        category, zone = queue.pop(0)
        if category in seen:
            continue
        seen.add(category)
        found = category_listing(live, archive, cache, category)
        if found is None:
            print(f"{category}: no capture found; its pages are listed only through other categories")
            if category == root:
                queue += [(f"Category:{registered.wiki}_{kind.title()}_Quests", None) for kind in QUEST_TYPES]
                for quest in tree_quests(live, archive, cache, registered):
                    quests.setdefault(quest, {"zones": set(), "types": set()})
            continue
        subcategories, members = found
        kind = quest_type_of(category)
        for quest in members:
            entry = quests.setdefault(quest, {"zones": set(), "types": set()})
            if zone:
                entry["zones"].add(zone)
            if kind:
                entry["types"].add(kind)
        for sub in subcategories:
            sub_zone = zone
            if category == root and not quest_type_of(sub):
                sub_zone = sub[len("Category:"):-len("_Quests")].replace("_", " ")
            queue.append((sub, sub_zone))
    return quests


def archived_quests(archive):
    """quest page key -> timestamp of its first capture with status 200, from the CDX index."""
    _, data = archive.get(CDX)
    found = {}
    for line in data.decode().splitlines():
        original, stamp, _status = line.split(" ")
        path = original.split("/wiki/", 1)[1]
        if "?" not in path:
            found.setdefault(page_key(path), stamp)
    return found


def index_path(cache, world):
    return os.path.join(cache, f"index-{world.lower()}.json")


def enumerate_world(live, archive, cache, registered):
    world = registered.name
    quests = walk_categories(live, archive, cache, registered)
    archived = archived_quests(archive)
    index = []
    for key in sorted(quests):
        entry = {"name": key[len("Quest:"):].replace("_", " "), "page": key}
        if key in archived:
            entry["timestamp"] = archived[key]
        else:
            entry["missing_snapshot"] = True
        entry["zones"] = sorted(quests[key]["zones"])
        entry["type"] = "/".join(sorted(quests[key]["types"])) or None
        index.append(entry)
    with open(index_path(cache, world), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    missing = sum(1 for e in index if e.get("missing_snapshot"))
    print(f"{world}: {len(index)} quests, {len(index) - missing} archived, {missing} without a snapshot")
    print(f"index: {index_path(cache, world)}")


def load_index(cache, world):
    path = index_path(cache, world)
    if not os.path.exists(path):
        raise SystemExit(f"{path}: run --enumerate {world} first")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch_world(live, archive, cache, world):
    counts = {LIVE: 0, ARCHIVED: 0, "kept": 0, "none": 0, "failed": 0}
    for entry in load_index(cache, world):
        hit = cached(cache, entry["page"])
        if hit and hit.source == LIVE:
            continue
        try:
            source = fetch_quest(live, archive, cache, entry)
        except urllib.error.HTTPError as e:
            print(f"{entry['name']}: HTTP {e.code}")
            counts["failed"] += 1
            continue
        outcome = source or ("kept" if hit else "none")
        counts[outcome] += 1
        if source:
            print(f"{entry['name']}: {source} {cached(cache, entry['page']).stamp}")
    print(f"{world}: {counts[LIVE]} live, {counts[ARCHIVED]} from the archive, {counts['kept']} archived copies kept, "
          f"{counts['none']} without a page, {counts['failed']} failed")


def page_lines(page):
    """The Quest Information section as text lines: links as [Namespace:text], '@' per indent level."""
    start = page.find('id="Quest_Information"')
    end = page.find('id="Quest_Dialogue"', start)
    text = page[start:end if end > 0 else None]
    text = re.sub(r'<a [^>]*href="[^"]*/wiki/File:([^"]*)"[^>]*>.*?</a>', r"[File:\1]", text, flags=re.S)
    text = re.sub(r'<a [^>]*href="[^"]*/wiki/([A-Za-z]+):[^"]*"[^>]*>(.*?)</a>',
                  lambda m: f"[{m.group(1)}:{re.sub('<[^>]+>', '', m.group(2))}]", text, flags=re.S)
    text = re.sub(r'<span style="margin-left:(\d+)px">', lambda m: "@" * (int(m.group(1)) // 20), text)
    text = re.sub(r"<br\s*/?>|</(p|dd|li|tr|dl|td)>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ")
    return [line.strip() for line in text.split("\n") if line.strip()]


def links(line, namespace):
    return re.findall(rf"\[{namespace}:([^\]]+)\]", line)


def plain(line):
    return re.sub(r"\[\w+:([^\]]*)\]", r"\1", line).lstrip("@").strip()


def section(lines, first, stop):
    start = next((i for i, line in enumerate(lines) if line.startswith(first)), None)
    if start is None:
        return []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(stop)), len(lines))
    return lines[start:end]


def read_page(page):
    """The fields of a quest page: prequests, giver, type sentence, goal lines, hand-in and reward."""
    lines = page_lines(page)
    head = section(lines, "", "Goals:")
    given = next((line for line in head if line.startswith("Given By:")), "")
    goal_lines = section(lines, "Goals:", "Hand In:")[1:]
    hand_in = next((line for line in lines if line.startswith("Hand In:")), "")
    reward = section(lines, "Reward:", "Leads to:")
    amounts = {}
    for i, line in enumerate(reward[:-1]):
        icon = re.match(r"\[File:\(Icon\)_(Gold|XP)\.png\]", line)
        if icon and re.fullmatch(r"[\d,]+", reward[i + 1]):
            amounts[icon.group(1).lower()] = int(reward[i + 1].replace(",", ""))
    leads_to = section(lines, "Leads to:", "<")[1:]
    sentence = next((line for line in head if line.startswith("This is a")), "")
    place = next((line for line in head if re.match(r"(Giver|Start) Location:", line)), "")
    return {
        "prequests": [q for line in (head[:head.index(given)] if given else head) for q in links(line, "Quest")],
        "giver": (links(given, "NPC") or [None])[0],
        "auto_start": "automatically" in given,
        "giver_location": (links(place, "Location") or [plain(place.split(":", 1)[-1]) or None])[0],
        "mainline": "storyline" in sentence,
        "instance": "instance" in sentence,
        "goals": goal_lines,
        "hand_in": (links(hand_in, "NPC") or [None])[0],
        "reward": amounts,
        "leads_to": [q for line in leads_to for q in links(line, "Quest")],
    }


def grouped_goals(goal_lines):
    """Goal lines as (line, sub-item lines): a line without '@' continues the one before, '@@' lines are sub-items."""
    groups = []
    for line in goal_lines:
        depth = len(line) - len(line.lstrip("@"))
        if depth >= 2 and groups:
            groups[-1][1].append(line.lstrip("@"))
        elif depth == 0 and groups:
            if line.startswith("("):
                continue
            if groups[-1][1]:
                groups[-1][1][-1] += " " + line
            else:
                groups[-1][0] += " " + line
        else:
            groups.append([line.lstrip("@"), []])
    return groups


def norm(text):
    return re.sub(r"[^a-z0-9]", "", text.lower().replace("’", "'"))


def title_norm(title):
    return norm(re.sub(r"^the\s+", "", title.strip(), flags=re.I))


def singular_forms(text):
    """Normalised spellings of a name as it may appear in the plural on the wiki."""
    base = norm(re.sub(r"^(the|a|an)\s+", "", text.strip(), flags=re.I))
    forms = [base]
    for suffix, replacement in (("ies", "y"), ("es", ""), ("s", "")):
        if base.endswith(suffix):
            forms.append(base[:-len(suffix)] + replacement)
    return forms


def singular(word):
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "xes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def nearest_folders(registered, folders):
    """ObjectData folders, the registered worlds' first, nearest the world in WORLDS order (the earlier of two equally
    near), then the rest by name."""
    here = WORLDS.index(registered)
    order = {w.folder: (abs(i - here), i) for i, w in enumerate(WORLDS)}
    return sorted(folders, key=lambda folder: (order.get(folder, (len(WORLDS), 0)), folder))


class ClientData:
    """The lookups a spec needs: titles, personas, mobs, objects, zone locations and the pack's quests."""

    def __init__(self, registered):
        self.world = registered.name
        self.folder = registered.folder
        self.level = registered.level
        self.read_lang = lambda name: read_lang(ROOTWAD_DIR, name)
        self.titles = self.read_lang("QuestTitle")
        self.lang_range = lang_cluster(registered, ROOTWAD_DIR)
        self.range_is_declared = registered.lang_range is not None
        self.lang_dir = os.path.join(ROOTWAD_DIR, LANG_SUBDIR)
        rows = list(templates.npcs(ROOTWAD_DIR, self.folder))
        placed = templates.zone_placements(GAMEDATA_DIR, self.world, {row["template"]: row["template_id"]
                                                                      for row in rows})
        zones_of_persona = {}
        for row in rows:
            zones_of_persona.setdefault(row["persona"], []).extend(placed[row["template"]])
        self.personas = {}
        for row in rows:
            if row["name"]:
                # A named template that no zone places may share its persona with an unnamed one that is placed.
                row["zones"] = placed[row["template"]] or list(dict.fromkeys(zones_of_persona[row["persona"]]))
                row["persona"] = row["persona"][:-len("_Persona")].strip()
                row["folder"] = self.folder
                self.personas.setdefault(norm(row["name"]), []).append(row)
        self.mob_keys = {}
        for key, text in self.read_lang("WizardMobs").items():
            self.mob_keys.setdefault(text, key)
        self.mobs = self.mob_index([self.folder])
        self.other_folders = nearest_folders(registered, [
            folder for folder in os.listdir(os.path.join(ROOTWAD_DIR, "ObjectData"))
            if folder != self.folder and os.path.isdir(os.path.join(ROOTWAD_DIR, "ObjectData", folder))])
        self.other_mobs, self.other_personas = None, None
        item_rows = list(templates.items(ROOTWAD_DIR, self.folder))
        self.objects = item_index(item_rows, self.folder)
        self.item_words = item_words(item_rows, self.folder)
        self.item_ids = {row["template"]: row["template_id"] for row in item_rows}
        self.item_zones = {}
        self.known_zones = set(zone_transfer_files())
        self.zone_names = {}
        for path in glob.glob(os.path.join(GAMEDATA_DIR, f"{self.world}-*.wad")):
            zone = zone_of_wad(path)
            self.zone_names.setdefault(norm(ZONE_PREFIX.sub("", zone.rsplit("/", 1)[-1])), []).append(zone)
        self.zone_locations = {}
        # Of the keys that read the same, the unpadded one with the lowest number is the zone's own.
        for key, text in sorted(self.read_lang("ZoneLocName").items(),
                                key=lambda item: (item[0].startswith("0"), int(item[0]) if item[0].isdigit() else 0)):
            self.zone_locations.setdefault(norm(text), "ZoneLocName_" + key)
        self.pack_quests = {}
        for path in quest_template_paths():
            with open(path, encoding="utf-8") as f:
                text = f.read()
            title = re.search(r'"m_questTitle":\s*"QuestTitle_([^"]*)"', text)
            name = re.search(r'"m_questName":\s*"([^"]*)"', text)
            if title and name:
                self.pack_quests.setdefault(title.group(1), name.group(1))

    def mob_index(self, folders):
        found = {}
        for folder in folders:
            for name, template, _id, adjectives in templates.mobs(ROOTWAD_DIR, folder):
                own = f"{template}.AdjRef"
                found.setdefault(norm(name), []).append(
                    {"adjective": own if own in adjectives else (adjectives or [None])[0],
                     "target": f"WizardMobs_{self.mob_keys[name]}" if name in self.mob_keys else "",
                     "folder": folder})
        return found

    def other_world_personas(self, wanted):
        """The persona rows of other ObjectData folders for a name, with the zones of any world that place them."""
        if self.other_personas is None:
            self.other_personas = {}
            for folder in self.other_folders:
                for row in templates.npcs(ROOTWAD_DIR, folder):
                    if row["name"]:
                        row["persona"] = row["persona"][:-len("_Persona")].strip()
                        row["folder"], row["zones"] = folder, None
                        self.other_personas.setdefault(norm(row["name"]), []).append(row)
        rows = self.other_personas.get(wanted, [])
        unplaced = [row for row in rows if row["zones"] is None]
        if unplaced:
            placed = templates.zone_placements(GAMEDATA_DIR, "*", {row["template"]: row["template_id"]
                                                                  for row in unplaced})
            for row in unplaced:
                row["zones"] = placed[row["template"]]
        return rows

    def in_range(self, key):
        return re.fullmatch(r"[0-9A-F]+", key) and self.lang_range[0] <= int(key, 16) <= self.lang_range[1]

    def has_quest_lang(self, key):
        return os.path.exists(os.path.join(self.lang_dir, f"WizQst{key}.lang"))

    def title_keys(self, title):
        """The QuestTitle keys that read the title; a title the wiki tagged with its world, `Monkey Business
        (Novus)`, is read without the tag when nothing reads it whole."""
        for wanted in dict.fromkeys([title_norm(title), title_norm(strip_notes(title))]):
            found = [key for key, text in self.titles.items() if title_norm(text) == wanted]
            if found:
                return found
        return []

    def title_lang(self, title):
        """The quest lang key that reads the title: in the world's range first; only in it when the range is
        declared."""
        keys = [k for k in self.title_keys(title) if self.has_quest_lang(k)] or self.close_title_keys(title)
        if self.range_is_declared:
            keys = [k for k in keys if self.in_range(k)]
        return min(keys, key=lambda k: not self.in_range(k), default=None)

    def close_title_keys(self, title):
        """The one in-range quest lang key whose title reads nearly as the title (`Till` for the wiki's `'Til`), when
        no key reads it exactly."""
        texts = {}
        for key, text in self.titles.items():
            if self.in_range(key) and self.has_quest_lang(key) and text.strip() and not self.internal_name(key):
                texts.setdefault(title_norm(text), []).append(key)
        close = difflib.get_close_matches(title_norm(strip_notes(title)), texts, n=2, cutoff=TITLE_CUTOFF)
        return texts[close[0]] if len(close) == 1 and len(texts[close[0]]) == 1 else []

    def internal_name(self, key):
        text = self.titles.get(key, "")
        return text if re.fullmatch(r"[A-Z]{2,}(-[A-Za-z0-9]+)+", text) else None

    def placeholder_langs(self):
        """The world's quest lang keys whose QuestTitle entry is empty or the internal name, not the title."""
        return [key for key in self.titles if self.in_range(key) and self.has_quest_lang(key)
                and (not self.titles[key].strip() or self.internal_name(key))]

    def quest_lines(self, key):
        return self.read_lang(f"WizQst{key}") if self.has_quest_lang(key) else {}

    def location(self, place):
        return self.zone_locations.get(norm(f"{self.world}|{place}"))

    def zone_by_place(self, place):
        """The world's one zone whose wad is named for the place, read without its article and else without its
        possessive (`the Drum House`: ZF_Z10_I03_Drum_House, `Centaurzan's Cabin`: LM_Z01_CentaurzanCabin), else
        None."""
        name = re.sub(r"^(the|a|an)\s+", "", place.strip(), flags=re.I)
        zones = self.zone_names.get(norm(name)) or self.zone_names.get(norm(re.sub(r"['’]s\b", "", name)), [])
        return zones[0] if len(zones) == 1 else None

    def has_persona(self, name):
        return norm(name) in self.personas

    def persona(self, name, zone):
        """The persona row for an NPC name, preferring one placed in the zone; None when the world has none."""
        wanted = norm(name)
        rows = self.personas.get(wanted) or [row for key, rows in self.personas.items() if key.endswith(wanted)
                                             for row in rows]
        close = difflib.get_close_matches(wanted, self.personas, n=2, cutoff=NAME_CUTOFF)
        if not rows and len(close) == 1:
            rows = self.personas[close[0]]
        rows = rows or self.other_world_personas(wanted)
        if not rows:
            return None
        reachable = (row for row in rows if self.known_zones.intersection(row["zones"]))
        return next((row for row in rows if zone in row["zones"]),
                    next(reachable, next((row for row in rows if row["zones"]), rows[0])))

    def mob_entries(self, name):
        """The mob entries for a name, from the world's folder, else from the nearest other folder that has it."""
        forms = mob_forms(name)
        found = next((self.mobs[form] for form in forms if form in self.mobs), [])
        if found:
            return found
        if self.other_mobs is None:
            self.other_mobs = self.mob_index(self.other_folders)
        found = next((self.other_mobs[form] for form in forms if form in self.other_mobs), [])
        nearest = min((entry["folder"] for entry in found), key=self.other_folders.index, default=None)
        return [entry for entry in found if entry["folder"] == nearest] or self.mob_entries_named_loosely(name)

    def mob_entries_named_loosely(self, name):
        """The entries of the one world mob the name reads without the mob's article or epithet (`Bantam`: The Bantam,
        `Eurgh`: Eurgh the Grinder), else of the one mob spelled closely (`Abberant`: Aberrant)."""
        wanted = norm(name)
        keys = [key for key in self.mobs if key == "the" + wanted or key.startswith(wanted + "the")]
        if not keys:
            keys = difflib.get_close_matches(wanted, self.mobs, n=2, cutoff=MOB_NAME_CUTOFF)
        return self.mobs[keys[0]] if len(keys) == 1 else []

    def object_entries(self, name):
        return item_entries(self.objects, name)

    def usage_entries(self, name, zone=""):
        """The entries of the item a usage goal names: by its name, else by its words when one item reads them, or
        one of the items they read that a zone places: the one in the goal's zone, else the one placed at all."""
        found = self.object_entries(name)
        if found:
            return found
        candidates = word_entries(self.item_words, name)
        if len(candidates) > 1:
            zones = self.zones_of_items(candidates)
            placed = {template: entry for template, entry in candidates.items() if zones[template]}
            candidates = {template: entry for template, entry in placed.items() if zone in zones[template]} or placed
        return list(candidates.values()) if len(candidates) == 1 else []

    def zones_of_items(self, names):
        """template name -> the zones of the world that place the item."""
        wanted = {name: self.item_ids[name] for name in names if name not in self.item_zones}
        if wanted:
            self.item_zones.update(templates.zone_placements(GAMEDATA_DIR, self.world, wanted))
        return {name: self.item_zones[name] for name in names}


def mob_forms(name):
    """Normalised spellings of a mob name: singular, with its article (`The Scorpion`), each word singular."""
    words = [norm(word) for word in re.findall(r"[\w'’-]+", name)]
    return list(dict.fromkeys(singular_forms(name) + [norm(name), "".join(map(singular, words))]))


def item_index(rows, folder):
    """Name form -> the usage goal entries (adjective, descriptor) of the items that go by it: the display name,
    the quest icon name and the template name without folder prefix and number padding."""
    index = {}
    for row in rows:
        own = f"{row['template']}.AdjRef"
        adjective = own if own in row["adjectives"] else row["adjectives"][0]
        lang_name = row["name_key"].rpartition("_")[0]
        if row["name"]:
            descriptor = row["name_key"] if lang_name != "WizardMobs" else ""
            index.setdefault(norm(row["name"]), []).append({"adjective": adjective, "descriptor": descriptor})
        if row["icon"]:
            index.setdefault(norm(row["icon"]), []).append({"adjective": adjective, "descriptor": ""})
        stem = re.sub(r"0*(\d+)$", r"\1", norm(re.sub(rf"^{folder}[-_]", "", row["template"], flags=re.I)))
        index.setdefault(stem, []).append({"adjective": adjective, "descriptor": ""})
    return {form: [entry for i, entry in enumerate(entries)
                   if entry["adjective"] not in {e["adjective"] for e in entries[:i]}]
            for form, entries in index.items()}


ITEM_STOP_WORDS = {"the", "a", "an", "of", "and", "in", "on", "at", "into", "to", "from", "near", "with", "for",
                   "away", "down", "up", "out", "off", "your"}
# Editor stand-ins, and objects the quest helper never points at (Mirage's carpets `To Alkali Barrows`).
UNMATCHED_ADJECTIVES = {"EditorOnly", "NoQH"}
ITEM_PREPOSITION = re.compile(r"\s+(?:in|on|at|into|near|from|to|with|for)\s+", re.I)


def name_words(text):
    """The words of a name or template name, camel case split, digits and possessives dropped, each singular, without
    articles, prepositions and particles."""
    text = re.sub(r"['’]s\b|['’]", "", text)
    words = (word.lower() for word in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", text))
    return frozenset(singular(word) for word in words if word not in ITEM_STOP_WORDS)


def item_words(rows, folder):
    """(template, word sets of its display name, quest icon and template name, usage goal entry) per item that a
    goal can name: not the editor's stand-ins or the objects the quest helper skips."""
    found = []
    for row in rows:
        if UNMATCHED_ADJECTIVES.intersection(row["adjectives"]):
            continue
        own = f"{row['template']}.AdjRef"
        adjective = own if own in row["adjectives"] else row["adjectives"][0]
        descriptor = row["name_key"] if row["name"] and not row["name_key"].startswith("WizardMobs_") else ""
        texts = [row["name"], row["icon"], re.sub(rf"^{folder}[-_]", "", row["template"], flags=re.I)]
        found.append((row["template"], [name_words(text) for text in texts if text],
                      {"adjective": adjective, "descriptor": descriptor}))
    return found


def word_matches(items, wanted, readings=3):
    """The items whose words read the wanted words, by the first of `readings` that any item meets: the same words,
    all of them, (two or more of the item's words) a part of them."""
    if not wanted:
        return []
    for reads in (lambda words: words == wanted, lambda words: wanted <= words,
                  lambda words: len(words) >= 2 and words <= wanted)[:readings]:
        found = [item for item in items if any(map(reads, item[1]))]
        if found:
            return found
    return []


def word_entries(items, phrase):
    """template -> entry of the items with a word that is the whole phrase (`Cell Door`: wot celldoor), else whose words
    read the goal phrase, else that its head or, by the same words, the object after its preposition reads (`seeds in
    Soil`)."""
    phrase = re.sub(r"\s*\([^)]*\)?|#", " ", phrase).strip()
    parts = ITEM_PREPOSITION.split(phrase)
    one_word = norm(phrase)
    found = ([item for item in items if any(one_word in words for words in item[1])]
             or word_matches(items, name_words(phrase), 3 if len(parts) == 1 else 2))
    if not found and len(parts) > 1:
        found = word_matches(items, name_words(parts[0])) + word_matches(items, name_words(parts[-1]), 1)
    return {template: entry for template, _, entry in found}


ITEM_PLACE = re.compile(r"\s*\(.*?\)|\s+(in|at|on|near|with|for|from)\s+.*$|#")
ITEM_ORDINAL = re.compile(r"^(a|an|the|first|second|third|final|last)\s+", re.I)
ITEM_MEASURE = re.compile(r"^(pieces?|piles?|bottles?|measures?|bits?|chunks?) of\s+", re.I)


def item_entries(index, phrase):
    """The item entries a goal phrase names, read without its place, article, measure word or trailing number."""
    name = ITEM_PLACE.sub("", phrase).strip()
    bare = ITEM_MEASURE.sub("", ITEM_ORDINAL.sub("", name))
    readings = list(dict.fromkeys(text for reading in (name, ITEM_ORDINAL.sub("", name), bare)
                                  for text in (reading, re.sub(r"\s+\d+$", "", reading))))
    forms = [form for reading in readings
             for form in singular_forms(reading) + [norm(re.sub(r"(?<=\w\w)s\b", "", reading))]]
    for form in dict.fromkeys(forms):
        if form in index:
            return index[form]
    for form in singular_forms(bare):
        prefixed = [entry for key, entries in index.items() if key.startswith(form) and len(form) >= 6
                    for entry in entries]
        if prefixed:
            return prefixed
    return []


UNDERWAY = re.compile(r"\b(in the middle of|you were (going|getting|supposed|meant)|thought you were|still need|"
                      r"haven't (yet )?|have you (found|got|defeated))", re.I)
THANKS = re.compile(r"^(oh,? )?(thank|thanks|excellent|wonderful|marvel|splendid|brilliant|smashing|spot on|good show|"
                    r"well done|good work|great|you did it|you found|you've|you have|ah,? you|there you are|"
                    r"you're back|you made it)", re.I)


def heuristic_dialogs(lines, internal):
    """Prep, Underway and Completion line keys of a WizQst file, guessed from the text of each line."""
    prep, underway, completion = [], [], []
    for key in sorted(lines):
        text = lines[key].strip()
        if not text or text == internal or "|" in text or (len(text.split()) <= 4 and not re.search(r"[.!?]", text)):
            continue
        if UNDERWAY.search(text):
            underway.append(key)
        elif THANKS.search(text):
            completion.append(key)
        else:
            prep.append(key)
    return prep, underway, completion


class SpecBuilder:
    """Turns the fields of one quest page into a questgen spec, listing what it could not resolve."""

    def __init__(self, data, entry, fields, zone_paths, quest_ids, known_zones, predecessor_hand_in=None):
        self.data, self.entry, self.fields = data, entry, fields
        self.predecessor_hand_in = predecessor_hand_in
        self.known_zones = known_zones
        self.zone_paths, self.quest_ids = zone_paths, quest_ids
        self.zone_name = zone_name_of(entry, fields)
        self.zone = zone_paths.get(self.zone_name, "")
        self.review = []
        self.personas = {}

    def unresolved(self, field, value, blocking):
        self.review.append({"field": field, "value": value, "blocking": blocking})

    def zone_loc(self):
        return self.data.location(self.zone_name) if self.zone_name else None

    def persona_ref(self, name, field):
        name = strip_notes(name)
        row = self.data.persona(name, self.zone)
        if row is None:
            self.unresolved(field, name, True)
            return None, ""
        if norm(row["name"]) != norm(name) and not norm(row["name"]).endswith(norm(name)):
            self.unresolved(f"{field} (closest name)", f"{name} read as {row['name']}", False)
        if row["folder"] != self.data.folder:
            self.unresolved(f"{field} (other world)", f"{name}: {row['template']} from ObjectData/{row['folder']}",
                            False)
        self.personas[row["persona"]] = {"portrait": row["portrait"], "template_id": row["template_id"]}
        reachable = [zone for zone in row["zones"] if zone in self.known_zones]
        zone = self.zone if self.zone in row["zones"] else (reachable or row["zones"] or [""])[0]
        if not zone:
            self.unresolved(f"{field}.zone (placed in no zone)", name, True)
        return row["persona"], zone

    def persona_goal(self, name, with_previous=False):
        bare = strip_notes(name)
        if (self.data.persona(bare, self.zone) is None and ITEM_PLACE.sub("", bare).strip() == bare
                and self.data.object_entries(bare)):
            goal = self.usage_goal([bare], 1)
            if with_previous:
                goal["with_previous"] = True
            return goal
        persona, zone = self.persona_ref(name, "goal.persona")
        if persona is None:
            return None
        goal = {"type": "persona", "persona": persona, "zone": zone}
        loc = self.data.location(self.place_of(zone)) if zone else None
        if loc:
            goal["loc"] = loc
        if with_previous:
            goal["with_previous"] = True
        return goal

    def place_of(self, zone):
        return next((name for name, path in self.zone_paths.items() if path == zone), self.zone_name or "")

    def bounty_goal(self, creatures, count, item, place, with_previous=False, zone=None):
        mobs, target = [], ""
        for creature in map(strip_notes, creatures):
            entries = self.data.mob_entries(creature)
            if not entries:
                self.unresolved("goal.mobs", creature, True)
            for folder in sorted({e["folder"] for e in entries} - {self.data.folder}):
                self.unresolved("goal.mobs (other folder)", f"{creature}: ObjectData/{folder}", False)
            mobs += [e["adjective"] for e in entries if e["adjective"]]
            target = target or next((e["target"] for e in entries if e["target"]), "")
        if not mobs:
            return None
        goal = {"type": "bountycollect" if item else "bounty", "mobs": list(dict.fromkeys(mobs)), "count": count,
                "target": target, "zone": zone or self.zone}
        if item:
            descriptor = self.descriptor(item)
            if descriptor:
                goal["descriptor"] = descriptor
            else:
                self.unresolved("goal.descriptor", item, False)
        loc = (place and self.data.location(place)) or self.zone_loc()
        if loc:
            goal["loc"] = loc
        if with_previous:
            goal["with_previous"] = True
        return goal

    def usage_goal(self, names, count):
        items, descriptor = [], ""
        for name in names:
            entries = self.data.usage_entries(name, self.zone)
            if not entries:
                self.unresolved("goal.items", name, True)
            items += [e["adjective"] for e in entries]
            descriptor = descriptor or next((e["descriptor"] for e in entries if e["descriptor"]), "")
        if not items:
            return None
        goal = {"type": "usage", "items": list(dict.fromkeys(items)), "count": count, "zone": self.zone}
        goal["descriptor"] = descriptor or self.descriptor(names[0]) or ""
        if not goal["descriptor"]:
            del goal["descriptor"]
            self.unresolved("goal.descriptor", names[0], False)
        loc = self.zone_loc()
        if loc:
            goal["loc"] = loc
        return goal

    def place_zone(self, place):
        """The zone path of a place: the zone its category's givers stand in, else the world's zone named for it
        when that zone has a ZoneTransfer file."""
        if place in self.zone_paths:
            return self.zone_paths[place]
        zone = self.data.zone_by_place(place)
        if zone and zone not in self.known_zones:
            self.unresolved("goal.zone (no ZoneTransfer)", f"{place}: {zone}", False)
            return None
        return zone

    def waypoint_goal(self, places, text, quiet=False):
        """A waypoint to the first place that has a zone: the linked places, else the line's target; a line naming
        one of the world's NPCs instead is a persona goal. None, listed unless quiet, when nothing resolves."""
        readings = places or place_readings(target_text(text))
        for place in readings:
            zone = self.place_zone(place)
            if zone:
                goal = {"type": "waypoint", "zone": zone}
                loc = self.data.location(place)
                if loc:
                    goal["loc"] = loc
                return goal
        name = target_text(text)
        if not places and name and self.data.has_persona(name):
            return self.persona_goal(name)
        if not quiet:
            self.unresolved("goal.zone (waypoint left out)", ", ".join(places) or text, False)
        return None

    def fallback_prep(self, giver):
        """The line that offers the quest when no line reads as an offer: the first naming the giver, else the first."""
        keys = sorted(self.lines)
        last = norm(giver.split()[-1]) if giver else ""
        named = [key for key in keys if last and last in norm(self.lines[key])]
        key = (named or keys)[0]
        self.unresolved("dialogs.prep", f"no offer line; {key} is the first line "
                        + ("naming the giver" if named else "of the file"), False)
        return key

    def descriptor(self, item):
        """The key of a line of the quest's own lang file that names the item, else ''."""
        forms = set(singular_forms(re.sub(r"^\d+\s+", "", item)))
        for key, text in self.lines.items():
            if forms & set(singular_forms(text)):
                return f"WizQst{self.lang}_{key}"
        return ""

    def goals(self):
        built = []
        for line, subs, times in repeated(grouped_goals(self.fields["goals"])):
            goals = [goal for goal in self.goals_of(line, subs, times) if goal is not None]
            if goals and goals[0]["type"] in UNCOUNTED_GOALS:
                goals += [dict(goal) for goal in goals * (times - 1)]
            built += goals
        return built

    def goals_of(self, line, subs, times=1):
        """The goals of a goal line; a line repeated on consecutive lines (`times`) counts that often."""
        text = plain(line)
        count = re.search(r"\b(\d+)\b", text)
        number = int(count.group(1)) if count else 1
        verb = verb_of(text)
        if subs:
            return self.header_goals(line, text, verb, subs, number)
        npcs, creatures, places = links(line, "NPC"), links(line, "Creature"), links(line, "Location")
        kind = goal_kind(verb, text, npcs, creatures)
        if kind == "persona":
            name = npcs[0] if npcs else target_text(re.sub(r"\s+(in|at)\s+.*$", "", text))
            if verb not in TALK_VERBS and not self.data.has_persona(name) and self.data.object_entries(name):
                return [self.usage_goal([name], number * times)]
            return [self.persona_goal(name)]
        if kind == "bounty":
            creatures = creatures or [re.sub(r"\s+and\s+.*$|\s+in\s+.*$", "", target_text(text))]
            collect = re.search(r"\bcollect\s+(?:(\d+)\s+)?(.+)$", text, re.I)
            place = (places or [None])[0]
            zone = next((zone for zone in map(self.place_zone, places) if zone), None)
            if collect:
                return [self.bounty_goal(creatures, int(collect.group(1) or 1), collect.group(2), place, zone=zone)]
            return [self.bounty_goal(creatures, number * times, None, place, zone=zone)]
        if kind == "waypoint":
            return [self.waypoint_goal(places, text)]
        name = target_text(re.sub(r"\s+(in|at|into|to)\s+.*$", "", text))
        if verb in PERSON_VERBS and self.data.has_persona(name):
            return [self.persona_goal(name)]
        item = target_text(text)
        if verb in FIND_VERBS and not self.data.object_entries(item):
            found = self.waypoint_goal(places, text, quiet=not places)
            if found or places:
                return [found]
        if verb in COLLECT_VERBS or self.data.usage_entries(item, self.zone):
            return [self.usage_goal([item], number * times)]
        return [self.goal_elsewhere(verb, text, places)]

    def goal_elsewhere(self, verb, text, places):
        """A line no item reads: a waypoint to where it sends the player or to the place it names whole, else a talk
        with the NPC it ends at; blocked under the field its verb asks for when none resolves."""
        ends = destinations(verb, text)
        whole = target_text(text)
        for place in ends + ([whole] if verb not in ITEM_VERBS or whole in places else []):
            goal = self.waypoint_goal([place], text, quiet=True)
            if goal:
                return goal
            if self.data.has_persona(place):
                return self.persona_goal(place)
        self.unresolved("goal.waypoint" if ends else unread_field(verb, text), text, True)
        return None

    def header_goals(self, line, text, verb, subs, number):
        if verb == "talk" or all(links(sub, "NPC") and not links(sub, "Creature") for sub in subs):
            return [self.persona_goal(links(sub, "NPC")[0] if links(sub, "NPC") else plain(sub), i > 0)
                    for i, sub in enumerate(subs)]
        if verb == "defeat" and re.search(r"collect\s+(\d+\s+)?(.+?)\s+from", text, re.I):
            item = re.search(r"collect\s+(?:(\d+)\s+)?(.+?)\s+from", text, re.I)
            creatures = [c for sub in subs for c in (links(sub, "Creature") or [plain(sub)])]
            return [self.bounty_goal(creatures, int(item.group(1) or 1), item.group(2), None)]
        if verb == "defeat":
            goals = []
            for i, sub in enumerate(subs):
                creatures = links(sub, "Creature") or [plain(sub)]
                collect = re.search(r"for\s+(\d+)\s+(.+)$", plain(sub))
                place = (links(sub, "Location") or [None])[0]
                goals.append(self.bounty_goal(creatures, int(collect.group(1)) if collect else 1,
                                              collect.group(2) if collect else None, place, i > 0))
            return goals
        if all(is_goal_line(plain(sub)) or plain(sub) in links(sub, "Location") for sub in subs):
            goals = []
            for i, sub in enumerate(subs):
                places = links(sub, "Location")
                found = [self.waypoint_goal(places, sub)] if plain(sub) in places else self.goals_of(sub, [])
                built = [goal for goal in found if goal is not None]
                if i > 0 and built:
                    built[0]["with_previous"] = True
                goals += built
            return goals
        if verb in MOVE_VERBS and not any(self.data.usage_entries(plain(sub), self.zone) for sub in subs):
            return [self.waypoint_of_list(sub, i > 0) for i, sub in enumerate(subs)]
        return [self.usage_goal([plain(sub) for sub in subs], len(subs))]

    def waypoint_of_list(self, sub, with_previous):
        goal = self.waypoint_goal(links(sub, "Location") or [plain(sub)], plain(sub), quiet=True)
        if goal is None:
            self.unresolved("goal.waypoint", plain(sub), True)
        elif with_previous:
            goal["with_previous"] = True
        return goal

    def build(self, lang, quest_id):
        self.lang = lang
        self.lines = self.data.quest_lines(lang) if lang else {}
        fields = self.fields
        spec = {"id": quest_id}
        if lang:
            spec["lang"] = lang
            title_keys = [k for k in self.data.title_keys(self.entry["name"]) if k != lang]
            if (self.data.internal_name(lang) or lang not in self.data.titles) and title_keys:
                spec["title"] = f"QuestTitle_{title_keys[0]}"
            elif lang not in self.data.titles:
                self.unresolved("title", self.entry["name"], True)
        else:
            self.unresolved("lang", self.entry["name"], True)
        giver = None
        giver_name = fields["giver"]
        if not giver_name and fields["auto_start"]:
            spec["auto_start"] = True
            if self.predecessor_hand_in and self.data.persona(strip_notes(self.predecessor_hand_in), self.zone):
                giver_name = self.predecessor_hand_in
            else:
                self.unresolved("giver (auto-start, no predecessor hand-in)", self.predecessor_hand_in or "none", True)
        if giver_name:
            giver, giver_zone = self.persona_ref(giver_name, "giver")
            if giver:
                spec["giver"] = {"persona": giver, "zone": giver_zone or self.zone}
                if not self.zone and self.entry["fetched_from"] == "repository":
                    self.zone = giver_zone
                giver_world = spec["giver"]["zone"].split("/")[0]
                if giver_world != self.data.world and giver_world in {w.name for w in WORLDS}:
                    self.unresolved("giver (other world)", f"{giver_name} is placed in {spec['giver']['zone']}", True)
        elif not fields["auto_start"]:
            self.unresolved("giver", "none", True)
        requires = []
        for title in fields["prequests"]:
            found = self.quest_ids.get(title_norm(title))
            if found:
                requires.append(found)
            else:
                self.unresolved("requires", title, False)
        spec["requires"] = requires
        if not requires:
            spec["min_level"] = self.data.level
        spec["mainline"] = fields["mainline"]
        spec["level"] = self.data.level
        if {"xp", "gold"} <= set(fields["reward"]):
            spec["reward"] = {"xp": fields["reward"]["xp"], "gold": fields["reward"]["gold"]}
        else:
            self.unresolved("reward", fields["reward"], False)
        goals = self.goals()
        hand_in_row = self.data.persona(fields["hand_in"], self.zone) if fields["hand_in"] else None
        ends_at_hand_in = bool(goals) and hand_in_row is not None and goals[-1].get("persona") == hand_in_row["persona"]
        if fields["hand_in"] and not ends_at_hand_in:
            hand_in = self.persona_goal(fields["hand_in"])
            if hand_in:
                goals.append(hand_in)
        if not goals:
            self.unresolved("goals", fields["goals"], True)
        prep, underway, completion = heuristic_dialogs(self.lines, self.data.internal_name(lang) if lang else None)
        if self.lines and not prep:
            prep = [self.fallback_prep(fields["giver"])]
        spec["dialogs"] = {"prep": [{"speaker": "giver", "line": k} for k in prep],
                           "underway": [{"speaker": "giver", "line": k} for k in underway]}
        if goals and goals[-1]["type"] == "persona" and completion:
            goals[-1]["completion"] = [{"speaker": goals[-1]["persona"], "line": k} for k in completion]
        if lang:
            self.unresolved("dialogs", "speaker and role guessed from the line text", False)
        for goal in goals:
            if goal["type"] == "persona" and giver and goal["persona"] == giver:
                goal["persona"] = "giver"
                for line in goal.get("completion", []):
                    line["speaker"] = "giver"
        spec["goals"] = goals
        zones = {goal.get("zone") for goal in goals} | {spec.get("giver", {}).get("zone")}
        for zone in sorted(zone for zone in zones if zone and zone not in self.known_zones):
            self.unresolved("zone (no ZoneTransfer)", zone, True)
        spec["personas"] = dict(sorted(self.personas.items()))
        spec["source"] = self.entry.get("source") or {"page": WIKI + self.entry["page"],
                                                      "from": self.entry["fetched_from"],
                                                      "timestamp": self.entry["fetched"]}
        spec["needs_review"] = self.review
        return spec


def placeholder_scores(data, fields, candidates):
    """(weight of the words a lang key shares with the page's goals, key), best first; rare words weigh more."""
    texts = {key: set(re.findall(r"[a-z]{4,}", " ".join(data.quest_lines(key).values()).lower()))
             for key in candidates}
    page_text = " ".join(plain(line) for line in fields["goals"]) + f" {fields['giver'] or ''} {fields['hand_in'] or ''}"
    words = set(re.findall(r"[a-z]{4,}", page_text.lower()))
    weight = {word: math.log(len(texts) / (1 + sum(word in text for text in texts.values()))) for word in words}
    return sorted((round(sum(max(weight[w], 0) for w in words & text), 2), key) for key, text in texts.items())[::-1]


def match_placeholders(data, pages, unmatched, candidates):
    """page -> lang key, one to one: a page's best key must clearly beat its second, and the best match goes first."""
    scores = {page: placeholder_scores(data, pages[page], candidates) for page in unmatched}
    matched, taken = {}, set()
    while True:
        best = None
        for page, ranked in scores.items():
            if page in matched or not ranked or ranked[0][1] in taken or ranked[0][0] < MIN_SHARED_WEIGHT:
                continue
            runner_up = ranked[1][0] if len(ranked) > 1 else 0
            if ranked[0][0] >= CLEAR_MARGIN * runner_up and (best is None or ranked[0][0] > best[0]):
                best = (ranked[0][0], page, ranked[0][1])
        if best is None:
            return matched
        matched[best[1]] = best[2]
        taken.add(best[2])


def quest_names(fields):
    """The NPCs, creatures and items a quest page names: what its WizQst lines should mention too."""
    names = [fields["giver"], fields["hand_in"]]
    for line in fields["goals"]:
        names += [strip_notes(name) for name in links(line, "NPC") + links(line, "Creature")]
        names += re.findall(r"\b(?:for|collect|find|gather)\s+(?:\d+\s+)?([A-Z][\w'-]*(?:\s+(?:of\s+)?[A-Z][\w'-]*)*)",
                            plain(line))
    return [name for name in dict.fromkeys(names) if name]


def named_in(data, fields, lang):
    """The page's names that the lines of WizQst<lang> mention: the full name, or an NPC's last name."""
    text = norm(" ".join(data.quest_lines(lang).values()))
    people = {fields["giver"], fields["hand_in"]} | {n for line in fields["goals"] for n in links(line, "NPC")}
    found = []
    for name in quest_names(fields):
        forms = singular_forms(name)
        last = norm(name.split()[-1])
        if any(form and form in text for form in forms) or (name in people and len(last) >= 4 and last in text):
            found.append(name)
    return found


def chain_anchor(page, pages, by_title, langs, link):
    """Walk the page's single prequest (or leads-to) link to the first quest with a lang: (lang, pages passed)."""
    passed, current, seen = [], page, {page}
    while True:
        steps = [by_title[title_norm(t)] for t in pages[current][link] if title_norm(t) in by_title]
        steps = [step for step in steps if step not in seen]
        if len(steps) != 1:
            return None, passed
        current = steps[0]
        seen.add(current)
        if langs.get(current):
            return langs[current], passed
        if current not in pages:
            return None, passed
        passed.append(current)


def match_by_chain(data, pages, by_title, langs, free):
    """page -> (lang, evidence) for unmatched pages that sit in a chain between two quests with langs, when the free
    lang keys between those two are exactly as many as the unmatched pages between them and each key's lines name
    something its page names."""
    matched = {}
    for page in pages:
        if langs.get(page) or page in matched:
            continue
        before, back = chain_anchor(page, pages, by_title, langs, "prequests")
        after, forward = chain_anchor(page, pages, by_title, langs, "leads_to")
        if not before or not after or int(before, 16) >= int(after, 16):
            continue
        run = back[::-1] + [page] + forward
        between = sorted((key for key in free if int(before, 16) < int(key, 16) < int(after, 16)),
                         key=lambda key: int(key, 16))
        if len(between) != len(run):
            continue
        for member, key in zip(run, between):
            names = named_in(data, pages[member], key)
            if names:
                matched[member] = (key, f"WizQst{key} by chain order between WizQst{before} and WizQst{after}; "
                                        f"its lines name {', '.join(names)}")
    return matched


def match_by_window(data, pages, by_title, langs, free):
    """page -> (lang, evidence) for unmatched pages where exactly one free lang key within CHAIN_WINDOW of a chain
    neighbour's key names something the page names, and no other page claims that key the same way."""
    found = {}
    for page in pages:
        if langs.get(page):
            continue
        before, _ = chain_anchor(page, pages, by_title, langs, "prequests")
        after, _ = chain_anchor(page, pages, by_title, langs, "leads_to")
        near = {key for key in free
                if (before and 0 < int(key, 16) - int(before, 16) <= CHAIN_WINDOW)
                or (after and 0 < int(after, 16) - int(key, 16) <= CHAIN_WINDOW)}
        named = {key: names for key in sorted(near) if (names := named_in(data, pages[page], key))}
        if len(named) == 1:
            key, names = next(iter(named.items()))
            anchors = " and ".join(f"WizQst{k}" for k in (before, after) if k)
            found[page] = (key, f"WizQst{key}, the only free key within {CHAIN_WINDOW} of its chain neighbour "
                                f"{anchors} whose lines name the page's names: {', '.join(names)}")
    keys = [key for key, _ in found.values()]
    return {page: hit for page, hit in found.items() if keys.count(hit[0]) == 1}


PROPER_NOUN = re.compile(r"\b[A-Z][A-Za-z-]{2,}")
MIN_PROPER_NOUNS = 2
COMMON_NOUN_SHARE = 0.1


def proper_nouns(text):
    return {word.lower(): word for word in PROPER_NOUN.findall(text)}


def common_nouns(data, keys):
    """The capitalised words of more than COMMON_NOUN_SHARE of the world's quest files: the world's own name and
    sentence openers, which tell no quest apart."""
    counts = {}
    for key in keys:
        for word in proper_nouns(" ".join(data.quest_lines(key).values())):
            counts[word] = counts.get(word, 0) + 1
    return {word for word, count in counts.items() if count > COMMON_NOUN_SHARE * len(keys)}


def match_by_proper_nouns(data, pages, zone_names, langs, free, common):
    """page -> (lang, evidence) for unmatched pages whose best free lang key, within CHAIN_WINDOW of a key of a quest
    of the same zone (a zone's quests hold a run of keys), shares at least MIN_PROPER_NOUNS of the page's proper nouns
    and more than any other; a key two pages want goes to the higher score, to neither on a tie."""
    nouns = {key: set(proper_nouns(" ".join(data.quest_lines(key).values()))) - common for key in free}
    best = {}
    for page, fields in pages.items():
        if langs.get(page):
            continue
        text = " ".join(plain(line).split(" ", 1)[-1] for line in fields["goals"])
        wanted = {lower: word for lower, word in proper_nouns(
            " ".join([text] + [fields[k] or "" for k in ("giver", "hand_in", "giver_location")])).items()
            if lower not in common}
        zone_keys = [int(lang, 16) for other, lang in langs.items()
                     if lang and zone_names.get(other) == zone_names.get(page)]
        ranked = sorted(((len(wanted.keys() & nouns[key]), key) for key in free
                         if any(abs(int(key, 16) - known) <= CHAIN_WINDOW for known in zone_keys)), reverse=True)
        if not ranked or ranked[0][0] < MIN_PROPER_NOUNS or (len(ranked) > 1 and ranked[1][0] == ranked[0][0]):
            continue
        score, key = ranked[0]
        shared = ", ".join(sorted(wanted[word] for word in wanted.keys() & nouns[key]))
        runner_up = f"; next best WizQst{ranked[1][1]} with {ranked[1][0]}" if len(ranked) > 1 else ""
        best[page] = (score, key, f"WizQst{key} by the proper nouns its lines share with the page ({shared}), within "
                                  f"{CHAIN_WINDOW} of a key of the zone's quests{runner_up}")
    found = {}
    for page, (score, key, evidence) in best.items():
        rivals = [other for other, hit in best.items() if other != page and hit[1] == key and hit[0] >= score]
        if not rivals:
            found[page] = (key, evidence)
    return found


def is_blocked_spec(spec):
    return any(item["blocking"] for item in spec["needs_review"])


def rewire_requires(ready, pages, by_title, ids, generated, level):
    """Point each ready spec's prerequisites that will not be generated at their nearest generated ancestors on the
    wiki's Prequest chain, so the chain stays playable; with none left the spec gets the world's min_level."""
    def ancestors(title, seen):
        key = title_norm(title)
        if ids.get(key) in generated:
            return [ids[key]]
        if key in seen or by_title.get(key) not in pages:
            return []
        seen.add(key)
        return [found for earlier in pages[by_title[key]]["prequests"] for found in ancestors(earlier, seen)]

    for fields, spec in ready:
        requires = []
        for title in fields["prequests"]:
            found = ancestors(title, set())
            if ids.get(title_norm(title)) not in generated:
                spec["needs_review"].append({"field": "requires (not generated)",
                                             "value": f"{title} replaced by {', '.join(found) or 'min_level'}",
                                             "blocking": False})
            requires += found
        spec["requires"] = list(dict.fromkeys(requires))
        spec.pop("min_level", None)
        if not spec["requires"]:
            spec["min_level"] = level


def hand_authored(world_dir):
    """lang key -> spec of the specs in the world's folder that did not come from this tool."""
    found = {}
    for path in glob.glob(os.path.join(world_dir, "*.json")):
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
        if "source" not in spec:
            found[spec["lang"]] = spec
    return found


def repository_quests(cache, world):
    """title_norm of the name -> quest entry of The Repository's index for the world, and the licence of its text;
    nothing without an index."""
    path = os.path.join(cache, "repository", f"index-repository-{world.lower()}.json")
    if not os.path.exists(path):
        return {}, {}
    with open(path, encoding="utf-8") as f:
        index = json.load(f)
    return ({title_norm(quest["name"]): quest for quest in index["quests"]},
            {"licence": index["licence"], "licence_url": index["licence_url"]})


def tracked_quests(cache, world):
    """title_norm of the name -> spiraltracker's quest entry for the world; empty without its list."""
    path = os.path.join(cache, "tracker", f"tracker-{world.lower()}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {title_norm(quest.get("wikiName") or quest["name"]): quest for quest in json.load(f)["quests"]}


def repository_fields(data, quest, tracked):
    """A Repository quest as the fields of a quest page: the giver is its first character when a zone places that
    persona, the hand-in the NPC of a last talk goal, the reward and zone name spiraltracker's."""
    first = data.persona(strip_notes(quest["characters"][0]), "") if quest["characters"] else None
    last = quest["goals"][-1] if quest["goals"] else ""
    tracked = tracked or {}
    return {
        "prequests": quest["prev"],
        "giver": quest["characters"][0] if first and first["zones"] else None,
        "auto_start": False,
        "giver_location": tracked["area"].split(" / ")[0] if tracked.get("area") else None,
        "mainline": "storyline" in (quest["type"] or ""),
        "instance": "instance" in (quest["type"] or ""),
        "goals": ["@" + line for line in quest["goals"]],
        "hand_in": target_text(re.sub(r"\s+(in|at)\s+.*$", "", last)) if verb_of(last) in TALK_VERBS else None,
        "reward": {key: tracked[key] for key in ("xp", "gold") if tracked.get(key) is not None},
        "leads_to": quest["next"],
    }


def repository_entry(entry, quest, licence):
    """An index entry whose spec comes from its Repository page: the page and the licence are the spec's source."""
    return {**entry, "fetched": None, "fetched_from": "repository",
            "source": {"page": quest["wiki_page"], "from": "repository", **licence}}


def dialogue_hits(data, key, quest):
    """How many of a Repository page's dialogue lines the quest's lang file holds, read loosely."""
    lines = [norm(text) for text in data.quest_lines(key).values()]
    return sum(1 for line in quest["dialogue"]
               if difflib.get_close_matches(norm(line["text"]), lines, n=1, cutoff=DIALOGUE_CUTOFF))


def preferred_lang(data, title_key, quest):
    """The Repository's lang key, the game's own id, over the one the title reads, when its WizQst file exists and
    holds no fewer of the page's dialogue lines: some pages give a neighbouring quest's id."""
    key = quest and quest["lang_hex"]
    if not key or key == title_key or not data.has_quest_lang(key):
        return title_key
    if title_key and dialogue_hits(data, title_key, quest) > dialogue_hits(data, key, quest):
        return title_key
    return key


def claimed_twice(data, langs, quests, from_repository):
    """The pages that lose a lang key another page also holds, when one of them took it from The Repository: all but
    the one whose Repository dialogue the key's file holds best, a title match winning a tie."""
    holders = {}
    for page, key in langs.items():
        if key:
            holders.setdefault(key, []).append(page)
    losers = []
    for key, pages in holders.items():
        if len(pages) > 1 and from_repository.keys() & set(pages):
            best = max(pages, key=lambda page: (dialogue_hits(data, key, quests[page]) if quests[page] else 0,
                                                page not in from_repository))
            losers += [page for page in pages if page != best]
    return losers


def predecessor_hand_in(pages, by_title, fields):
    """Who gives a quest that starts automatically: the hand-in NPC of the first prerequisite page that names one,
    else the giver of the first prerequisite page that names one."""
    found = [pages[by_title[title_norm(title)]] for title in fields["prequests"]
             if by_title.get(title_norm(title)) in pages]
    return next((page[role] for role in ("hand_in", "giver") for page in found if page[role]), None)


def repository_matches(repository, index):
    """page -> The Repository's quest for each index entry: by its title, read whole or without the wiki's notes, else
    the one Repository title no entry reads that is spelled closely (`All's Well that Cleanses Wells`)."""
    keys = {entry["page"]: next((key for key in (title_norm(entry["name"]), title_norm(strip_notes(entry["name"])))
                                 if key in repository), None) for entry in index}
    free = [key for key in repository if key not in set(keys.values())]
    for entry in index:
        if keys[entry["page"]] is None:
            close = difflib.get_close_matches(title_norm(entry["name"]), free, n=2, cutoff=TITLE_CUTOFF)
            keys[entry["page"]] = close[0] if len(close) == 1 else None
    return {page: repository.get(key) for page, key in keys.items()}


def zone_name_of(entry, fields):
    """The quest's zone: its zone category, else the giver's location (some zone categories are not archived)."""
    return (entry["zones"] or [fields["giver_location"]])[0]


def zone_paths_by_vote(data, pages, index):
    """Category zone name -> the zone path where most of its quest givers stand."""
    votes = {}
    for entry in index:
        fields = pages.get(entry["page"])
        if not fields or not fields["giver"] or not zone_name_of(entry, fields):
            continue
        rows = data.personas.get(norm(fields["giver"]), [])
        if len(rows) == 1:
            for zone in rows[0]["zones"]:
                if "/Interiors/" not in zone:
                    tally = votes.setdefault(zone_name_of(entry, fields), {})
                    tally[zone] = tally.get(zone, 0) + 1
    return {name: max(tally, key=tally.get) for name, tally in votes.items()}


def parse_world(cache, registered):
    world = registered.name
    data = ClientData(registered)
    index = load_index(cache, world)
    pages = {}
    for entry in index:
        hit = cached(cache, entry["page"])
        if hit:
            entry["fetched"], entry["fetched_from"] = hit.stamp, hit.source
            with open(hit.path, encoding="utf-8") as f:
                pages[entry["page"]] = read_page(f.read())
    zone_paths = zone_paths_by_vote(data, pages, index)
    repository, licence = repository_quests(cache, world)
    tracked = tracked_quests(cache, world)
    quests = repository_matches(repository, index)
    from_repository = {page: quest for page, quest in quests.items() if quest and page not in pages}
    for entry in index:
        if entry["page"] in from_repository:
            pages[entry["page"]] = repository_fields(data, from_repository[entry["page"]],
                                                     tracked.get(title_norm(entry["name"])))
    world_dir = os.path.join(QUEST_SPECS_DIR, world.lower())
    blocked_dir = os.path.join(world_dir, "blocked")
    reference_dir = os.path.join(cache, f"reference-{world.lower()}")
    os.makedirs(blocked_dir, exist_ok=True)
    os.makedirs(reference_dir, exist_ok=True)
    authored = hand_authored(world_dir)
    for path in glob.glob(os.path.join(world_dir, "*.json")) + glob.glob(os.path.join(blocked_dir, "*.json")):
        with open(path, encoding="utf-8") as f:
            if "source" in json.load(f):
                os.remove(path)
    placeholders = data.placeholder_langs()
    langs, ids, evidence = {}, {}, {}
    for entry in index:
        title_key = data.title_lang(entry["name"])
        key = preferred_lang(data, title_key, quests[entry["page"]])
        langs[entry["page"]] = key
        if key != title_key:
            evidence[entry["page"]] = f"WizQst{key} is The Repository's id; the title reads {title_key or 'no key'}"
    for page in claimed_twice(data, langs, quests, evidence):
        langs[page] = None
        evidence.pop(page, None)
    by_title = {title_norm(entry["name"]): entry["page"] for entry in index}
    for page in from_repository:
        pages[page]["giver"] = pages[page]["giver"] or predecessor_hand_in(pages, by_title, pages[page])

    def chain_pass(rules):
        while True:
            claimed = set(langs.values()) | set(authored)
            free = [k for k in placeholders if k not in claimed]
            found = next((hits for rule in rules if (hits := rule(data, pages, by_title, langs, free))), None)
            if not found:
                return
            for page, (key, note) in found.items():
                langs[page], evidence[page] = key, note

    chain_pass([match_by_chain])
    unmatched = [page for page, lang in langs.items() if lang is None and page in pages]
    claimed = set(langs.values())
    for page, key in match_placeholders(data, pages, unmatched, [k for k in placeholders if k not in claimed]).items():
        langs[page] = key
        names = named_in(data, pages[page], key)
        evidence[page] = (f"WizQst{key} matched by the words it shares with the goals; its lines name "
                          + (", ".join(names) if names else "none of the page's names"))
    zone_names = {entry["page"]: zone_name_of(entry, pages[entry["page"]]) for entry in index if entry["page"] in pages}
    common = common_nouns(data, placeholders)

    def match_in_zone(data, pages, _by_title, langs, free):
        return match_by_proper_nouns(data, pages, zone_names, langs, free, common)

    chain_pass([match_by_chain, match_by_window, match_in_zone])
    for entry in index:
        lang = langs[entry["page"]]
        if lang in authored:
            ids[title_norm(entry["name"])] = authored[lang]["id"]
        elif lang:
            ids[title_norm(entry["name"])] = data.internal_name(lang) or f"{data.folder}-Q-{lang}"
    for title_key, name in data.pack_quests.items():
        if title_key in data.titles:
            ids.setdefault(title_norm(data.titles[title_key]), name)
    known_zones = set(zone_transfer_files())
    unresolved, written, blocked, compared = {}, 0, [], []
    built = []
    for entry in index:
        if entry["page"] not in pages:
            continue
        lang = langs[entry["page"]]
        quest_id = ids.get(title_norm(entry["name"])) or f"{data.folder}-Q-{norm(entry['name'])}"
        source = repository_entry(entry, from_repository[entry["page"]], licence) if entry["page"] in from_repository \
            else entry
        builder = SpecBuilder(data, source, pages[entry["page"]], zone_paths, ids, known_zones,
                              predecessor_hand_in(pages, by_title, pages[entry["page"]]))
        if entry["page"] in evidence:
            builder.unresolved("lang", evidence[entry["page"]], False)
        built.append((entry, lang, builder.build(lang, quest_id)))
    blocked_ids = {spec["id"] for _, _, spec in built if is_blocked_spec(spec)}
    generated = ({spec["id"] for _, _, spec in built} | {spec["id"] for spec in authored.values()}
                 | set(data.pack_quests.values())) - blocked_ids
    rewire_requires([(pages[entry["page"]], spec) for entry, _, spec in built if spec["id"] not in blocked_ids],
                    pages, by_title, ids, generated, registered.level)
    for _, lang, spec in built:
        quest_id = spec["id"]
        for item in spec["needs_review"]:
            counts = unresolved.setdefault(item["field"], [0, 0])
            counts[0 if item["blocking"] else 1] += 1
        is_blocked = quest_id in blocked_ids
        if lang in authored:
            target = os.path.join(reference_dir, f"{quest_id}.json")
            compared.append((authored[lang], spec))
        else:
            target = os.path.join(blocked_dir if is_blocked else world_dir, f"{quest_id}.json")
        with open(target, "w", encoding="utf-8") as f:
            f.write(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
        if is_blocked:
            blocked.append(quest_id)
        elif lang not in authored:
            written += 1
    print(f"{world}: {len(pages)} pages parsed ({len(from_repository)} from The Repository), {written} specs ready, "
          f"{len(blocked)} blocked, "
          f"{len(compared)} compared with hand-authored specs; zones: "
          + ", ".join(f"{name} = {path}" for name, path in sorted(zone_paths.items())))
    print(f"{'field':<20} {'blocking':>8} {'review':>8}")
    for field, (hard, soft) in sorted(unresolved.items()):
        print(f"{field:<20} {hard:>8} {soft:>8}")
    for reference, spec in compared:
        differences = list(diff({k: v for k, v in spec.items() if k not in ("source", "needs_review")},
                                         reference))
        print(f"== {reference['id']} vs archive: {len(differences)} differences")
        for line in differences:
            print("  " + line)


def add_arguments(parser):
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--enumerate", metavar="WORLD", help="list the world's quests from the wiki's categories")
    mode.add_argument("--fetch", metavar="WORLD", help="download the listed quest pages into the cache")
    mode.add_argument("--parse", metavar="WORLD", help="write a questgen spec per cached quest page")
    add_cache_argument(parser)


def add_cache_argument(parser):
    parser.add_argument("--cache", default=DEFAULT_CACHE, help="the directory of fetched pages and the index")


def run(args):
    registered = world(args.enumerate or args.fetch or args.parse)
    os.makedirs(args.cache, exist_ok=True)
    archive, live = Archive(), LiveWiki()
    try:
        if args.enumerate:
            enumerate_world(live, archive, args.cache, registered)
        elif args.fetch:
            fetch_world(live, archive, args.cache, registered.name)
        else:
            parse_world(args.cache, registered)
    except ArchiveUnavailable as e:
        sys.exit(f"archive unavailable: {e}")


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    add_arguments(parser)
    run(parser.parse_args())
