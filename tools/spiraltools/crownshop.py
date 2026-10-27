"""The crown shop's Gear tab: the crowns-only gear of the root wad, curated, at placeholder prices."""
import argparse
import glob
import os
import re

from .lang import ROOTWAD_DIR
from .pack import PACK, append_items, tolerant_load
from .templates import read_binary_xml, template_ids

DESCRIPTION = "List the crowns-only gear of the client's root wad in the crown shop's Gear tab."
GEAR_TAB = os.path.join(PACK, "CrownShop", "Tab7.json")

CATEGORY_BY_FOLDER = {
    "Wands": 15,
    "Hat": 11,
    "Hats": 11,
    "Robe": 9,
    "Robes": 9,
    "Shoes": 10,
    "Rings": 12,
    "Athames": 14,
}
EXCLUDED_NAME_PARTS = ("DONOTUSE", "Test", "Stitch")
CROWNS_ONLY_FLAG = b"FLAG_CrownsOnly"
WAND_CATEGORY = 15
WAND_SURCHARGE = 500
UNLEVELLED_PRICE = 2500
LEVEL_BANDS = ((100, 6500), (80, 5500), (60, 4500), (40, 3500), (20, 2500), (0, 1500))
SERIES_PER_BAND = 3
MAX_PER_CATEGORY = 500
MAYCAST = "-Maycast-"
MAYCAST_KEPT_ENCHANT = "-E3-"
STARTER = "Starter"


def series_order(folder):
    digits = re.sub(r"\D", "", folder)
    return (0, int(digits)) if digits else (1, folder)


def level_band(name):
    """The LEVEL_BANDS floor for the level in the name, None without one."""
    level = re.search(r"-L(\d+)(?!\d)", name)
    if level is None:
        return None
    return next(floor for floor, _ in LEVEL_BANDS if int(level.group(1)) >= floor)


def price(name, category):
    band = level_band(name)
    crowns = UNLEVELLED_PRICE if band is None else dict(LEVEL_BANDS)[band]
    return crowns + (WAND_SURCHARGE if category == WAND_CATEGORY else 0)


def gear(rootwad):
    """(series folder, name, entry) for each crowns-only gear template, in series and file order;
    also the skipped counts."""
    ids = template_ids(rootwad)
    crown_items = os.path.join(rootwad, "ObjectData", "CrownItems")
    found, skipped = [], {"excluded name": 0, "no FLAG_CrownsOnly": 0, "not in manifest": 0}
    series = [s for s in os.listdir(crown_items) if s.startswith("Series") or s == "Starter"]
    for folder in sorted(series, key=series_order):
        for kind in sorted(os.listdir(os.path.join(crown_items, folder))):
            category = CATEGORY_BY_FOLDER.get(kind)
            if category is None:
                continue
            for path in sorted(glob.glob(os.path.join(crown_items, folder, kind, "*.xml"))):
                name = os.path.basename(path)[:-4]
                if any(part in name for part in EXCLUDED_NAME_PARTS):
                    skipped["excluded name"] += 1
                    continue
                if CROWNS_ONLY_FLAG not in read_binary_xml(path):
                    skipped["no FLAG_CrownsOnly"] += 1
                    continue
                template_id = ids.get(os.path.relpath(path, rootwad).replace(os.sep, "/"))
                if template_id is None:
                    skipped["not in manifest"] += 1
                    continue
                found.append((folder, name, {
                    "templateId": template_id,
                    "crownsCost": price(name, category),
                    "displayPriority": [category],
                    "goldCost": 0,
                }))
    return found, skipped


def curate(found, series_per_band, max_per_category):
    """Starter sets, plus per category and level band the newest series_per_band series, Maycast wands at E3 only;
    over max_per_category, the oldest series go first."""
    found = [f for f in found if MAYCAST not in f[1] or MAYCAST_KEPT_ENCHANT in f[1]]
    series_in = {}
    for folder, name, e in found:
        if folder != STARTER:
            series_in.setdefault((e["displayPriority"][0], level_band(name)), set()).add(series_order(folder))
    newest = {key: sorted(s)[-series_per_band:] for key, s in series_in.items()}
    kept = [f for f in found
            if f[0] == STARTER or series_order(f[0]) in newest[(f[2]["displayPriority"][0], level_band(f[1]))]]
    by_category = {}
    for index, f in enumerate(kept):
        by_category.setdefault(f[2]["displayPriority"][0], []).append((index, f))
    capped = []
    for members in by_category.values():
        members.sort(key=lambda m: (m[1][0] != STARTER, -series_order(m[1][0])[1] if m[1][0] != STARTER else 0))
        capped.extend(members[:max_per_category])
    return [f for _, f in sorted(capped, key=lambda m: m[0])]


def merge(entries):
    """Append the entries whose templateId the Gear tab lacks; returns those added."""
    present = {i["templateId"] for i in tolerant_load(GEAR_TAB)["items"] if "templateId" in i}
    added = []
    for e in entries:
        if e["templateId"] not in present:
            present.add(e["templateId"])
            added.append(e)
    if not added:
        return []
    append_items(GEAR_TAB, added)
    return added


def add_arguments(parser):
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true", help="print the counts per category")
    action.add_argument("--apply", action="store_true", help="append the entries to CrownShop/Tab7.json")
    parser.add_argument("--rootwad", default=ROOTWAD_DIR, help="the unpacked root wad")
    parser.add_argument("--series-per-band", type=int, default=SERIES_PER_BAND,
                        help="newest series kept per category and level band")
    parser.add_argument("--max-per-category", type=int, default=MAX_PER_CATEGORY,
                        help="entries kept per category, the oldest series dropped first")


def run(args):
    found, skipped = gear(args.rootwad)
    entries = [e for _, _, e in curate(found, args.series_per_band, args.max_per_category)]
    if args.apply:
        entries = merge(entries)
    counts = {}
    for e in entries:
        counts[e["displayPriority"][0]] = counts.get(e["displayPriority"][0], 0) + 1
    verb = "added" if args.apply else "found"
    for category, count in sorted(counts.items()):
        print(f"category {category}: {count} {verb}")
    print(f"total: {len(entries)} {verb}; skipped: " + ", ".join(f"{k} {v}" for k, v in skipped.items()))


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    add_arguments(parser)
    run(parser.parse_args())
