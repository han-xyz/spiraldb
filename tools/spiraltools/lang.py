"""The client's UTF-16 lang files: string tables keyed by lang file and entry."""
import os
import re

ROOTWAD_DIR = "/kioxia/generator-input/rootwad"
LANG_SUBDIR = os.path.join("Locale", "en-US")
QUEST_LANG = re.compile(r"WizQst([0-9A-F]+)\.lang")


def lang_path(rootwad, name):
    return os.path.join(rootwad, LANG_SUBDIR, name + ".lang")


def parse_lang(data):
    """A lang file's bytes as {key: text}; the file is a header line then key, comment, text triplets."""
    lines = data.decode("utf-16").split("\r\n")
    return dict(zip(lines[1::3], lines[3::3]))


def read_lang(rootwad, name):
    with open(lang_path(rootwad, name), "rb") as f:
        return parse_lang(f.read())


def lang_exists(rootwad, name):
    return os.path.exists(lang_path(rootwad, name))


def quest_lang_keys(rootwad):
    """The hex keys of every WizQst<key>.lang, in numeric order."""
    names = os.listdir(os.path.join(rootwad, LANG_SUBDIR))
    return sorted((m.group(1) for name in names if (m := QUEST_LANG.fullmatch(name))), key=lambda k: int(k, 16))


def zone_location_keys(rootwad):
    """ZoneLocName text -> the first key that reads it."""
    keys = {}
    for key, text in read_lang(rootwad, "ZoneLocName").items():
        keys.setdefault(text, key)
    return keys
