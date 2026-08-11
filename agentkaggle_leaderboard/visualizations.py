from __future__ import annotations

from typing import Any


GROUP_KEYS = ("ongoing", "completed")


def _quantile(top_percent: float) -> float:
    return round(100.0 - top_percent, 4)


def _official_result(
    competition: dict[str, Any],
    entry: dict[str, Any],
) -> dict[str, object] | None:
    rank = entry["rank"]
    top_percent = entry["top_percent"]
    if rank is None or top_percent is None:
        return None

    state = str(competition["state"])
    leaderboard_kind = str(competition["leaderboard_kind"])
    score = str(entry["score"])
    if state == "active":
        result_kind = "official_current"
        rank_kind = "official_public"
        score_kind = "official_public"
        provenance = "Official current Public rank and score"
    elif leaderboard_kind == "private":
        result_kind = "official_final"
        rank_kind = "official_private"
        score_kind = "official_private"
        provenance = "Official final Private rank and score"
    else:
        result_kind = "official_public"
        rank_kind = "official_public"
        authenticated_private_score = str(entry["authenticated_private_score"] or "")
        if authenticated_private_score:
            score = authenticated_private_score
            score_kind = "authenticated_private"
            provenance = "Official Public rank with authenticated Private score"
        else:
            score_kind = "official_public"
            provenance = "Official Public rank and score at snapshot"

    numeric_top_percent = float(top_percent)
    return {
        "team_name": str(entry["team_name"]),
        "rank": int(rank),
        "leaderboard_team_count": int(competition["leaderboard_team_count"]),
        "top_percent": numeric_top_percent,
        "quantile": _quantile(numeric_top_percent),
        "score": score,
        "result_kind": result_kind,
        "rank_kind": rank_kind,
        "score_kind": score_kind,
        "is_official": True,
        "provenance": provenance,
    }


def _late_result(entry: dict[str, Any]) -> dict[str, object] | None:
    rank = entry["late_rank"]
    top_percent = entry["late_top_percent"]
    team_count = entry["late_rank_team_count"]
    if rank is None or top_percent is None or team_count is None:
        return None

    private_score = str(entry["late_private_score"] or "")
    public_score = str(entry["late_public_score"] or "")
    score = private_score or public_score
    if not score:
        return None

    numeric_top_percent = float(top_percent)
    return {
        "team_name": str(entry["team_name"]),
        "rank": int(rank),
        "leaderboard_team_count": int(team_count),
        "top_percent": numeric_top_percent,
        "quantile": _quantile(numeric_top_percent),
        "score": score,
        "result_kind": "late_estimate",
        "rank_kind": "late_estimate",
        "score_kind": "late_private" if private_score else "late_public",
        "is_official": False,
        "provenance": (
            "Late Private score rank estimate"
            if private_score
            else "Late Public score rank estimate"
        ),
    }


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
    """Build the two chart datasets for active and completed competitions."""

    groups: dict[str, dict[str, object]] = {
        key: {"competition_count": 0, "result_count": 0, "competitions": []}
        for key in GROUP_KEYS
    }
    for competition in competitions:
        state = str(competition["state"])
        group_key = "ongoing" if state == "active" else "completed" if state == "ended" else ""
        if not group_key:
            continue

        results = [
            result
            for entry in competition["entries"]
            if (result := _selected_result(competition, entry)) is not None
        ]
        results.sort(
            key=lambda result: (
                -float(result["quantile"]),
                int(result["rank"]),
                str(result["team_name"]).casefold(),
            )
        )
        if not results:
            continue

        group_competitions = groups[group_key]["competitions"]
        if not isinstance(group_competitions, list):
            raise TypeError("Visualization competitions must be a list")
        group_competitions.append(
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

    for group in groups.values():
        group_competitions = group["competitions"]
        if not isinstance(group_competitions, list):
            raise TypeError("Visualization competitions must be a list")
        group_competitions.sort(
            key=lambda competition: (
                -float(competition["best_quantile"]),
                str(competition["title"]).casefold(),
            )
        )
        group["competition_count"] = len(group_competitions)
        group["result_count"] = sum(
            int(competition["result_count"])
            for competition in group_competitions
        )
    return groups
