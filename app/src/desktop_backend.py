"""Background collector for the native desktop app. No console, browser or local server."""
import base64
import queue
import json
import os
import re
import threading
import time
from pathlib import Path
import requests
from src.catalog import (public_catalog, merge_weapons, normalize_id, resolve_weapon,
                         WARDEN_ID, WARDEN_SKINS)
from src.desktop_stats import competitive_stats, visible_identity, team_summary, headshot_stats


class NotReady(Exception):
    pass


def read_connection_info(log_path):
    """Keep startup version metadata as well as recent region endpoints."""
    try:
        with Path(log_path).open("rb") as handle:
            startup = handle.read(1_000_000)
            handle.seek(0, 2)
            end = handle.tell()
            # Avoid overlapping/duplicating a short log. Both sections belong
            # to the same open file, so a rotated log cannot mix sessions.
            handle.seek(max(len(startup), end - 8_000_000))
            recent = handle.read(8_000_000)
        log = (startup + b"\n" + recent).decode("utf-8", errors="replace")
    except OSError:
        raise NotReady("VALORANT logs are not ready. Reach the main menu first.")
    pd = re.findall(r"https://pd\.([a-z0-9-]+)\.a\.pvp\.net", log)
    glz = re.findall(r"https://glz-([a-z0-9-]+)\.([a-z0-9-]+)\.a\.pvp\.net", log)
    versions = re.findall(r"CI server version:\s*([^\r\n]+)", log)
    if not glz or not versions:
        raise NotReady("Waiting for VALORANT's region and version information in its logs.")
    region = pd[-1] if pd else glz[-1][1]
    shard, glz_region = glz[-1]
    if region == "pbe":
        region, shard, glz_region = "na", "na-1", "na"
    return region, shard, glz_region, versions[-1].strip()


class LocalClient:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {}
        self.puuid = ""
        self.pd_url = ""
        self.glz_url = ""

    def close(self):
        self.session.close()

    def connect(self):
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        path = local / "Riot Games/Riot Client/Config/lockfile"
        if not path.is_file():
            raise NotReady("Open VALORANT and reach its main menu. This window connects automatically.")
        parts = path.read_text(encoding="utf-8").strip().split(":")
        if len(parts) != 5 or not parts[2].isdigit():
            raise NotReady("Riot Client is starting. Waiting for its local connection.")
        auth = "Basic " + base64.b64encode(("riot:" + parts[3]).encode()).decode()
        try:
            r = self.session.get("https://127.0.0.1:" + parts[2] + "/entitlements/v1/token",
                                 headers={"Authorization": auth}, verify=False, timeout=8)
            r.raise_for_status()
            token = r.json()
        except (requests.RequestException, ValueError):
            raise NotReady("Waiting for the local Riot Client. Open VALORANT and sign in there.")
        if not all(token.get(k) for k in ("subject", "accessToken", "token")):
            raise NotReady("Riot Client has not finished signing in. Waiting...")
        log_path = local / "VALORANT/Saved/Logs/ShooterGame.log"
        region, shard, glz_region, client_version = read_connection_info(log_path)
        self.region = region
        self.pd_url = "https://pd." + region + ".a.pvp.net"
        self.glz_url = "https://glz-" + shard + "." + glz_region + ".a.pvp.net"
        platform = {"platformType": "PC", "platformOS": "Windows",
                    "platformOSVersion": "10.0.19042.1.256.64bit", "platformChipset": "Unknown"}
        self.headers = {"Authorization": "Bearer " + token["accessToken"],
                        "X-Riot-Entitlements-JWT": token["token"],
                        "X-Riot-ClientVersion": client_version,
                        "X-Riot-ClientPlatform": base64.b64encode(json.dumps(platform).encode()).decode()}
        self.puuid = token["subject"]

    def get(self, kind, endpoint, allow_missing=False):
        base = self.glz_url if kind == "glz" else self.pd_url
        if kind == "content":
            base = "https://shared." + self.region + ".a.pvp.net"
        r = self.session.get(base + endpoint, headers=self.headers, timeout=12)
        if allow_missing and r.status_code == 404:
            return {}
        if r.status_code == 429:
            raise NotReady("Riot is rate limiting requests. Waiting before trying again.")
        if r.status_code in (401, 403):
            raise NotReady("Riot did not authorize this request. Keep the signed-in game open.")
        r.raise_for_status()
        return r.json()

    def names(self, players):
        ids = [p["Subject"] for p in players if p.get("Subject") and
               (not (p.get("PlayerIdentity") or {}).get("Incognito")
                or p["Subject"] == self.puuid)]
        if not ids:
            return {}
        r = self.session.put(self.pd_url + "/name-service/v2/players",
                             headers=self.headers, json=ids, timeout=12)
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list):
            return {}
        return {p["Subject"]: str(p.get("GameName", "")) + "#" + str(p.get("TagLine", ""))
                for p in rows if p.get("Subject") in ids and p.get("GameName")}


class Collector(threading.Thread):
    def __init__(self, events):
        super().__init__(daemon=True, name="Valorant collector")
        self.events = events
        self.stop_event = threading.Event()
        self.refresh_event = threading.Event()
        self.paused = threading.Event()
        self.client = LocalClient()
        self.stats_cache = {}
        self.match_id = None
        self.content = None
        self.tier_maps = None

    def status(self, message):
        self.events.put(("status", message))

    def refresh(self):
        self.refresh_event.set()

    def run(self):
        try:
            while not self.stop_event.is_set():
                if self.paused.is_set():
                    self.stop_event.wait(.3)
                    continue
                forced = self.refresh_event.is_set()
                self.refresh_event.clear()
                if forced:
                    self.stats_cache.clear()
                try:
                    self.status("Connecting to the local Riot Client...")
                    self.client.connect()
                    self.collect()
                except NotReady as error:
                    self.status(str(error))
                except requests.RequestException:
                    self.status("Connection unavailable. Keep VALORANT open; retrying automatically.")
                except (ValueError, KeyError, TypeError, OSError):
                    self.status("The game returned incomplete data. Waiting for its next update.")
                except Exception:
                    self.status("Could not refresh this match. Press Refresh to try again.")
                for _ in range(50):
                    if self.stop_event.wait(.3) or self.refresh_event.is_set():
                        break
        finally:
            self.client.close()

    def collect(self):
        client = self.client
        match = client.get("glz", "/core-game/v1/players/" + client.puuid, True)
        state, endpoint = "In match", "core-game"
        if not match.get("MatchID"):
            match = client.get("glz", "/pregame/v1/players/" + client.puuid, True)
            state, endpoint = "Agent select", "pregame"
        match_id = match.get("MatchID")
        if not match_id:
            self.events.put(("snapshot", {"state": "Main menu", "map": "", "players": [],
                                           "time": time.time()}))
            return
        if match_id != self.match_id:
            self.match_id, self.stats_cache = match_id, {}
        self.status("Loading match roster and equipped items...")
        details = client.get("glz", "/" + endpoint + "/v1/matches/" + match_id)
        players = (details.get("AllyTeam") or {}).get("Players", []) if endpoint == "pregame" else details.get("Players", [])
        players = [p for p in players if isinstance(p, dict) and p.get("Subject")]
        # The roster is essential; public artwork, act metadata and stats are
        # optional and can be slow or unavailable. Show every player first.
        rows = []
        for p in players:
            name, level = visible_identity(p, {}, "Loading agent...", client.puuid)
            rows.append({"id": p["Subject"], "name": name, "agent": "Loading agent...",
                         "level": level, "team": p.get("TeamID") or (details.get("AllyTeam") or {}).get("TeamID") or "Other",
                         "weapons": [], "winRate": None, "games": None, "rank": "Unavailable"})
        self.events.put(("snapshot", {"state": state, "map": "Current match", "players": list(rows),
                                       "rosterSize": len(players), "time": time.time(), "partial": True}))
        if not self.content:
            try:
                self.content = client.get("content", "/content-service/v3/content")
            except (requests.RequestException, NotReady, ValueError):
                self.content = {}
        season_id = next((s.get("ID") for s in self.content.get("Seasons", [])
                          if s.get("IsActive") and s.get("Type") == "act"), None)
        try:
            names = client.names(players)
        except (requests.RequestException, ValueError):
            names = {}
        agents = {normalize_id(a.get("uuid")): a for a in public_catalog("agents?isPlayableCharacter=true")
                  if isinstance(a, dict)}
        riot_agents = {normalize_id(a.get("ID")): a.get("Name")
                       for a in self.content.get("Characters", []) if a.get("ID")}
        if self.tier_maps is None:
            catalogs = {normalize_id(c.get("uuid")): {t["tier"]: str(t.get("tierName", "")).title()
                        for t in c.get("tiers", []) if isinstance(t, dict) and isinstance(t.get("tier"), int)}
                        for c in public_catalog("competitivetiers") if isinstance(c, dict)}
            self.tier_maps = {s.get("seasonUuid") or s.get("uuid"): catalogs.get(normalize_id(s.get("competitiveTiersUuid")))
                              for s in public_catalog("seasons/competitive") if isinstance(s, dict)}
        weapons = merge_weapons(public_catalog("weapons"))
        buddies = {normalize_id(b.get("uuid")): b for b in public_catalog("buddies") if isinstance(b, dict)}
        try:
            raw_loadouts = client.get("glz", "/" + endpoint + "/v1/matches/" + match_id + "/loadouts", True)
        except (requests.RequestException, NotReady, ValueError):
            raw_loadouts = {}
        inventories = {}
        for entry in raw_loadouts.get("Loadouts", []):
            inventories[normalize_id(entry.get("Subject"))] = entry.get("Loadout", entry)
        for index, p in enumerate(players):
            if self.stop_event.is_set() or self.paused.is_set():
                return
            subject = p.get("Subject")
            if not subject:
                continue
            self.status("Loading player stats " + str(index + 1) + "/" + str(len(players)) + "...")
            agent_id = normalize_id(p.get("CharacterID"))
            agent = agents.get(agent_id, {})
            agent_name = agent.get("displayName") or riot_agents.get(agent_id) or "Unknown agent"
            name, level = visible_identity(p, names, agent_name, client.puuid)
            cached = self.stats_cache.get(subject)
            if cached and time.time() - cached[0] < 180:
                stats = cached[1]
            else:
                try:
                    mmr = client.get("pd", "/mmr/v1/players/" + subject, True)
                    stats = competitive_stats(mmr, season_id, self.tier_maps)
                except (requests.RequestException, NotReady, ValueError, KeyError, TypeError):
                    stats = {"winRate": None, "games": None, "wins": None, "rank": "Unavailable"}
                self.stats_cache[subject] = (time.time(), stats)
            inventory = inventories.get(normalize_id(subject), {})
            items = []
            for weapon_id, item in (inventory.get("Items") or {}).items():
                record = resolve_weapon(weapon_id, item, weapons)
                buddy = buddies.get(record.get("skin_buddy"), {})
                record["buddy_displayIcon"] = buddy.get("displayIcon")
                items.append(record)
            team = p.get("TeamID") or (details.get("AllyTeam") or {}).get("TeamID") or "Other"
            rows[index] = {"id": subject, "name": name, "agent": agent_name, "level": level,
                           "team": team, "agentColor": next(iter(agent.get("backgroundGradientColors") or []), None), "weapons": items, **stats}
            # Stats appear progressively; the UI remains interactive during requests.
            self.events.put(("snapshot", {"state": state, "map": self.map_name(details),
                                           "players": list(rows), "rosterSize": len(players),
                                           "time": time.time(), "partial": index + 1 < len(players)}))
        self.events.put(("snapshot", {"state": state, "map": self.map_name(details), "players": rows,
                                       "time": time.time(), "partial": False}))

    @staticmethod
    def map_name(details):
        map_id = str(details.get("MapID") or "").lower()
        return next((m.get("displayName") for m in public_catalog("maps")
                     if str(m.get("mapUrl") or "").lower() == map_id), "Current match")


def sample_snapshot():
    weapons = merge_weapons([])
    items = [resolve_weapon(WARDEN_ID, {"Sockets": {
        "bcef87d6-209b-46c6-8b19-fbe40bd95abc": {"Item": {"ID": WARDEN_SKINS[i % 3][0]}}
    }}, weapons) for i in range(3)]
    items.append({"weapon": "Vandal", "skinDisplayName": "Standard Vandal",
        "skinDisplayIcon": "https://media.valorant-api.com/weapons/9c82e19d-4575-0200-1a81-3eacf00cf872/displayicon.png"})
    players = []
    agents = ["Jett", "Hush", "Omen", "Sage", "Sova"]
    for i in range(10):
        games = 20 + i * 2
        wins = (12 if i < 5 else 9) + i // 2
        players.append({"id": "sample-" + str(i), "name": "Example player " + str(i + 1),
                        "agent": agents[i % 5], "team": "Blue" if i < 5 else "Red",
                        "level": 30 + i * 17, "rank": "Gold " + str(i % 3 + 1),
                        "games": games, "wins": wins, "winRate": wins / games * 100,
                        "peakRank": "Diamond " + str(i % 3 + 1), "rr": 30 + i,
                        "weapons": [items[i % 3], items[3]]})
    return {"state": "SAMPLE PREVIEW", "map": "Example match", "players": players,
            "time": time.time(), "sample": True}

class HeadshotCollector(threading.Thread):
    """One low-priority worker; only the most recently selected player is queued."""
    def __init__(self, events):
        super().__init__(daemon=True, name="Headshot history")
        self.events = events
        self.jobs = queue.Queue(maxsize=1)
        self.stop_event = threading.Event()
        self.cache = {}
        self.matches = {}

    def request(self, subject):
        cached = self.cache.get(subject)
        if cached and time.time() - cached[0] < 1800:
            self.events.put(("headshots", subject, cached[1]))
            return
        try: self.jobs.get_nowait()
        except queue.Empty: pass
        try: self.jobs.put_nowait(subject)
        except queue.Full: pass

    def run(self):
        client = LocalClient()
        try:
            while not self.stop_event.is_set():
                try: subject = self.jobs.get(timeout=.5)
                except queue.Empty: continue
                details = []
                interrupted = False
                try:
                    client.connect()
                    history = client.get("pd", "/match-history/v1/history/" + subject + "?queue=competitive&startIndex=0&endIndex=10", True)
                    seen = set()
                    for entry in (history.get("History") or [])[:10]:
                        if self.stop_event.is_set(): return
                        if not self.jobs.empty():
                            interrupted = True
                            break
                        match_id = entry.get("MatchID")
                        if not match_id or match_id in seen: continue
                        seen.add(match_id)
                        if match_id not in self.matches:
                            payload = client.get("pd", "/match-details/v1/matches/" + match_id, True)
                            # Keep only aggregate hit counts; discard the full match payload.
                            totals = {}
                            info = payload.get("matchInfo") or {}
                            if info.get("queueID") == "competitive" and info.get("isCompleted") is True:
                                for row in payload.get("roundResults") or []:
                                    for player in row.get("playerStats") or []:
                                        key = player.get("subject")
                                        if not key: continue
                                        totals.setdefault(key, []).extend(player.get("damage") or [])
                            compact = {"matchInfo": info, "roundResults": [{"playerStats": [
                                {"subject": key, "damage": value} for key, value in totals.items()]}]}
                            self.matches[match_id] = compact
                            while len(self.matches) > 100: self.matches.pop(next(iter(self.matches)))
                        details.append(self.matches[match_id])
                        if self.stop_event.wait(.15): return
                except (requests.RequestException, NotReady, ValueError, KeyError, TypeError, OSError):
                    pass
                if interrupted: continue
                result = headshot_stats(details, subject)
                self.cache[subject] = (time.time(), result)
                self.events.put(("headshots", subject, result))
        finally:
            client.close()
