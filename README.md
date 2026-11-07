# LAST ARMORY

**Build guns. Sell guns. Survive the night.**

A first-person, multiplayer gunsmith game set in a zombie-apocalypse outpost.

### Day: run your gun shop
- Every player owns a shop on the same town square.
- **Supplier terminal:** buy parts from today's stock. Rarity runs Common → Uncommon → Rare → Epic → Legendary, and better stock shows up as the days go on.
- **Workbench:** assemble a gun from a receiver, barrel and magazine, plus an optional stock, grip, scope, muzzle and bayonet. There are no compatibility rules, so any part fits any gun, and the gun builds up in 3D as you go.
- **Shelves:** put guns on display at your own price. Townspeople walk in with a budget and a wish ("wants LONG RANGE", "wants A BAYONET"...). They buy if the gun suits them and the price is fair, and pay a premium when it matches what they want.
- **Upgrade board:** buy display racks, cozy decor, a shop sign, a pro workbench (scrap guns back into parts, supplier discount) and night armor.
- **Shooting range:** test your guns on the targets at the back of your shop.
- **Rivals:** walk into another player's shop and **buy their guns off the shelf**.

### Night: PvP raid
Everyone grabs the gun they're holding and heads into the wasteland.
- Zombies attack in waves, and killing them pays cash.
- Rival gunsmiths are fair game: a kill **loots 25% of their cash**.
- The last one standing earns a **$250 bounty**.

After the final day (5 by default), **the richest gunsmith wins.**

## Controls
| | |
|---|---|
| WASD / Space | move / jump |
| Mouse | look, left click shoot, right click aim |
| E | use (workbench, supplier, shelves, upgrade board, rival shelves) |
| F (or middle mouse) | bayonet stab |
| R | reload |
| 1-6 | switch which gun you hold |
| Tab | cash leaderboard |
| Enter / T | chat |
| Esc | close a window / pause menu (mouse, FOV, volume) |
| F11 | fullscreen |

## Install and play
### Windows
Unzip `LastArmory-Windows.zip` and run **LastArmory.exe**. Click **Quick Play** to get a game with bots.

### macOS
See **[mac/README-mac.md](mac/README-mac.md)**. The short version: double-click **Play.command**, which installs Panda3D the first time and starts the game. You can also build a real **LastArmory.app** with `mac/build_mac_app.sh`.

### From source (any OS)
```bash
python3 -m pip install panda3d
```
```bash
python3 LastArmory.py
```

## Hosting
- **In game:** Host Server, then Start & Join. Friends join with your IP (port **27030** TCP; forward it on your router for internet play).
- **Dedicated (any OS, no graphics needed):** `python3 ArmoryServer.py`, `ArmoryServer.exe`, or `LastArmory --server`.

`server_config.json`:

| key | default | |
|---|---|---|
| name, motd | | |
| port | 27030 | |
| maxPlayers | 8 | one shop per player (8 plots in the default town) |
| password | "" | |
| minPlayers / bots / botSkill | 4 / true / 0.5 | bots run shops too |
| days | 5 | |
| daySeconds / nightSeconds | 180 / 100 | |
| startCash | 400 | |
| town, arenas | | pick by id (empty = default / all) |
| disabledMods | [] | |

Flags: `--port --name --min-players --no-bots --days --day-seconds --config`

Server console: `help, say, list, kick, skip, givecash <name> <n>, days <n>, minplayers <n>, bots on|off, reload, quit`

## Modding
Everything is JSON in `mods/`: gun parts (with box models), upgrades, customer types, zombie types, the town, the shop layout and night arenas. Gameplay scripting is Python. Players install nothing, because the server sends its content when they join. See **[MODDING.md](MODDING.md)** and `mods/example_mod`.

Built with Python and [Panda3D](https://www.panda3d.org). Everything is made from boxes and synthesized sounds, so there are no asset files. An original game inspired by the gun-shop simulator genre.

## Credits
3D models: Quaternius (Zombie Apocalypse Kit, Ultimate Gun Pack) and Kenney (Furniture Kit), all CC0 / public domain. Licence files are in `mods/core/models/`. To rebuild the models from the original packs, put the zips in `assets_src/` and run `python tools/convert_assets.py` (needs `pip install panda3d-gltf`).
