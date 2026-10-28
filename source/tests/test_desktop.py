import unittest
from src.desktop_stats import competitive_stats, team_summary, visible_identity, headshot_stats
from src.desktop_backend import LocalClient, sample_snapshot

def mmr(games, wins):
    return {"QueueSkills": {"competitive": {"SeasonalInfoBySeasonID": {"act": {
        "NumberOfGames": games, "NumberOfWinsWithPlacements": wins, "CompetitiveTier": 12}}}}}

class DesktopTests(unittest.TestCase):
    def test_headshots_are_weighted_hits_not_mean_or_kills(self):
        def match(h,b,l):
            return {"matchInfo":{"queueID":"competitive","isCompleted":True},"roundResults":[{"playerStats":[
                {"subject":"self","damage":[{"headshots":h,"bodyshots":b,"legshots":l}]},
                {"subject":"other","damage":[{"headshots":999,"bodyshots":0,"legshots":0}]}]}]}
        result=headshot_stats([match(1,0,0),match(1,7,1)],"self")
        self.assertEqual(result["headshotRate"],20)
        self.assertEqual(result["matches"],2)
    def test_headshots_missing_is_na(self):
        self.assertIsNone(headshot_stats([],"self")["headshotRate"])
    def test_headshots_ignore_incomplete_or_noncompetitive(self):
        self.assertEqual(headshot_stats([{"matchInfo":{"queueID":"unrated","isCompleted":True}}],"self")["matches"],0)

    def test_peak_uses_history_and_wins_by_tier(self):
        data=mmr(40,22)
        data["QueueSkills"]["competitive"]["SeasonalInfoBySeasonID"]["old"]={"CompetitiveTier":15,"WinsByTier":{"20":1,"23":0}}
        result=competitive_stats(data,"act")
        self.assertEqual(result["peakRank"],"Diamond 3")
        self.assertEqual(result["rank"],"Gold 1")

    def test_historical_immortal_tier_uses_act_mapping(self):
        data=mmr(40,22)
        data["QueueSkills"]["competitive"]["SeasonalInfoBySeasonID"]["old"]={"CompetitiveTier":23}
        result=competitive_stats(data,"act",{"old":{23:"Immortal 3"}})
        self.assertEqual(result["peakRank"],"Immortal 3")

    def test_ambiguous_old_high_tier_is_not_guessed(self):
        data=mmr(40,22)
        data["QueueSkills"]["competitive"]["SeasonalInfoBySeasonID"]["old"]={"CompetitiveTier":23}
        self.assertEqual(competitive_stats(data,"act")["peakRank"],"Gold 1")

    def test_peak_missing_is_unavailable(self):
        self.assertEqual(competitive_stats({},"act")["peakRank"],"Unavailable")
    def test_win_rate_uses_current_act_wins_over_games(self):
        s = competitive_stats(mmr(40, 22), "act")
        self.assertAlmostEqual(s["winRate"], 55)
        self.assertEqual(s["games"], 40)
        self.assertEqual(s["rank"], "Gold 1")

    def test_zero_games_is_unavailable_not_100_percent(self):
        self.assertIsNone(competitive_stats(mmr(0, 0), "act")["winRate"])

    def test_zero_wins_is_valid_zero_percent(self):
        self.assertEqual(competitive_stats(mmr(10, 0), "act")["winRate"], 0)

    def test_missing_season_is_unavailable(self):
        self.assertIsNone(competitive_stats(mmr(40, 22), "missing")["winRate"])

    def test_invalid_counts_are_unavailable(self):
        for games, wins in ((10, 11), (10, -1), ("10", 5), (True, 1)):
            self.assertIsNone(competitive_stats(mmr(games, wins), "act")["winRate"])

    def test_team_comparison_is_mean_of_available_player_rates(self):
        rows = [{"team": "Blue", "games": 10, "winRate": 80},
                {"team": "Blue", "games": 100, "winRate": 40},
                {"team": "Blue", "games": None, "winRate": None},
                {"team": "Red", "games": 20, "winRate": 55}]
        result = team_summary(rows)
        self.assertEqual(result["Blue"]["average"], 60)
        self.assertEqual(result["Blue"]["available"], 2)
        self.assertEqual(result["Blue"]["total"], 3)
        self.assertEqual(result["leader"], "Blue")

    def test_missing_team_does_not_predict_winner(self):
        self.assertIsNone(team_summary([{"team": "Blue", "games": 10, "winRate": 80}])["leader"])

    def test_equal_rates_are_a_tie(self):
        self.assertEqual(team_summary([{"team": t, "games": 10, "winRate": 50}
                                     for t in ("Blue", "Red")])["leader"], "Tie")

    def test_hidden_names_and_levels_are_not_exposed(self):
        player = {"Subject": "other", "PlayerIdentity": {
            "Incognito": True, "HideAccountLevel": True, "AccountLevel": 999}}
        name, level = visible_identity(player, {"other": "ShouldNotAppear"}, "Hush", "self")
        self.assertEqual(name, "Hush")
        self.assertIsNone(level)

    def test_visible_identity_is_shown(self):
        player = {"Subject": "other", "PlayerIdentity": {"AccountLevel": 42}}
        self.assertEqual(visible_identity(player, {"other": "Visible#123"}, "Hush", "self"),
                         ("Visible#123", 42))

    def test_hidden_players_are_omitted_from_name_requests(self):
        client = LocalClient()
        client.puuid, client.pd_url = "self", "https://pd.test.invalid"
        captured = {}
        class Reply:
            def raise_for_status(self): pass
            def json(self):
                return [{"Subject": "visible", "GameName": "Visible", "TagLine": "123"}]
        def put(url, **kwargs):
            captured.update(kwargs)
            return Reply()
        client.session.put = put
        players = [{"Subject": "hidden", "PlayerIdentity": {"Incognito": True}},
                   {"Subject": "visible", "PlayerIdentity": {}},
                   {"Subject": "self", "PlayerIdentity": {"Incognito": True}}]
        names = client.names(players)
        self.assertNotIn("hidden", captured["json"])
        self.assertIn("self", captured["json"])
        self.assertEqual(names["visible"], "Visible#123")
        client.close()

    def test_sample_is_labelled_and_has_two_teams(self):
        sample = sample_snapshot()
        self.assertTrue(sample["sample"])
        self.assertEqual(len(sample["players"]), 10)
        for p in sample["players"]:
            self.assertEqual(sum(w["weapon"] == "Warden" for w in p["weapons"]), 1)
        self.assertEqual(team_summary(sample["players"])["leader"], "Blue")

if __name__ == "__main__":
    unittest.main()
