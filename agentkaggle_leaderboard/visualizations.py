from __future__ import annotations

from typing import Any


GROUP_KEYS = ("ongoing", "completed")


def _result(
    entry: dict[str, Any],
    *,
    rank: Any,
    team_count: Any,
    top_percent: Any,
    score: str,
    kinds: tuple[str, str, str],
    result_time: str,
    provenance: str,
) -> dict[str, object]:
    result_kind, rank_kind, score_kind = kinds
    top_percent = float(top_percent)
    return {
        "team_name": str(entry["team_name"]),
        "rank": int(rank),
        "leaderboard_team_count": int(team_count),
        "top_percent": top_percent,
        "quantile": round(100.0 - top_percent, 4),
        "score": score,
        "result_kind": result_kind,
        "rank_kind": rank_kind,
        "score_kind": score_kind,
        "result_time": result_time,
        "is_official": result_kind != "late_estimate",
        "provenance": provenance,
    }


def _official_result(
    competition: dict[str, Any],
    entry: dict[str, Any],
) -> dict[str, object] | None:
    rank = entry["rank"]
    top_percent = entry["top_percent"]
    if rank is None or top_percent is None:
        return None

    score = str(entry["score"])
    team_count = int(competition["leaderboard_team_count"])
    result_time = str(entry["submission_date"] or "")
    private_score = str(entry["authenticated_private_score"] or "")

    if competition["state"] == "active":
        kinds = ("official_current", "official_public", "official_public")
        provenance = "Official current Public rank and score"
    elif competition["leaderboard_kind"] == "private":
        kinds = ("official_final", "official_private", "official_private")
        provenance = "Official final Private rank and score"
    elif not private_score:
        kinds = ("official_public", "official_public", "official_public")
        provenance = "Official Public rank and score at snapshot"
    else:
        score = private_score
        result_time = str(entry["authenticated_private_submission_date"] or result_time)
        private_rank = (
            entry["authenticated_private_rank"],
            entry["authenticated_private_top_percent"],
            entry["authenticated_private_rank_team_count"],
        )
        if all(value is not None for value in private_rank):
            rank, top_percent, team_count = private_rank
            kinds = ("official_final", "authenticated_private", "authenticated_private")
            provenance = "Authenticated final Private rank and score"
        else:
            kinds = ("official_public", "official_public", "authenticated_private")
            provenance = "Official Public rank with authenticated Private score"

    return _result(
        entry,
        rank=rank,
        team_count=team_count,
        top_percent=top_percent,
        score=score,
        kinds=kinds,
        result_time=result_time,
        provenance=provenance,
    )


def _late_result(entry: dict[str, Any]) -> dict[str, object] | None:
    rank = entry["late_rank"]
    top_percent = entry["late_top_percent"]
    team_count = entry["late_rank_team_count"]
    private_score = str(entry["late_private_score"] or "")
    score = private_score or str(entry["late_public_score"] or "")
    if rank is None or top_percent is None or team_count is None or not score:
        return None

    return _result(
        entry,
        rank=rank,
        team_count=team_count,
        top_percent=top_percent,
        score=score,
        kinds=(
            "late_estimate",
            "late_estimate",
            "late_private" if private_score else "late_public",
        ),
        result_time=str(entry["late_submission_date"] or ""),
        provenance=(
            "Late Private score rank estimate"
            if private_score
            else "Late Public score rank estimate"
        ),
    )


def _selected_result(
    competition: dict[str, Any],
    entry: dict[str, Any],
) -> dict[str, object] | None:
    official = _official_result(competition, entry)
    if competition["state"] != "ended":
        return official
    if competition["leaderboard_kind"] == "private" and official is not None:
        return official

    candidates = [candidate for candidate in (official, _late_result(entry)) if candidate]
    return min(
        candidates,
        key=lambda candidate: (
            float(candidate["top_percent"]),
            not bool(candidate["is_official"]),
            int(candidate["rank"]),
        ),
        default=None,
    )


def build_visualizations(
    competitions: list[dict[str, Any]],
) -> dict[str, dict[str, object]]:
    """Build the chart datasets for active and completed competitions."""

    grouped: dict[str, list[dict[str, object]]] = {key: [] for key in GROUP_KEYS}
    for competition in competitions:
        state = str(competition["state"])
        if state not in {"active", "ended"}:
            continue

        results = [
            result
            for entry in competition["entries"]
            if (result := _selected_result(competition, entry)) is not None
        ]
        if not results:
            continue
        results.sort(
            key=lambda result: (
                -float(result["quantile"]),
                int(result["rank"]),
                str(result["team_name"]).casefold(),
            )
        )
        grouped["ongoing" if state == "active" else "completed"].append(
            {
                "slug": str(competition["slug"]),
                "title": str(competition["title"]),
                "url": str(competition["url"]),
                "leaderboard_kind": str(competition["leaderboard_kind"]),
                "result_count": len(results),
                "best_quantile": results[0]["quantile"],
                "results": results,
            }
        )

    groups: dict[str, dict[str, object]] = {}
    for key, group_competitions in grouped.items():
        group_competitions.sort(
            key=lambda competition: (
                -float(competition["best_quantile"]),
                str(competition["title"]).casefold(),
            )
        )
        groups[key] = {
            "competition_count": len(group_competitions),
            "result_count": sum(
                int(competition["result_count"]) for competition in group_competitions
            ),
            "competitions": group_competitions,
        }
    return groups
