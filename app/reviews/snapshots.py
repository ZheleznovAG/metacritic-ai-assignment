"""R12/R17: lightweight read-only collection checkpoints shared by builder and UI."""

import hashlib
import json
from dataclasses import dataclass

from catalog.models import Game, GamePlatform
from processing.models import DailyCandidate

from reviews.models import ReviewCollectionJob


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def known_routes(game: Game, audience: str) -> list[GamePlatform]:
    field = "critic_reviews_path" if audience == "critic" else "user_reviews_path"
    return [
        platform
        for platform in game.platforms.order_by("source_platform_id", "id")
        if getattr(platform, field)
    ]


@dataclass(frozen=True)
class CollectionState:
    checkpoint: str
    jobs: list[ReviewCollectionJob] | None
    reason: str | None


def collection_state(
    game: Game, audience: str, routes: list[GamePlatform] | None = None
) -> CollectionState:
    if routes is None:
        routes = known_routes(game, audience)
    # Daily order wins over completion/arrival times: an older backlog route can finish later.
    # One cohort prevents a current platform snapshot from being combined with yesterday's.
    candidate = (
        DailyCandidate.objects.filter(game=game, state="processed")
        .order_by("-cycle__business_date", "-id")
        .first()
    )
    jobs = {
        job.game_platform_id: job
        for job in ReviewCollectionJob.objects.filter(daily_candidate=candidate, audience=audience)
    }
    checkpoint = hashlib.sha256(
        _canonical_json(
            {
                "candidate": candidate.pk if candidate else None,
                "locator": game.canonical_locator,
                "routes": [
                    {
                        "id": route.pk,
                        "source_id": route.source_platform_id,
                        "slug": route.slug,
                        "path": getattr(
                            route,
                            "critic_reviews_path" if audience == "critic" else "user_reviews_path",
                        ),
                        "job": {
                            field: getattr(jobs[route.pk], field)
                            for field in (
                                "id",
                                "collection_generation",
                                "state",
                                "page_count",
                                "next_cursor",
                                "reported_total",
                                "fetched_count",
                                "unique_count",
                                "duplicate_count",
                            )
                        }
                        if route.pk in jobs
                        else None,
                    }
                    for route in routes
                ],
            }
        ).encode("utf-8")
    ).hexdigest()
    selected = []
    if candidate is None or not routes:
        return CollectionState(checkpoint, None, "collection_in_progress")
    for route in routes:
        job = jobs.get(route.id)
        if job is None or job.state not in ("complete", "empty") or job.next_cursor is not None:
            reason = (
                f"collection_{job.state}"
                if job and job.state in ("failed", "unstable", "retryable")
                else "collection_in_progress"
            )
            return CollectionState(checkpoint, None, reason)
        if job.reported_total is None or not (
            job.reported_total == job.unique_count == job.fetched_count and job.duplicate_count == 0
        ):
            return CollectionState(checkpoint, None, "collection_unverified")
        if (job.state == "empty") != (job.reported_total == 0):
            return CollectionState(checkpoint, None, "collection_unverified")
        selected.append(job)
    return CollectionState(checkpoint, selected, None)
