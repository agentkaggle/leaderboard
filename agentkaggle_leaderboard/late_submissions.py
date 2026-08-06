from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from kagglesdk.competitions.types.competition_api_service import ApiListSubmissionsRequest
from kagglesdk.competitions.types.competition_enums import SubmissionGroup, SubmissionSortBy

from .kaggle_source import (
    InvalidKaggleResponse,
    _KaggleRequestSource,
    competition_from_api,
    competition_slug,
)
from .models import (
    AuthenticatedSubmissionScoreEntry,
    Competition,
    LateSubmissionEntry,
)
from .settings import normalize_team_name


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class LateSubmissionScan:
    entries: tuple[LateSubmissionEntry, ...]
    authenticated_scores: tuple[AuthenticatedSubmissionScoreEntry, ...]
    discovered_team_names: tuple[str, ...]
    entered_competitions: tuple[Competition, ...]


class KaggleLateSubmissionSource(_KaggleRequestSource):
    CATALOG_PAGE_SIZE = 20
    SUBMISSION_PAGE_SIZE = 100
    MAX_CATALOG_PAGES = 1000
    MAX_SUBMISSION_PAGES = 1000

    def _list_entered_competitions(self) -> list[object]:
        competitions: list[object] = []
        seen_slugs: set[str] = set()
        for page in range(1, self.MAX_CATALOG_PAGES + 1):
            response = self._call_with_retry(
                lambda page=page: self._api.competitions_list(
                    group="entered",
                    category="all",
                    sort_by="latestDeadline",
                    page=page,
                    page_size=self.CATALOG_PAGE_SIZE,
                )
            )
            items = list(response.competitions or []) if response else []
            if not items:
                return competitions

            new_items = []
            for item in items:
                slug = competition_slug(item.ref)
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)
                new_items.append(item)
            if not new_items:
                raise InvalidKaggleResponse("Kaggle returned a repeated entered competition page")
            competitions.extend(new_items)
            if len(items) < self.CATALOG_PAGE_SIZE:
                return competitions

        raise InvalidKaggleResponse("Kaggle entered competition catalog exceeded the page limit")

    def _list_submission_page(self, slug: str, page_token: str):
        request = ApiListSubmissionsRequest()
        request.competition_name = slug
        request.page_size = self.SUBMISSION_PAGE_SIZE
        request.page_token = page_token
        request.group = SubmissionGroup.SUBMISSION_GROUP_ALL
        request.sort_by = SubmissionSortBy.SUBMISSION_SORT_BY_DATE
        with self._api.build_kaggle_client() as client:
            return client.competitions.competition_api_client.list_submissions(request)

    def _competition_submissions(
        self,
        slug: str,
        title: str,
        deadline: datetime | None,
        normalized_teams: dict[str, str],
        *,
        discover_teams: bool,
        include_late_submissions: bool,
        include_authenticated_scores: bool,
    ) -> tuple[
        list[LateSubmissionEntry],
        list[AuthenticatedSubmissionScoreEntry],
        dict[str, str],
    ]:
        entries: list[LateSubmissionEntry] = []
        authenticated_scores: list[AuthenticatedSubmissionScoreEntry] = []
        discovered_teams: dict[str, str] = {}
        page_token = ""
        seen_page_tokens: set[str] = set()
        page_count = 0

        while True:
            page_count += 1
            if page_count > self.MAX_SUBMISSION_PAGES:
                raise InvalidKaggleResponse(
                    "Kaggle submission history exceeded the page limit"
                )
            response = self._call_with_retry(
                lambda page_token=page_token: self._list_submission_page(slug, page_token)
            )
            submissions = list(response.submissions or []) if response else []

            for submission in submissions:
                if submission is None or submission.date is None:
                    continue
                submitted_at = _as_utc(submission.date)
                status_name = str(getattr(submission.status, "name", "")).casefold()
                if status_name != "complete":
                    continue
                raw_team_name = str(submission.team_name or "").strip()
                team_key = normalize_team_name(raw_team_name)
                if not team_key:
                    continue
                configured_name = normalized_teams.get(team_key)
                if discover_teams:
                    discovered_teams.setdefault(team_key, configured_name or raw_team_name)
                    configured_name = configured_name or discovered_teams[team_key]
                if configured_name is None:
                    continue
                public_score = str(submission.public_score or "").strip()
                private_score = str(submission.private_score or "").strip()
                if (
                    include_authenticated_scores
                    and deadline is not None
                    and submitted_at <= deadline
                    and public_score
                    and private_score
                ):
                    authenticated_scores.append(
                        AuthenticatedSubmissionScoreEntry(
                            competition_slug=slug,
                            configured_team_name=configured_name,
                            public_score=public_score,
                            private_score=private_score,
                            submission_date=submitted_at,
                        )
                    )
                if (
                    not include_late_submissions
                    or deadline is None
                    or submitted_at <= deadline
                ):
                    continue
                entries.append(
                    LateSubmissionEntry(
                        competition_slug=slug,
                        competition_title=title,
                        competition_url=f"https://www.kaggle.com/competitions/{slug}",
                        deadline=deadline,
                        configured_team_name=configured_name,
                        public_score=public_score,
                        private_score=private_score,
                        submission_date=submitted_at,
                    )
                )

            next_page_token = str(getattr(response, "next_page_token", "") or "")
            if not include_late_submissions and not include_authenticated_scores:
                break
            if not next_page_token:
                break
            if next_page_token in seen_page_tokens:
                raise InvalidKaggleResponse("Kaggle returned a repeated submission page token")
            seen_page_tokens.add(next_page_token)
            page_token = next_page_token

        return entries, authenticated_scores, discovered_teams

    def collect(
        self,
        normalized_teams: dict[str, str],
        *,
        now: datetime | None = None,
        discover_teams: bool = False,
    ) -> LateSubmissionScan:
        current_time = _as_utc(now or datetime.now(timezone.utc))
        collected: list[LateSubmissionEntry] = []
        collected_authenticated_scores: list[AuthenticatedSubmissionScoreEntry] = []
        discovered_teams: dict[str, str] = {}
        entered_competitions = tuple(
            competition_from_api(item) for item in self._list_entered_competitions()
        )

        for competition in entered_competitions:
            deadline = (
                _as_utc(competition.deadline)
                if competition.deadline is not None
                else None
            )
            include_late_submissions = deadline is not None and deadline < current_time
            include_authenticated_scores = include_late_submissions
            if (
                not discover_teams
                and not include_late_submissions
                and not include_authenticated_scores
            ):
                continue
            entries, authenticated_scores, competition_teams = (
                self._competition_submissions(
                    competition.slug,
                    competition.title,
                    deadline,
                    normalized_teams,
                    discover_teams=discover_teams,
                    include_late_submissions=include_late_submissions,
                    include_authenticated_scores=include_authenticated_scores,
                )
            )
            collected.extend(entries)
            collected_authenticated_scores.extend(authenticated_scores)
            for team_key, team_name in competition_teams.items():
                discovered_teams.setdefault(team_key, team_name)

        unique = {
            (
                entry.competition_slug,
                entry.configured_team_name,
                entry.submission_date,
                entry.public_score,
                entry.private_score,
            ): entry
            for entry in collected
        }
        entries = tuple(
            sorted(
                unique.values(),
                key=lambda entry: (
                    -entry.submission_date.timestamp(),
                    entry.competition_title.casefold(),
                    entry.configured_team_name.casefold(),
                ),
            )
        )
        unique_authenticated_scores = {
            (
                entry.competition_slug,
                entry.configured_team_name,
                entry.submission_date,
                entry.public_score,
                entry.private_score,
            ): entry
            for entry in collected_authenticated_scores
        }
        authenticated_scores = tuple(
            sorted(
                unique_authenticated_scores.values(),
                key=lambda entry: (
                    entry.competition_slug,
                    entry.configured_team_name.casefold(),
                    -entry.submission_date.timestamp(),
                ),
            )
        )
        return LateSubmissionScan(
            entries=entries,
            authenticated_scores=authenticated_scores,
            discovered_team_names=tuple(discovered_teams.values()),
            entered_competitions=entered_competitions,
        )
