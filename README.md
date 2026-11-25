# MVSDsion

MVSDsion gives your weapons new looks in the Roblox game
[Murderers VS Sheriffs Duels](https://www.roblox.com/games/12355337193/). Pick a skin, turn it on,
and you see it in the game. Only you see the skins – other players still see
the normal weapons.

New skins are added online, so they show up in the app by themselves. You do
not need to download a new version for them.

## What you can do

- **Use skins** – browse all skins with a picture and a short description,
  turn them on or off with one click, search them, and pin your favourites
  to the top.
- **Choose which weapon gets the skin** – some weapons come in several
  versions in the game (for example different colors). Click the small
  picture in the top-left corner of a skin to choose which version it
  replaces.
- **Paint your own colors** – pick any color for a weapon, see it on a 3D
  model right away, and use it in the game just like a skin.
- **Play smoother** – optional game settings, such as a higher FPS limit.
- **Switch Roblox accounts** – change which Roblox account this PC plays
  with.

Some skins are free, others you can buy. Bought skins are linked to your
User ID, so they stay yours.

## Install

1. Download the newest `MVSDsion-…-Windows.exe` from
   [Releases](../../releases).
2. Open it. The first time, Windows may say the app is from an unknown
   publisher: click **More info → Run anyway**.
3. Want to buy skins? Copy your **User ID** in the app (Settings) and send it
   to the owner.

## How to use it

1. Open MVSDsion and press **Sync** at the bottom to load the newest skins.
2. Click **Enable** on the skins you want.
3. Close Roblox, press **Clear Cache** at the bottom, then start Roblox and
   join MVSD. Keep MVSDsion open while you play.

### A skin does not show up?

- **Close Roblox Studio** if it is open, then press **Clear Cache** again.
  While Studio is open, Roblox keeps using the old weapon looks.
- **Sign in again under Accounts.** Some skins only load when your Roblox
  login on this PC is still valid.
- **Check which weapon you use in the game.** A skin only shows on the
  weapon version you chose with the small picture on the skin.

## Build from source

Requires [uv](https://docs.astral.sh/uv/) and, for the fast launcher,
[Rust](https://rustup.rs).

```powershell
uv sync
uv run --frozen python scripts/build_launcher.py
```

The exe is written to `dist/`. Every push to `main` also builds the app on
GitHub Actions (without the Rust launcher).

## Credits and license

MVSDsion is a fork of [Fleasion](https://github.com/fleasion/Fleasion) by its
authors and contributors, used under the GNU General Public License v3.0. The
MVSDsion changes are released under the same license; see [LICENSE](LICENSE).
