from __future__ import annotations

import json
import unittest
from pathlib import Path

from agentkaggle_leaderboard.medals import medal_candidate
from agentkaggle_leaderboard.output import validate_public_payload
from agentkaggle_leaderboard.visualizations import build_visualizations


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "leaderboard.json"


class FixtureConsistencyTests(unittest.TestCase):
    """The synthetic snapshot renders the site in CI, so it must match the live schema."""

    def setUp(self) -> None:
        self.payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.competitions = self.payload["competitions"]
        self.entries = [
            entry for competition in self.competitions for entry in competition["entries"]
        ]

    def team_entries(self, name: str) -> list[dict]:
        return [entry for entry in self.entries if entry["team_name"] == name]

    def test_fixture_matches_the_published_schema(self) -> None:
        validate_public_payload(self.payload)
        self.assertEqual(self.payload["schema_version"], 10)
        self.assertEqual(
            self.payload["visualizations"], build_visualizations(self.competitions)
        )

    def test_summary_counts_match_the_published_content(self) -> None:
        summary = self.payload["summary"]
        late_submissions = self.payload["late_submissions"]
        self.assertEqual(summary["matched_competition_count"], len(self.competitions))
        self.assertEqual(summary["participation_count"], len(self.entries))
        self.assertEqual(summary["tracked_team_count"], len(self.payload["ongoing_teams"]))
        self.assertEqual(summary["late_submission_count"], len(late_submissions))
        self.assertEqual(
            summary["late_submission_competition_count"],
            len({entry["competition_slug"] for entry in late_submissions}),
        )
        self.assertEqual(
            {team["name"] for team in self.payload["ongoing_teams"]},
            {team["name"] for team in self.payload["late_teams"]},
        )
        self.assertTrue(all(competition["entries"] for competition in self.competitions))

    def test_ranks_percentages_and_medals_are_derived_consistently(self) -> None:
        for competition in self.competitions:
            team_count = competition["leaderboard_team_count"]
            for entry in competition["entries"]:
                for rank_key, percent_key, count in (
                    ("rank", "top_percent", team_count),
                    (
                        "authenticated_private_rank",
                        "authenticated_private_top_percent",
                        entry["authenticated_private_rank_team_count"],
                    ),
                    ("late_rank", "late_top_percent", entry["late_rank_team_count"]),
                ):
                    if entry[rank_key] is None:
                        self.assertIsNone(entry[percent_key])
                        continue
                    self.assertEqual(
                        entry[percent_key], round(entry[rank_key] / count * 100, 4)
                    )

                if entry["rank"] is None:
                    self.assertEqual(entry["score"], "")
                    self.assertEqual(entry["medal_candidate"], "unavailable")
                    continue
                rank = entry["authenticated_private_rank"] or entry["rank"]
                count = entry["authenticated_private_rank_team_count"] or team_count
                self.assertEqual(
                    entry["medal_candidate"],
                    medal_candidate(rank, count) if competition["awards_points"] else "not_eligible",
                )

    def test_ongoing_board_counts_medals_and_top_five_percent_results(self) -> None:
        for position, team in enumerate(self.payload["ongoing_teams"], start=1):
            entries = self.team_entries(team["name"])
            for medal in ("gold", "silver", "bronze"):
                self.assertEqual(
                    team[f"{medal}_count"],
                    sum(entry["medal_candidate"] == medal for entry in entries),
                )
            self.assertEqual(
                team["medal_count"],
                team["gold_count"] + team["silver_count"] + team["bronze_count"],
            )
            self.assertEqual(
                team["top_percent_count"],
                sum(
                    (entry["authenticated_private_top_percent"] or entry["top_percent"] or 100)
                    <= 5
                    for entry in entries
                ),
            )
            ranked = team["medal_count"] or team["top_percent_count"]
            self.assertEqual(team["position"], position if ranked else None)

    def test_late_board_counts_only_results_better_than_the_original_winner(self) -> None:
        for position, team in enumerate(self.payload["late_teams"], start=1):
            entries = self.team_entries(team["name"])
            self.assertEqual(
                team["beat_winner_count"],
                sum(entry["late_beats_winner"] for entry in entries),
            )
            self.assertEqual(
                team["position"], position if team["beat_winner_count"] else None
            )

    def test_every_late_submission_is_mirrored_into_its_competition(self) -> None:
        for submission in self.payload["late_submissions"]:
            competition = next(
                item
                for item in self.competitions
                if item["slug"] == submission["competition_slug"]
            )
            entry = next(
                item
                for item in competition["entries"]
                if item["team_name"] == submission["team_name"]
            )
            self.assertEqual(entry["late_public_score"], submission["public_score"])
            self.assertEqual(entry["late_private_score"], submission["private_score"])
            self.assertEqual(entry["late_submission_date"], submission["submission_date"])


if __name__ == "__main__":
    unittest.main()
