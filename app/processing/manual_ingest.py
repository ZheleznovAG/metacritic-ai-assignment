"""`IMP-02` one-off manual ingest of one game (`manage.py ingest_game`, `add_rated_games`).

It reuses the catalogue's upsert core and then enrols the game in today's cycle with a simplified
candidate of its own. It never goes through the scheduled Selector/lease (`processing.selector`);
`processing.runner` owns that periodic path and the `CoreAttempt` lifecycle.
"""

from dataclasses import dataclass

from catalog.ingest import (
    IdentityConflict,
    PlatformIdentityConflict,
    apply_game_dto,
    fetch_and_prepare,
)
from catalog.models import Game
from core.clock import Clock
from django.db import transaction
from metacritic.gateway import GatewayProtocol

from processing.enrollment import ensure_jobs
from processing.models import DailyCandidate, DailyCycle


@dataclass(frozen=True, slots=True)
class IngestResult:
    ok: bool
    game_id: int | None
    game_created: bool
    platforms_created: int
    platforms_updated: int
    jobs_created: int
    candidate_state: str | None
    fetch_outcome: str
    error: str | None


def _ensure_candidate(game: Game, clock: Clock) -> DailyCandidate:
    business_date = clock.now_utc().date()
    cycle, _ = DailyCycle.objects.get_or_create(business_date=business_date, timezone="UTC")
    # Locked for the rest of this transaction: serialises concurrent candidates within one cycle
    # so two ingests racing on next `source_order` cannot both insert the same value. This manual
    # one-off path never goes through the real Selector/lease (`processing.selector`) — it is not
    # the periodic production path.
    cycle = DailyCycle.objects.select_for_update().get(pk=cycle.pk)
    candidate = DailyCandidate.objects.filter(cycle=cycle, game=game).first()
    if candidate is None:
        next_order = (
            DailyCandidate.objects.filter(cycle=cycle)
            .order_by("-source_order")
            .values_list("source_order", flat=True)
            .first()
            or 0
        ) + 1
        candidate = DailyCandidate.objects.create(
            cycle=cycle, game=game, source_order=next_order, state="processed"
        )
    elif candidate.state != "processed":
        candidate.state = "processed"
        candidate.save(update_fields=["state"])
    return candidate


def ingest_game(gateway: GatewayProtocol, clock: Clock, detail_url: str) -> IngestResult:
    game_dto, fetch, platform_userscore_fetch = fetch_and_prepare(gateway, detail_url)
    if game_dto is None:
        return IngestResult(
            ok=False,
            game_id=None,
            game_created=False,
            platforms_created=0,
            platforms_updated=0,
            jobs_created=0,
            candidate_state=None,
            fetch_outcome=fetch.outcome,
            error=fetch.error_code,
        )

    now = clock.now_utc()
    try:
        with transaction.atomic():
            applied = apply_game_dto(game_dto, fetch, platform_userscore_fetch, now)
            candidate = _ensure_candidate(applied.game, clock)
            jobs_created = ensure_jobs(candidate, applied.platforms)
    except (IdentityConflict, PlatformIdentityConflict) as error:
        return IngestResult(
            ok=False,
            game_id=None,
            game_created=False,
            platforms_created=0,
            platforms_updated=0,
            jobs_created=0,
            candidate_state=None,
            fetch_outcome=fetch.outcome,
            error=str(error),
        )

    return IngestResult(
        ok=True,
        game_id=applied.game.id,
        game_created=applied.game_created,
        platforms_created=applied.platforms_created,
        platforms_updated=applied.platforms_updated,
        jobs_created=jobs_created,
        candidate_state=candidate.state,
        fetch_outcome=fetch.outcome,
        error=None,
    )
