"""Public parsing entry points and the parser contract version.

The parsers themselves are split by the source page whose markup they depend on, because each one
changes for its own reason: `metacritic.detail_parser` (game-detail and platform user-score
pages), `metacritic.listing_parser` (New Releases and browse listings) and
`metacritic.review_parser` (review backend pages), all built on the shared SSR primitives in
`metacritic.page`. No network access happens in any of them.
"""

from metacritic.detail_parser import parse_game_detail, parse_platform_userscore
from metacritic.listing_parser import parse_browse_page, parse_new_releases
from metacritic.review_parser import parse_review_page

PARSER_CONTRACT_VERSION = "1.1.0"

__all__ = [
    "PARSER_CONTRACT_VERSION",
    "parse_browse_page",
    "parse_game_detail",
    "parse_new_releases",
    "parse_platform_userscore",
    "parse_review_page",
]
