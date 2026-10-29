# LoadoutRoom

A small Windows app for checking the skins and stats of players in your VALORANT match. Everything is in one window, so you don’t need to keep a browser or command prompt open.

[Download here](https://github.com/thatguyforgotten-design/LoadoutRoom/releases/latest)

## What’s in it

- Player loadouts, skin variants and gun buddies
- Current rank, recorded peak rank, level and RR
- Player win rates and team averages
- Headshot % from up to 10 recent Competitive matches
- Agent-coloured names, with hidden names shown as their agent
- Search, weapon filters and a keep-on-top option
- Installed version shown in the bottom-right corner
- Updates through the app, with permission before installing

## How to use it

1. Download **LoadoutRoom-v1.0.20.zip** from the latest release.
2. Extract the whole ZIP into a folder.
3. Open **LoadoutRoom.exe**. Leave the `app` and `runtime` folders next to it.
4. Open VALORANT and join a match, then click a player to see their loadout.

Python is included. You can also click **Show sample** to look around without joining a match.

For updates, open **Updates → Save and check**.

## A few things to know

Win rates are for the current Competitive act. The team number is an average of available players, not a prediction. Peak rank comes from the history available to the app, and HS% is based on recorded hits in recent matches.

Some stats or skins might be unavailable. If something shows N/A, the app couldn’t get enough data. Live match and history access still need testing in-game.

The app uses your signed-in Riot Client. It doesn’t ask for your Riot password, and hidden names and levels stay hidden.

## Credits

This project is a modified version of the original [VALORANT-rank-yoinker](https://github.com/zayKenyon/VALORANT-rank-yoinker) created by [@zayKenyon](https://github.com/zayKenyon). All original code credit goes to him and his contributors.

Warden data and artwork from [valorant.gs](https://valorant.gs/weapons/warden/). Game catalog from [VALORANT-API](https://valorant-api.com/). Licenses are included in the download.

Unofficial fan project. Not affiliated with Riot Games.

## Running from source

Install Python with Tk support, then run `python -m pip install -r requirements.txt` and `python app/desktop.py`.

The `app/` and `source/` folders contain the v1.0.20 application and launcher source. The ready-to-run Windows app, bundled Python, and dependency licenses are in the release ZIP.
