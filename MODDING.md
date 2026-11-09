# Modding LAST ARMORY

A mod is a folder in `mods/`. Everything is JSON plus optional Python, and there's nothing to compile.

```
mods/my_mod/
  mod.json          required
  parts/*.json      gun parts (with box models)
  upgrades/*.json   shop upgrades
  customers/*.json  what townspeople want
  zombies/*.json    zombie types
  towns/*.json      town layouts (plots for shops)
  shops/*.json      the shop interior template
  arenas/*.json     the wasteland outside town
  items/*.json      food, medicine, shields, tools sold at market stalls
  patches.json      tweak anything existing
  server.py         gameplay scripting (server only)
```

**Mods run on the server.** On join, the server sends players every part, upgrade, customer type, zombie type, town, shop and arena, so players install nothing. Only `server.py` executes code, and only on the server, which makes joining modded servers safe.

To test changes, type `reload` in the server console. Errors show in the console and on the main menu. Copy `mods/example_mod` to get started.

## mod.json
```json
{ "id": "my_mod", "name": "My Mod", "version": "1.0", "description": "...", "enabled": true, "loadOrder": 100 }
```
Mods load in `loadOrder` order (core = 0). If two mods use the same id, the later one wins.

## Parts
```json
{ "id": "my_scope", "slot": "sight", "name": "Sniper Scope", "tier": 3, "price": 200,
  "description": "...", "set": {}, "add": { "zoom": 3 }, "mul": { "spread": 0.5 },
  "model": [ { "p": [0, 0, 0.04], "s": [0.04, 0.25, 0.04], "c": "#222222" } ] }
```
- **slot:** `receiver`, `barrel`, `magazine` (these three are required), plus `stock`, `grip`, `sight`, `muzzle`, `bayonet`.
- **tier** 0-4 sets the rarity (Common to Legendary). Rarer tiers appear more often on later days, and the default price comes from the tier (20/45/90/170/320). Set **price** to override it.
- **start: true** puts the part in every player's starting kit.
- **extends** copies another part (your fields override it), and **hidden: true** removes a part.
- **short** is the short name used in auto-generated gun names (receivers).

**Stats:** first the receiver's `set`, then every part's `add`, then every `mul`, then clamping.
`damage, fireRate, auto, pellets, spread, recoil, range, magSize, reloadTime, moveSpeed, headshot, zoom, explosionRadius, melee`.
Custom stats are allowed and can be read from `server.py`.

**Models:** boxes with `p` = centre, `s` = size and `c` = colour, in metres. The gun points along **+Y** and **+Z** is up.
The receiver's origin is its back end. Its `length` and `mounts` (`barrel, stock, magazine, sight, grip`) say where the other parts attach.
The barrel extends +Y from its mount, and its `length` places the muzzle. The bayonet hangs under the muzzle, the stock goes at −Y, the magazine hangs down (−Z) and the scope sits on top (+Z).

**Value:** a gun's worth is the sum of its part prices, plus 5% per optional part.

## Upgrades
```json
{ "id": "vault", "name": "Vault", "description": "...",
  "levels": [ { "cost": 300, "effects": { "shelves": 1 } }, { "cost": 700, "effects": { "attract": 2 } } ] }
```
Built-in effect keys: `shelves`, `attract` (decor), `signs`, `disassemble`, `stock` (extra supplier offers), `discount` (%), `maxHp` (night).
Any other key is a **custom effect**: read it in `server.py` with `api.game.effects(player)["yourKey"]` (see the example mod's `zombieBounty`).

## Customers
```json
{ "id": "sniper_fan", "label": "A SNIPER", "stat": "range", "ref": 80, "weight": 5, "lower": false }
```
A customer values a gun at `worth × (0.75 + 0.45 × match)`, where `match = stat / ref` (or `ref / stat` when `lower` is true), clamped between 0.3 and 2.2. They buy the best deal that fits their budget, as long as the price is under about 1.0-1.3× that value.

## Zombies
```json
{ "id": "screamer", "name": "Screamer", "hp": 80, "speed": 4, "damage": 15, "reward": 30, "weight": 4, "minDay": 2,
  "color": "#9a4f4f", "scale": 1.1 }
```

## Towns and shops
- **Town:** `size`, `boxes` (static props and walls), `plots` (`x`, `y`, `rot` in 0/90/180/270), `gates` (where customers come from), `plaza`, plus colours (`groundColor`, `skyColor`, `fogColor`, `lightColor`, `ambient`) and `roads` (decoration).
- **Shop template:** uses local coordinates, with the door at y=0 and the interior at +y. It contains `boxes`, `door`, `browse` (where customers stand), `spawn [x, y, heading]`, `workbench`, `terminal`, `board`, `shelves [[x, y, z, heading]...]`, `targets`, `decor` (box lists per upgrade level), `sign`, `awning` and `signText`. Optional service window: `service` (where the owner presses E), `serviceSpot` (where clients queue outside) and `serviceSign` (`[x, y, z]` of the GUN CLEANING sign).

## Arenas (night)
`size`, `boxes` (`x y z w d h color`, min corner), `spawns [[x, y, z, heading]]`, `zspawns [[x, y]]`, plus colours and `fogDensity`.

## Materials (what walls look like)
Any box can pick a texture with `"mat"`: `brick`, `plaster`, `concrete`, `corrugated`, `metal`, `siding`, `planks`, `roof`, `asphalt` or `paving`, plus an optional `"tint": "#rrggbb"`. Textures repeat every couple of metres instead of stretching, so a 100 m wall looks as sharp as a crate. Boxes without `"mat"` get one guessed from their `color`. Towns and arenas pick their floor with `"groundMat"`.
Add your own material by dropping `<name>_color.jpg` and `<name>_normal.jpg` (OpenGL normal map) into your mod's `models/materials/`, with an optional `materials.json` like `{"<name>": {"tile": 2.5}}` (metres per repeat).

## patches.json
```json
{ "rcv_railgun": { "price": 500 }, "decor": { "levels": [ { "cost": 50, "effects": { "attract": 3 } } ] }, "brl_twin": { "hidden": true } }
```

## server.py hooks (all optional)
```python
def on_load(api)                              # register /commands here
def on_player_join(api, player) / on_player_leave(api, player)
def on_day_start(api, day) / on_night_start(api, day) / on_phase(api, phase)
def on_customer(api, customer)                # dict: name, pref, budget, tol ... edit freely
def on_sale(api, seller, buyer_name, gun, price)
def on_craft(api, player, gun)
def on_damage(api, event)                     # victim, attacker, amount, head, cancel
def on_contract(api, player, contract)        # a Collector order was filled
def on_service(api, player, client, success)  # a service-window cleaning job ended
def on_kill(api, victim, killer)
def on_zombie_kill(api, zombie, killer)
def on_tick(api, dt, phase)
def on_chat(api, player, text)                # return True to swallow it
def on_match_end(api, winner)
```
**api:** `players()`, `get_player()`, `broadcast()`, `tell()`, `give_cash(player, n, why)`, `give_part(player, id)`, `damage()`, `heal()`, `spawn_zombie(type, x, y)`, `command(name, help)`, `log()`, plus `day`, `phase`, `config`, `content` and `game` (full server access).
**player:** `name, cash, parts, guns, shelf, upgrades, stats, hp, alive, kills, zkills, speed_mul, damage_mul, data`.

A crashing hook is logged and ignored.

## 3D models
Put models in `mods/<your_mod>/models/` as `.bam`, `.gltf`/`.glb` or `.obj`, and refer to them by path without the extension (e.g. `props/MyCrate`). The core models came from free CC0 packs and were converted with `tools/convert_assets.py`.
- **Gun receivers:** `"meshes": ["AssaultRifle_1", "AssaultRifle_2"]` uses real gun models from `models/guns/`. The barrel, magazine and stock pick which variant shows, while the scope, muzzle, grip and bayonet still attach visibly. `"meshScale"` and `"tint"` are optional.
- **Zombies:** `"mesh": "zombies/basic"` (animated: Walk, Run_Arms, Idle_Attack, Death).
- **Props** (in towns, shops, arenas and shop decor levels): `{"mesh": "props/Barrel", "x": 10, "y": 5, "z": 0, "h": 90, "s": 1.0, "tint": "#ffffff", "collide": [0.7, 0.7, 1.1]}`. `collide` adds a solid box that the server also uses.
- **Boxes:** add `"mesh"` to show a model stretched to fill the box (e.g. containers), or `"invisible": true` to keep only the collision.

If a player is missing a model that a server references, the game draws the box version instead, so nothing breaks.

## Items and market stalls
```json
{ "id": "burger", "name": "Wasteland Burger", "kind": "food", "value": 70, "energy": 5, "price": 28 }
```
Kinds: `food` (+hunger), `drink` (+energy), `heal` (+health), `armor` (shields, worn on purchase, max 50), `tool` (`cleaning_kit` cleans one gun).
Stalls are listed in the town JSON: `"vendors": [{"id", "name", "kind", "x", "y", "h", "color", "items": [ids]}]`. A stall with `"kind": "collector"` is where players deliver the Collector's special orders.

## The wasteland (`arenas/*.json`)
Besides `boxes`/`props`/`spawns`/`zspawns`: `entry` (where players arrive), `exits` (walk here and press E to go back to town), `loot` (supply crate spots), plus `day` and `night` colour sets. Choose which arena is outside with `"outside"` in `server_config.json`.

## Damage
Guns use Valorant-style numbers: `damage` is body damage, `headshot` is the head multiplier, and legs take 85%. Players have 100 HP plus up to 50 shields, which absorb damage first. More hooks: `on_zone(api, player, zone)` and `api.give_item(player, id)`.
