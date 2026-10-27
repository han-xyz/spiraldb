"""The pack's JSON files: tolerant reading, the trailing-comma convention of appended entries, and their paths."""
import glob
import json
import os
import re

PACK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ZONE_TRANSFER_DIR = os.path.join(PACK, "ZoneTransfer")
QUEST_TEMPLATES_DIR = os.path.join(PACK, "QuestTemplates")
QUEST_SPECS_DIR = os.path.join(PACK, "tools", "quest-specs")


def parse_tolerant(text):
    """JSON that may carry a trailing comma before a closing bracket, as many pack files do."""
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", text))


def tolerant_load(path):
    with open(path, encoding="utf-8") as f:
        return parse_tolerant(f.read())


def render(document):
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def render_entry(item):
    """An entry of a top-level list, indented to sit inside it."""
    return "\n".join("    " + line for line in json.dumps(item, indent=2, ensure_ascii=False).splitlines())


def append_teleports(path, added):
    """Append entries to the Teleports list that closes a ZoneTransfer file, in the file's comma style."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"(\S)\s*\]\s*\}\s*$", text)
    if m is None:
        raise SystemExit(f"{path}: Teleports is not the last key; edit by hand")
    trailing_comma = m.group(1) == ","
    separator = "\n" if trailing_comma else ",\n"
    body = separator.join(render_entry(e) + ("," if trailing_comma else "") for e in added)
    if m.group(1) == "[":
        text = text[:m.start(1)] + "[\n" + body + "\n  ]\n}\n"
    else:
        text = text[:m.end(1)] + separator + body + "\n  ]\n}\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def append_items(path, added):
    """Append entries to the items list that closes a crown shop tab, in the file's comma style."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"(\S)(\s*\]\s*\}\s*)$", text)
    if m is None:
        raise SystemExit(f"{path}: items is not the last key; edit by hand")
    trailing_comma = m.group(1) == ","
    separator = "\n" if trailing_comma or m.group(1) == "[" else ",\n"
    body = separator.join(render_entry(e) + ("," if trailing_comma else "") for e in added)
    text = text[:m.end(1)] + separator + body + m.group(2)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def write_unless_same(path, document, ignored=()):
    """Write the document; a file equal to it but for the ignored keys is left as it is."""
    if os.path.exists(path):
        current = tolerant_load(path)
        if {k: v for k, v in current.items() if k not in ignored} == {k: v for k, v in document.items() if k not in ignored}:
            return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(document))
    return True


def zone_transfer_paths(directory=ZONE_TRANSFER_DIR):
    return sorted(glob.glob(os.path.join(directory, "*.json")))


def zone_transfer_files(directory=ZONE_TRANSFER_DIR):
    """ZoneName -> its ZoneTransfer file."""
    return {tolerant_load(p)["ZoneName"]: p for p in zone_transfer_paths(directory)}


def new_zone_file_path(zone_name, directory=ZONE_TRANSFER_DIR):
    """WizardZoneDatas_<last segment>.json, widened by parent segments while the name is taken."""
    segments = zone_name.split("/")
    for n in range(1, len(segments) + 1):
        path = os.path.join(directory, f"WizardZoneDatas_{'_'.join(segments[-n:])}.json")
        if not os.path.exists(path):
            return path
    raise SystemExit(f"{zone_name}: every file name is taken; name the file by hand")


def duplicate_trigger_names(directory=ZONE_TRANSFER_DIR):
    """{file: [TriggerName, ...]} for the ZoneTransfer files that list a TriggerName more than once."""
    found = {}
    for path in zone_transfer_paths(directory):
        seen, repeated = set(), []
        for teleport in tolerant_load(path).get("Teleports", []):
            name = teleport["TriggerName"]
            if name in seen and name not in repeated:
                repeated.append(name)
            seen.add(name)
        if repeated:
            found[path] = repeated
    return found


def quest_template_paths(directory=QUEST_TEMPLATES_DIR):
    return glob.glob(os.path.join(directory, "questtemplates_*.json"))


def quest_output_paths(quest_id):
    """The quest template, and the drop table in the folder the server loads and in its QuestTemplates copy."""
    table = f"droptables_{quest_id.lower()}.json"
    return (os.path.join(QUEST_TEMPLATES_DIR, f"questtemplates_{quest_id}.json"),
            [os.path.join(PACK, "DropTables", table), os.path.join(QUEST_TEMPLATES_DIR, "droptables", table)])
