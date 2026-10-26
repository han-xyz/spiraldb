#!/usr/bin/env python3
"""List the crowns-only gear of the client's root wad in the crown shop's Gear tab.

See tools/README.md for usage and the placeholder prices.
"""
import argparse
import glob
import json
import os
import re
import struct
import zlib

PACK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOTWAD_DIR = "/kioxia/generator-input/rootwad"
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

MANIFEST_ENTRY = re.compile(
    rb"(?s)\xbc\x90\xce\xb9(.)(ObjectData/CrownItems/[ -~]+?\.xml)\x60\x00\x00\x00\x3a\x8f\x35\x89(.{4})")
ZLIB_HEADER = b"\x78\x9c"


def tolerant_load(path):
    with open(path, encoding="utf-8") as f:
        return json.loads(re.sub(r",(\s*[}\]])", r"\1", f.read()))


def read_binary_xml(path):
    """A BINd file, its body zlib-compressed when the manifest-style header carries a stream."""
    with open(path, "rb") as f:
        data = f.read()
    start = data.find(ZLIB_HEADER, 8, 16)
    if start < 0:
        return data
    try:
        return zlib.decompress(data[start:])
    except zlib.error:
        return data


def template_ids(rootwad):
    """CrownItems manifest paths -> template id."""
    manifest = read_binary_xml(os.path.join(rootwad, "TemplateManifest.xml"))
    ids = {}
    for m in MANIFEST_ENTRY.finditer(manifest):
        if m.group(1)[0] == 2 * len(m.group(2)):
            ids[m.group(2).decode()] = struct.unpack("<I", m.group(3))[0]
    return ids


def series_order(folder):
    digits = re.sub(r"\D", "", folder)
    return (0, int(digits)) if digits else (1, folder)


def price(name, category):
    level = re.search(r"-L(\d+)(?!\d)", name)
    if level is None:
        crowns = UNLEVELLED_PRICE
    else:
        crowns = next(cost for floor, cost in LEVEL_BANDS if int(level.group(1)) >= floor)
    return crowns + (WAND_SURCHARGE if category == WAND_CATEGORY else 0)


def gear(rootwad):
    """(name, entry) for each crowns-only gear template, in series and file order; also the skipped counts."""
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
                found.append((name, {
                    "templateId": template_id,
                    "crownsCost": price(name, category),
                    "displayPriority": [category],
                    "goldCost": 0,
                }))
    return found, skipped


def render_entry(item):
    return "\n".join("    " + line for line in json.dumps(item, indent=2, ensure_ascii=False).splitlines())


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
    with open(GEAR_TAB, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"(\S)(\s*\]\s*\}\s*)$", text)
    if m is None:
        raise SystemExit(f"{GEAR_TAB}: items is not the last key; edit by hand")
    trailing_comma = m.group(1) == ","
    separator = "\n" if trailing_comma or m.group(1) == "[" else ",\n"
    body = separator.join(render_entry(e) + ("," if trailing_comma else "") for e in added)
    text = text[:m.end(1)] + separator + body + m.group(2)
    with open(GEAR_TAB, "w", encoding="utf-8") as f:
        f.write(text)
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true", help="print the counts per category")
    action.add_argument("--apply", action="store_true", help="append the entries to CrownShop/Tab7.json")
    parser.add_argument("--rootwad", default=ROOTWAD_DIR, help="the unpacked root wad")
    args = parser.parse_args()
    found, skipped = gear(args.rootwad)
    entries = [e for _, e in found]
    if args.apply:
        entries = merge(entries)
    counts = {}
    for e in entries:
        counts[e["displayPriority"][0]] = counts.get(e["displayPriority"][0], 0) + 1
    verb = "added" if args.apply else "found"
    for category, count in sorted(counts.items()):
        print(f"category {category}: {count} {verb}")
    print(f"total: {len(entries)} {verb}; skipped: " + ", ".join(f"{k} {v}" for k, v in skipped.items()))


if __name__ == "__main__":
    main()
