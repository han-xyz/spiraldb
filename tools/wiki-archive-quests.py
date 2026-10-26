#!/usr/bin/env python3
"""Build questgen specs for a world from the Internet Archive's copies of the Wizard101 Central wiki.

See tools/README.md for the modes, the cache and what a spec needs after parsing.
"""
import argparse
import glob
import gzip
import html
import importlib.util
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PACK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CACHE = os.path.join(PACK, ".scratch", "friends-server", "task-A1", "cache")
WIKI = "https://wiki.wizard101central.com/wiki/"
ARCHIVE = "https://web.archive.org/web/"
CDX = ("https://web.archive.org/cdx/search/cdx?url=wiki.wizard101central.com/wiki/Quest:*"
       "&fl=original,timestamp,statuscode&filter=statuscode:200&collapse=urlkey")
# A partial timestamp redirects to the capture nearest to it, so this year asks for the newest capture.
NEWEST = "2026"
CATEGORY_YEARS = (NEWEST, "2024", "2023")
USER_AGENT = "spiraldb-wiki-archive-quests/1.0 (read-only; one request per second)"
REQUEST_INTERVAL = 1.0
RETRY_STATUSES = {429, 500, 502, 503, 504}
BACKOFF_START, BACKOFF_CAP, BACKOFF_TOTAL = 2.0, 60.0, 300.0
QUEST_TYPES = ("storyline", "side", "instance")
MIN_SHARED_WEIGHT, CLEAR_MARGIN = 4.0, 1.5
WORLDS = {"Celestia": {"folder": "CL", "lang_range": (0x371A8, 0x3780E), "level": 48}}


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


def page_key(title):
    """A wiki page title as the archive's URL path writes it: underscores, no percent escapes."""
    return urllib.parse.unquote(title).replace(" ", "_")


def file_name(key):
    return re.sub(r"[^A-Za-z0-9_.()'-]", "_", key)


def cached(cache, key):
    """The newest cached capture of a page as (timestamp, path), or None."""
    paths = sorted(glob.glob(os.path.join(cache, f"[0-9]*_{glob.escape(file_name(key))}.html")))
    return (os.path.basename(paths[-1])[:14], paths[-1]) if paths else None


def fetch_page(archive, cache, key, raw=True, at=NEWEST):
    """A wiki page's newest capture, from the cache or the archive; cached as <timestamp>_<page>.html."""
    hit = cached(cache, key)
    if hit:
        with open(hit[1], encoding="utf-8") as f:
            return hit[0], f.read()
    url, data = archive.get(f"{ARCHIVE}{at}{'id_' if raw else ''}/{WIKI}{urllib.parse.quote(key, safe=':_()/,!')}")
    stamp = re.search(r"/web/(\d{14})", url).group(1)
    text = data.decode("utf-8", errors="replace")
    with open(os.path.join(cache, f"{stamp}_{file_name(key)}.html"), "w", encoding="utf-8") as f:
        f.write(text)
    return stamp, text


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


def fetch_category(archive, cache, category):
    """A category page from the newest capture that answers, or None; newer captures can be error pages."""
    for year in CATEGORY_YEARS:
        try:
            return fetch_page(archive, cache, category, raw=False, at=year)[1]
        except urllib.error.HTTPError as e:
            if e.code not in (403, 404):
                raise
    return None


def walk_categories(archive, cache, world):
    """quest page key -> {"zones": set, "types": set}, from the world's category tree."""
    root = f"Category:{world}_Quests"
    quests = {}
    queue = [(root, None)]
    seen = set()
    while queue:
        category, zone = queue.pop(0)
        if category in seen:
            continue
        seen.add(category)
        page = fetch_category(archive, cache, category)
        if page is None:
            print(f"{category}: no capture found; its pages are listed only through other categories")
            continue
        subcategories, members = category_members(page)
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


def enumerate_world(archive, cache, world):
    quests = walk_categories(archive, cache, world)
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


def fetch_world(archive, cache, world):
    fetched = failed = 0
    for entry in load_index(cache, world):
        if entry.get("missing_snapshot") or cached(cache, entry["page"]):
            continue
        try:
            try:
                stamp, _ = fetch_page(archive, cache, entry["page"])
            except urllib.error.HTTPError as e:
                if e.code not in (403, 404):
                    raise
                # The newest capture can be an error page or refused; the CDX timestamp is a capture with status 200.
                stamp, _ = fetch_page(archive, cache, entry["page"], at=entry["timestamp"])
        except urllib.error.HTTPError as e:
            print(f"{entry['name']}: HTTP {e.code}")
            failed += 1
            continue
        fetched += 1
        print(f"{entry['name']}: {stamp}")
    print(f"{world}: {fetched} fetched, {failed} failed")


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
    }


def grouped_goals(goal_lines):
    """Goal lines as (line, sub-item lines): a line without '@' continues the one before, '@@' lines are sub-items."""
    groups = []
    for line in goal_lines:
        depth = len(line) - len(line.lstrip("@"))
        if depth >= 2 and groups:
            groups[-1][1].append(line.lstrip("@"))
        elif depth == 0 and groups:
            if not line.startswith("("):
                groups[-1][0] += " " + line
        else:
            groups.append([line.lstrip("@"), []])
    return groups


def norm(text):
    return re.sub(r"[^a-z0-9]", "", text.lower().replace("’", "'"))


def singular_forms(text):
    """Normalised spellings of a name as it may appear in the plural on the wiki."""
    base = norm(re.sub(r"^(the|a|an)\s+", "", text.strip(), flags=re.I))
    forms = [base]
    for suffix, replacement in (("ies", "y"), ("es", ""), ("s", "")):
        if base.endswith(suffix):
            forms.append(base[:-len(suffix)] + replacement)
    return forms


def load_module(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py")
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClientData:
    """The lookups a spec needs: titles, personas, mobs, objects, zone locations and the pack's quests."""

    def __init__(self, world):
        from client_data import (ADJECTIVE_LIST, DISPLAY_NAME, GAMEDATA_DIR, ROOTWAD_DIR, read_binary_xml,
                                 read_lang, string_field, string_list_field)
        self.world = world
        config = WORLDS[world]
        self.folder = config["folder"]
        self.read_lang = lambda name: read_lang(ROOTWAD_DIR, name)
        self.titles = self.read_lang("QuestTitle")
        self.lang_range = config["lang_range"]
        self.lang_dir = os.path.join(ROOTWAD_DIR, "Locale", "en-US")
        npc_module = load_module("npc-personas-from-wad")
        rows = list(npc_module.npcs(ROOTWAD_DIR, self.folder))
        placed = npc_module.zone_placements(GAMEDATA_DIR, world, [row["template"] for row in rows])
        self.personas = {}
        for row in rows:
            if row["name"]:
                row["zones"] = placed[row["template"]]
                row["persona"] = row["persona"][:-len("_Persona")].strip()
                self.personas.setdefault(norm(row["name"]), []).append(row)
        mob_names = self.read_lang("WizardMobs")
        mob_keys = {}
        for key, text in mob_names.items():
            mob_keys.setdefault(text, key)
        self.mobs = {}
        for name, template, _id, adjectives in load_module("mob-adjectives-from-wad").mobs(ROOTWAD_DIR, self.folder):
            own = f"{template}.AdjRef"
            self.mobs.setdefault(norm(name), []).append(
                {"adjective": own if own in adjectives else (adjectives or [None])[0],
                 "target": f"WizardMobs_{mob_keys[name]}" if name in mob_keys else ""})
        self.objects = {}
        langs = {}
        directory = os.path.join(ROOTWAD_DIR, "ObjectData", self.folder)
        for filename in sorted(os.listdir(directory)):
            if not filename.endswith(".xml"):
                continue
            data = read_binary_xml(os.path.join(directory, filename))
            adjectives = string_list_field(data, ADJECTIVE_LIST)
            template = filename[:-4]
            adjective = f"{template}.AdjRef" if f"{template}.AdjRef" in adjectives else (adjectives or [None])[0]
            if not adjective or norm(template) in self.mobs:
                continue
            key = string_field(data, DISPLAY_NAME) or ""
            lang_name, _, entry = key.rpartition("_")
            if lang_name and lang_name != "WizardMobs":
                if lang_name not in langs:
                    langs[lang_name] = self.read_lang(lang_name) if os.path.exists(
                        os.path.join(self.lang_dir, lang_name + ".lang")) else {}
                name = langs[lang_name].get(entry)
                if name:
                    self.objects.setdefault(norm(name), []).append({"adjective": adjective, "descriptor": key})
            stem = re.sub(r"0*(\d+)$", r"\1", norm(re.sub(rf"^{self.folder}[-_]", "", template, flags=re.I)))
            self.objects.setdefault(stem, []).append({"adjective": adjective, "descriptor": ""})
        self.zone_locations = {}
        # Of the keys that read the same, the unpadded one with the lowest number is the zone's own.
        for key, text in sorted(self.read_lang("ZoneLocName").items(),
                                key=lambda item: (item[0].startswith("0"), int(item[0]) if item[0].isdigit() else 0)):
            self.zone_locations.setdefault(norm(text), "ZoneLocName_" + key)
        self.pack_quests = {}
        for path in glob.glob(os.path.join(PACK, "QuestTemplates", "questtemplates_*.json")):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            title = re.search(r'"m_questTitle":\s*"QuestTitle_([^"]*)"', text)
            name = re.search(r'"m_questName":\s*"([^"]*)"', text)
            if title and name:
                self.pack_quests.setdefault(title.group(1), name.group(1))

    def in_range(self, key):
        return re.fullmatch(r"[0-9A-F]+", key) and self.lang_range[0] <= int(key, 16) <= self.lang_range[1]

    def has_quest_lang(self, key):
        return os.path.exists(os.path.join(self.lang_dir, f"WizQst{key}.lang"))

    def title_keys(self, title):
        wanted = norm(title)
        return [key for key, text in self.titles.items() if norm(text) == wanted]

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

    def persona(self, name, zone):
        """The persona row for an NPC name, preferring one placed in the zone; None when the world has none."""
        wanted = norm(name)
        rows = self.personas.get(wanted) or [row for key, rows in self.personas.items() if key.endswith(wanted)
                                             for row in rows]
        if not rows:
            return None
        return next((row for row in rows if zone in row["zones"]), next((r for r in rows if r["zones"]), rows[0]))

    def mob_entries(self, name):
        return next((self.mobs[form] for form in singular_forms(name) if form in self.mobs), [])

    def object_entries(self, name):
        name = re.sub(r"\s*\(.*?\)|\s+(in|at|on|with|for|from)\s+.*$|#", "", name)
        name = re.sub(r"^(pieces|piles|bottles|measures|bits|chunks) of\s+", "", name, flags=re.I)
        for form in singular_forms(name):
            if form in self.objects:
                return self.objects[form]
        for form in singular_forms(name):
            prefixed = [entry for key, entries in self.objects.items() if key.startswith(form) and len(form) >= 6
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

    def __init__(self, data, entry, fields, zone_paths, quest_ids, known_zones):
        self.data, self.entry, self.fields = data, entry, fields
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
        row = self.data.persona(name, self.zone)
        if row is None:
            self.unresolved(field, name, True)
            return None, ""
        self.personas[row["persona"]] = {"portrait": row["portrait"], "template_id": row["template_id"]}
        zone = self.zone if self.zone in row["zones"] else (row["zones"] or [""])[0]
        if not zone:
            self.unresolved(f"{field}.zone (placed in no zone)", name, True)
        return row["persona"], zone

    def persona_goal(self, name, with_previous=False):
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

    def bounty_goal(self, creatures, count, item, place, with_previous=False):
        mobs, target = [], ""
        for creature in creatures:
            entries = self.data.mob_entries(creature)
            if not entries:
                self.unresolved("goal.mobs", creature, True)
            mobs += [e["adjective"] for e in entries if e["adjective"]]
            target = target or next((e["target"] for e in entries if e["target"]), "")
        if not mobs:
            return None
        goal = {"type": "bountycollect" if item else "bounty", "mobs": list(dict.fromkeys(mobs)), "count": count,
                "target": target, "zone": self.zone}
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
            entries = self.data.object_entries(name)
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

    def waypoint_goal(self, place):
        zone = self.zone_paths.get(place)
        if not zone:
            self.unresolved("goal.zone (waypoint left out)", place, False)
            return None
        goal = {"type": "waypoint", "zone": zone}
        loc = self.data.location(place)
        if loc:
            goal["loc"] = loc
        return goal

    def descriptor(self, item):
        """The key of a line of the quest's own lang file that names the item, else ''."""
        forms = set(singular_forms(re.sub(r"^\d+\s+", "", item)))
        for key, text in self.lines.items():
            if forms & set(singular_forms(text)):
                return f"WizQst{self.lang}_{key}"
        return ""

    def goals(self):
        built = []
        for line, subs in grouped_goals(self.fields["goals"]):
            built += [goal for goal in self.goals_of(line, subs) if goal is not None]
        return built

    def goals_of(self, line, subs):
        text = plain(line)
        count = re.search(r"\b(\d+)\b", text)
        number = int(count.group(1)) if count else 1
        verb = text.split(" ", 1)[0].rstrip(":").lower()
        if subs:
            return self.header_goals(line, text, verb, subs, number)
        if verb == "talk":
            name = (links(line, "NPC") or [re.sub(r"^Talk to\s+|\s+in\s+.*$", "", text)])[0]
            return [self.persona_goal(name)]
        if verb == "defeat":
            creatures = links(line, "Creature") or [re.sub(r"^Defeat\s+(\d+\s+)?|\s+and\s+.*$|\s+in\s+.*$", "", text)]
            collect = re.search(r"\bcollect\s+(?:(\d+)\s+)?(.+)$", text, re.I)
            place = (links(line, "Location") or [None])[0]
            if collect:
                return [self.bounty_goal(creatures, int(collect.group(1) or 1), collect.group(2), place)]
            return [self.bounty_goal(creatures, number, None, place)]
        if verb == "go":
            places = links(line, "Location")
            if not places:
                self.unresolved("goal.zone (waypoint left out)", text, False)
                return []
            return [self.waypoint_goal(places[-1])]
        item = re.sub(rf"^\S+\s+(\d+\s+)?", "", text)
        return [self.usage_goal([item], number)]

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
        return [self.usage_goal([plain(sub) for sub in subs], len(subs))]

    def build(self, lang, quest_id):
        self.lang = lang
        self.lines = self.data.quest_lines(lang) if lang else {}
        fields = self.fields
        spec = {"id": quest_id}
        if lang:
            spec["lang"] = lang
            title_keys = [k for k in self.data.title_keys(self.entry["name"]) if k != lang]
            if self.data.internal_name(lang) and title_keys:
                spec["title"] = f"QuestTitle_{title_keys[0]}"
        else:
            self.unresolved("lang", self.entry["name"], True)
        giver = None
        if fields["giver"]:
            giver, giver_zone = self.persona_ref(fields["giver"], "giver")
            if giver:
                spec["giver"] = {"persona": giver, "zone": giver_zone or self.zone}
        else:
            self.unresolved("giver", "starts automatically" if fields["auto_start"] else "none", True)
        requires = []
        for title in fields["prequests"]:
            found = self.quest_ids.get(norm(title))
            if found:
                requires.append(found)
            else:
                self.unresolved("requires", title, False)
        spec["requires"] = requires
        if not requires:
            spec["min_level"] = WORLDS[self.data.world]["level"]
        spec["mainline"] = fields["mainline"]
        spec["level"] = WORLDS[self.data.world]["level"]
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
        spec["source"] = {"page": WIKI + self.entry["page"], "timestamp": self.entry["fetched"]}
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


def hand_authored(world_dir):
    """lang key -> spec of the specs in the world's folder that did not come from this tool."""
    found = {}
    for path in glob.glob(os.path.join(world_dir, "*.json")):
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
        if "source" not in spec:
            found[spec["lang"]] = spec
    return found


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


def parse_world(cache, world):
    import questgen
    data = ClientData(world)
    index = load_index(cache, world)
    pages = {}
    for entry in index:
        hit = cached(cache, entry["page"])
        if hit:
            entry["fetched"] = hit[0]
            with open(hit[1], encoding="utf-8") as f:
                pages[entry["page"]] = read_page(f.read())
    zone_paths = zone_paths_by_vote(data, pages, index)
    world_dir = os.path.join(PACK, "tools", "quest-specs", world.lower())
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
    langs, ids = {}, {}
    for entry in index:
        keys = sorted((k for k in data.title_keys(entry["name"]) if data.has_quest_lang(k)),
                      key=lambda k: not data.in_range(k))
        langs[entry["page"]] = keys[0] if keys else None
    unmatched = [page for page, lang in langs.items() if lang is None and page in pages]
    claimed = set(langs.values())
    by_text = match_placeholders(data, pages, unmatched, [k for k in placeholders if k not in claimed])
    langs.update(by_text)
    for entry in index:
        lang = langs[entry["page"]]
        if lang in authored:
            ids[norm(entry["name"])] = authored[lang]["id"]
        elif lang:
            ids[norm(entry["name"])] = data.internal_name(lang) or f"{data.folder}-Q-{lang}"
    for title_key, name in data.pack_quests.items():
        if title_key in data.titles:
            ids.setdefault(norm(data.titles[title_key]), name)
    known_zones = questgen.zone_transfer_zones()
    unresolved, written, blocked, compared = {}, 0, [], []
    for entry in index:
        if entry["page"] not in pages:
            continue
        lang = langs[entry["page"]]
        quest_id = ids.get(norm(entry["name"])) or f"{data.folder}-Q-{norm(entry['name'])}"
        builder = SpecBuilder(data, entry, pages[entry["page"]], zone_paths, ids, known_zones)
        if entry["page"] in by_text:
            builder.unresolved("lang", f"WizQst{lang} matched by the words it shares with the goals", False)
        spec = builder.build(lang, quest_id)
        for item in spec["needs_review"]:
            counts = unresolved.setdefault(item["field"], [0, 0])
            counts[0 if item["blocking"] else 1] += 1
        is_blocked = any(item["blocking"] for item in spec["needs_review"])
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
    print(f"{world}: {len(pages)} pages parsed, {written} specs ready, {len(blocked)} blocked, "
          f"{len(compared)} compared with hand-authored specs; zones: "
          + ", ".join(f"{name} = {path}" for name, path in sorted(zone_paths.items())))
    print(f"{'field':<20} {'blocking':>8} {'review':>8}")
    for field, (hard, soft) in sorted(unresolved.items()):
        print(f"{field:<20} {hard:>8} {soft:>8}")
    for reference, spec in compared:
        differences = list(questgen.diff({k: v for k, v in spec.items() if k not in ("source", "needs_review")},
                                         reference))
        print(f"== {reference['id']} vs archive: {len(differences)} differences")
        for line in differences:
            print("  " + line)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--enumerate", metavar="WORLD", help="list the world's quests from the archived categories")
    mode.add_argument("--fetch", metavar="WORLD", help="download the listed quest pages into the cache")
    mode.add_argument("--parse", metavar="WORLD", help="write a questgen spec per cached quest page")
    parser.add_argument("--cache", default=DEFAULT_CACHE, help="the directory of fetched pages and the index")
    args = parser.parse_args()
    world = args.enumerate or args.fetch or args.parse
    if world not in WORLDS:
        raise SystemExit(f"{world}: not configured; known worlds: {', '.join(WORLDS)}")
    os.makedirs(args.cache, exist_ok=True)
    archive = Archive()
    try:
        if args.enumerate:
            enumerate_world(archive, args.cache, world)
        elif args.fetch:
            fetch_world(archive, args.cache, world)
        else:
            parse_world(args.cache, world)
    except ArchiveUnavailable as e:
        sys.exit(f"archive unavailable: {e}")


if __name__ == "__main__":
    main()
