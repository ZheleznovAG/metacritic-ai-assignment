class MetacriticFetchError(Exception):
    """Transport/HTTP failure while fetching a Metacritic page (not a parse problem)."""


class MetacriticParseError(Exception):
    """The page is structurally invalid: required identity/title/platform data is missing."""
