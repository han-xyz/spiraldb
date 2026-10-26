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
python3 -I tools/zone-transfer-from-wad.py --all --dry-run                             # per-world counts for every client zone
python3 -I tools/zone-transfer-from-wad.py --all --world Celestia --apply              # write one world
python3 -I tools/zone-transfer-from-wad.py --check --all-zones                         # client zones still without a file
```

`--gamedata <dir>` points at another client install. A bare `--street` must come after the zone paths.

What it emits, from `gamedata.bin` and `triggers.xml` of the zone's wad:

- **Pads and sigils** in the zone: an object whose teleport behaviour names a zone, the zone itself included (a
  teleport within the zone). `TriggerName` is the object name, the location is the pad's own destination location, or
  `Start` when the pad has none.
- **Exits**: a trigger fired by `Enter_TeleportVol_<volume>`. The client keeps no destination for these, so the tool
  picks, in order: the one zone of the world that has a location named `<volume>`; the one location of the world named
  after the zone (`GH_Hero_T2` matches `FromHeroT2`); the parent's location nearest the pad into the zone, within 1000
  units; else the parent's `Start`. The parent is the zone whose pad leads here, or the `--street` zone. The last three
  rules need a single exit and a single parent. Anything else is skipped and listed on stderr.
- **Inbound** (`--street`): the street's pads into the zone, else the street's triggers fired by `Enter_<location>`
  where `<location>` is a location of the zone (the door volumes of houses).

`--apply` is append-only: an entry whose `TriggerName` the file already has is left as it is, and nothing is removed.
A zone without a file gets `ZoneTransfer/WizardZoneDatas_<last path segment>.json`.

### Every client zone: `--all`

`--all` takes every wad of `Data/GameData` that holds a `gamedata.bin` (3356 in the current client) as a zone, whose
path is the wad name with `-` read as `/` (`Celestia-Interiors-CL_Z09i1_Science_Center.wad` is
`Celestia/Interiors/CL_Z09i1_Science_Center`). A zone that already has a ZoneTransfer file is left alone. Every other
zone gets its pads, sigils and exits by the rules above, the parents being the zones of the same world whose pads lead
into it; a parent that has a file gets those pads appended. `--world <World>` (repeatable) limits the run to one world.

`--dry-run` prints, per world: the zones, those already covered, those generated and their entries, the pads appended
to covered parents, and the zones skipped because the wad has no pad or teleport volume (`no teleport`) or because no
exit resolved and the zone has no pad (`exits unresolved`). The notes on stderr name each skipped exit and each exit
placed by nearest pad or `Start`.

A file name already taken by another zone gets the parent segments in front (`WizardZoneDatas_Interiors_<zone>.json`).

Checked against the 1406 zones the pack covers, regenerated as if absent: pads matched in 211 of 213 entries the pack
also has, exits by nearest pad in 189 of 205, exits by volume name in 118 of 144 (the misses are mostly street exits
whose volume name is also a location of the hub), and the `Start` fallback reached the right zone in 8 of 8 but the
right spot in 1. Most zones still skipped are reached only by quest scripts or other worlds: nothing in the world's
wads leads into them, so their exits have no parent.

`--check` lists the zones the quest templates send a player to (`m_destinationZone`, goal `m_zoneTag`, `ReqInZone`,
`ResAddDynaMod`) that have no ZoneTransfer file, then those that have one but no teleport leading into them.
`--check --all-zones` lists every client zone without a ZoneTransfer file, with a count per world.

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
