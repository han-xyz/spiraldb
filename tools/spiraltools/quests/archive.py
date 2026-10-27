"""Questgen specs for a world, built from the Internet Archive's copies of the Wizard101 Central wiki: enumerate the
world's quest pages, fetch them, parse them into specs."""
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
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import templates
from ..lang import LANG_SUBDIR, ROOTWAD_DIR, read_lang
from ..pack import PACK, QUEST_SPECS_DIR, quest_template_paths, zone_transfer_files
from ..wad import GAMEDATA_DIR
from ..worlds import lang_cluster, world
from .generate import diff

DESCRIPTION = "Build questgen specs for a world from the Internet Archive's copies of the Wizard101 Central wiki."
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
CHAIN_WINDOW = 16
NAME_CUTOFF = 0.8


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


def walk_categories(archive, cache, registered):
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


def enumerate_world(archive, cache, registered):
    world = registered.name
    quests = walk_categories(archive, cache, registered)
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
            if not line.startswith("("):
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


class ClientData:
    """The lookups a spec needs: titles, personas, mobs, objects, zone locations and the pack's quests."""

    def __init__(self, registered):
        self.world = registered.name
        self.folder = registered.folder
        self.level = registered.level
        self.read_lang = lambda name: read_lang(ROOTWAD_DIR, name)
        self.titles = self.read_lang("QuestTitle")
        self.lang_range = lang_cluster(registered, ROOTWAD_DIR)
        self.lang_dir = os.path.join(ROOTWAD_DIR, LANG_SUBDIR)
        rows = list(templates.npcs(ROOTWAD_DIR, self.folder))
        placed = templates.zone_placements(GAMEDATA_DIR, self.world, [row["template"] for row in rows])
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
        self.other_folders = sorted(folder for folder in os.listdir(os.path.join(ROOTWAD_DIR, "ObjectData"))
                                    if folder != self.folder
                                    and os.path.isdir(os.path.join(ROOTWAD_DIR, "ObjectData", folder)))
        self.other_mobs, self.other_personas = None, None
        self.objects = item_index(templates.items(ROOTWAD_DIR, self.folder), self.folder)
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
            placed = templates.zone_placements(GAMEDATA_DIR, "*", [row["template"] for row in unplaced])
            for row in unplaced:
                row["zones"] = placed[row["template"]]
        return rows

    def in_range(self, key):
        return re.fullmatch(r"[0-9A-F]+", key) and self.lang_range[0] <= int(key, 16) <= self.lang_range[1]

    def has_quest_lang(self, key):
        return os.path.exists(os.path.join(self.lang_dir, f"WizQst{key}.lang"))

    def title_keys(self, title):
        wanted = title_norm(title)
        return [key for key, text in self.titles.items() if title_norm(text) == wanted]

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
        close = difflib.get_close_matches(wanted, self.personas, n=2, cutoff=NAME_CUTOFF)
        if not rows and len(close) == 1:
            rows = self.personas[close[0]]
        rows = rows or self.other_world_personas(wanted)
        if not rows:
            return None
        return next((row for row in rows if zone in row["zones"]), next((r for r in rows if r["zones"]), rows[0]))

    def mob_entries(self, name):
        """The mob entries for a name, from the world's folder, else from any other folder."""
        found = next((self.mobs[form] for form in singular_forms(name) if form in self.mobs), [])
        if found:
            return found
        if self.other_mobs is None:
            self.other_mobs = self.mob_index(self.other_folders)
        return next((self.other_mobs[form] for form in singular_forms(name) if form in self.other_mobs), [])

    def object_entries(self, name):
        return item_entries(self.objects, name)


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
        if norm(row["name"]) != norm(name) and not norm(row["name"]).endswith(norm(name)):
            self.unresolved(f"{field} (closest name)", f"{name} read as {row['name']}", False)
        if row["folder"] != self.data.folder:
            self.unresolved(f"{field} (other world)", f"{name}: {row['template']} from ObjectData/{row['folder']}",
                            False)
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
            for folder in sorted({e["folder"] for e in entries} - {self.data.folder}):
                self.unresolved("goal.mobs (other folder)", f"{creature}: ObjectData/{folder}", False)
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
            name = (links(line, "NPC") or [re.sub(r"^Talk to\s+|\s+in\s+.*$", "", text, flags=re.I)])[0]
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


def quest_names(fields):
    """The NPCs, creatures and items a quest page names: what its WizQst lines should mention too."""
    names = [fields["giver"], fields["hand_in"]]
    for line in fields["goals"]:
        names += links(line, "NPC") + links(line, "Creature")
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
            entry["fetched"] = hit[0]
            with open(hit[1], encoding="utf-8") as f:
                pages[entry["page"]] = read_page(f.read())
    zone_paths = zone_paths_by_vote(data, pages, index)
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
    langs, ids = {}, {}
    for entry in index:
        keys = sorted((k for k in data.title_keys(entry["name"]) if data.has_quest_lang(k)),
                      key=lambda k: not data.in_range(k))
        langs[entry["page"]] = keys[0] if keys else None
    by_title = {title_norm(entry["name"]): entry["page"] for entry in index}
    evidence = {}

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
        builder = SpecBuilder(data, entry, pages[entry["page"]], zone_paths, ids, known_zones)
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
    print(f"{world}: {len(pages)} pages parsed, {written} specs ready, {len(blocked)} blocked, "
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
    mode.add_argument("--enumerate", metavar="WORLD", help="list the world's quests from the archived categories")
    mode.add_argument("--fetch", metavar="WORLD", help="download the listed quest pages into the cache")
    mode.add_argument("--parse", metavar="WORLD", help="write a questgen spec per cached quest page")
    add_cache_argument(parser)


def add_cache_argument(parser):
    parser.add_argument("--cache", default=DEFAULT_CACHE, help="the directory of fetched pages and the index")


def run(args):
    registered = world(args.enumerate or args.fetch or args.parse)
    os.makedirs(args.cache, exist_ok=True)
    archive = Archive()
    try:
        if args.enumerate:
            enumerate_world(archive, args.cache, registered)
        elif args.fetch:
            fetch_world(archive, args.cache, registered.name)
        else:
            parse_world(args.cache, registered)
    except ArchiveUnavailable as e:
        sys.exit(f"archive unavailable: {e}")


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    add_arguments(parser)
    run(parser.parse_args())
