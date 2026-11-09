# LAST ARMORY

**Build guns. Sell guns. Survive outside.**

A first-person, multiplayer gunsmith game set in a zombie-apocalypse outpost. There are no bots: just you, your friends, the townspeople and the dead.

### Your gun shop (the town is a safe zone)
- Every player owns a shop on the same town square.
- **Supplier terminal:** buy parts, Common to Legendary. **The stock changes every time you walk to the middle of town and come back.**
- **Workbench:** assemble a gun from a receiver, barrel and magazine, plus an optional stock, grip, scope, muzzle and bayonet. There are no compatibility rules, so any part fits any gun.
- **Cleaning bench:** fresh guns come out grimy, and firing dirties them further. Dirty guns jam, shoot wider and sell for less, and customers refuse anything under 30%. Cleaning is a scrub minigame that uses a cleaning kit: click the grime before it spreads, and missed clicks waste the kit.
- **Shelves:** price your guns yourself. Townspeople have real money now:
  - They buy something **80% of the time**.
  - When a gun matches what they want ("wants LONG RANGE"), they **always** buy it, even above their stated budget.
- **Bed:** your energy drains through the day. Tired means slower movement and shaky aim, so **sleep** in your shop's bed.
- **Upgrade board:** display racks, decor, sign, pro workbench, and an armor locker (free shields every morning).
- **Rivals:** walk into another player's shop and buy their guns off the shelf.

### The market (town square)
- **Ma's Diner:** food (a hunger meter drains, and starving hurts) and coffee/energy drinks.
- **Field Clinic:** bandages and medkits.
- **Ironside Supply:** light (25) and heavy (50) shields, and cleaning kits.
- **The Collector:** posts **special orders** every morning, such as "full-auto, magazine 27+, recoil 0.3 or less". Build a gun that meets every requirement, hold it, and deliver it for a big payout (often $900-1500+). Only the first gunsmith to deliver gets paid.

### Outside (zombies + PvP)
Walk to a town gate to go out into the wasteland.
- Zombies roam there all the time, with more and tougher ones at night. Kills pay cash.
- Supply crates hold parts, cash and items.
- **Supply drops:** every few minutes a crate parachutes into the wasteland, marked by an orange smoke beam you can see from anywhere. It holds 2 rare parts, cash, a heavy shield and a medkit. Everyone is told when one falls, so expect a fight over it.
- **Blood Moon:** every 3rd night (and the last night) the sky turns red, zombies swarm in far greater numbers, and every zombie kill pays double.
- **PvP is only on while 2 or more players are outside.** A kill loots 25% of the victim's cash.
- Damage works like Valorant: you have 100 HP plus shields, and shields soak damage first. Rifles do 40 to the body and 160 to the head (a one-tap even through heavy shields); the revolver, marksman and railgun one-shot heads too, while pistols and SMGs need more hits. Legs take 85%.

A day lasts 6 minutes plus a 3-minute night, and there are no customers at night. After the last day (5 by default), **the richest gunsmith wins.**

## Controls
| | |
|---|---|
| WASD / Space | move / jump |
| Mouse | look, left click shoot, right click aim |
| E | use (workbench, supplier, cleaning bench, bed, shelves, stalls, gates, crates) |
| I | inventory |
| H / G | quick-use: heal / eat |
| F (or middle mouse) | bayonet stab |
| R | reload (also clears a jam) |
| 1-6 | switch which gun you hold |
| Tab | cash leaderboard |
| Enter / T | chat |
| Esc | close a window / pause menu (mouse, FOV, volume) |
| F11 | fullscreen |

## Install and play
### Windows
Unzip `LastArmory-Windows.zip` and run **LastArmory.exe**. Click **Play** to host your own town; friends join with your address.

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
| pvpMinPlayers | 2 | players outside needed for PvP |
| airdropMinutes | 3 | average minutes between supply drops (0 = off) |
| bloodMoonEvery | 3 | every Nth night is a Blood Moon, plus the last night (0 = off) |
| contracts | 2 | Collector special orders posted each morning |
| days | 5 | |
| dayMinutes / nightMinutes | 6 / 3 | |
| outside | "" | wasteland arena id |
| startCash | 400 | |
| town, arenas | | pick by id (empty = default / all) |
| disabledMods | [] | |

Flags: `--port --name --days --day-minutes --night-minutes --config`

Server console: `help, say, list, kick, givecash <name> <n>, days <n>, skipday, reload, quit`

## Modding
Everything is JSON in `mods/`: gun parts (real gun models or box models), upgrades, customer types, zombie types, the town, the shop layout and night arenas. Gameplay scripting is Python. Players install nothing, because the server sends its content when they join. See **[MODDING.md](MODDING.md)** and `mods/example_mod`.

Built with Python and [Panda3D](https://www.panda3d.org), using free CC0 3D models (see Credits) and synthesized sounds. An original game inspired by the gun-shop simulator genre.

## Credits
Building textures: [ambientCG](https://ambientcg.com) photo-scanned materials (CC0); rebuild them with `python tools/convert_materials.py`. 3D models: Quaternius (Zombie Apocalypse Kit, Ultimate Gun Pack, Universal Base Characters, Universal Animation Library 1 & 2) and Kenney (Furniture Kit), all CC0 / public domain. Licence files are in `mods/core/models/`. To rebuild the models from the original packs, put the zips in `assets_src/` and run `python tools/convert_assets.py`, `python tools/convert_characters.py` and `python tools/make_outfits.py` (needs `pip install panda3d-gltf pillow`; the game itself needs neither).
