"""spiraltracker.com's quest list of a world into the cache: the JSON its Next.js page embeds, kept as it is."""
import datetime
import json
import os
import re

from .repository import Polite

SITE = "https://spiraltracker.com/"
# The page's React flight data: self.__next_f.push([1,"<chunk>"]), the chunks concatenated in order.
FLIGHT_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
QUESTS_KEY = '"quests":'


def quest_list(page):
    """The quest array of a world page, as the page holds it."""
    flight = "".join(json.loads(chunk) for chunk in FLIGHT_CHUNK.findall(page))
    at = flight.find(QUESTS_KEY + "[")
    if at < 0:
        raise ValueError("no quest list in the page")
    return json.JSONDecoder().raw_decode(flight, at + len(QUESTS_KEY))[0]


def fetch_world(client, cache, registered):
    """tracker-<world>.json from the world's page, fetched once and kept as tracker/<world>.html."""
    slug = registered.name.lower()
    folder = os.path.join(cache, "tracker")
    os.makedirs(folder, exist_ok=True)
    page_path = os.path.join(folder, f"{slug}.html")
    if not os.path.exists(page_path):
        page = client.get(SITE + slug)
        with open(page_path, "w", encoding="utf-8") as f:
            f.write(page)
    with open(page_path, encoding="utf-8") as f:
        quests = quest_list(f.read())
    fetched = datetime.datetime.fromtimestamp(os.path.getmtime(page_path), datetime.timezone.utc)
    path = os.path.join(folder, f"tracker-{slug}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"url": SITE + slug, "fetched": fetched.isoformat(timespec="seconds"), "quests": quests}, f,
                  indent=1, ensure_ascii=False)
    print(f"{registered.name}: {len(quests)} quests in {path}")
