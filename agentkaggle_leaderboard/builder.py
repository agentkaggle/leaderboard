from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable

from requests import exceptions as requests_exceptions

from .kaggle_source import (
    InvalidKaggleResponse,
    KaggleAuthenticationError,
    UnsafePrivateLeaderboard,
)
from .medals import MEDALS, medal_candidate
from .models import (
    AuthenticatedSubmissionScoreEntry,
    Competition,
    CompetitionSource,
    LateSubmissionEntry,
    LeaderboardEntry,
    LeaderboardSnapshot,
    ScanFailure,
)
from .settings import Settings, normalize_team_name
from .visualizations import build_visualizations


ProgressCallback = Callable[[int, int], None]
MINIMUM_SCAN_SUCCESS_RATIO = 0.5
TOP_PERCENT_THRESHOLD = 5.0
EXCLUDED_COMPETITION_SLUGS = frozenset(
    {
        "ai-agent-security-multi-step-tool-attacks",
        "orbit-wars",
        "restaurant-revenue-prediction2",
    }
)
# Maps a Kaggle team/account name to the student's display name, so every
# team a student competes under is shown and ranked as one person.
STUDENT_NAMES_BY_TEAM = {
    "FlameZywoo": "李孟涵",
    "zgdllt": "李孟涵",
    "Hutao715": "Liu Yitong",
    "henrytb": "黄镜元",
    "Jingyuan Huang": "黄镜元",
    "WestLakeDiver": "何宸禹",
    "TeamDock": "Boshi Zhang",
    "SoraGinko": "tingjun wu",
    "lynx": "郭洪恺",
    "Lynx Guo": "郭洪恺",
    "pones_kaggle": "yi duo pang",
    "Pones": "yi duo pang",
    "PYD966": "yi duo pang",
    "kimlim": "Justin 林钲凯",
    "Justin Kimlim": "Justin 林钲凯",
}
_STUDENT_NAME_BY_NORMALIZED_TEAM = {
    normalize_team_name(team): student for team, student in STUDENT_NAMES_BY_TEAM.items()
}


def _display_team_name(team_name: str) -> str:
    return _STUDENT_NAME_BY_NORMALIZED_TEAM.get(normalize_team_name(team_name), team_name)


def _iso_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _competition_state(deadline: datetime | None, generated_at: datetime) -> str:
    if deadline is None:
        return "unknown"
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return "active" if deadline >= generated_at else "ended"


def _numeric_value(value: object) -> Decimal | None:
    try:
        score = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        return None
    return score if score.is_finite() else None


def _is_better(candidate: Decimal, reference: Decimal, score_order: str) -> bool:
    return candidate > reference if score_order == "higher" else candidate < reference


def _safe_failure_kind(exc: BaseException) -> str:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in {401, 403} or isinstance(exc, KaggleAuthenticationError):
        return "access_denied"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if isinstance(
        exc,
        (
            TimeoutError,
            ConnectionError,
            requests_exceptions.ConnectionError,
            requests_exceptions.Timeout,
        ),
    ):
        return "network"
    if isinstance(exc, UnsafePrivateLeaderboard):
        return "unsafe_private_leaderboard"
    if isinstance(exc, InvalidKaggleResponse):
        return "invalid_response"
    return "unexpected"


def _new_entry(team_name: str) -> dict[str, object]:
    """One published row per team and competition, with every field defaulted."""
    return {
        "team_name": team_name,
        "rank": None,
        "top_percent": None,
        "score": "",
        "authenticated_private_score": "",
        "authenticated_private_submission_date": "",
        "authenticated_private_rank": None,
        "authenticated_private_top_percent": None,
        "authenticated_private_rank_team_count": None,
        "submission_date": "",
        "medal_candidate": "unavailable",
        "late_public_score": "",
        "late_private_score": "",
        "late_submission_date": "",
        "late_rank": None,
        "late_top_percent": None,
        "late_rank_team_count": None,
        "late_beats_winner": False,
    }


def _public_competition(
    competition: Competition,
    snapshot: LeaderboardSnapshot | None,
    generated_at: datetime,
) -> dict[str, object]:
    best_by_team: dict[str, LeaderboardEntry] = {}
    for match in snapshot.matches if snapshot is not None else ():
        key = normalize_team_name(_display_team_name(match.configured_team_name))
        existing = best_by_team.get(key)
        if existing is None or match.rank < existing.rank:
            best_by_team[key] = match

    entries: list[dict[str, object]] = []
    if snapshot is not None:  # Matches only exist alongside a leaderboard snapshot.
        for match in sorted(
            best_by_team.values(),
            key=lambda item: (item.rank, item.configured_team_name),
        ):
            entry = _new_entry(_display_team_name(match.configured_team_name))
            entry.update(
                rank=match.rank,
                top_percent=round((match.rank / snapshot.team_count) * 100, 4),
                score=match.score,
                submission_date=match.submission_date,
                medal_candidate=(
                    medal_candidate(match.rank, snapshot.team_count)
                    if competition.awards_points
                    else "not_eligible"
                ),
            )
            entries.append(entry)

    return {
        "slug": competition.slug,
        "title": competition.title,
        "url": competition.url,
        "category": competition.category,
        "reward": competition.reward,
        "deadline": _iso_utc(competition.deadline),
        "state": _competition_state(competition.deadline, generated_at),
        "leaderboard_kind": snapshot.kind if snapshot is not None else "unavailable",
        "leaderboard_team_count": snapshot.team_count if snapshot is not None else 0,
        "api_team_count": competition.api_team_count,
        "awards_points": competition.awards_points,
        "entries": entries,
    }


def _public_late_submissions(
    late_submissions: tuple[LateSubmissionEntry, ...],
    score_orders: dict[str, str],
) -> list[dict[str, object]]:
    def numeric_score(entry: LateSubmissionEntry) -> Decimal | None:
        for value in (entry.private_score, entry.public_score):
            if (score := _numeric_value(value)) is not None:
                return score
        return None

    def is_better(candidate: LateSubmissionEntry, existing: LateSubmissionEntry) -> bool:
        score_order = score_orders.get(candidate.competition_slug, "unknown")
        candidate_score = numeric_score(candidate)
        existing_score = numeric_score(existing)
        if score_order in {"higher", "lower"} and candidate_score is not None:
            if existing_score is None:
                return True
            if candidate_score != existing_score:
                return _is_better(candidate_score, existing_score, score_order)
        return candidate.submission_date > existing.submission_date

    unique: dict[tuple[str, str], LateSubmissionEntry] = {}
    for entry in late_submissions:
        key = (
            entry.competition_slug,
            normalize_team_name(_display_team_name(entry.configured_team_name)),
        )
        existing = unique.get(key)
        if existing is None or is_better(entry, existing):
            unique[key] = entry

    return [
        {
            "competition_slug": entry.competition_slug,
            "competition_title": entry.competition_title,
            "competition_url": entry.competition_url,
            "deadline": _iso_utc(entry.deadline),
            "team_name": _display_team_name(entry.configured_team_name),
            "public_score": entry.public_score,
            "private_score": entry.private_score,
            "submission_date": _iso_utc(entry.submission_date),
        }
        for entry in sorted(
            unique.values(),
            key=lambda entry: (
                -entry.submission_date.timestamp(),
                entry.competition_title.casefold(),
                _display_team_name(entry.configured_team_name).casefold(),
            ),
        )
    ]


def _scores_match(left: object, right: object) -> bool:
    left_numeric = _numeric_value(left)
    right_numeric = _numeric_value(right)
    if left_numeric is not None and right_numeric is not None:
        return left_numeric == right_numeric
    return str(left or "").strip() == str(right or "").strip()


def _entries(competition: dict[str, object]) -> list[dict[str, object]]:
    entries = competition["entries"]
    if not isinstance(entries, list):
        raise TypeError("Competition entries must be a list")
    return entries


def _merge_authenticated_private_scores(
    competitions: list[dict[str, object]],
    authenticated_scores: tuple[AuthenticatedSubmissionScoreEntry, ...],
) -> int:
    scores_by_team: dict[tuple[str, str], list[AuthenticatedSubmissionScoreEntry]] = {}
    for score in authenticated_scores:
        key = (
            score.competition_slug,
            normalize_team_name(_display_team_name(score.configured_team_name)),
        )
        scores_by_team.setdefault(key, []).append(score)

    matched_count = 0
    for competition in competitions:
        if competition["leaderboard_kind"] != "public" or competition["state"] != "ended":
            continue
        slug = str(competition["slug"])
        for entry in _entries(competition):
            candidates = [
                candidate
                for candidate in scores_by_team.get(
                    (slug, normalize_team_name(str(entry["team_name"]))), []
                )
                if _scores_match(candidate.public_score, entry["score"])
            ]
            private_scores = {
                candidate.private_score.strip()
                for candidate in candidates
                if candidate.private_score.strip()
            }
            if len(private_scores) != 1:
                continue
            private_score = private_scores.pop()
            matches = [
                candidate
                for candidate in candidates
                if candidate.private_score.strip() == private_score
            ]
            newest = max(matches, key=lambda candidate: candidate.submission_date)
            entry["authenticated_private_score"] = private_score
            entry["authenticated_private_submission_date"] = _iso_utc(newest.submission_date)
            private_ranks = {
                (candidate.private_rank, candidate.private_rank_team_count)
                for candidate in matches
                if candidate.private_rank is not None
                and candidate.private_rank_team_count is not None
                and candidate.private_rank_team_count > 0
            }
            if len(private_ranks) == 1:
                private_rank, private_team_count = private_ranks.pop()
                entry["authenticated_private_rank"] = private_rank
                entry["authenticated_private_top_percent"] = round(
                    (private_rank / private_team_count) * 100, 4
                )
                entry["authenticated_private_rank_team_count"] = private_team_count
                if competition["awards_points"]:
                    entry["medal_candidate"] = medal_candidate(private_rank, private_team_count)
            matched_count += 1
    return matched_count


def _merge_late_results_into_competitions(
    competitions: list[dict[str, object]],
    late_submissions: list[dict[str, object]],
    snapshots: dict[str, LeaderboardSnapshot],
) -> None:
    competitions_by_slug = {
        str(competition["slug"]): competition for competition in competitions
    }
    # Only the competitions that actually received a late submission are compared.
    scored_slugs = {
        str(late_submission["competition_slug"]) for late_submission in late_submissions
    }
    # score_values keeps the leaderboard's rank order, so index 0 is the winner's
    # score. Non-numeric values stay in place as None so a blank winning score
    # suppresses the winner comparison instead of promoting the runner-up.
    board_scores_by_slug = {
        slug: tuple(_numeric_value(value) for value in snapshots[slug].score_values)
        for slug in scored_slugs
        if slug in snapshots
    }

    for late_submission in late_submissions:
        slug = str(late_submission["competition_slug"])
        competition = competitions_by_slug.get(slug)
        if competition is None:
            competition = {
                "slug": slug,
                "title": late_submission["competition_title"],
                "url": late_submission["competition_url"],
                "category": "Entered",
                "reward": "",
                "deadline": late_submission["deadline"],
                "state": "ended",
                "leaderboard_kind": "unavailable",
                "leaderboard_team_count": 0,
                "api_team_count": 0,
                "awards_points": False,
                "entries": [],
            }
            competitions.append(competition)
            competitions_by_slug[slug] = competition

        entries = _entries(competition)
        team_key = normalize_team_name(str(late_submission["team_name"]))
        entry = next(
            (
                item
                for item in entries
                if normalize_team_name(str(item["team_name"])) == team_key
            ),
            None,
        )
        if entry is None:
            entry = _new_entry(str(late_submission["team_name"]))
            entries.append(entry)

        entry["late_public_score"] = late_submission["public_score"]
        entry["late_private_score"] = late_submission["private_score"]
        entry["late_submission_date"] = late_submission["submission_date"]

        snapshot = snapshots.get(slug)
        late_score = next(
            (
                score
                for value in (
                    late_submission["private_score"],
                    late_submission["public_score"],
                )
                if (score := _numeric_value(value)) is not None
            ),
            None,
        )
        board_scores = board_scores_by_slug.get(slug, ())
        ranked_scores = [score for score in board_scores if score is not None]
        if (
            snapshot is None
            or late_score is None
            or not ranked_scores
            or snapshot.team_count <= 0
            or snapshot.score_order not in {"higher", "lower"}
        ):
            continue

        order = snapshot.score_order
        winner_score = board_scores[0]
        entry["late_beats_winner"] = winner_score is not None and _is_better(
            late_score, winner_score, order
        )

        # The late score replaces the team's own official score in the distribution.
        official_score = _numeric_value(entry["score"])
        better_count = sum(_is_better(score, late_score, order) for score in ranked_scores)
        if (
            official_score is not None
            and official_score in ranked_scores
            and _is_better(official_score, late_score, order)
        ):
            better_count -= 1
        # A late estimate can never place below the last team on the board it is
        # measured against, so Top% stays inside the published 0-100 range.
        late_rank = min(better_count + 1, snapshot.team_count)
        entry["late_rank"] = late_rank
        entry["late_top_percent"] = round((late_rank / snapshot.team_count) * 100, 4)
        entry["late_rank_team_count"] = snapshot.team_count


def _sort_entries(competitions: list[dict[str, object]]) -> None:
    """Order rows by the rank each row actually displays, so the table reads in order."""

    def key(entry: dict[str, object]) -> tuple[bool, int, str]:
        rank = entry["authenticated_private_rank"]
        if rank is None:
            rank = entry["rank"]
        return (
            rank is None,
            int(rank) if rank is not None else 0,
            str(entry["team_name"]).casefold(),
        )

    for competition in competitions:
        _entries(competition).sort(key=key)


def _ranked(
    summaries: list[dict[str, object]],
    sort_key: Callable[[dict], tuple],
    is_ranked: Callable[[dict], bool],
) -> list[dict[str, object]]:
    """Order a board and number only the teams that have something to rank."""
    ordered = sorted(summaries, key=sort_key)
    position = 0
    for summary in ordered:
        if is_ranked(summary):
            position += 1
            summary["position"] = position
    return ordered


def _ongoing_board(
    teams: tuple[str, ...],
    competitions: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Rank official participation by medal-zone count, then by Top 5% count."""
    medals = {team: Counter() for team in teams}
    top_percent_counts = {team: 0 for team in teams}

    for competition in competitions:
        for entry in _entries(competition):
            team = str(entry["team_name"])
            if team not in medals:
                continue
            if entry["medal_candidate"] in MEDALS:
                medals[team][entry["medal_candidate"]] += 1
            # An authenticated final Private rank replaces the Public one when known.
            top_percent = entry["authenticated_private_top_percent"]
            if top_percent is None:
                top_percent = entry["top_percent"]
            if top_percent is not None and float(top_percent) <= TOP_PERCENT_THRESHOLD:
                top_percent_counts[team] += 1

    summaries = [
        {
            "position": None,
            "name": team,
            "gold_count": medals[team]["gold"],
            "silver_count": medals[team]["silver"],
            "bronze_count": medals[team]["bronze"],
            "medal_count": sum(medals[team].values()),
            "top_percent_count": top_percent_counts[team],
        }
        for team in teams
    ]
    return _ranked(
        summaries,
        lambda summary: (
            -int(summary["medal_count"]),
            -int(summary["top_percent_count"]),
            -int(summary["gold_count"]),
            -int(summary["silver_count"]),
            str(summary["name"]).casefold(),
        ),
        lambda summary: bool(summary["medal_count"] or summary["top_percent_count"]),
    )


def _late_board(
    teams: tuple[str, ...],
    competitions: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Rank post-deadline work by how often it beat the original winning score."""
    beat_winner_counts = {team: 0 for team in teams}
    for competition in competitions:
        for entry in _entries(competition):
            team = str(entry["team_name"])
            if entry["late_beats_winner"] and team in beat_winner_counts:
                beat_winner_counts[team] += 1

    summaries = [
        {
            "position": None,
            "name": team,
            "beat_winner_count": beat_winner_counts[team],
        }
        for team in teams
    ]
    return _ranked(
        summaries,
        lambda summary: (
            -int(summary["beat_winner_count"]),
            str(summary["name"]).casefold(),
        ),
        lambda summary: bool(summary["beat_winner_count"]),
    )


def build_leaderboard(
    source: CompetitionSource,
    settings: Settings,
    *,
    max_competitions: int | None = None,
    generated_at: datetime | None = None,
    progress: ProgressCallback | None = None,
    late_submissions: tuple[LateSubmissionEntry, ...] = (),
    authenticated_submission_scores: tuple[AuthenticatedSubmissionScoreEntry, ...] = (),
    late_submission_account_count: int = 0,
    late_submission_failure_kinds: tuple[str, ...] = (),
) -> dict[str, object]:
    generated_at = generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    competitions = source.list_competitions(max_competitions=max_competitions)
    if not competitions:
        raise RuntimeError("Kaggle returned no competitions")
    snapshots: dict[str, LeaderboardSnapshot] = {}
    failures: list[ScanFailure] = []

    with ThreadPoolExecutor(max_workers=settings.workers) as executor:
        futures = {
            executor.submit(
                source.get_leaderboard, competition, settings.normalized_teams
            ): competition
            for competition in competitions
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            competition = futures[future]
            try:
                snapshots[competition.slug] = future.result()
            except Exception as exc:  # Each competition is an independent, best-effort source.
                failures.append(ScanFailure(competition.slug, _safe_failure_kind(exc)))
            if progress:
                progress(completed, len(competitions))

    if not snapshots:
        raise RuntimeError("Kaggle returned no usable competition leaderboards")
    if len(snapshots) / len(competitions) < MINIMUM_SCAN_SUCCESS_RATIO:
        raise RuntimeError("Kaggle scan was too degraded to replace the last good snapshot")

    public_late_submissions = [
        entry
        for entry in _public_late_submissions(
            late_submissions,
            {slug: snapshot.score_order for slug, snapshot in snapshots.items()},
        )
        if str(entry["competition_slug"]) not in EXCLUDED_COMPETITION_SLUGS
    ]
    late_competition_slugs = {
        str(entry["competition_slug"]) for entry in public_late_submissions
    }
    public_competitions = [
        _public_competition(competition, snapshots.get(competition.slug), generated_at)
        for competition in competitions
        if competition.slug not in EXCLUDED_COMPETITION_SLUGS
        and (
            (competition.slug in snapshots and bool(snapshots[competition.slug].matches))
            or competition.slug in late_competition_slugs
        )
    ]
    _merge_late_results_into_competitions(
        public_competitions, public_late_submissions, snapshots
    )
    authenticated_private_score_count = _merge_authenticated_private_scores(
        public_competitions, authenticated_submission_scores
    )
    _sort_entries(public_competitions)
    public_competitions.sort(
        key=lambda item: (
            item["state"] != "active",
            str(item["deadline"] or "0000"),
            str(item["title"]).casefold(),
        )
    )

    truncated = max_competitions is not None and len(competitions) >= max_competitions
    display_teams = tuple(dict.fromkeys(_display_team_name(team) for team in settings.teams))
    return {
        "schema_version": 10,
        "generated_at": _iso_utc(generated_at),
        "status": (
            "partial" if failures or late_submission_failure_kinds or truncated else "ready"
        ),
        "summary": {
            "tracked_team_count": len(display_teams),
            "discovered_competition_count": len(competitions),
            "scanned_competition_count": len(snapshots),
            "failed_competition_count": len(failures),
            "matched_competition_count": len(public_competitions),
            "participation_count": sum(len(_entries(item)) for item in public_competitions),
            "late_submission_account_count": late_submission_account_count,
            "failed_late_submission_account_count": len(late_submission_failure_kinds),
            "late_submission_competition_count": len(late_competition_slugs),
            "late_submission_count": len(public_late_submissions),
            "authenticated_private_score_count": authenticated_private_score_count,
            "late_submission_error_counts": dict(
                sorted(Counter(late_submission_failure_kinds).items())
            ),
            "truncated": truncated,
            "error_counts": dict(sorted(Counter(failure.kind for failure in failures).items())),
        },
        "ongoing_teams": _ongoing_board(display_teams, public_competitions),
        "late_teams": _late_board(display_teams, public_competitions),
        "competitions": public_competitions,
        "late_submissions": public_late_submissions,
        "visualizations": build_visualizations(public_competitions),
        "methodology": {
            "rank": (
                "Final authenticated Private Rank from each account's entered competition "
                "metadata is preferred after the deadline; otherwise Rank comes from Kaggle's "
                "complete leaderboard CSV."
            ),
            "top_percent": (
                "Each team contributes at most once per competition using its preferred official "
                "rank, divided by the team count of the leaderboard that rank came from, "
                "multiplied by 100."
            ),
            "score": "Score is preserved as text exactly as provided by Kaggle.",
            "authenticated_private_score": (
                "After a competition ends, an authenticated pre-deadline submission's private "
                "score and final Private Rank are shown only when its public score uniquely "
                "matches the team's current official public leaderboard score. The rank is read "
                "from that authenticated account's entered competition metadata, never inferred "
                "from a public leaderboard."
            ),
            "late_submission": (
                "The best completed post-deadline result per team and competition, returned by "
                "the authenticated account's My Submissions API. Score direction is inferred "
                "from the official leaderboard; the latest result is used when direction is "
                "unknown. A starred late rank compares that score with the complete leaderboard "
                "score distribution; it is not Kaggle's official Rank."
            ),
            "medal_candidate": (
                "Shown only when Kaggle marks the competition as awarding points. It remains a "
                "rank-only estimate: team eligibility, disqualification, verification and active "
                "standings can change it."
            ),
            "ongoing_board": (
                "Official participation only. Counts gold, silver and bronze medal-zone results "
                "and results inside the top 5 percent, then ranks by total medal-zone count and "
                "breaks ties with the top 5 percent count."
            ),
            "late_board": (
                "Post-deadline submissions only. Counts the competitions where a late score is "
                "strictly better than the winning score of the leaderboard that was downloaded, "
                "and ranks by that count. Like the starred late rank this is an estimate: the "
                "late score prefers the private value while the downloaded leaderboard may be "
                "the public one, and the comparison is skipped when the winning score or the "
                "score direction is unknown. No other late statistic is aggregated."
            ),
        },
    }
