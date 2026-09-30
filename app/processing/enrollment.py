"""Enrol an applied game's platforms for review collection within one daily candidate."""

from catalog.models import GamePlatform
from reviews.models import ReviewCollectionJob

from processing.models import DailyCandidate


def ensure_jobs(candidate: DailyCandidate, platforms: list[GamePlatform]) -> int:
    created_count = 0
    for platform in platforms:
        for audience, path in (
            ("critic", platform.critic_reviews_path),
            ("user", platform.user_reviews_path),
        ):
            if not path:
                continue
            _, created = ReviewCollectionJob.objects.get_or_create(
                daily_candidate=candidate, game_platform=platform, audience=audience
            )
            created_count += int(created)
    return created_count
