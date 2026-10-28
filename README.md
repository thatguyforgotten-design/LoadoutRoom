# Loadout room1.0

A Windows desktop companion for browsing your VALORANT match roster, player statistics, and equipped weapon skins in one window. No browser page or command window is needed.

[Download the latest desktop release](https://github.com/thatguyforgotten-design/LoadoutRoom/releases/latest)

## What the app does

- Shows up to 10 players in a compact selector at the top, with names coloured to match their agents.
- Displays current rank, recorded peak rank, visible account level, RR, win rate, and games played when data is available.
- Lets you select a player to browse their equipped weapon skins, variants, and gun buddies.
- Includes weapon filters, skin search, team filters, Refresh match, and Keep on top.
- Shows Blue and Red team average player win rates, with unavailable players excluded.
- Loads selected-player headshot percentage from up to 10 recent completed Competitive matches in the background.
- Uses agent names for hidden players and respects hidden account levels.
- Includes an offline Show sample mode for previewing the interface. Sample artwork is illustrative.
- Checks for published updates and asks permission before downloading and installing a newer version.

## Install and use

1. Open [Releases](https://github.com/thatguyforgotten-design/LoadoutRoom/releases/latest) and download **Loadout-room1.0-Desktop.zip** under Assets.
2. Extract the entire ZIP into a fresh folder.
3. Open **LoadoutRoom1.0.exe**. Keep the `app` and `runtime` folders beside it. Python is bundled.
4. Open VALORANT, sign in through Riot Client, and join a match.
5. Select a player at the top to view their equipment and available statistics.

Use **Show sample** to try the layout without a live match. Agent select may only provide your own team and may not include equipped weapons.

## Updates

Open **Updates → Save and check** to check immediately. Startup checks can be switched off in the Updates window. Each installation asks permission, verifies the ZIP checksum, installs a separate copy, and restarts the app. The previous installation is retained.

Versions older than 1.0.14 may need a fresh download to connect to this repository automatically.

## Understanding the statistics

| Statistic | Meaning |
| --- | --- |
| Player win rate | Wins divided by games in the current act’s Competitive data. |
| Team win rate | Unweighted average of available player win rates. This is not a prediction of who will win. |
| Peak rank | Highest rank found in the available recorded act history. Missing or ambiguous history is not guessed. |
| HS% | Head hits divided by head + body + leg hits across up to 10 recent completed Competitive matches. This is not a lifetime or live-match percentage. |
| N/A / Unavailable | Data is missing, inaccessible, or insufficient to calculate the statistic. |

## Privacy and connection

The app uses the already signed-in local Riot Client. It does not ask for your Riot password or save login tokens. Hidden player names are not looked up through the name service. Remote requests retain HTTPS certificate verification; the local Riot Client uses its self-signed connection.

Live data depends on what Riot makes available. Live match and headshot-history access still need validation in-game; game updates may change availability.

## Troubleshooting

- **No roster:** keep VALORANT open and signed in, join a match, then choose Refresh match.
- **Missing weapons or artwork:** data may not be available yet. Artwork failures show as unavailable.
- **Missing HS%:** select the player and allow time for history to load. Restricted or zero-hit history shows N/A.
- **App will not start:** extract the complete ZIP to a fresh folder and run the EXE from there.

## Credits

This project is a modified version of the original [VALORANT-rank-yoinker](https://github.com/zayKenyon/VALORANT-rank-yoinker) created by [@zayKenyon](https://github.com/zayKenyon). All original code credit goes to him and his contributors.

Warden fallback metadata and artwork: [valorant.gs](https://valorant.gs/weapons/warden/). Public game catalog: [VALORANT-API](https://valorant-api.com/). Original project and dependency licenses are included in the desktop ZIP.

Unofficial fan project. Not affiliated with or endorsed by Riot Games.
