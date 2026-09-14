"""IMP-06: canonical genre labels, without translation or inferred taxonomy."""


def normalize_label(value: str) -> str:
    return " ".join(value.split()).casefold()


def normalize_genres(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(label for value in values if (label := normalize_label(value))))
