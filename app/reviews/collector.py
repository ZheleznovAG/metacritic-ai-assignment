"""Durable, row-leased review-page collection: one worker claim processes exactly one page.

Terminal-state rules follow `docs/design.md`'s "Скачанные отзывы" section: no `next` + stable
`totalResults` + unique count == reported total -> `complete`; valid zero total -> `empty`; a
repeated page identity or a changed `totalResults` mid-route -> `unstable`; a transport/parse
failure -> `retryable` (bounded attempts) or `failed`. Only `links.next.href` ever advances the
cursor; `?page=N` is never synthesized (confirmed dead for this route in `SPK-02`).

Automatic generation-restart after `unstable`/`failed` is out of scope for this cycle (documented
in `docs/requirements/imp_04_review.md`'s known limitations) — such a job stays visible and
diagnosable for `HRD-02`/`HRD-04`, not silently retried forever or auto-restarted.
"""

from __future__ import annotations

import hashlib
import html
from datetime import datetime, timedelta

from catalog.models import Game, SourceFetch
from django.db import transaction
from django.db.models import F, Q
from metacritic.dto import ReviewRecordDTO
from metacritic.gateway import ReviewGatewayProtocol
from processing.clock import Clock

from reviews import corpus as corpus_module
from reviews.models import Review, ReviewCollectionJob, ReviewObservation

LEASE_TTL = timedelta(minutes=5)
MAX_AUTOMATIC_ATTEMPTS = 5
BACKOFF_STEPS = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=6),
)


def _backoff_for(attempt_count: int) -> timedelta:
    index = min(attempt_count - 1, len(BACKOFF_STEPS) - 1)
    return BACKOFF_STEPS[index]


def _recover_stale_leases(now: datetime) -> None:
    """A `running` job whose lease has expired was left mid-flight by a crashed/killed worker
    (or one that outlived its lease). Bumping the fencing token here — not only on the next
    claim — immediately invalidates any late commit the presumed-dead worker might still attempt,
    even before anyone re-claims the row (same reasoning as `processing.selector`'s stale-
    candidate recovery, adapted to a per-row lease instead of one singleton lease)."""
    ReviewCollectionJob.objects.filter(state="running", lease_expires_at__lt=now).update(
        state="retryable",
        fencing_token=F("fencing_token") + 1,
        last_error="lease_expired",
    )


def claim_next_job(clock: Clock) -> ReviewCollectionJob | None:
    with transaction.atomic():
        now = clock.now_utc()
        _recover_stale_leases(now)
        job = (
            ReviewCollectionJob.objects.select_for_update(skip_locked=True)
            .filter(state__in=["pending", "retryable"])
            .filter(Q(available_at__isnull=True) | Q(available_at__lte=now))
            .order_by("id")
            .first()
        )
        if job is None:
            return None
        job.fencing_token += 1
        job.lease_expires_at = now + LEASE_TTL
        job.state = "running"
        if job.started_at is None:
            job.started_at = now
        job.save(update_fields=["fencing_token", "lease_expires_at", "state", "started_at"])
        return job


def _still_owned(job_id: int, expected_token: int) -> ReviewCollectionJob | None:
    job = ReviewCollectionJob.objects.select_for_update().get(pk=job_id)
    return job if job.fencing_token == expected_token else None


def _normalize_text(text: str) -> str:
    return " ".join(html.unescape(text).split())


def _identity_key(
    item: ReviewRecordDTO, audience: str, platform_id: str, normalized_text: str
) -> str:
    if item.source_review_id:
        return f"id:{item.source_review_id}"
    seed = "|".join(
        [
            audience,
            platform_id,
            item.external_url or "",
            item.author_or_source_label or "",
            item.date_label or "",
            item.score_label or "",
            normalized_text,
        ]
    )
    return f"fallback:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


def _maybe_build_corpus_and_summary_job(game: Game, audience: str) -> None:
    if not corpus_module.all_routes_terminal(game, audience):
        return
    new_corpus = corpus_module.build(game, audience)
    if new_corpus is None:
        return
    from summaries.worker import ensure_job

    ensure_job(new_corpus)


def collect_one_page(
    gateway: ReviewGatewayProtocol, clock: Clock, job: ReviewCollectionJob
) -> ReviewCollectionJob:
    fencing_token = job.fencing_token
    platform = job.game_platform
    game = platform.game
    game_slug = game.canonical_locator.strip("/").removeprefix("game/").rstrip("/")

    page, evidence = gateway.fetch_review_page(
        job.audience, game_slug, platform.slug, job.next_cursor
    )
    now = clock.now_utc()

    with transaction.atomic():
        current = _still_owned(job.id, fencing_token)
        if current is None:
            return job  # lease lost mid-flight; the next claim's recovery sweeps this job
        job = current

        source_fetch = SourceFetch.objects.create(
            kind="review_page",
            url=evidence.url,
            started_at=evidence.started_at,
            completed_at=evidence.completed_at,
            http_status=evidence.http_status,
            response_sha256=evidence.response_sha256,
            parser_contract_version=evidence.parser_contract_version,
            outcome=evidence.outcome,
            error_code=evidence.error_code,
            review_job=job,
            collection_generation=job.collection_generation,
            page_ordinal=job.page_count,
            attempt_no=job.attempt_count + 1,
            fencing_token=fencing_token,
            reported_total=page.reported_total if page else None,
            item_count=len(page.items) if page else None,
        )
        job.attempt_count += 1

        if page is None:
            if job.attempt_count >= MAX_AUTOMATIC_ATTEMPTS:
                job.state = "failed"
            else:
                job.state = "retryable"
                job.available_at = now + _backoff_for(job.attempt_count)
            job.last_error = evidence.error_code
            job.save(update_fields=["attempt_count", "state", "available_at", "last_error"])
            return job

        job.last_error = None
        identity_keys = []
        normalized_texts = []
        for item in page.items:
            normalized = _normalize_text(item.text)
            normalized_texts.append(normalized)
            identity_keys.append(
                _identity_key(item, job.audience, platform.source_platform_id, normalized)
            )
        page_fingerprint = hashlib.sha256("|".join(identity_keys).encode("utf-8")).hexdigest()

        if page_fingerprint in job.visited_page_fingerprints:
            job.state = "unstable"
            job.last_error = "repeated_page_identity"
            job.save(update_fields=["attempt_count", "state", "last_error"])
            return job
        if job.reported_total is not None and page.reported_total != job.reported_total:
            job.state = "unstable"
            job.last_error = "total_results_changed"
            job.save(update_fields=["attempt_count", "state", "last_error"])
            return job

        job.reported_total = page.reported_total
        job.visited_page_fingerprints = [*job.visited_page_fingerprints, page_fingerprint]

        route_position = job.fetched_count
        for offset, (item, key, normalized) in enumerate(
            zip(page.items, identity_keys, normalized_texts, strict=True)
        ):
            content_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            review, created = Review.objects.get_or_create(
                game_platform=platform,
                audience=job.audience,
                identity_key=key,
                content_sha256=content_sha256,
                defaults={
                    "source_review_id": item.source_review_id,
                    "author_label": item.author_or_source_label,
                    "score_label": item.score_label,
                    "date_label": item.date_label,
                    "text_original": normalized,
                    "first_seen_at": now,
                },
            )
            if created:
                job.unique_count += 1
                if item.source_review_id:
                    older = (
                        Review.objects.filter(
                            game_platform=platform,
                            audience=job.audience,
                            identity_key=key,
                            superseded_by__isnull=True,
                        )
                        .exclude(pk=review.pk)
                        .first()
                    )
                    if older is not None:
                        review.supersedes = older
                        review.save(update_fields=["supersedes"])
            else:
                job.duplicate_count += 1

            ReviewObservation.objects.get_or_create(
                collection_job=job,
                collection_generation=job.collection_generation,
                review=review,
                defaults={
                    "source_fetch": source_fetch,
                    "page_position": offset,
                    "route_global_position": route_position + offset,
                },
            )

        job.fetched_count += len(page.items)
        job.page_count += 1
        job.next_cursor = page.next_cursor

        if page.next_cursor is None:
            if job.reported_total == 0:
                job.state = "empty"
            elif job.reported_total == job.unique_count:
                job.state = "complete"
            else:
                job.state = "unstable"
                job.last_error = "unique_count_mismatch"
            job.completed_at = now
        else:
            job.state = "pending"

        job.save()

    if job.state in ("complete", "empty"):
        _maybe_build_corpus_and_summary_job(game, job.audience)

    return job
