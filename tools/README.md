# tools

The spiraldb tools read the Wizard101 client's data (read-only) and write the pack's JSON from it. They are one
Python 3 package, `tools/spiraltools/`, standard library only: install nothing, run them with `python3 -I`.

```sh
python3 -I tools/spiraltools.py check            # what the pack still lacks
python3 -I tools/spiraltools.py <command> --help
```

| command | does |
| --- | --- |
| `zones` | ZoneTransfer entries from the zone wads ([zones](#zones)) |
| `crownshop` | the crown shop's Gear tab ([crownshop](#crownshop)) |
| `mobs`, `items`, `npcs` | the mob and item adjectives and NPC personas a quest spec names ([mobs and npcs](#mobs-and-npcs)) |
| `quests check\|generate\|diff` | quest templates and drop tables from specs ([quests](#quests)) |
| `archive enumerate\|fetch\|parse` | specs for a world from the wiki archive ([archive](#archive)) |
| `check` | everything missing across the pack ([check](#check)) |

The client is read at `/kioxia/generator-input/rootwad` (the unpacked root wad) and the client's `Data/GameData`
under `/kioxia/lutris/wizard101`; `--rootwad` and `--gamedata` point at another one.

The scripts from before the package (`zone-transfer-from-wad.py`, `crown-shop-gear-from-wad.py`,
`mob-adjectives-from-wad.py`, `npc-personas-from-wad.py`, `questgen.py`, `wiki-archive-quests.py`) still run, with
the same flags and the same output; each calls the package.

## Adding a world

```sh
python3 -I tools/spiraltools.py archive enumerate Zafaria         # the world's quests from the wiki's categories
python3 -I tools/spiraltools.py archive fetch Zafaria             # each quest page, live else archived (network)
python3 -I tools/spiraltools.py archive parse Zafaria             # specs into tools/quest-specs/zafaria
python3 -I tools/spiraltools.py quests check --world Zafaria      # validate them against the client
python3 -I tools/spiraltools.py quests generate --world Zafaria --apply   # write templates and drop tables
python3 -I tools/spiraltools.py zones --all --world Zafaria --apply       # ZoneTransfer for the world's zones
python3 -I tools/spiraltools.py check                              # what is still missing
```

A spec the check reports with a zone without ZoneTransfer is ready once `zones` has written that zone; parse again,
then check. `quests` takes spec files or `--world <World>` (every spec of `tools/quest-specs/<world>`).

### Worlds

`spiraltools/worlds.py` holds one row per world: its name (the zone wad prefix, `Zafaria-*.wad`), the prefix of its
quest names and ObjectData folder (`ZF`), its wiki category (`Category:Zafaria_Quests`) and the quest level a spec
gets when the wiki gives none. The world's `WizQst` lang cluster is derived: the run of quest lang files (keys at
most `CLUSTER_GAP` apart) holding the most `QuestTitle.lang` entries that read as one of the world's internal quest
names (`CL-CAMP-C01-001`), widened to the other such runs within `CLUSTER_REACH`. A row's declared `lang_range`
wins over the derived cluster: Zafaria and Polaris have no such title, Lemuria's one title (`LM-URSAI-ENC-002a`) sits
in a run of encounter quests, Karamelle's anchored run holds 11 of its files, Empyrea's holds few of its quests, and
Khrysalis's quests lie in runs from 0x126322 to 0x13D76F that its few titles do not anchor, and Avalon's and
Azteca's quests are spread over runs their few titles do not anchor, interleaved with each other's. A declared range
is exclusive: `archive parse` takes no title key outside it, so a title read only outside it stays blocked on `lang`
(a title of the same name in another world). Zafaria's range was widened to cover the keys its titles read. A world outside the table is refused with the list of the known ones.

## check

`check` prints, in turn: the quest zones absent from ZoneTransfer and those without an inbound teleport (as
`zones --check`), every TriggerName a ZoneTransfer file lists more than once (`duplicate<TAB><file><TAB><name>`), the
client zones without a ZoneTransfer file per world (`zones --check --all-zones` lists them), and the `quests check`
of every world folder under `quest-specs`. It exits 1 when a TriggerName repeats or a spec fails its check.

## Tests

```sh
python3 -I -m unittest discover tools/tests
```

No network. The tests that read the client skip when `/kioxia` is absent.

## Package

| module | holds |
| --- | --- |
| `wad.py` | KIWAD reading; a zone wad's pads, locations, triggers and volumes; zone and world lookup |
| `lang.py` | UTF-16 lang files, the quest lang keys, the ZoneLocName index |
| `templates.py` | the template manifest, BINd fields, mob adjectives, NPC personas and where zones place them |
| `pack.py` | the pack's JSON: tolerant reading, appending in the file's comma style, file paths |
| `zones.py` | the ZoneTransfer generator and its rules |
| `crownshop.py` | the Gear tab |
| `worlds.py` | the world registry |
| `quests/spec.py` | spec loading and validation |
| `quests/generate.py` | templates and drop tables from specs |
| `quests/archive.py` | the wiki archive: enumerate, fetch, parse |
| `cli.py` | the subcommands of `spiraltools.py` |

## zones

Rebuilds `ZoneTransfer` entries for a zone from the client's zone wad (`Data/GameData/<World>-<Zone>.wad`,
read-only):

```sh
python3 -I tools/spiraltools.py zones Grizzleheim/Interiors/GH_Hero_T2            # print the entries
python3 -I tools/spiraltools.py zones Grizzleheim/Interiors/GH_Hero_T2 --street   # also the street's pad into it
python3 -I tools/spiraltools.py zones <zone>... --apply --street                  # write them
python3 -I tools/spiraltools.py zones <zone> --street WizardCity/WC_Streets/WC_Colossus --apply
python3 -I tools/spiraltools.py zones --check                                     # quest zones absent from ZoneTransfer
python3 -I tools/spiraltools.py zones --all --dry-run                             # per-world counts for every client zone
python3 -I tools/spiraltools.py zones --all --world Celestia --apply              # write one world
python3 -I tools/spiraltools.py zones --all --review                              # what --all held back, with candidates
python3 -I tools/spiraltools.py zones --check --all-zones                         # client zones still without a file
```

`--gamedata <dir>` points at another client install. A bare `--street` must come after the zone paths.

What it emits, from `gamedata.bin` and `triggers.xml` of the zone's wad:

- **Pads and sigils** in the zone: an object whose teleport behaviour names another zone. `TriggerName` is the object
  name, the location is the pad's own destination location, or `Start` when the pad has none.
- **Exits**: a trigger fired by `Enter_TeleportVol_<volume>`. The client keeps no destination for these, so the tool
  picks, in order: the one zone of the world that has a location named `<volume>`; the one location of the world named
  after the zone (`GH_Hero_T2` matches `FromHeroT2`); the parent's location nearest the pad into the zone, within 1000
  units. The parent is the zone whose pad leads here, or the `--street` zone. Anything else is skipped and listed on stderr.
- **Inbound** (`--street`): the street's pads into the zone, else the street's triggers fired by `Enter_<location>`
  where `<location>` is a location of the zone (the door volumes of houses).

`--apply` is append-only: an entry whose `TriggerName` the file already has is left as it is, and nothing is removed.
A zone without a file gets `ZoneTransfer/WizardZoneDatas_<last path segment>.json`.

### Every client zone: `--all`

`--all` takes every wad of `Data/GameData` that holds a `gamedata.bin` (3356 in the current client) as a zone, whose
path is the wad name with `-` read as `/` (`Celestia-Interiors-CL_Z09i1_Science_Center.wad` is
`Celestia/Interiors/CL_Z09i1_Science_Center`). A zone that already has a ZoneTransfer file is left alone. `--world
<World>` (repeatable) limits the run to one world.

It writes only what the wad states, because a wrong teleport sends a player to the wrong place:

- **Pads and sigils** of each uncovered zone, teleports within the zone included, and the pads of covered zones (the
  same world) into it, appended to their files.
- A pad is held back when the destination wad has no location of the pad's name, or when the destination has no file
  from before the run, has a teleport volume and no exit was written for it: the door would lead into a zone with no
  way out.
- **Exits** of interiors when the street confirms the interior. `triggers.xml` names no destination
  for a teleport volume, so the candidates are: the world's locations named after the volume; with a single exit, the
  world's locations named after the interior and each parent's location nearest its pad into the interior (within
  1000 units). A candidate counts only when its own wad names the interior (the full path, or the last path segment
  of 8 characters or more) and the interior has no pad into it (a child room). One such candidate is written; with
  several, the one nearest its pad into the interior; with none, the exit is withheld. An interior that other zones
  extend (`<path>_...`: gauntlet `_Sub` rooms, `_C02` variants) gets no exit, because its volumes lead on to the
  next room.
- **Exits** of any zone, streets and hubs included, that name their neighbour and that the neighbour names back. The
  trigger or volume name, read after its last `To` (or `_2_`), names a zone of the world: the text is the zone's name
  without world prefix and zone number (`To_Badlands` for `LM_Z04_Badlands`) or its end (`To_Hub` for
  `EM_Z00_Aeriel_HUB`), contains such a name of 4 characters or more, or is the numbered end of the zone's name
  (`To_80_03` for `KH_Gauntlet80_03`). A name with `From` names where one came from and counts for nothing. The
  neighbour confirms with an exit of its own that names the zone this way, or a location that contains the zone's
  name (`From_Mandoria`). The landing is the neighbour's one location containing the zone's name, else its location
  nearest the volume of its exit back (`volumes.xml`, within 1000 units). With no neighbour, several, or no landing,
  the exit is withheld. The interior rule above goes first.

`--review` prints what was held back, one line per trigger: zone, trigger, and the candidates (for an exit, the guess
of the single-zone rules above and each parent's `Start`; for a pad, why it was held). A person picks the destination
and writes the entry, by hand or with the single-zone mode.

`--dry-run` prints, per world: the zones, those already covered, those generated and their entries, the pads appended
to covered parents, the exits written, the pads and exits withheld, and the zones skipped because the wad has no teleport (`no teleport`)
or every teleport was withheld (`all withheld`).

A file name already taken by another zone gets the parent segments in front (`WizardZoneDatas_Interiors_<zone>.json`).

Checked against the 1406 zones the pack covers, regenerated as if absent: pads have no zone difference in the 213
entries the pack also has, and the 2 location differences are pads whose location the destination wad lacks, which
`--all` now holds back. The single-zone exit rules, measured the same way, pick a wrong zone in 24 of 144 volume-name
exits and 6 of 205 nearest-pad exits. The confirmed rule of `--all` places 244 of the 1860 covered exits the pack
defines and withholds 1616: 232 match the pack, 11 land beside the street's door into the interior where the pack
lands elsewhere in the same zone, and 1 (GH_Wolf_T1 `TeleportToWOLF`) goes to GH_Wolf, where the pack names
DragonSpire although the wad's own pad says GH_Wolf. The neighbour rule, measured the same way on its own, places 185
of those 1860 exits: 179 at the pack's spot (within 150 units) and 6 elsewhere in the right zone, none in a wrong
zone. With both rules, 405 are placed: 387 at the spot, 17 elsewhere in the right zone, and the GH_Wolf_T1 one. Of the
874 street and hub exits, 101 are placed, 11 of the 118 that lead to a hub, and none in a wrong zone.

`--check` lists the zones the quest templates send a player to (`m_destinationZone`, goal `m_zoneTag`, `ReqInZone`,
`ResAddDynaMod`) that have no ZoneTransfer file, then those that have one but no teleport leading into them.
`--check --all-zones` lists every client zone without a ZoneTransfer file, with a count per world.

### Location: name or coordinates

`m_destinationLoc` is either a location name or `x,y,z,direction`. The server passes it to the client unchanged, and
the client looks a name up in the destination zone's location list (`gamedata.bin`). The tool writes names, because the
wad gives them. Write coordinates only for a spot with no named location, as the shortest float32 text
(`484.1623,31.0982,1.989745,1.167386`), the same style as the entries captured from the live game.

## crownshop

Lists the crowns-only gear of the client's root wad (`ObjectData/CrownItems`, unpacked at `/kioxia/generator-input/rootwad`,
read-only) in the Gear tab, `CrownShop/Tab7.json`:

```sh
python3 -I tools/spiraltools.py crownshop --dry-run   # count the entries per category
python3 -I tools/spiraltools.py crownshop --apply     # append them to CrownShop/Tab7.json
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
`WAND_SURCHARGE` at the top of `crownshop.py`.

## quests

Writes a quest template and its drop table from one JSON spec per quest. The specs are JSON, not YAML, because the
standard library has no YAML parser:

```sh
python3 -I tools/spiraltools.py quests generate tools/quest-specs/celestia/*.json           # list what it would write
python3 -I tools/spiraltools.py quests check tools/quest-specs/celestia/*.json              # validate them against the client
python3 -I tools/spiraltools.py quests generate --apply tools/quest-specs/celestia/*.json   # write them
python3 -I tools/spiraltools.py quests diff tools/quest-specs/roundtrip/*.json               # compare with the pack's own templates
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
  `level`: `REWARD_BANDS` at the top of `quests/generate.py` (40 and up is Dragonspyre's 3805 XP and 103 gold).
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

`quests check` reports, per spec: a missing `WizQst<lang>.lang`, an empty `dialogs.prep` (no NPC would offer the quest), a
title or line key the lang files lack, a `loc` text ZoneLocName.lang lacks, a zone with no ZoneTransfer entry, and a
persona whose zone wad places none of the templates that carry it.

### Not generated

`quests diff` lists the fields where a generated template differs from the pack's. On the three WC quests in
`quest-specs/roundtrip` (built from the pack's own templates) the goals, goal logic, requirements, dialog keys and
speakers match; what differs is dialog presentation the client keeps nowhere a tool can read: sound files, cinematic
cameras, animations and music, the `m_nameSTKey`/`m_nameOverride` name format, per-line template ids, and `m_madlibs`
(the server builds the quest madlibs). The tool also writes Completion lines on the turn-in goal rather than at quest
level, an empty goal dialog list as `null`, and `m_bountyType`/`m_bountyTotal` where some captured quests omit them.

## archive

Builds questgen specs for a world from the Wizard101 Central wiki: the live wiki first, the Internet Archive's copies
when the live wiki refuses. Read-only GET requests, identified as `spiraltools/1.0 (+https://github.com/han-xyz/spiraldb)`:

```sh
python3 -I tools/spiraltools.py archive enumerate Celestia   # list the world's quests from the wiki's categories
python3 -I tools/spiraltools.py archive fetch Celestia       # download each quest page, live else archived
python3 -I tools/spiraltools.py archive parse Celestia       # write the specs, print what did not resolve
python3 -I tools/spiraltools.py quests check --world Celestia   # validate the specs
```

The live wiki is asked through its API first (`api.php?action=parse` for a page, `list=categorymembers` for a
category), then the page itself; robots.txt is obeyed, one request every two seconds (longer when robots.txt sets a
crawl delay), exponential backoff on 429 and 503. A 403, a challenge page or an outage is not retried: the rest of the
run goes to the archive. The archive is web.archive.org, one request a second, with exponential backoff on 429 and 5xx
for up to five minutes.

`--cache <dir>` holds the fetched pages, as `<timestamp>_<live|archive>_<page>.html` (the fetch time of a live page,
the capture time of an archived one; a name without a source is an archive capture), and the index
`index-<world>.json` (quest, first capture in the CDX index or `missing_snapshot`, zone categories, type). The default
is `.scratch/friends-server/task-A1/cache` in the checkout; the cache is not committed. A live copy in the cache is not
fetched again; a page with only an archived copy is asked of the live wiki, and the archived copy is kept when the live
wiki does not answer. The world comes from the registry ([Worlds](#worlds)): its ObjectData folder, quest lang cluster
and level.

`enumerate` walks `Category:<World>_Quests` and its subcategories, live or archived, and reads the CDX index of
`Quest:` pages. An archived category is the newest capture with status 200 in its CDX list that lists members (the
newest captures can be recorded refusals, served by the archive as a page of its own). A category with no answer is
reported; its quests still come in through the other categories. When the world's own category lists nothing (no
capture, or only refusals), `enumerate` walks `Category:<World>_<Storyline|Side|Instance>_Quests` instead and adds the
quests `Quest:<World>_Quest_Tree` links to; those entries have no zone (Polaris, Wallaru). `fetch`
takes the live page, else the newest capture, and the CDX timestamp when the newest capture is an error page; a quest
without a snapshot is fetched only live.

`parse` reads each page's Prequest, Given By, Giver Location, type sentence, Goals, Hand In and Reward, and resolves:

- the title to `lang` through `QuestTitle.lang`, compared without case, punctuation or a leading "The". Most Celestia
  quests keep their real title under a placeholder key (`QuestTitle_00000103`) and the internal name, or nothing, under
  the lang key; those are matched to a free `WizQst` file in three ways, each recorded with its evidence under `lang`
  in `needs_review`:
  - chain order: the quests of a chain hold consecutive keys, so the unmatched quests between two matched ones on the
    Prequest / Leads to chain take the free keys between those two, when there are exactly as many;
  - shared words: the rare words a key's lines share with the goal lines, one to one, and only when the best match
    clearly beats the second;
  - chain window: the only free key within `CHAIN_WINDOW` of a chain neighbour's key;
  - proper nouns: the free key, within `CHAIN_WINDOW` of a key of a quest of the same zone (a zone's quests hold a
    run of keys), whose lines share the most capitalised words with the page's goals, giver, hand-in and giver
    location, at least `MIN_PROPER_NOUNS` and more than any other key; words in more than a tenth of the world's
    quest files do not count, and a key two pages want goes to the higher score.

  Chain order and chain window keep a key only when its lines name the page's giver, hand-in NPC, or a goal NPC,
  creature or item.
- NPC names to personas as `npcs` lists them, mobs to their `.AdjRef` adjectives as `mobs` lists them, objects to the adjectives of the world's items (`items`) by display name, quest icon name or
  template name, read without the place, article, measure word ("Pieces of") or trailing number of the goal line, and item names to a line of the quest's own `WizQst` file. A named NPC template that no zone wad places takes
  the zones of an unnamed template with the same persona (Queen Calypso is placed as `CL-CalypsoReset`). A name the
  world's folder lacks is taken from the one world name close to it (`NAME_CUTOFF`; the wiki's Koltan Grimfane is
  Koltan Gloomfane), else from the other ObjectData folders, placed by every zone wad; a mob the world's folder lacks
  comes from the other folders too (the Spellwrit Wildclaws are in `PageEvent`), from the nearest one that has it:
  the registered worlds' folders by distance in the registry (Karamelle's Quake Charmer is Novus's, not Darkmoor's),
  then the rest. Each of these is listed in `needs_review` with the folder used. A title the wiki tagged with its
  world (`Monkey Business (Novus)`) is matched without the tag when nothing reads it whole.
- goal lines by their verb (`quests/goal_lines.py`): defeat-like verbs are bounty goals, talk-like verbs and person
  verbs with an NPC link (rescue, escort, find [NPC]...) persona goals, movement verbs (go, enter, explore, search,
  return, exit...) waypoints, everything else (collect, gather, use, examine, light, open, place, release,
  Photomance...) usage goals on the world's items. A hint in parentheses wins over the verb (`Locate (Collect) the
  Moon Relic` is a usage goal), notes in parentheses are not part of a name (`Dog of War (Balance)`, `Moo Bu (in
  Conatus)`), a use or defeat line repeated on consecutive lines is one goal with that count, and a header whose
  sub-items are goal lines or places (`Complete the following:`, `Explore:`) is one step of those goals. A place resolves to the zone path
  of its category,
  else to the world's one zone wad named for it (`the Drum House`: `ZF_Z10_I03_Drum_House`) when that zone has a
  ZoneTransfer file; a waypoint line naming one of the world's NPCs instead (`Go to Governor Nereus`) is a persona
  goal, and one that resolves to neither is left out and listed. A find-like line that names no item but a place is a
  waypoint. A defeat in a place with its own zone (`Defeat Morganthe (in Morganthe's Chamber)`) sends the player
  there.
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

Each spec carries `source` (page, `live` or `archive`, and the timestamp) and `needs_review`: what did not resolve,
`blocking` or not. A spec with a blocking gap goes to `quest-specs/<world>/blocked/`, where the questgen glob does not
reach; a waypoint whose place has no zone path is left out and listed. A spec for a lang that a hand-authored spec
already covers is written to `<cache>/reference-<world>/` instead, and the differences are printed. A rerun replaces the specs it wrote before.

## mobs and npcs

The lookups a spec needs, from the root wad's object templates (`ObjectData/<folder>`, a world's mobs and NPCs) and
the zone wads:

```sh
python3 -I tools/spiraltools.py mobs   # CL: display name, template, template id, adjectives
python3 -I tools/spiraltools.py items Celestia   # display name, quest icon name, template, template id, adjectives
python3 -I tools/spiraltools.py npcs   # CL / Celestia: persona, name, template id, portrait, zones
python3 -I tools/spiraltools.py npcs --folder WC --world WizardCity
```

A bounty goal counts a defeated mob once for each of its adjectives in `mobs`, so name one adjective per mob: its
own `<template>.AdjRef`. A shared adjective (`Crustacean_Pincer`, `MONST_Fish`) catches every template that has it.
A usage goal's `items` are adjectives of `items`: the world's object templates with an adjective that the player
interacts with or whose display name is not a mob's (`CL-TeslaTower.AdjRef`, a Galvanic Tower), the pattern of the
pack's `m_itemAdjectives`. A persona goal's `persona` is the persona without `_Persona`; the zones column is where to send the player:
the zones whose wad names the template or places an object by its template id (Zaltanna the Mirrormask in
`KR_Z00_Hub`).

## Authoring a world by hand

1. List the world's quests: `QuestTitle.lang` keys next to `WizQst<hex>.lang` files, and the zone wads' quest names.
2. For each quest, read its `WizQst<hex>.lang` and order the lines: the offer (Prep), the reminder (Underway), the
   turn-in (Completion), and which persona says each.
3. Take givers, turn-in NPCs and their zones from `npcs`, and mob adjectives and name keys from `mobs` and
   `WizardMobs.lang`.
4. Write the spec, run `quests check`, then `quests generate --apply`. A zone the check reports without
   ZoneTransfer is added with `zones`.

The client does not hold quest order and prerequisites, goal sequence, counts beyond what the lines say, rewards,
or which NPC says a line; those come from a walkthrough. `quest-specs/celestia` is the Survey Camp pilot.
