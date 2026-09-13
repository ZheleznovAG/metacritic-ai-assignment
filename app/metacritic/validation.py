"""R19: deterministic source-data bounds before PostgreSQL writes; no coercion/truncation."""

from decimal import Decimal
from urllib.parse import urlsplit

from metacritic.dto import GameDTO
from metacritic.errors import MetacriticParseError


def metascore(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 100:
        raise MetacriticParseError("invalid_metascore")
    return value


def userscore(value: object) -> Decimal | None:
    if value is None:
        return None
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or not 0 <= value <= 10
        or value * 10 != (value * 10).to_integral_value()
    ):
        raise MetacriticParseError("invalid_userscore")
    return value


def _text(value: object, limit: int | None, *, required: bool = False) -> None:
    if value is None and not required:
        return
    if (
        not isinstance(value, str)
        or (required and not value.strip())
        or (limit is not None and len(value) > limit)
        or "\x00" in value
    ):
        raise MetacriticParseError("invalid_text_field")


def validate_game(dto: GameDTO) -> None:
    for field, limit in (("source_game_id", 64), ("canonical_locator", 512), ("title", 255)):
        _text(getattr(dto, field), limit, required=True)
    if not dto.canonical_locator.startswith("/game/"):
        raise MetacriticParseError("invalid_game_locator")
    _text(dto.developer, 255)
    _text(dto.description, None)
    for value in (dto.cover_url, dto.video_embed_url, dto.video_content_url):
        _text(value, None)
        if value:
            try:
                parsed = urlsplit(value)
            except ValueError as error:
                raise MetacriticParseError("invalid_media_url") from error
            if parsed.scheme not in ("https", "http") or not parsed.netloc:
                raise MetacriticParseError("invalid_media_url")
    platforms: set[str] = set()
    related_ids: set[str] = set()
    for platform in dto.platforms:
        for field, limit in (
            ("source_platform_id", 64),
            ("source_game_platform_id", 64),
            ("slug", 128),
            ("name", 128),
        ):
            _text(getattr(platform, field), limit, required=True)
        _text(platform.critic_reviews_path, 512)
        _text(platform.user_reviews_path, 512)
        metascore(platform.metascore)
        userscore(platform.userscore)
        if (
            platform.source_platform_id in platforms
            or platform.source_game_platform_id in related_ids
        ):
            raise MetacriticParseError("duplicate_platform_identity")
        platforms.add(platform.source_platform_id)
        related_ids.add(platform.source_game_platform_id)
