"""Non-destructive identity-first upsert per `research/feasibility/game-identity.md` (`SPK-03`).

`fetch_and_prepare`/`apply_game_dto` are the reusable core: `ingest_game` below is the `IMP-02`
one-off manual-proof entry point (still used by `scripts/ingest_game.py`), while `processing`
(`IMP-03`) calls the same two functions directly so it can own the `DailyCandidate`/`CoreAttempt`
lifecycle itself instead of `ingest_game`'s own simplified `_ensure_candidate`. Fetch evidence
(`SourceFetch`) is always saved, even on failure, independent of the upsert transaction.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from django.db import transaction
from metacritic.dto import FetchEvidence, GameDTO, GameIdentityDTO, GamePlatformDTO
from metacritic.errors import MetacriticParseError
from metacritic.gateway import GatewayProtocol
from metacritic.validation import userscore as validate_userscore
from metacritic.validation import validate_game
from processing.clock import Clock
from processing.models import DailyCandidate, DailyCycle
from reviews.models import ReviewCollectionJob

from catalog.genres import normalize_genres
from catalog.models import Game, GameAlias, GamePlatform, SourceFetch


class IdentityConflict(Exception):
    """A canonical locator is already bound to a different `source_game_id`."""


class PlatformIdentityConflict(Exception):
    """A `source_game_platform_id` assertion already points at a different game/platform pair."""


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


@dataclass(frozen=True, slots=True)
class AppliedGame:
    game: Game
    game_created: bool
    platforms: list[GamePlatform]
    platforms_created: int
    platforms_updated: int


def _merge_field[T](current: T | None, new: T | None) -> T | None:
    """Non-destructive merge: a genuine new value replaces the old one; a null (or a blank
    string, which carries no information either) keeps it."""
    if new is None:
        return current
    if isinstance(new, str) and not new.strip():
        return current
    return new


def save_fetch_evidence(evidence: FetchEvidence) -> SourceFetch:
    return SourceFetch.objects.create(
        kind=evidence.kind,
        url=evidence.url,
        started_at=evidence.started_at,
        completed_at=evidence.completed_at,
        http_status=evidence.http_status,
        response_sha256=evidence.response_sha256,
        parser_contract_version=evidence.parser_contract_version,
        outcome=evidence.outcome,
        error_code=evidence.error_code,
    )


def _resolve_game(dto: GameDTO, now: datetime) -> tuple[Game, bool]:
    try:
        game = Game.objects.get(source="metacritic", source_game_id=dto.source_game_id)
    except Game.DoesNotExist:
        if GameAlias.objects.filter(source="metacritic", locator=dto.canonical_locator).exists():
            raise IdentityConflict(
                f"locator {dto.canonical_locator!r} is already bound to a different game"
            ) from None
        game = Game.objects.create(
            source="metacritic",
            source_game_id=dto.source_game_id,
            canonical_locator=dto.canonical_locator,
            title=dto.title,
            cover_url=dto.cover_url,
            developer=dto.developer,
            description=dto.description,
            video_embed_url=dto.video_embed_url,
            video_content_url=dto.video_content_url,
            genres=list(normalize_genres(dto.genres or ())),
            release_date=dto.release_date,
            publishers=list(dto.publishers or ()),
            content_rating=dto.content_rating,
        )
        GameAlias.objects.create(
            game=game,
            source="metacritic",
            locator=dto.canonical_locator,
            first_seen_at=now,
            last_seen_at=now,
        )
        return game, True

    existing_alias = GameAlias.objects.filter(
        source="metacritic", locator=dto.canonical_locator
    ).first()
    if existing_alias is not None and existing_alias.game_id != game.id:
        raise IdentityConflict(
            f"locator {dto.canonical_locator!r} is already bound to a different game"
        )
    if existing_alias is None:
        GameAlias.objects.create(
            game=game,
            source="metacritic",
            locator=dto.canonical_locator,
            first_seen_at=now,
            last_seen_at=now,
        )
    else:
        existing_alias.last_seen_at = now
        existing_alias.save(update_fields=["last_seen_at"])

    game.canonical_locator = dto.canonical_locator
    game.title = dto.title
    game.cover_url = _merge_field(game.cover_url, dto.cover_url)
    game.developer = _merge_field(game.developer, dto.developer)
    game.description = _merge_field(game.description, dto.description)
    game.video_embed_url = _merge_field(game.video_embed_url, dto.video_embed_url)
    game.video_content_url = _merge_field(game.video_content_url, dto.video_content_url)
    if incoming_genres := normalize_genres(dto.genres or ()):
        game.genres = list(incoming_genres)
    game.release_date = _merge_field(game.release_date, dto.release_date)
    if dto.publishers:
        game.publishers = list(dto.publishers)
    game.content_rating = _merge_field(game.content_rating, dto.content_rating)
    game.save()
    return game, False


def resolve_game_identity(identity: GameIdentityDTO, now: datetime) -> tuple[Game, bool]:
    """Creates or finds a `Game` from list-page identity alone (id/locator/title only).

    Used by `processing.selector` at discovery time, before a full `apply_game_dto` detail fetch
    exists. The non-destructive merge in `_resolve_game` means this can never clobber a fuller
    Game row created by an earlier detail fetch — every other field stays `None` here, and `None`
    never overwrites a genuine prior value.
    """
    thin_dto = GameDTO(
        source_game_id=identity.source_game_id,
        canonical_locator=identity.canonical_locator,
        title=identity.title,
        cover_url=None,
        developer=None,
        description=None,
        video_embed_url=None,
        video_content_url=None,
        platforms=(),
    )
    return _resolve_game(thin_dto, now)


def _upsert_platform(game: Game, dto: GamePlatformDTO) -> tuple[GamePlatform, bool]:
    try:
        platform = GamePlatform.objects.get(game=game, source_platform_id=dto.source_platform_id)
    except GamePlatform.DoesNotExist:
        conflict = (
            GamePlatform.objects.filter(
                source="metacritic", source_game_platform_id=dto.source_game_platform_id
            )
            .exclude(game=game, source_platform_id=dto.source_platform_id)
            .exists()
        )
        if conflict:
            raise PlatformIdentityConflict(
                f"source_game_platform_id {dto.source_game_platform_id!r} already belongs to "
                "a different game/platform pair"
            ) from None
        platform = GamePlatform.objects.create(
            game=game,
            source="metacritic",
            source_platform_id=dto.source_platform_id,
            source_game_platform_id=dto.source_game_platform_id,
            slug=dto.slug,
            name=dto.name,
            metascore=dto.metascore,
            userscore=dto.userscore,
            critic_reviews_path=dto.critic_reviews_path,
            user_reviews_path=dto.user_reviews_path,
        )
        return platform, True

    conflict = (
        GamePlatform.objects.filter(
            source="metacritic", source_game_platform_id=dto.source_game_platform_id
        )
        .exclude(pk=platform.pk)
        .exists()
    )
    if conflict:
        raise PlatformIdentityConflict(
            f"source_game_platform_id {dto.source_game_platform_id!r} already belongs to "
            "a different game/platform pair"
        )
    platform.source_game_platform_id = dto.source_game_platform_id
    platform.name = dto.name
    platform.slug = dto.slug
    platform.metascore = _merge_field(platform.metascore, dto.metascore)
    platform.userscore = _merge_field(platform.userscore, dto.userscore)
    platform.critic_reviews_path = _merge_field(
        platform.critic_reviews_path, dto.critic_reviews_path
    )
    platform.user_reviews_path = _merge_field(platform.user_reviews_path, dto.user_reviews_path)
    platform.save()
    return platform, False


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


def _absolute_url(detail_url: str, path: str) -> str:
    parts = urlsplit(detail_url)
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def fetch_and_prepare(
    gateway: GatewayProtocol, detail_url: str
) -> tuple[GameDTO | None, SourceFetch, dict[str, SourceFetch]]:
    """Fetches the game detail page, then fans out to each non-lead platform's Userscore page.
    `SourceFetch` evidence is saved for every request made, including failed ones.

    Returns the fully-resolved `GameDTO` (`None` if the detail fetch itself failed/was invalid),
    the `game_detail` `SourceFetch`, and a `source_platform_id -> SourceFetch` map covering only
    the platforms whose own Userscore fetch *succeeded* (used for per-field provenance).
    """
    game_dto, evidence = gateway.fetch_game(detail_url)
    fetch = save_fetch_evidence(evidence)
    if game_dto is None:
        return None, fetch, {}
    try:
        validate_game(game_dto)
    except MetacriticParseError:
        fetch.outcome = "invalid"
        fetch.error_code = "invalid_game_data"
        fetch.save(update_fields=["outcome", "error_code"])
        return None, fetch, {}

    resolved_platforms: list[GamePlatformDTO] = []
    platform_userscore_fetch: dict[str, SourceFetch] = {}
    for platform_dto in game_dto.platforms:
        if platform_dto.is_lead_platform or platform_dto.user_reviews_path is None:
            resolved_platforms.append(platform_dto)
            continue
        userscore, platform_evidence = gateway.fetch_platform_userscore(
            _absolute_url(detail_url, platform_dto.user_reviews_path)
        )
        saved_fetch = save_fetch_evidence(platform_evidence)
        try:
            validate_userscore(userscore)
        except MetacriticParseError:
            saved_fetch.outcome = "invalid"
            saved_fetch.error_code = "invalid_userscore"
            saved_fetch.save(update_fields=["outcome", "error_code"])
            userscore = None
        if saved_fetch.outcome == "succeeded":
            platform_userscore_fetch[platform_dto.source_platform_id] = saved_fetch
        resolved_platforms.append(replace(platform_dto, userscore=userscore))
    game_dto = replace(game_dto, platforms=tuple(resolved_platforms))
    return game_dto, fetch, platform_userscore_fetch


def apply_game_dto(
    game_dto: GameDTO,
    fetch: SourceFetch,
    platform_userscore_fetch: dict[str, SourceFetch],
    now: datetime,
) -> AppliedGame:
    """Identity resolution and non-destructive Game/GamePlatform merge.

    Must run inside the caller's own `transaction.atomic()` block. Raises `IdentityConflict`/
    `PlatformIdentityConflict` on a genuine identity collision (nothing is written in that case).
    """
    validate_game(game_dto)
    game, game_created = _resolve_game(game_dto, now)
    game.last_changed_fetch = fetch
    if normalize_genres(game_dto.genres or ()):
        game.genres_last_changed_fetch = fetch
    game.save(update_fields=["last_changed_fetch", "genres_last_changed_fetch"])

    platforms: list[GamePlatform] = []
    platforms_created = 0
    platforms_updated = 0
    for platform_dto in game_dto.platforms:
        platform, created = _upsert_platform(game, platform_dto)
        # A missing new score can leave an older value (including zero) in place.
        # Keep that value's source; record this fetch only when its score was accepted
        # or the stored score is itself absent. A successful HTTP response alone does
        # not prove it supplied the value retained by the non-destructive merge.
        if platform_dto.metascore is not None or platform.metascore is None:
            platform.metascore_last_changed_fetch = fetch
        if platform_dto.userscore is not None or platform.userscore is None:
            if platform_dto.is_lead_platform:
                platform.userscore_last_changed_fetch = fetch
            elif platform_dto.source_platform_id in platform_userscore_fetch:
                platform.userscore_last_changed_fetch = platform_userscore_fetch[
                    platform_dto.source_platform_id
                ]
        platform.save(
            update_fields=["metascore_last_changed_fetch", "userscore_last_changed_fetch"]
        )
        platforms.append(platform)
        platforms_created += int(created)
        platforms_updated += int(not created)

    return AppliedGame(
        game=game,
        game_created=game_created,
        platforms=platforms,
        platforms_created=platforms_created,
        platforms_updated=platforms_updated,
    )


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
