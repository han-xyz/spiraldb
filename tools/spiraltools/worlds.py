"""The worlds the tools know: quest-name prefix, wiki category, client folders, level and quest lang cluster."""
import re
from typing import NamedTuple

from .lang import quest_lang_keys, read_lang

# WizQst keys closer than this belong to one group; a world's cluster also takes the anchored groups within reach.
CLUSTER_GAP = 0x100
CLUSTER_REACH = 0x1000
INTERNAL_NAME = re.compile(r"[A-Z]{2,}(-[A-Za-z0-9]+)+")
HEX_KEY = re.compile(r"[1-9A-F][0-9A-F]*")


class World(NamedTuple):
    name: str
    prefix: str
    wiki: str
    level: int
    lang_range: tuple = None

    @property
    def category(self):
        return f"Category:{self.wiki}_Quests"

    @property
    def folder(self):
        """The ObjectData folder of the world's templates."""
        return self.prefix


# name: the zone wad prefix (Celestia-*.wad); prefix: the quest names (CL-CAMP-C01-001) and the ObjectData folder.
# level: the quest level a spec gets when the wiki gives none. lang_range: declared where QuestTitle.lang has no
# internal quest name of the world to anchor its cluster, or where the anchor sits outside the world's quests.
WORLDS = (
    World("WizardCity", "WC", "Wizard_City", 5),
    World("Krokotopia", "KT", "Krokotopia", 15),
    World("Marleybone", "MB", "Marleybone", 22),
    World("MooShu", "MS", "MooShu", 30),
    World("DragonSpire", "DS", "Dragonspyre", 40),
    World("Grizzleheim", "GH", "Grizzleheim", 45),
    World("Celestia", "CL", "Celestia", 48),
    # Widened from 0x71A69 to cover the keys its quest titles read.
    World("Zafaria", "ZF", "Zafaria", 60, (0x718AF, 0x82A92)),
    World("Avalon", "AV", "Avalon", 68, (0x72D11, 0x96B64)),
    World("Azteca", "AZ", "Azteca", 78, (0x72E2E, 0xB4FAF)),
    World("Khrysalis", "KR", "Khrysalis", 88, (0x126322, 0x13D76F)),
    World("Polaris", "PL", "Polaris", 100, (0x1294F8, 0x14E7DF)),
    World("Mirage", "MR", "Mirage", 105),
    World("Empyrea", "EM", "Empyrea", 112, (0x132297, 0x16437F)),
    World("Karamelle", "KM", "Karamelle", 122, (0x16B48E, 0x1716FA)),
    World("Lemuria", "LM", "Lemuria", 132, (0x170115, 0x1744C6)),
    World("Novus", "NV", "Novus", 142),
    World("Wallaru", "WL", "Wallaru", 152, (0x17D895, 0x188A01)),
)


class UnknownWorld(SystemExit):
    pass


def world(name):
    """The registered world of that name, case and spaces ignored."""
    wanted = name.replace(" ", "").lower()
    found = next((w for w in WORLDS if w.name.lower() == wanted), None)
    if found is None:
        raise UnknownWorld(f"{name}: not a registered world; known worlds: {', '.join(w.name for w in WORLDS)}")
    return found


def key_groups(keys):
    """Hex keys in runs whose neighbours are at most CLUSTER_GAP apart, as [(first, last)]."""
    groups = []
    for value in (int(k, 16) for k in keys):
        if groups and value - groups[-1][1] <= CLUSTER_GAP:
            groups[-1][1] = value
        else:
            groups.append([value, value])
    return [tuple(g) for g in groups]


def lang_cluster(registered, rootwad):
    """(first, last) WizQst key of the world's quests: the run of quest lang files that holds the most QuestTitle
    entries carrying one of the world's internal quest names (CL-CAMP-C01-001), widened to the other anchored runs
    within CLUSTER_REACH; the declared lang_range when the world has one."""
    if registered.lang_range is not None:
        return registered.lang_range
    titles = read_lang(rootwad, "QuestTitle")
    anchors = [int(key, 16) for key, text in titles.items()
               if HEX_KEY.fullmatch(key) and INTERNAL_NAME.fullmatch(text.strip())
               and text.strip().startswith(registered.prefix + "-")]
    groups = [(g, sum(g[0] <= a <= g[1] for a in anchors)) for g in key_groups(quest_lang_keys(rootwad))]
    anchored = [(g, n) for g, n in groups if n]
    if not anchored:
        raise UnknownWorld(f"{registered.name}: no QuestTitle entry anchors its quest langs; declare lang_range")
    main = max(anchored, key=lambda item: item[1])[0]
    near = [g for g, _ in anchored if g[0] - main[1] <= CLUSTER_REACH and main[0] - g[1] <= CLUSTER_REACH]
    return min(g[0] for g in near), max(g[1] for g in near)
