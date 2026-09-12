"""Builds the immutable, bounded `ReviewCorpus` from collected reviews (`docs/design.md`'s
corpus-building steps 1-2, plus persistence); `reviews.selection` does steps 3-6 (the actual
ASM-16 candidate policy) as a pure function this module feeds and persists the result of.
"""

from __future__ import annotations

import hashlib
import json

from catalog.models import Game, GamePlatform
from django.db import IntegrityError, transaction

from reviews.models import Review, ReviewCollectionJob, ReviewCorpus, ReviewCorpusItem
from reviews.selection import (
    POLICY_VERSION,
    TOKENIZER_ID,
    ReviewRecord,
    SelectionPool,
    select_reviews,
)


def _route_path_field(audience: str) -> str:
    return "critic_reviews_path" if audience == "critic" else "user_reviews_path"


def known_routes(game: Game, audience: str) -> list[GamePlatform]:
    field = _route_path_field(audience)
    return [platform for platform in game.platforms.all() if getattr(platform, field)]


def _latest_terminal_job(platform: GamePlatform, audience: str) -> ReviewCollectionJob | None:
    return (
        ReviewCollectionJob.objects.filter(
            game_platform=platform, audience=audience, state__in=["complete", "empty"]
        )
        .order_by("-completed_at")
        .first()
    )


def all_routes_terminal(game: Game, audience: str) -> bool:
    routes = known_routes(game, audience)
    if not routes:
        return False
    return all(_latest_terminal_job(platform, audience) is not None for platform in routes)


def _dedup_fingerprint(review: Review) -> str:
    parts = "|".join(
        [
            (review.author_label or "").strip().casefold(),
            review.date_label or "",
            review.score_label or "",
            " ".join((review.text_original or "").split()).casefold(),
        ]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build(game: Game, audience: str) -> ReviewCorpus | None:
    """Returns the current corpus for `(game, audience)`, building and persisting a new one if the
    source set changed since the last build. Returns None if any known route has not yet reached a
    terminal collection generation — no corpus is built from a partial snapshot."""
    routes = known_routes(game, audience)
    if not routes:
        return None
    latest_jobs = []
    for platform in routes:
        job = _latest_terminal_job(platform, audience)
        if job is None:
            return None
        latest_jobs.append(job)

    reviews = list(
        Review.objects.filter(
            game_platform__in=routes, audience=audience, superseded_by__isnull=True
        )
        .select_related("game_platform")
        .order_by("identity_key")
    )

    canonical_of: dict[int, str] = {}
    seen_fingerprints: dict[str, str] = {}
    for review in reviews:
        fingerprint = _dedup_fingerprint(review)
        if fingerprint in seen_fingerprints:
            canonical_of[review.id] = seen_fingerprints[fingerprint]
        else:
            seen_fingerprints[fingerprint] = review.identity_key

    def _score(review: Review) -> float | None:
        try:
            return float(review.score_label) if review.score_label else None
        except ValueError:
            return None

    records = tuple(
        ReviewRecord(
            identity_key=review.identity_key,
            platform_slug=review.game_platform.slug,
            page_offset=0,
            language="",
            score=_score(review),
            text=review.text_original,
            meaningful=bool(review.text_original.strip()),
            duplicate_of=canonical_of.get(review.id),
        )
        for review in reviews
    )
    pool = SelectionPool(
        audience=audience,
        game_slug=game.canonical_locator,
        collection_status="complete",
        reviews=records,
    )
    result = select_reviews(pool)

    source_set_fingerprint = hashlib.sha256(
        "|".join(sorted(r.identity_key for r in records)).encode("utf-8")
    ).hexdigest()

    def _fetch_existing() -> ReviewCorpus | None:
        return ReviewCorpus.objects.filter(
            game=game,
            audience=audience,
            policy_version=POLICY_VERSION,
            source_set_fingerprint=source_set_fingerprint,
        ).first()

    # Fast path only: two workers can both complete a game's last needed route at nearly the same
    # time and both pass this check before either commits. The real race guard is the unique
    # constraint below plus the IntegrityError fallback, matching summaries.worker.ensure_job's
    # get_or_create pattern.
    existing = _fetch_existing()
    if existing is not None:
        return existing

    by_key = {review.identity_key: review for review in reviews}
    id_texts = []
    rows = []
    for ordinal, selected in enumerate(result.selected, start=1):
        prompt_id = f"R{ordinal:02d}"
        review = by_key[selected.identity_key]
        rows.append((prompt_id, ordinal, review, selected))
        id_texts.append({"id": prompt_id, "text": selected.text})

    model_input_fingerprint = hashlib.sha256(
        _canonical_json(
            {
                "game": game.canonical_locator,
                "audience": audience,
                "policy_version": POLICY_VERSION,
                "tokenizer": TOKENIZER_ID,
                "reviews": id_texts,
            }
        ).encode("utf-8")
    ).hexdigest()

    raw_prompt_tokens = sum(item.token_count for item in result.selected)
    deduplicated_count = len(canonical_of)

    try:
        with transaction.atomic():
            corpus = ReviewCorpus.objects.create(
                game=game,
                audience=audience,
                policy_version=POLICY_VERSION,
                source_set_fingerprint=source_set_fingerprint,
                model_input_fingerprint=model_input_fingerprint,
                complete_route_count=sum(1 for job in latest_jobs if job.state == "complete"),
                empty_route_count=sum(1 for job in latest_jobs if job.state == "empty"),
                reported_count=sum(job.reported_total or 0 for job in latest_jobs),
                fetched_count=sum(job.fetched_count for job in latest_jobs),
                unique_count=len(reviews),
                deduplicated_count=deduplicated_count,
                selected_count=len(result.selected),
                tokenizer_id=TOKENIZER_ID,
                tokenizer_version="0.14.0",
                raw_prompt_tokens=raw_prompt_tokens,
                guarded_prompt_tokens=raw_prompt_tokens + 64,
                completion_reservation=800,
            )
            ReviewCorpusItem.objects.bulk_create(
                ReviewCorpusItem(
                    corpus=corpus,
                    ordinal=ordinal,
                    prompt_review_id=prompt_id,
                    review=review,
                    input_text=selected.text,
                    input_token_count=selected.token_count,
                    sha256=hashlib.sha256(selected.text.encode("utf-8")).hexdigest(),
                    was_truncated=selected.truncated,
                )
                for prompt_id, ordinal, review, selected in rows
            )
    except IntegrityError:
        # Lost the race to a concurrent worker building the same corpus; its row is equivalent
        # (a pure function of the same underlying reviews), so use it instead of failing the tick.
        winner = _fetch_existing()
        if winner is None:
            raise
        return winner
    return corpus
