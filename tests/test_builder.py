from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from agentkaggle_leaderboard.builder import _safe_failure_kind, build_leaderboard
from agentkaggle_leaderboard.kaggle_source import (
    InvalidKaggleResponse,
    KaggleAuthenticationError,
)
from agentkaggle_leaderboard.models import (
    AuthenticatedSubmissionScoreEntry,
    Competition,
    LateSubmissionEntry,
    LeaderboardEntry,
    LeaderboardSnapshot,
)
from agentkaggle_leaderboard.output import validate_public_payload
from agentkaggle_leaderboard.settings import Settings


NOW = datetime(2026, 7, 17, tzinfo=timezone.utc)
ACTIVE_DEADLINE = datetime(2026, 8, 1, tzinfo=timezone.utc)
ENDED_DEADLINE = datetime(2026, 6, 1, tzinfo=timezone.utc)


def utc(day: int, month: int = 7) -> datetime:
    return datetime(2026, month, day, tzinfo=timezone.utc)


def competition(
    slug: str,
    *,
    deadline: datetime | None = ACTIVE_DEADLINE,
    category: str = "Featured",
    api_team_count: int = 100,
    awards_points: bool = False,
) -> Competition:
    return Competition(
        slug=slug,
        title=slug,
        url=f"https://www.kaggle.com/competitions/{slug}",
        category=category,
        reward="",
        deadline=deadline,
        api_team_count=api_team_count,
        awards_points=awards_points,
    )


def snapshot(
    *matches: LeaderboardEntry,
    team_count: int = 100,
    kind: str = "public",
    score_order: str = "unknown",
    score_values: tuple[str, ...] = (),
) -> LeaderboardSnapshot:
    return LeaderboardSnapshot(
        team_count=team_count,
        kind=kind,
        matches=matches,
        score_order=score_order,
        score_values=score_values,
    )


def board_entry(team: str, rank: int, score: str, day: int = 1) -> LeaderboardEntry:
    return LeaderboardEntry(team, rank, score, f"2026-07-0{day}T00:00:00Z")


def late(
    slug: str,
    team: str,
    public_score: str,
    private_score: str = "",
    *,
    day: int = 1,
) -> LateSubmissionEntry:
    return LateSubmissionEntry(
        competition_slug=slug,
        competition_title=slug,
        competition_url=f"https://www.kaggle.com/competitions/{slug}",
        deadline=ENDED_DEADLINE,
        configured_team_name=team,
        public_score=public_score,
        private_score=private_score,
        submission_date=utc(day),
    )


def authenticated(
    team: str,
    public_score: str,
    private_score: str,
    *,
    day: int = 30,
    rank: int | None = None,
    team_count: int | None = None,
    slug: str = "ended-public",
) -> AuthenticatedSubmissionScoreEntry:
    return AuthenticatedSubmissionScoreEntry(
        competition_slug=slug,
        configured_team_name=team,
        public_score=public_score,
        private_score=private_score,
        submission_date=utc(day, month=5),
        private_rank=rank,
        private_rank_team_count=team_count,
    )


class FakeSource:
    """Serve a fixed catalog where each competition yields a snapshot or a failure."""

    def __init__(self, *pairs: tuple[Competition, object]) -> None:
        self.competitions = [competition for competition, _ in pairs]
        self.results = {competition.slug: result for competition, result in pairs}

    def list_competitions(self, max_competitions: int | None = None) -> list[Competition]:
        return self.competitions[:max_competitions]

    def get_leaderboard(self, item: Competition, normalized_teams: dict[str, str]):
        result = self.results[item.slug]
        if isinstance(result, Exception):
            raise result
        return result


def access_denied() -> Exception:
    error = RuntimeError("sensitive upstream text")
    error.response = type("Response", (), {"status_code": 403})()
    return error


def default_source() -> FakeSource:
    return FakeSource(
        (
            competition("active-comp", api_team_count=500, awards_points=True),
            snapshot(board_entry("Alpha", 11, "0.123456789"), team_count=500),
        ),
        (
            competition("no-match", deadline=utc(1, month=1), category="Playground"),
            snapshot(team_count=20, kind="private"),
        ),
        (competition("blocked", deadline=None, api_team_count=100), access_denied()),
    )


def build(source: FakeSource, teams: tuple[str, ...] = ("Alpha",), **kwargs):
    kwargs.setdefault("generated_at", NOW)
    return build_leaderboard(source, Settings(teams, workers=2), **kwargs)


def ended_public_source(*matches: LeaderboardEntry, **snapshot_kwargs) -> FakeSource:
    return FakeSource(
        (
            competition("ended-public", deadline=ENDED_DEADLINE),
            snapshot(*matches, **snapshot_kwargs),
        )
    )


class BuilderTests(unittest.TestCase):
    def test_builds_sanitized_partial_dashboard_payload(self) -> None:
        payload = build(default_source(), ("Alpha", "Beta"))

        self.assertEqual(payload["schema_version"], 10)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["summary"]["discovered_competition_count"], 3)
        self.assertEqual(payload["summary"]["scanned_competition_count"], 2)
        self.assertEqual(payload["summary"]["matched_competition_count"], 1)
        self.assertEqual(payload["summary"]["error_counts"], {"access_denied": 1})

        entry = payload["competitions"][0]["entries"][0]
        self.assertEqual(payload["competitions"][0]["leaderboard_team_count"], 500)
        self.assertEqual(entry["rank"], 11)
        self.assertEqual(entry["top_percent"], 2.2)
        self.assertEqual(entry["score"], "0.123456789")
        self.assertEqual(entry["medal_candidate"], "gold")

        serialized = json.dumps(payload)
        self.assertNotIn("sensitive upstream text", serialized)
        self.assertNotIn("TeamMemberUserNames", serialized)
        self.assertNotIn("average", serialized)
        validate_public_payload(payload)

    def test_public_schema_rejects_raw_fields(self) -> None:
        payload = build(default_source(), max_competitions=1)
        payload["competitions"][0]["TeamMemberUserNames"] = "must never be published"
        with self.assertRaisesRegex(ValueError, "unexpected or missing fields"):
            validate_public_payload(payload)

    def test_public_schema_rejects_unapproved_error_categories(self) -> None:
        payload = build(default_source())
        payload["summary"]["error_counts"] = {"SensitiveInternalException": 1}
        with self.assertRaisesRegex(ValueError, "unsupported competition error category"):
            validate_public_payload(payload)

    def test_failure_kinds_are_fixed_public_categories(self) -> None:
        self.assertEqual(
            _safe_failure_kind(InvalidKaggleResponse("raw upstream detail")),
            "invalid_response",
        )
        sensitive_exception = type("SensitiveInternalException", (RuntimeError,), {})
        self.assertEqual(_safe_failure_kind(sensitive_exception("raw detail")), "unexpected")
        self.assertEqual(
            _safe_failure_kind(KaggleAuthenticationError("raw auth detail")),
            "access_denied",
        )

    def test_max_competitions_marks_result_truncated(self) -> None:
        payload = build(default_source(), max_competitions=1)
        self.assertEqual(payload["status"], "partial")
        self.assertTrue(payload["summary"]["truncated"])

    def test_severely_degraded_scan_is_rejected(self) -> None:
        source = FakeSource(
            (competition("competition-0", deadline=None), snapshot(team_count=10)),
            *(
                (competition(f"competition-{index}"), RuntimeError("upstream failure"))
                for index in range(1, 4)
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "too degraded"):
            build(source)

    def test_each_competition_uses_only_the_best_rank_per_team(self) -> None:
        payload = build(
            FakeSource(
                (
                    competition("active-comp"),
                    snapshot(
                        board_entry("Alpha", 25, "0.80"),
                        board_entry("Alpha", 5, "0.95", day=2),
                    ),
                )
            )
        )

        entries = payload["competitions"][0]["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["rank"], 5)
        self.assertEqual(entries[0]["top_percent"], 5.0)

    def test_late_submissions_are_sanitized_deduplicated_and_counted(self) -> None:
        late_entry = late("ended-comp", "Beta", "0.91", "0.87", day=1)
        payload = build(
            default_source(),
            ("Alpha", "Beta"),
            late_submissions=(late_entry, late_entry),
            late_submission_account_count=2,
            late_submission_failure_kinds=("access_denied",),
        )

        self.assertEqual(payload["summary"]["late_submission_account_count"], 2)
        self.assertEqual(payload["summary"]["failed_late_submission_account_count"], 1)
        self.assertEqual(payload["summary"]["late_submission_competition_count"], 1)
        self.assertEqual(payload["summary"]["late_submission_count"], 1)
        self.assertEqual(
            payload["summary"]["late_submission_error_counts"], {"access_denied": 1}
        )

        late_competition = next(
            item for item in payload["competitions"] if item["slug"] == "ended-comp"
        )
        self.assertEqual(late_competition["leaderboard_kind"], "unavailable")
        self.assertEqual(late_competition["leaderboard_team_count"], 0)
        entry = late_competition["entries"][0]
        self.assertIsNone(entry["rank"])
        self.assertEqual(entry["late_public_score"], "0.91")
        self.assertEqual(entry["late_private_score"], "0.87")
        self.assertFalse(entry["late_beats_winner"])
        self.assertEqual(
            set(payload["late_submissions"][0]),
            {
                "competition_slug",
                "competition_title",
                "competition_url",
                "deadline",
                "team_name",
                "public_score",
                "private_score",
                "submission_date",
            },
        )
        validate_public_payload(payload)

    def test_late_submissions_keep_the_best_score_per_team_and_competition(self) -> None:
        source = FakeSource(
            (
                competition("ended-comp", deadline=ENDED_DEADLINE),
                snapshot(
                    board_entry("Alpha", 10, "0.20"),
                    kind="private",
                    score_order="lower",
                    score_values=("0.05", "0.20", "0.40"),
                ),
            )
        )
        payload = build(
            source,
            late_submissions=(
                late("ended-comp", "Alpha", "0.15", "0.10", day=1),
                late("ended-comp", "Alpha", "0.25", "0.30", day=2),
            ),
            late_submission_account_count=1,
        )

        self.assertEqual(payload["summary"]["late_submission_count"], 1)
        self.assertEqual(payload["late_submissions"][0]["private_score"], "0.10")
        entry = payload["competitions"][0]["entries"][0]
        self.assertEqual(entry["rank"], 10)
        self.assertEqual(entry["late_private_score"], "0.10")
        self.assertEqual(entry["late_rank"], 2)
        self.assertEqual(entry["late_top_percent"], 2.0)
        self.assertEqual(entry["late_rank_team_count"], 100)
        self.assertEqual(entry["late_submission_date"], "2026-07-01T00:00:00Z")

        completed = payload["visualizations"]["completed"]
        self.assertEqual((completed["competition_count"], completed["result_count"]), (1, 1))
        result = completed["competitions"][0]["results"][0]
        self.assertEqual(result["result_kind"], "official_final")
        self.assertTrue(result["is_official"])
        self.assertEqual(result["rank_kind"], "official_private")
        self.assertEqual(result["quantile"], 90.0)

    def test_late_only_team_result_keeps_known_competition_metadata(self) -> None:
        source = FakeSource(
            (
                competition("no-match", deadline=utc(1, month=1), category="Playground"),
                snapshot(
                    team_count=20,
                    kind="private",
                    score_order="higher",
                    score_values=("120000", "114300", "100000"),
                ),
            )
        )
        payload = build(
            source,
            ("Alpha", "Beta"),
            late_submissions=(late("no-match", "Beta", "114302", "114302", day=11),),
            late_submission_account_count=1,
        )

        item = payload["competitions"][0]
        self.assertEqual(item["category"], "Playground")
        self.assertEqual(item["leaderboard_kind"], "private")
        self.assertEqual(item["leaderboard_team_count"], 20)
        entry = item["entries"][0]
        self.assertEqual(entry["team_name"], "Beta")
        self.assertIsNone(entry["rank"])
        self.assertEqual(entry["late_public_score"], "114302")
        self.assertEqual(entry["late_rank"], 2)
        self.assertEqual(entry["late_top_percent"], 10.0)
        self.assertFalse(entry["late_beats_winner"])

    def test_a_late_score_below_the_whole_board_stays_inside_the_published_range(self) -> None:
        source = FakeSource(
            (
                competition("ended-comp", deadline=ENDED_DEADLINE, api_team_count=4),
                snapshot(
                    team_count=4,
                    score_order="higher",
                    score_values=("0.90", "0.80", "0.70", "0.60"),
                ),
            )
        )
        payload = build(
            source,
            late_submissions=(late("ended-comp", "Alpha", "0.10"),),
            late_submission_account_count=1,
        )

        entry = payload["competitions"][0]["entries"][0]
        self.assertIsNone(entry["rank"])
        self.assertEqual(entry["late_rank"], 4)
        self.assertEqual(entry["late_top_percent"], 100.0)
        self.assertFalse(entry["late_beats_winner"])
        # A rank past the last place would publish Top% > 100 and a negative quantile.
        validate_public_payload(payload)

    def test_a_non_numeric_winning_score_publishes_no_winner_comparison(self) -> None:
        source = FakeSource(
            (
                competition("ended-comp", deadline=ENDED_DEADLINE),
                snapshot(
                    score_order="higher",
                    score_values=("", "0.90", "0.80"),
                ),
            )
        )
        payload = build(
            source,
            late_submissions=(late("ended-comp", "Alpha", "0.95"),),
            late_submission_account_count=1,
        )

        entry = payload["competitions"][0]["entries"][0]
        self.assertEqual(entry["late_rank"], 1)
        # The runner-up must never stand in for an unreadable winning score.
        self.assertFalse(entry["late_beats_winner"])

    def test_entries_are_ordered_by_the_rank_the_table_shows(self) -> None:
        source = ended_public_source(
            board_entry("Alpha", 20, "0.80"),
            board_entry("Beta", 60, "0.50"),
        )
        payload = build(
            source,
            ("Alpha", "Beta"),
            authenticated_submission_scores=(
                authenticated("Alpha", "0.80", "0.10", rank=90, team_count=100),
                authenticated("Beta", "0.50", "0.90", rank=3, team_count=100),
            ),
        )

        entries = payload["competitions"][0]["entries"]
        self.assertEqual([entry["team_name"] for entry in entries], ["Beta", "Alpha"])
        self.assertEqual([entry["authenticated_private_rank"] for entry in entries], [3, 90])

    def test_only_explicitly_excluded_competitions_are_removed(self) -> None:
        excluded_slugs = (
            "restaurant-revenue-prediction2",
            "orbit-wars",
            "ai-agent-security-multi-step-tool-attacks",
        )
        included_slugs = ("included-competition", "arc-prize-2026-arc-agi-2")
        source = FakeSource(
            *(
                (
                    competition(slug),
                    snapshot(
                        board_entry("Alpha", 10, "0.90"),
                        score_order="higher",
                        score_values=("1.0", "0.90", "0.80"),
                    ),
                )
                for slug in (*included_slugs, *excluded_slugs)
            )
        )
        payload = build(
            source,
            late_submissions=tuple(
                late(slug, "Alpha", "0.95", "0.95", day=2) for slug in excluded_slugs
            ),
            late_submission_account_count=1,
        )

        self.assertCountEqual(
            [item["slug"] for item in payload["competitions"]], list(included_slugs)
        )
        self.assertEqual(payload["late_submissions"], [])
        self.assertEqual(payload["summary"]["matched_competition_count"], 2)
        self.assertEqual(payload["summary"]["late_submission_count"], 0)
        self.assertEqual(payload["late_teams"][0]["beat_winner_count"], 0)
        self.assertIn(
            "arc-prize-2026-arc-agi-2",
            {
                item["slug"]
                for item in payload["visualizations"]["ongoing"]["competitions"]
            },
        )
        validate_public_payload(payload)

    def test_authenticated_private_score_matches_ended_public_result(self) -> None:
        source = ended_public_source(
            board_entry("Alpha", 25, "7.229", day=1),
            score_order="lower",
            score_values=("6.0", "7.229", "8.0"),
        )
        score = authenticated("Alpha", "7.2290", "9.595", day=31, rank=37, team_count=100)
        payload = build(source, authenticated_submission_scores=(score,))

        entry = payload["competitions"][0]["entries"][0]
        self.assertEqual(entry["authenticated_private_score"], "9.595")
        self.assertEqual(entry["authenticated_private_submission_date"], "2026-05-31T00:00:00Z")
        self.assertEqual(entry["authenticated_private_rank"], 37)
        self.assertEqual(entry["authenticated_private_top_percent"], 37.0)
        self.assertEqual(entry["authenticated_private_rank_team_count"], 100)
        self.assertEqual(payload["summary"]["authenticated_private_score_count"], 1)

        result = payload["visualizations"]["completed"]["competitions"][0]["results"][0]
        self.assertEqual(result["rank"], 37)
        self.assertEqual(result["top_percent"], 37.0)
        self.assertEqual(result["leaderboard_team_count"], 100)
        self.assertEqual(result["score"], "9.595")
        self.assertEqual(result["rank_kind"], "authenticated_private")
        self.assertEqual(result["score_kind"], "authenticated_private")
        self.assertEqual(result["result_kind"], "official_final")
        self.assertEqual(result["result_time"], "2026-05-31T00:00:00Z")
        validate_public_payload(payload)

        active_payload = build(
            source,
            generated_at=utc(1, month=5),
            authenticated_submission_scores=(score,),
        )
        active_entry = active_payload["competitions"][0]["entries"][0]
        self.assertEqual(active_entry["authenticated_private_score"], "")
        self.assertIsNone(active_entry["authenticated_private_rank"])
        self.assertEqual(active_payload["summary"]["authenticated_private_score_count"], 0)

    def test_authenticated_private_result_time_uses_the_scored_submission(self) -> None:
        payload = build(
            ended_public_source(board_entry("Alpha", 25, "0.90")),
            authenticated_submission_scores=(
                authenticated("Alpha", "0.90", "0.81", day=30, rank=10, team_count=100),
                authenticated("Alpha", "0.90", "", day=31, rank=10, team_count=100),
            ),
        )

        entry = payload["competitions"][0]["entries"][0]
        self.assertEqual(entry["authenticated_private_submission_date"], "2026-05-30T00:00:00Z")

    def test_ambiguous_authenticated_private_score_is_not_published(self) -> None:
        payload = build(
            ended_public_source(board_entry("Alpha", 25, "0.90")),
            authenticated_submission_scores=(
                authenticated("Alpha", "0.90", "0.81", day=30, rank=40, team_count=100),
                authenticated("Alpha", "0.90", "0.82", day=31, rank=41, team_count=100),
            ),
        )

        entry = payload["competitions"][0]["entries"][0]
        self.assertEqual(entry["authenticated_private_score"], "")
        self.assertIsNone(entry["authenticated_private_rank"])
        self.assertEqual(payload["summary"]["authenticated_private_score_count"], 0)

    def test_conflicting_authenticated_private_ranks_are_not_published(self) -> None:
        payload = build(
            ended_public_source(board_entry("Alpha", 25, "0.90")),
            authenticated_submission_scores=(
                authenticated("Alpha", "0.90", "0.81", day=30, rank=9, team_count=100),
                authenticated("Alpha", "0.90", "0.81", day=31, rank=10, team_count=100),
            ),
        )

        entry = payload["competitions"][0]["entries"][0]
        self.assertEqual(entry["authenticated_private_score"], "0.81")
        self.assertIsNone(entry["authenticated_private_rank"])
        result = payload["visualizations"]["completed"]["competitions"][0]["results"][0]
        self.assertEqual(result["rank"], 25)
        self.assertEqual(result["rank_kind"], "official_public")
        validate_public_payload(payload)

    def test_visualizations_split_states_and_keep_every_team_result(self) -> None:
        source = FakeSource(
            (
                competition("active-visual"),
                snapshot(board_entry("Alpha", 5, "0.95"), board_entry("Beta", 20, "0.80")),
            ),
            (
                competition("ended-visual", deadline=ENDED_DEADLINE, api_team_count=200),
                snapshot(
                    LeaderboardEntry("Alpha", 8, "0.91", "2026-06-01T00:00:00Z"),
                    LeaderboardEntry("Beta", 40, "0.75", "2026-06-01T00:00:00Z"),
                    team_count=200,
                    kind="private",
                ),
            ),
        )
        payload = build(source, ("Alpha", "Beta"))

        ongoing = payload["visualizations"]["ongoing"]
        completed = payload["visualizations"]["completed"]
        self.assertEqual((ongoing["competition_count"], ongoing["result_count"]), (1, 2))
        self.assertEqual((completed["competition_count"], completed["result_count"]), (1, 2))
        self.assertEqual(
            [result["team_name"] for result in ongoing["competitions"][0]["results"]],
            ["Alpha", "Beta"],
        )
        self.assertEqual(ongoing["competitions"][0]["best_quantile"], 95.0)
        self.assertEqual(completed["competitions"][0]["best_quantile"], 96.0)
        self.assertTrue(
            all(
                result["result_kind"] == "official_final"
                and result["rank_kind"] == "official_private"
                and result["score_kind"] == "official_private"
                and result["result_time"] == "2026-06-01T00:00:00Z"
                for result in completed["competitions"][0]["results"]
            )
        )
        validate_public_payload(payload)


class OngoingBoardTests(unittest.TestCase):
    def build_board(self):
        source = FakeSource(
            (
                competition("big-medals", api_team_count=1000, awards_points=True),
                snapshot(
                    board_entry("Alpha", 5, "0.99"),
                    board_entry("Beta", 60, "0.90"),
                    team_count=1000,
                ),
            ),
            (
                competition("small-medals", awards_points=True),
                snapshot(board_entry("Alpha", 15, "0.80"), board_entry("Beta", 3, "0.95")),
            ),
            (
                competition("no-points"),
                snapshot(board_entry("Alpha", 2, "0.70")),
            ),
        )
        return build(source, ("Alpha", "Beta", "Gamma"))["ongoing_teams"]

    def test_medal_and_top_percent_counts_are_separate(self) -> None:
        alpha, beta = self.build_board()[:2]
        self.assertEqual(alpha["name"], "Alpha")
        # Gold in a 1000-team board, silver in a 100-team board, and two top 5% results.
        self.assertEqual(
            (alpha["gold_count"], alpha["silver_count"], alpha["bronze_count"]), (1, 1, 0)
        )
        self.assertEqual((alpha["medal_count"], alpha["top_percent_count"]), (2, 2))
        self.assertEqual(
            (beta["gold_count"], beta["silver_count"], beta["bronze_count"]), (1, 0, 1)
        )
        self.assertEqual((beta["medal_count"], beta["top_percent_count"]), (2, 1))

    def test_equal_medal_counts_are_broken_by_top_percent_count(self) -> None:
        board = self.build_board()
        self.assertEqual(
            [(team["name"], team["position"]) for team in board],
            [("Alpha", 1), ("Beta", 2), ("Gamma", None)],
        )

    def test_teams_without_a_counted_result_stay_unranked(self) -> None:
        gamma = self.build_board()[2]
        self.assertEqual(gamma["medal_count"], 0)
        self.assertEqual(gamma["top_percent_count"], 0)
        self.assertIsNone(gamma["position"])

    def test_authenticated_private_rank_replaces_the_public_medal_and_top_percent(self) -> None:
        source = FakeSource(
            (
                competition("ended-public", deadline=ENDED_DEADLINE, awards_points=True),
                snapshot(board_entry("Alpha", 60, "0.90")),
            )
        )
        payload = build(
            source,
            authenticated_submission_scores=(
                authenticated("Alpha", "0.90", "0.95", rank=4, team_count=100),
            ),
        )

        entry = payload["competitions"][0]["entries"][0]
        self.assertEqual(entry["medal_candidate"], "gold")
        team = payload["ongoing_teams"][0]
        self.assertEqual((team["gold_count"], team["medal_count"]), (1, 1))
        self.assertEqual(team["top_percent_count"], 1)


class LateBoardTests(unittest.TestCase):
    def build_board(self):
        source = FakeSource(
            (
                competition("higher-is-better", deadline=ENDED_DEADLINE),
                snapshot(
                    kind="private",
                    score_order="higher",
                    score_values=("0.90", "0.80", "0.70"),
                ),
            ),
            (
                competition("lower-is-better", deadline=ENDED_DEADLINE),
                snapshot(
                    kind="private",
                    score_order="lower",
                    score_values=("0.10", "0.20", "0.30"),
                ),
            ),
        )
        return build(
            source,
            ("Alpha", "Beta", "Gamma"),
            late_submissions=(
                late("higher-is-better", "Alpha", "0.95", "0.95"),
                late("higher-is-better", "Beta", "0.90", "0.90"),
                late("lower-is-better", "Alpha", "0.05", "0.05"),
                late("lower-is-better", "Beta", "0.05", "0.05"),
            ),
            late_submission_account_count=1,
        )

    def test_only_results_better_than_the_original_winner_are_counted(self) -> None:
        payload = self.build_board()
        beats_winner = {
            (item["slug"], entry["team_name"]): entry["late_beats_winner"]
            for item in payload["competitions"]
            for entry in item["entries"]
        }
        self.assertTrue(beats_winner[("higher-is-better", "Alpha")])
        # Matching the winning score is not better than it.
        self.assertFalse(beats_winner[("higher-is-better", "Beta")])
        self.assertTrue(beats_winner[("lower-is-better", "Alpha")])
        self.assertTrue(beats_winner[("lower-is-better", "Beta")])

    def test_board_ranks_by_that_count_only(self) -> None:
        board = self.build_board()["late_teams"]
        self.assertEqual(
            board,
            [
                {"position": 1, "name": "Alpha", "beat_winner_count": 2},
                {"position": 2, "name": "Beta", "beat_winner_count": 1},
                {"position": None, "name": "Gamma", "beat_winner_count": 0},
            ],
        )

    def test_a_teams_own_winning_score_still_counts_as_the_score_to_beat(self) -> None:
        source = FakeSource(
            (
                competition("own-win", deadline=ENDED_DEADLINE),
                snapshot(
                    board_entry("Alpha", 1, "0.90"),
                    kind="private",
                    score_order="higher",
                    score_values=("0.90", "0.80", "0.70"),
                ),
            )
        )
        payload = build(
            source,
            late_submissions=(late("own-win", "Alpha", "0.85", "0.85"),),
            late_submission_account_count=1,
        )

        entry = payload["competitions"][0]["entries"][0]
        self.assertFalse(entry["late_beats_winner"])
        # The team's own official score leaves the pool when estimating a late rank.
        self.assertEqual(entry["late_rank"], 1)
        self.assertEqual(payload["late_teams"][0]["beat_winner_count"], 0)

    def test_unknown_score_direction_publishes_no_late_rank_or_win(self) -> None:
        source = FakeSource(
            (
                competition("unknown-order", deadline=ENDED_DEADLINE),
                snapshot(kind="private", score_values=("0.90", "0.80")),
            )
        )
        payload = build(
            source,
            late_submissions=(late("unknown-order", "Alpha", "0.95", "0.95"),),
            late_submission_account_count=1,
        )

        entry = payload["competitions"][0]["entries"][0]
        self.assertIsNone(entry["late_rank"])
        self.assertFalse(entry["late_beats_winner"])


if __name__ == "__main__":
    unittest.main()
