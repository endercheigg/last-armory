# LAST ARMORY on macOS

## Play (easiest)
1. Double-click **Play.command**.
   - The first time, macOS may say it's from an unidentified developer. **Right-click Play.command, choose Open, then Open** (you only have to do this once).
   - If you don't have Python 3, it opens python.org so you can install it. Then double-click Play.command again.
   - The first launch installs the Panda3D engine (about a minute, needs internet). After that it starts straight away.
2. Click **Quick Play** to start a game with bots, or **Join Server** to play with friends on Windows or Mac. Everyone uses the same servers.

## Make a real LastArmory.app
On your Mac, in Terminal:
```bash
cd path/to/LastArmory-Mac
```
```bash
bash mac/build_mac_app.sh
```
You get `dist/LastArmory.app` and `dist/LastArmory-macOS.zip`. The app is ad-hoc signed, so the first time you (or friends) open it: **right-click, Open, Open**. If macOS says it's "damaged" (this happens to downloaded unsigned apps), run:
```bash
xattr -dr com.apple.quarantine /Applications/LastArmory.app
```

**No Mac to build on?** Push this folder to GitHub. The included workflow (`.github/workflows/build.yml`) builds the Mac app (Apple Silicon and Intel) and the Windows exe automatically. Download them from the run's "Artifacts".

## Host a server on a Mac
- **In the game:** Host Server, then Start & Join.
- **Dedicated:** double-click **HostServer.command** (or run `python3 ArmoryServer.py`). It needs no extra installs, just Python 3. Friends connect to your IP on port **27030**. macOS will ask to allow incoming connections; click Allow.

## Where things are saved
Settings, generated sounds and the hosted server's log are in `~/Library/Application Support/LastArmory`.

## Mods
With Play.command, put mods in the `mods/` folder next to it. Inside the built .app, mods live in `LastArmory.app/Contents/Resources/mods` (right-click the app, Show Package Contents). Remember that mods only need to be on the **server**.

## Black screen or crash on start?
Older Macs might not support the high-quality lighting. Start in compatible mode (simpler lighting, no shadows):
```bash
./Play.command --compat
```
Or switch **Settings, Graphics** to Compatible. The setting is remembered.
