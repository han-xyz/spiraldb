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
