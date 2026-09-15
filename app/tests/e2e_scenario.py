"""IMP-07 controlled external inputs; all persisted state comes from real services."""

from dataclasses import replace
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from metacritic.dto import (
    FetchEvidence,
    GameDTO,
    GameIdentityDTO,
    GamePlatformDTO,
    ReviewPageDTO,
    ReviewRecordDTO,
)

from tests.test_processing_selector import FakeGateway as DiscoveryGateway
from tests.test_processing_selector import _evidence

COVER_URL = "https://example.invalid/alpha-cover.svg"
TRAILER_URL = "https://example.invalid/alpha-trailer"
ANCHOR_SLUG = "e2e-anchor"
CRITIC_LIKE = "Responsive combat."
CRITIC_DISLIKE = "An awkward camera."
USER_LIKE = "Rewarding exploration."
USER_DISLIKE = "Confusing menus."
LIKES_BY_AUDIENCE = {
    "critic": (CRITIC_LIKE, CRITIC_DISLIKE),
    "user": (USER_LIKE, USER_DISLIKE),
}


def game(slug: str, title: str, scores: tuple[int | None, ...], genre: str) -> GameDTO:
    platforms = tuple(
        GamePlatformDTO(
            source_platform_id=platform,
            source_game_platform_id=f"{slug}-{platform}",
            slug=platform,
            name=name,
            is_lead_platform=ordinal == 0,
            metascore=score,
            userscore=Decimal("8.1") if score is not None else None,
            critic_reviews_path=f"/game/{slug}/critic-reviews/?platform={platform}",
            user_reviews_path=f"/game/{slug}/user-reviews/?platform={platform}",
        )
        for ordinal, (score, (platform, name)) in enumerate(
            zip(scores, (("pc", "PC"), ("playstation-5", "PlayStation 5")), strict=False)
        )
    )
    return GameDTO(
        source_game_id=slug,
        canonical_locator=f"/game/{slug}/",
        title=title,
        cover_url=COVER_URL if slug == ANCHOR_SLUG else None,
        developer="Example Studio",
        description="A synthetic adventure with responsive combat and rewarding exploration.",
        video_embed_url=TRAILER_URL if slug == ANCHOR_SLUG else None,
        video_content_url=None,
        platforms=platforms,
        genres=(genre,),
    )


GAMES = (
    game(ANCHOR_SLUG, "Alpha Quest", (70, 95), "Action RPG"),
    game("e2e-peer", "BETA Quest", (80,), "Action RPG"),
    game("e2e-unscored", "Unscored Quest", (None,), "Puzzle"),
    game("e2e-puzzle", "Orbit Puzzler", (66,), "Puzzle"),
)


class ScenarioGateway(DiscoveryGateway):
    def __init__(self) -> None:
        super().__init__(
            new_releases=[
                GameIdentityDTO(g.source_game_id, g.canonical_locator, g.title) for g in GAMES
            ]
        )
        self.review_calls: list[tuple[str, str, str, str | None]] = []

    def fetch_game(self, url: str) -> tuple[GameDTO | None, FetchEvidence]:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return next(g for g in GAMES if g.source_game_id == slug), replace(
            _evidence("game_detail"), url=url, parser_contract_version="1.1.0"
        )

    def fetch_platform_userscore(self, url: str) -> tuple[Decimal | None, FetchEvidence]:
        parts = urlsplit(url)
        slug = parts.path.split("/game/", 1)[1].split("/", 1)[0]
        platform_slug = parse_qs(parts.query)["platform"][0]
        g = next(candidate for candidate in GAMES if candidate.source_game_id == slug)
        platform = next(p for p in g.platforms if p.slug == platform_slug)
        return platform.userscore, _evidence("platform_userscore")

    def fetch_review_page(
        self, audience: str, game_slug: str, platform_slug: str, cursor: str | None
    ) -> tuple[ReviewPageDTO | None, FetchEvidence]:
        self.review_calls.append((audience, game_slug, platform_slug, cursor))
        if game_slug != ANCHOR_SLUG or platform_slug != "pc":
            return ReviewPageDTO((), 0, None), _evidence("review_page")
        like, dislike = LIKES_BY_AUDIENCE[audience]
        items = tuple(
            ReviewRecordDTO(
                source_review_id=f"{audience}-{n}",
                author_or_source_label=f"Example {audience} {n}",
                score_label="8",
                date_label="2026-09-15",
                text=f"{like} {dislike} Independent observation number {n}.",
                external_url=None,
            )
            for n in ((1, 2) if cursor is None else (3,))
        )
        if cursor not in (None, "next"):
            raise AssertionError("Unexpected review cursor")
        return ReviewPageDTO(items, 3, "next" if cursor is None else None), _evidence("review_page")
