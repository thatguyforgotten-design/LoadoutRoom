"""Pure match statistics and privacy-aware desktop rows."""
import math
import re

RANK_NAMES = ["Unranked"] * 3 + [
    tier + " " + str(i) for tier in ("Iron", "Bronze", "Silver", "Gold", "Platinum",
                                    "Diamond", "Ascendant", "Immortal") for i in (1, 2, 3)
] + ["Radiant"]


def competitive_stats(mmr, season_id, tier_maps=None):
    seasonal = ((mmr or {}).get("QueueSkills") or {}).get("competitive") or {}
    season = (seasonal.get("SeasonalInfoBySeasonID") or {}).get(season_id) or {}
    games = season.get("NumberOfGames")
    wins = season.get("NumberOfWinsWithPlacements")
    if wins is None:
        wins = season.get("NumberOfWins")
    valid = (isinstance(games, int) and not isinstance(games, bool) and games > 0
             and isinstance(wins, int) and not isinstance(wins, bool) and 0 <= wins <= games)
    tier = season.get("CompetitiveTier")
    rank = RANK_NAMES[tier] if isinstance(tier, int) and 0 <= tier < len(RANK_NAMES) else "Unavailable"
    peaks = []
    for act_id, history in (seasonal.get("SeasonalInfoBySeasonID") or {}).items():
        if not isinstance(history, dict):
            continue
        candidates = [history.get("CompetitiveTier")]
        for key, count in (history.get("WinsByTier") or {}).items():
            if isinstance(count, int) and not isinstance(count, bool) and count > 0 and str(key).isdigit():
                candidates.append(int(key))
        for candidate in candidates:
            if not isinstance(candidate, int) or isinstance(candidate, bool) or not 3 <= candidate < len(RANK_NAMES):
                continue
            names = (tier_maps or {}).get(act_id)
            # Older acts used different Immortal/Radiant IDs. Never guess their names.
            if names is None and act_id != season_id and candidate >= 21:
                continue
            name = names.get(candidate) if names is not None else RANK_NAMES[candidate]
            if name in RANK_NAMES:
                peaks.append((RANK_NAMES.index(name), name, act_id))
    peak = max(peaks, default=None)
    rr = season.get("RankedRating")
    return {"peakRank": peak[1] if peak else "Unavailable",
            "peakSeason": peak[2] if peak else None,
            "rr": rr if isinstance(rr, int) and not isinstance(rr, bool) and rr >= 0 else None,
            "winRate": wins / games * 100 if valid else None,
            "games": games if isinstance(games, int) and games >= 0 else None,
            "wins": wins if valid else None, "rank": rank}


def visible_identity(player, resolved_names, agent_name, self_id):
    subject = player.get("Subject")
    identity = player.get("PlayerIdentity") or {}
    hidden = bool(identity.get("Incognito")) and subject != self_id
    name = agent_name if hidden else (resolved_names.get(subject) or agent_name)
    level = identity.get("AccountLevel")
    if identity.get("HideAccountLevel") and subject != self_id:
        level = None
    if not isinstance(level, int) or isinstance(level, bool) or level < 0:
        level = None
    return name, level


def team_summary(players):
    result = {}
    for team in ("Blue", "Red"):
        roster = [p for p in players if p.get("team") == team]
        eligible = [p["winRate"] for p in roster
                    if isinstance(p.get("winRate"), (int, float))
                    and not isinstance(p.get("winRate"), bool)
                    and math.isfinite(p["winRate"]) and 0 <= p["winRate"] <= 100
                    and isinstance(p.get("games"), int) and p["games"] > 0]
        result[team] = {"average": sum(eligible) / len(eligible) if eligible else None,
                        "available": len(eligible), "total": len(roster)}
    blue, red = result["Blue"]["average"], result["Red"]["average"]
    result["leader"] = None if blue is None or red is None else (
        "Tie" if abs(blue - red) < 0.000001 else "Blue" if blue > red else "Red")
    return result

def headshot_stats(matches, subject):
    """Hit-based HS%, weighted across completed Competitive matches, never kill-based."""
    head, body, legs, games = 0, 0, 0, 0
    for match in matches:
        info = match.get("matchInfo") or {}
        if info.get("queueID") != "competitive" or info.get("isCompleted") is not True:
            continue
        found = False
        for round_result in match.get("roundResults") or []:
            for player in round_result.get("playerStats") or []:
                if player.get("subject") != subject:
                    continue
                found = True
                for damage in player.get("damage") or []:
                    counts = [damage.get(key) for key in ("headshots", "bodyshots", "legshots")]
                    if all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in counts):
                        head += counts[0]; body += counts[1]; legs += counts[2]
        games += int(found)
    total = head + body + legs
    return {"headshotRate": head / total * 100 if total else None,
            "headshots": head, "hits": total, "matches": games}
