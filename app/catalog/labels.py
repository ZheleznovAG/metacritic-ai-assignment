"""Reading stored JSON label lists (`Game.genres`, `Game.publishers`)."""


def saved_labels(value: object) -> tuple[str, ...]:
    """Stored JSON list as labels; corrupt/manual JSON is unknown, never split into fake
    single-letter labels."""
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return ()
    return tuple(value)
