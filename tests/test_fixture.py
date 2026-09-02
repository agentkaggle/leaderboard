from __future__ import annotations

import json
import unittest
from pathlib import Path

from agentkaggle_leaderboard.builder import _late_board, _ongoing_board
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
                rank = entry["authenticated_private_rank"]
                count = entry["authenticated_private_rank_team_count"]
                if rank is None:
                    rank, count = entry["rank"], team_count
                self.assertEqual(
                    entry["medal_candidate"],
                    medal_candidate(rank, count) if competition["awards_points"] else "not_eligible",
                )

    def test_both_boards_match_the_current_board_rules(self) -> None:
        teams = tuple(team["name"] for team in self.payload["ongoing_teams"])
        self.assertEqual(self.payload["ongoing_teams"], _ongoing_board(teams, self.competitions))
        self.assertEqual(self.payload["late_teams"], _late_board(teams, self.competitions))

    def test_boards_only_number_teams_with_a_counted_result(self) -> None:
        for board, counted in (
            ("ongoing_teams", lambda team: team["medal_count"] or team["top_percent_count"]),
            ("late_teams", lambda team: team["beat_winner_count"]),
        ):
            positions = [team["position"] for team in self.payload[board] if counted(team)]
            self.assertEqual(positions, list(range(1, len(positions) + 1)))
            self.assertTrue(
                all(
                    team["position"] is None
                    for team in self.payload[board]
                    if not counted(team)
                )
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
