# tools

## zone-transfer-from-wad.py

Rebuilds `ZoneTransfer` entries for a zone from the client's zone wad (`Data/GameData/<World>-<Zone>.wad`,
read-only). Python 3, standard library only:

```sh
python3 -I tools/zone-transfer-from-wad.py Grizzleheim/Interiors/GH_Hero_T2            # print the entries
python3 -I tools/zone-transfer-from-wad.py Grizzleheim/Interiors/GH_Hero_T2 --street   # also the street's pad into it
python3 -I tools/zone-transfer-from-wad.py <zone>... --apply --street                  # write them
python3 -I tools/zone-transfer-from-wad.py <zone> --street WizardCity/WC_Streets/WC_Colossus --apply
python3 -I tools/zone-transfer-from-wad.py --check                                     # quest zones absent from ZoneTransfer
```

`--gamedata <dir>` points at another client install. A bare `--street` must come after the zone paths.

What it emits, from `gamedata.bin` and `triggers.xml` of the zone's wad:

- **Pads and sigils** in the zone: an object whose teleport behaviour names a zone. `TriggerName` is the object name,
  the location is the pad's own destination location, or `Start` when the pad has none.
- **Exits**: a trigger fired by `Enter_TeleportVol_<volume>`. The client keeps no destination for these, so the tool
  picks, in order: the one zone of the world that has a location named `<volume>`; the one location of the world named
  after the zone (`GH_Hero_T2` matches `FromHeroT2`); the parent's location nearest the pad into the zone, within 1000
  units. The parent is the zone whose pad leads here, or the `--street` zone. Anything else is skipped and listed on stderr.
- **Inbound** (`--street`): the street's pads into the zone, else the street's triggers fired by `Enter_<location>`
  where `<location>` is a location of the zone (the door volumes of houses).

`--apply` is append-only: an entry whose `TriggerName` the file already has is left as it is, and nothing is removed.
A zone without a file gets `ZoneTransfer/WizardZoneDatas_<last path segment>.json`.

`--check` lists the zones the quest templates send a player to (`m_destinationZone`, goal `m_zoneTag`, `ReqInZone`,
`ResAddDynaMod`) that have no ZoneTransfer file, then those that have one but no teleport leading into them.

### Location: name or coordinates

`m_destinationLoc` is either a location name or `x,y,z,direction`. The server passes it to the client unchanged, and
the client looks a name up in the destination zone's location list (`gamedata.bin`). The tool writes names, because the
wad gives them. Write coordinates only for a spot with no named location, as the shortest float32 text
(`484.1623,31.0982,1.989745,1.167386`), the same style as the entries captured from the live game.

## crown-shop-gear-from-wad.py

Lists the crowns-only gear of the client's root wad (`ObjectData/CrownItems`, unpacked at `/kioxia/generator-input/rootwad`,
read-only) in the Gear tab, `CrownShop/Tab7.json`. Python 3, standard library only:

```sh
python3 -I tools/crown-shop-gear-from-wad.py --dry-run   # count the entries per category
python3 -I tools/crown-shop-gear-from-wad.py --apply     # append them to CrownShop/Tab7.json
```

`--rootwad <dir>` points at another unpacked root wad.

It reads the `Series<N>` and `Starter` folders (not `Stitch`) and takes the templates that carry `FLAG_CrownsOnly`,
skipping names containing `DONOTUSE`, `Test` or `Stitch`. The template id comes from `TemplateManifest.xml`. The
folder sets the category: `Wands` 15, `Hat`/`Hats` 11, `Robe`/`Robes` 9, `Shoes` 10, `Rings` 12, `Athames` 14.

It lists a curated set, because the whole shop goes to the client in one response: the Starter sets, plus for each
category and level band (the price bands below, and one for names without a level) the `--series-per-band` newest
series (default 3), all schools, with Maycast wands at the E3 enchant only. A category over `--max-per-category`
(default 500) drops its oldest series first. Raise either flag to widen the list.

`--apply` is append-only: an entry whose `templateId` the tab already has is left as it is, and nothing is removed.

### Placeholder prices

The retail catalogue is not available, so the prices are placeholders to retune: by the level in the name (`-L<n>`),
L0-19 1500, L20-39 2500, L40-59 3500, L60-79 4500, L80-99 5500, L100 and up 6500 crowns; 2500 when the name has no
level; wands 500 more. `goldCost` is 0: crowns only. The bands are `LEVEL_BANDS`, `UNLEVELLED_PRICE` and
`WAND_SURCHARGE` at the top of the script.

## questgen.py

Writes a quest template and its drop table from one JSON spec per quest. Python 3, standard library only (so the
specs are JSON, not YAML):

```sh
python3 -I tools/questgen.py tools/quest-specs/celestia/*.json           # list what it would write
python3 -I tools/questgen.py --check tools/quest-specs/celestia/*.json   # validate the specs against the client
python3 -I tools/questgen.py --apply tools/quest-specs/celestia/*.json   # write them
python3 -I tools/questgen.py --diff tools/quest-specs/roundtrip/*.json   # compare with the pack's own templates
```

`--rootwad` and `--gamedata` point at another client, as in the other tools.

It writes `QuestTemplates/questtemplates_<id>.json`, and the drop table to `DropTables/droptables_<id>.json` (the
folder the server loads) and to its copy in `QuestTemplates/droptables/`. A file that would not change is left alone,
drop-table timestamps included.

### Spec

```json
{
  "id": "CL-CAMP-C03-002",
  "lang": "371B8",
  "title": "QuestTitle_00000103",
  "giver": {"persona": "CL-CAMP-NPC08", "zone": "Celestia/CL_Z01_Survey_Camp"},
  "requires": ["CL-CAMP-C03-003"],
  "min_level": 48,
  "mainline": false,
  "level": 48,
  "reward": {"xp": 2155, "gold": 160},
  "dialogs": {"prep": [{"speaker": "giver", "line": "00000005"}], "underway": [{"speaker": "giver", "line": "00000004"}]},
  "goals": [
    {"type": "bountycollect", "mobs": ["CL-Eel-Green-R9.AdjRef"], "count": 3, "descriptor": "WizQst371B8_00000002",
     "target": "WizardMobs_00000748", "zone": "Celestia/CL_Z02_Crab_Realm", "loc": "ZoneLocName_227135"},
    {"type": "persona", "persona": "giver", "zone": "Celestia/CL_Z01_Survey_Camp", "loc": "Celestia|Survey Camp",
     "completion": [{"speaker": "giver", "line": "00000003"}]}
  ],
  "personas": {"CL-CAMP-NPC08": {"portrait": "GUI/NpcPortraits/Art_Portrait_MB_Engineer_03.dds", "template_id": 227163}}
}
```

- `lang` is the hex of the quest's `WizQst<lang>.lang`. A dialog `line` is a key of that file; a key with `_` in it
  (`WizQst1625C1_00000011`) is used as written. `speaker` is `giver`, a persona, or `""` for narration.
- `title` defaults to `QuestTitle_<lang>`. Many Celestia quests carry their internal name there; use the key of the
  real title instead (`Gone Fishing` is `QuestTitle_00000103`).
- `requires` becomes `ReqHasEntry Complete` on each quest; `min_level` a `ReqMagicLevel` at or above it. Every quest
  also gets a `ReqHasEntry Completed` NOT on its successors, taken from the other specs of the same run that require
  it, or from a `successors` list.
- `reward` is the drop table's XP and gold. Without it the tool takes the median quest reward of the pack's world for
  `level`: `REWARD_BANDS` at the top of the script (40 and up is Dragonspyre's 3805 XP and 103 gold).
- Goals run in order; a goal with `"with_previous": true` runs alongside the one before it. Each is named
  `<n>_<title>`, its `m_goalNameID` the string id of `Goal` / `Goal <n-1>`, as in the builder-made pack quests.

| `type` | template | needs |
| --- | --- | --- |
| `persona` | PersonaGoalTemplate, `WizardQuestGoals_TalkNPC` | `persona`; `completion` lines become its Completion dialog |
| `bounty` | BountyGoalTemplate `GOAL_TYPE_BOUNTY`, `WizardQuestGoals_Kill` | `mobs` (adjectives), `count`, `target` (mob name key) |
| `bountycollect` | BountyGoalTemplate `GOAL_TYPE_BOUNTYCOLLECT`, `WizardQuestGoals_KillCollect` | as bounty, plus `descriptor` (item name key), `chance` (default 1.0) |
| `waypoint` | WaypointGoalTemplate, zone entry, `WizardQuestGoals_ExploreZone` | `zone` |
| `usage` | ScavengeGoalTemplate `GOAL_TYPE_USAGE`, `WizardQuestGoals_UseItem` | `items` (object adjectives), `count`, `descriptor` |

Every goal takes `zone` (its destination), `loc` (a `ZoneLocName_<key>`, any other lang key, or a
`World|Place` text that the tool looks up in ZoneLocName.lang, first match), `portrait`, `client_tags` and `title`.
`personas` gives a persona's portrait and template id for its dialog lines and goal; the server fills the speaker's
name, and a missing portrait, from the persona.

`--check` reports, per spec: a missing `WizQst<lang>.lang`, an empty `dialogs.prep` (no NPC would offer the quest), a
title or line key the lang files lack, a `loc` text ZoneLocName.lang lacks, a zone with no ZoneTransfer entry, and a
persona whose zone wad places none of the templates that carry it.

### Not generated

`--diff` lists the fields where a generated template differs from the pack's. On the three WC quests in
`quest-specs/roundtrip` (built from the pack's own templates) the goals, goal logic, requirements, dialog keys and
speakers match; what differs is dialog presentation the client keeps nowhere a tool can read: sound files, cinematic
cameras, animations and music, the `m_nameSTKey`/`m_nameOverride` name format, per-line template ids, and `m_madlibs`
(the server builds the quest madlibs). The tool also writes Completion lines on the turn-in goal rather than at quest
level, an empty goal dialog list as `null`, and `m_bountyType`/`m_bountyTotal` where some captured quests omit them.

## wiki-archive-quests.py

Builds questgen specs for a world from the Internet Archive's copies of the Wizard101 Central wiki (the wiki itself
refuses requests). Python 3, standard library only; read-only GET requests to web.archive.org, one a second, with
exponential backoff on 429 and 5xx for up to five minutes:

```sh
python3 -I tools/wiki-archive-quests.py --enumerate Celestia   # list the world's quests from the archived categories
python3 -I tools/wiki-archive-quests.py --fetch Celestia       # download each quest page's newest capture
python3 -I tools/wiki-archive-quests.py --parse Celestia       # write the specs, print what did not resolve
python3 -I tools/questgen.py --check tools/quest-specs/celestia/*.json
```

`--cache <dir>` holds the fetched pages, as `<capture timestamp>_<page>.html`, and the index
`index-<world>.json` (quest, first capture in the CDX index or `missing_snapshot`, zone categories, type). The default
is `.scratch/friends-server/task-A1/cache` in the checkout; the cache is not committed. A page already in the cache is
not fetched again. `WORLDS` at the top of the script gives each world its ObjectData folder, its quest lang range and
its level.

`--enumerate` walks `Category:<World>_Quests` and its subcategories, and reads the CDX index of `Quest:` pages. A
category with no capture is reported; its quests still come in through the other categories. `--fetch` takes the
newest capture, and the CDX timestamp when the newest capture is an error page.

`--parse` reads each page's Prequest, Given By, Giver Location, type sentence, Goals, Hand In and Reward, and resolves:

- the title to `lang` through `QuestTitle.lang`, compared without case, punctuation or a leading "The". Most Celestia
  quests keep their real title under a placeholder key (`QuestTitle_00000103`) and the internal name, or nothing, under
  the lang key; those are matched to a free `WizQst` file in three ways, each recorded with its evidence under `lang`
  in `needs_review`:
  - chain order: the quests of a chain hold consecutive keys, so the unmatched quests between two matched ones on the
    Prequest / Leads to chain take the free keys between those two, when there are exactly as many;
  - shared words: the rare words a key's lines share with the goal lines, one to one, and only when the best match
    clearly beats the second;
  - chain window: the only free key within `CHAIN_WINDOW` of a chain neighbour's key.

  Chain order and chain window keep a key only when its lines name the page's giver, hand-in NPC, or a goal NPC,
  creature or item.
- NPC names to personas with `npc-personas-from-wad.py`, mobs to their `.AdjRef` adjectives with
  `mob-adjectives-from-wad.py`, objects to the adjectives of the world's object templates by display name or template
  name, and item names to a line of the quest's own `WizQst` file. A named NPC template that no zone wad places takes
  the zones of an unnamed template with the same persona (Queen Calypso is placed as `CL-CalypsoReset`). A name the
  world's folder lacks is taken from the one world name close to it (`NAME_CUTOFF`; the wiki's Koltan Grimfane is
  Koltan Gloomfane), else from the other ObjectData folders, placed by every zone wad; a mob the world's folder lacks
  comes from the other folders too (the Spellwrit Wildclaws are in `PageEvent`). Each of these is listed in
  `needs_review`.
- the zone from the zone category, else the giver's location, to the zone where most of that zone's givers stand.
- prerequisites to the ids of the other specs, or of the pack's quests with that title.

The id is the hand-authored spec's for the same lang, else the internal name in `QuestTitle.lang`, else
`<folder>-Q-<lang>`. The wiki has no level, so every quest gets the world's. A ready spec's prerequisite that will
not be generated (blocked, or no archived page) is replaced by its nearest generated ancestors on the wiki's Prequest
chain, listed as `requires (not generated)`; a quest left with no prerequisite gets `min_level`.

Dialog keys are guessed from the text of each `WizQst` line: lines that remind the player of the task are Underway,
lines that thank the player are the hand-in NPC's Completion, the rest are the giver's Prep in key order. The server
offers a quest through its first Prep line, so a spec needs at least one: when no line reads as an offer, the first
line that names the giver is the Prep line, else the file's first line, listed as `dialogs.prep`.

Each spec carries `source` (page and capture) and `needs_review`: what did not resolve, `blocking` or not. A spec with
a blocking gap goes to `quest-specs/<world>/blocked/`, where the questgen glob does not reach; a waypoint whose place
has no zone path is left out and listed. A spec for a lang that a hand-authored spec already covers is written to
`<cache>/reference-<world>/` instead, and the differences are printed. A rerun replaces the specs it wrote before.

## mob-adjectives-from-wad.py and npc-personas-from-wad.py

The lookups a spec needs, from the root wad's object templates (`ObjectData/<folder>`, a world's mobs and NPCs) and
the zone wads:

```sh
python3 -I tools/mob-adjectives-from-wad.py            # CL: display name, template, template id, adjectives
python3 -I tools/npc-personas-from-wad.py               # CL / Celestia: persona, name, template id, portrait, zones
python3 -I tools/npc-personas-from-wad.py --folder WC --world WizardCity
```

A bounty goal counts a defeated mob once for each of its adjectives in `mobs`, so name one adjective per mob: its
own `<template>.AdjRef`. A shared adjective (`Crustacean_Pincer`, `MONST_Fish`) catches every template that has it.
A persona goal's `persona` is the persona without `_Persona`; the zones column is where to send the player.

## Authoring a world

1. List the world's quests: `QuestTitle.lang` keys next to `WizQst<hex>.lang` files, and the zone wads' quest names.
2. For each quest, read its `WizQst<hex>.lang` and order the lines: the offer (Prep), the reminder (Underway), the
   turn-in (Completion), and which persona says each.
3. Take givers, turn-in NPCs and their zones from `npc-personas-from-wad.py`, and mob adjectives and name keys from
   `mob-adjectives-from-wad.py` and `WizardMobs.lang`.
4. Write the spec, run `--check`, then `--apply`. A zone the check reports without ZoneTransfer is added with
   `zone-transfer-from-wad.py`.

The client does not hold quest order and prerequisites, goal sequence, counts beyond what the lines say, rewards,
or which NPC says a line; those come from a walkthrough. `quest-specs/celestia` is the Survey Camp pilot.
