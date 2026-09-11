from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class FetchEvidence:
    kind: str
    url: str
    started_at: datetime
    completed_at: datetime
    http_status: int | None
    response_sha256: str | None
    parser_contract_version: str
    outcome: str
    error_code: str | None


@dataclass(frozen=True, slots=True)
class GamePlatformDTO:
    source_platform_id: str
    source_game_platform_id: str
    slug: str
    name: str
    is_lead_platform: bool
    metascore: int | None
    userscore: Decimal | None
    critic_reviews_path: str | None
    user_reviews_path: str | None


@dataclass(frozen=True, slots=True)
class GameDTO:
    source_game_id: str
    canonical_locator: str
    title: str
    cover_url: str | None
    developer: str | None
    description: str | None
    video_embed_url: str | None
    video_content_url: str | None
    platforms: tuple[GamePlatformDTO, ...]


@dataclass(frozen=True, slots=True)
class GameIdentityDTO:
    """Identity-only DTO from a list page (New Releases / SEE ALL); no core fields."""

    source_game_id: str
    canonical_locator: str
    title: str


@dataclass(frozen=True, slots=True)
class BrowsePage:
    games: tuple[GameIdentityDTO, ...]
    has_next_page: bool
