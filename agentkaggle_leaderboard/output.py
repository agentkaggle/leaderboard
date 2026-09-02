from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


PUBLIC_KEYS = {
    "top": {
        "schema_version",
        "generated_at",
        "status",
        "summary",
        "ongoing_teams",
        "late_teams",
        "competitions",
        "late_submissions",
        "visualizations",
        "methodology",
    },
    "summary": {
        "tracked_team_count",
        "discovered_competition_count",
        "scanned_competition_count",
        "failed_competition_count",
        "matched_competition_count",
        "participation_count",
        "late_submission_account_count",
        "failed_late_submission_account_count",
        "late_submission_competition_count",
        "late_submission_count",
        "authenticated_private_score_count",
        "late_submission_error_counts",
        "truncated",
        "error_counts",
    },
    "ongoing_teams": {
        "position",
        "name",
        "gold_count",
        "silver_count",
        "bronze_count",
        "medal_count",
        "top_percent_count",
    },
    "late_teams": {"position", "name", "beat_winner_count"},
    "competition": {
        "slug",
        "title",
        "url",
        "category",
        "reward",
        "deadline",
        "state",
        "leaderboard_kind",
        "leaderboard_team_count",
        "api_team_count",
        "awards_points",
        "entries",
    },
    "entry": {
        "team_name",
        "rank",
        "top_percent",
        "score",
        "authenticated_private_score",
        "authenticated_private_submission_date",
        "authenticated_private_rank",
        "authenticated_private_top_percent",
        "authenticated_private_rank_team_count",
        "submission_date",
        "medal_candidate",
        "late_public_score",
        "late_private_score",
        "late_submission_date",
        "late_rank",
        "late_top_percent",
        "late_rank_team_count",
        "late_beats_winner",
    },
    "late_submission": {
        "competition_slug",
        "competition_title",
        "competition_url",
        "deadline",
        "team_name",
        "public_score",
        "private_score",
        "submission_date",
    },
    "visualizations": {"ongoing", "completed"},
    "visualization_group": {"competition_count", "result_count", "competitions"},
    "visualization_competition": {
        "slug",
        "title",
        "url",
        "leaderboard_kind",
        "result_count",
        "best_quantile",
        "results",
    },
    "visualization_result": {
        "team_name",
        "rank",
        "leaderboard_team_count",
        "top_percent",
        "quantile",
        "score",
        "result_kind",
        "rank_kind",
        "score_kind",
        "result_time",
        "is_official",
        "provenance",
    },
    "methodology": {
        "rank",
        "top_percent",
        "score",
        "authenticated_private_score",
        "late_submission",
        "medal_candidate",
        "ongoing_board",
        "late_board",
    },
}
PUBLIC_ERROR_KINDS = {
    "access_denied",
    "not_found",
    "rate_limited",
    "network",
    "unsafe_private_leaderboard",
    "invalid_response",
    "unexpected",
}
PUBLIC_RANK_KINDS = {
    "official_public",
    "official_private",
    "authenticated_private",
    "late_estimate",
}
PUBLIC_SCORE_KINDS = {
    "official_public",
    "official_private",
    "authenticated_private",
    "late_public",
    "late_private",
}


def _require_exact_keys(value: dict[str, Any], expected_name: str, location: str) -> None:
    if set(value) != PUBLIC_KEYS[expected_name]:
        raise ValueError(f"Public payload has unexpected or missing fields at {location}")


def _require_error_counts(counts: Any, label: str) -> None:
    if not isinstance(counts, dict) or not set(counts).issubset(PUBLIC_ERROR_KINDS):
        raise ValueError(f"Public payload has an unsupported {label} error category")
    if not all(isinstance(count, int) and count > 0 for count in counts.values()):
        raise ValueError(f"Public payload has an invalid {label} error count")


def _require_private_rank(entry: dict[str, Any]) -> None:
    values = (
        entry["authenticated_private_rank"],
        entry["authenticated_private_top_percent"],
        entry["authenticated_private_rank_team_count"],
    )
    if all(value is None for value in values):
        return
    if any(value is None for value in values):
        raise ValueError("Public payload has an incomplete authenticated private rank")
    rank, top_percent, team_count = values
    if (
        not isinstance(rank, int)
        or not isinstance(team_count, int)
        or not 0 < rank <= team_count
        or not 0 <= float(top_percent) <= 100
    ):
        raise ValueError("Public payload has an invalid authenticated private rank")


def validate_public_payload(payload: dict[str, Any]) -> None:
    """Fail closed unless every published field is an approved, in-range value."""
    _require_exact_keys(payload, "top", "root")
    _require_exact_keys(payload["summary"], "summary", "summary")
    _require_error_counts(payload["summary"]["error_counts"], "competition")
    _require_error_counts(payload["summary"]["late_submission_error_counts"], "late submission")
    _require_exact_keys(payload["methodology"], "methodology", "methodology")

    for board in ("ongoing_teams", "late_teams"):
        for index, team in enumerate(payload[board]):
            _require_exact_keys(team, board, f"{board}[{index}]")

    for competition_index, competition in enumerate(payload["competitions"]):
        location = f"competitions[{competition_index}]"
        _require_exact_keys(competition, "competition", location)
        for entry_index, entry in enumerate(competition["entries"]):
            _require_exact_keys(entry, "entry", f"{location}.entries[{entry_index}]")
            _require_private_rank(entry)

    for index, submission in enumerate(payload["late_submissions"]):
        _require_exact_keys(submission, "late_submission", f"late_submissions[{index}]")

    _require_exact_keys(payload["visualizations"], "visualizations", "visualizations")
    for group_name, group in payload["visualizations"].items():
        _require_exact_keys(group, "visualization_group", f"visualizations.{group_name}")
        for competition_index, competition in enumerate(group["competitions"]):
            location = f"visualizations.{group_name}.competitions[{competition_index}]"
            _require_exact_keys(competition, "visualization_competition", location)
            for result_index, result in enumerate(competition["results"]):
                _require_exact_keys(
                    result, "visualization_result", f"{location}.results[{result_index}]"
                )
                if not 0 <= float(result["quantile"]) <= 100:
                    raise ValueError("Public payload has an invalid visualization quantile")
                if result["rank_kind"] not in PUBLIC_RANK_KINDS:
                    raise ValueError("Public payload has an invalid visualization rank source")
                if result["score_kind"] not in PUBLIC_SCORE_KINDS:
                    raise ValueError("Public payload has an invalid visualization score source")


def write_json_atomic(payload: dict[str, Any], output_path: Path) -> None:
    validate_public_payload(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary_file:
        temporary_file.write(encoded)
        temporary_name = temporary_file.name
    try:
        os.replace(temporary_name, output_path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
