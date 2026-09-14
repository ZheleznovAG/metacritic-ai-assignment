"""Build immutable audience corpora from exact, complete daily route observations (R04/R05)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from catalog.models import Game, GamePlatform
from django.db import transaction
from processing.models import DailyCandidate

from reviews.models import Review, ReviewCollectionJob, ReviewCorpus, ReviewCorpusItem
from reviews.selection import (
    POLICY_VERSION,
    TOKENIZER_ID,
    ReviewRecord,
    SelectionPool,
    select_reviews,
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def known_routes(game: Game, audience: str) -> list[GamePlatform]:
    field = "critic_reviews_path" if audience == "critic" else "user_reviews_path"
    return [
        platform
        for platform in game.platforms.order_by("source_platform_id", "id")
        if getattr(platform, field)
    ]


def _current_jobs(
    game: Game, audience: str, routes: list[GamePlatform]
) -> list[ReviewCollectionJob] | None:
    # Daily order wins over completion/arrival times: an older backlog route can finish later.
    # One cohort prevents a current platform snapshot from being combined with yesterday's.
    candidate = (
        DailyCandidate.objects.filter(game=game, state="processed")
        .order_by("-cycle__business_date", "-id")
        .first()
    )
    if candidate is None or not routes:
        return None
    jobs = {
        job.game_platform_id: job
        for job in ReviewCollectionJob.objects.filter(daily_candidate=candidate, audience=audience)
    }
    selected = []
    for route in routes:
        job = jobs.get(route.id)
        if job is None or job.state not in ("complete", "empty") or job.next_cursor is not None:
            return None
        if job.reported_total is None or not (
            job.reported_total == job.unique_count == job.fetched_count and job.duplicate_count == 0
        ):
            return None
        if (job.state == "empty") != (job.reported_total == 0):
            return None
        selected.append(job)
    return selected


def all_routes_terminal(game: Game, audience: str) -> bool:
    return _current_jobs(game, audience, known_routes(game, audience)) is not None


def _dedup_fingerprint(review: Review) -> str:
    # Canonical tuple avoids ambiguous separators in source-supplied author/text values.
    parts = [
        (review.author_label or "").strip().casefold(),
        review.date_label or "",
        review.score_label or "",
        " ".join(review.text_original.split()).casefold(),
    ]
    return hashlib.sha256(_canonical_json(parts).encode("utf-8")).hexdigest()


@transaction.atomic
def build(game: Game, audience: str) -> ReviewCorpus | None:
    """Serialize against collection commits/core upserts, select current complete observations,
    then persist the corpus atomically. No fallback to an older or partial route is permitted.
    The game lock also makes concurrent builders agree on one corpus without a check/create race.
    """
    game = Game.objects.select_for_update().get(pk=game.pk)
    routes = known_routes(game, audience)
    jobs = _current_jobs(game, audience, routes)
    if jobs is None:
        return None

    reviews: list[Review] = []
    snapshots = []
    for route, job in zip(routes, jobs, strict=True):
        observed = list(
            Review.objects.filter(
                game_platform=route,
                audience=audience,
                observations__collection_job=job,
                observations__collection_generation=job.collection_generation,
                observations__source_fetch__review_job=job,
                observations__source_fetch__collection_generation=job.collection_generation,
                observations__source_fetch__outcome="succeeded",
            )
            .select_related("game_platform")
            .order_by("identity_key", "version_sha256")
        )
        # A terminal label is not proof that a complete snapshot was persisted.
        if len(observed) != job.unique_count or len({r.identity_key for r in observed}) != len(
            observed
        ):
            return None
        reviews.extend(observed)
        snapshots.append(
            {
                "platform": route.source_platform_id,
                "slug": route.slug,
                "state": job.state,
                "reported": job.reported_total,
                "fetched": job.fetched_count,
                "reviews": [
                    {"identity": r.identity_key, "version": r.version_sha256} for r in observed
                ],
            }
        )
    source_set_fingerprint = hashlib.sha256(
        _canonical_json({"snapshot_version": 2, "routes": snapshots}).encode("utf-8")
    ).hexdigest()
    existing = ReviewCorpus.objects.filter(
        game=game,
        audience=audience,
        policy_version=POLICY_VERSION,
        source_set_fingerprint=source_set_fingerprint,
    ).first()
    if existing is not None:
        return existing

    # Keep first canonical representatives deterministic across platform queries.
    reviews.sort(key=lambda r: (r.identity_key, r.game_platform.source_platform_id))
    # Review identity is platform-scoped, while the selector's group keys are pool-wide.
    # Qualify collisions only; ordinary identities retain the frozen sampling/hash behavior.
    identity_counts = Counter(review.identity_key for review in reviews)
    selection_keys = {
        review.id: (
            "platform:"
            + _canonical_json([review.game_platform.source_platform_id, review.identity_key])
            if identity_counts[review.identity_key] > 1
            else review.identity_key
        )
        for review in reviews
    }
    canonical_of: dict[int, str] = {}
    seen_fingerprints: dict[str, str] = {}
    for review in reviews:
        fingerprint = _dedup_fingerprint(review)
        if fingerprint in seen_fingerprints:
            canonical_of[review.id] = seen_fingerprints[fingerprint]
        else:
            seen_fingerprints[fingerprint] = selection_keys[review.id]

    def score(review: Review) -> float | None:
        try:
            return float(review.score_label) if review.score_label else None
        except ValueError:
            return None

    records = tuple(
        ReviewRecord(
            identity_key=selection_keys[review.id],
            platform_slug=review.game_platform.slug,
            page_offset=0,
            language="",
            score=score(review),
            text=review.text_original,
            meaningful=bool(review.text_original.strip()),
            duplicate_of=canonical_of.get(review.id),
        )
        for review in reviews
    )
    result = select_reviews(
        SelectionPool(
            audience=audience,
            game_slug=game.canonical_locator,
            collection_status="complete",
            reviews=records,
        )
    )
    by_key = {(review.game_platform.slug, selection_keys[review.id]): review for review in reviews}
    id_texts = []
    rows = []
    for ordinal, selected in enumerate(result.selected, start=1):
        prompt_id = f"R{ordinal:02d}"
        review = by_key[(selected.platform_slug, selected.identity_key)]
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
    from summaries import contour, preflight

    # Before a job has an ID, use the longest PostgreSQL bigint correlation suffix. These
    # corpus diagnostics bound that placeholder; admission always measures the actual request.
    measured = preflight.measure(
        contour.build_request_payload("summary-job-9223372036854775807", audience, id_texts)
    )
    raw_prompt_tokens = measured.raw_tokens
    corpus = ReviewCorpus.objects.create(
        game=game,
        audience=audience,
        policy_version=POLICY_VERSION,
        source_set_fingerprint=source_set_fingerprint,
        model_input_fingerprint=model_input_fingerprint,
        complete_route_count=sum(job.state == "complete" for job in jobs),
        empty_route_count=sum(job.state == "empty" for job in jobs),
        reported_count=sum(job.reported_total or 0 for job in jobs),
        fetched_count=sum(job.fetched_count for job in jobs),
        unique_count=len(reviews),
        deduplicated_count=len(canonical_of),
        selected_count=len(result.selected),
        tokenizer_id=TOKENIZER_ID,
        tokenizer_version="0.14.0",
        raw_prompt_tokens=raw_prompt_tokens,
        guarded_prompt_tokens=measured.guarded_tokens,
        completion_reservation=contour.MAX_COMPLETION_TOKENS,
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
    return corpus
