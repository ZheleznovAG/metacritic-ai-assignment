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
from django.db.models import Q
from metacritic.dto import ReviewRecordDTO
from metacritic.gateway import ReviewGatewayProtocol, review_page_url
from metacritic.parser import PARSER_CONTRACT_VERSION
from processing.clock import Clock

from reviews import corpus as corpus_module
from reviews.models import Review, ReviewCollectionJob, ReviewObservation
from reviews.versioning import version_fingerprint

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


def _page_attempt_count(job: ReviewCollectionJob) -> int:
    return job.fetch_attempts.filter(
        collection_generation=job.collection_generation, page_ordinal=job.page_count
    ).count()


def _recover_stale_leases(now: datetime) -> None:
    for job in ReviewCollectionJob.objects.select_for_update(skip_locked=True).filter(
        state="running", lease_expires_at__lte=now
    ):
        job.fetch_attempts.filter(outcome="started").update(
            outcome="abandoned", error_code="lease_expired", completed_at=now
        )
        job.state = "failed" if _page_attempt_count(job) >= MAX_AUTOMATIC_ATTEMPTS else "retryable"
        job.fencing_token += 1
        job.last_error = "lease_expired"
        job.available_at = now
        job.save(update_fields=["state", "fencing_token", "last_error", "available_at"])


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


def _still_owned(claim: ReviewCollectionJob, now: datetime) -> ReviewCollectionJob | None:
    job = ReviewCollectionJob.objects.select_for_update().get(pk=claim.pk)
    if (
        job.fencing_token == claim.fencing_token
        and job.state == "running"
        and job.lease_expires_at is not None
        and job.lease_expires_at > now
        and job.collection_generation == claim.collection_generation
        and job.page_count == claim.page_count
        and job.next_cursor == claim.next_cursor
    ):
        return job
    return None


def _finish_fetch(fetch: SourceFetch, now: datetime, outcome: str, error: str | None) -> None:
    fetch.completed_at = now
    fetch.outcome = outcome
    fetch.error_code = error
    fetch.save()


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

    with transaction.atomic():
        Game.objects.select_for_update().get(pk=game.pk)
        current = _still_owned(job, clock.now_utc())
        if current is None:
            return ReviewCollectionJob.objects.get(pk=job.pk)
        if current.fetch_attempts.filter(outcome="started", fencing_token=fencing_token).exists():
            return current
        page_attempt_count = _page_attempt_count(current)
        if page_attempt_count >= MAX_AUTOMATIC_ATTEMPTS:
            current.state = "failed"
            current.last_error = "attempt_limit"
            current.save(update_fields=["state", "last_error"])
            return current
        current.attempt_count += 1
        source_fetch = SourceFetch.objects.create(
            kind="review_page",
            url=review_page_url(job.audience, game_slug, platform.slug, job.next_cursor),
            started_at=clock.now_utc(),
            parser_contract_version=PARSER_CONTRACT_VERSION,
            outcome="started",
            review_job=current,
            collection_generation=current.collection_generation,
            page_ordinal=current.page_count,
            attempt_no=current.attempt_count,
            fencing_token=fencing_token,
        )
        current.save(update_fields=["attempt_count"])

    page, evidence = gateway.fetch_review_page(
        job.audience, game_slug, platform.slug, job.next_cursor
    )
    now = clock.now_utc()

    with transaction.atomic():
        # Core upserts and all collection page commits take the game lock first. Besides
        # serializing versions, this makes terminal readiness + corpus + summary intent one
        # transaction even when different platform workers finish together (R05/R06).
        Game.objects.select_for_update().get(pk=game.pk)
        current = _still_owned(job, now)
        if current is None:
            SourceFetch.objects.filter(pk=source_fetch.pk, outcome="started").update(
                outcome="superseded", completed_at=now, error_code="lease_lost"
            )
            return ReviewCollectionJob.objects.get(pk=job.pk)
        job = current
        source_fetch.refresh_from_db()
        if source_fetch.outcome != "started":
            return job
        source_fetch.http_status = evidence.http_status
        source_fetch.response_sha256 = evidence.response_sha256
        source_fetch.parser_contract_version = evidence.parser_contract_version
        source_fetch.reported_total = page.reported_total if page else None
        source_fetch.item_count = len(page.items) if page else None

        if page is None:
            _finish_fetch(source_fetch, now, evidence.outcome, evidence.error_code)
            if page_attempt_count + 1 >= MAX_AUTOMATIC_ATTEMPTS:
                job.state = "failed"
            else:
                job.state = "retryable"
                job.available_at = now + _backoff_for(page_attempt_count + 1)
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
            _finish_fetch(source_fetch, now, "invalid", job.last_error)
            job.save(update_fields=["attempt_count", "state", "last_error"])
            return job
        if job.reported_total is not None and page.reported_total != job.reported_total:
            job.state = "unstable"
            job.last_error = "total_results_changed"
            _finish_fetch(source_fetch, now, "invalid", job.last_error)
            job.save(update_fields=["attempt_count", "state", "last_error"])
            return job

        job.reported_total = page.reported_total
        job.visited_page_fingerprints = [*job.visited_page_fingerprints, page_fingerprint]

        observations = job.observations.filter(collection_generation=job.collection_generation)
        seen = dict(
            observations.filter(review__identity_key__in=identity_keys).values_list(
                "review__identity_key", "review__version_sha256"
            )
        )
        versions = [
            version_fingerprint(
                text, item.author_or_source_label, item.score_label, item.date_label
            )
            for item, text in zip(page.items, normalized_texts, strict=True)
        ]
        # A source edit within a route is not two distinct reviews. Reject that page before
        # saving any of its observations; previous accepted pages remain an incomplete snapshot.
        for key, version in zip(identity_keys, versions, strict=True):
            if key in seen and seen[key] != version:
                job.state = "unstable"
                job.last_error = "review_changed_during_collection"
                _finish_fetch(source_fetch, now, "invalid", job.last_error)
                job.save(update_fields=["attempt_count", "state", "last_error"])
                return job
            seen[key] = version

        route_position = job.fetched_count
        for offset, (item, key, normalized, version) in enumerate(
            zip(page.items, identity_keys, normalized_texts, versions, strict=True)
        ):
            content_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            older = None
            if item.source_review_id:
                older = (
                    Review.objects.filter(
                        game_platform=platform, audience=job.audience, identity_key=key
                    )
                    .order_by("-first_seen_at", "-id")
                    .first()
                )
            review, _ = Review.objects.get_or_create(
                game_platform=platform,
                audience=job.audience,
                identity_key=key,
                version_sha256=version,
                defaults={
                    "content_sha256": content_sha256,
                    "source_review_id": item.source_review_id,
                    "author_label": item.author_or_source_label,
                    "score_label": item.score_label,
                    "date_label": item.date_label,
                    "text_original": normalized,
                    "first_seen_at": now,
                    "supersedes": older,
                },
            )

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
        # Count the current generation, not globally new Review rows (R03). Deriving counters
        # from observations also corrects old counters on an in-flight job's next accepted page.
        job.unique_count = observations.values("review__identity_key").distinct().count()
        job.duplicate_count = job.fetched_count - job.unique_count
        job.page_count += 1
        job.next_cursor = page.next_cursor

        if page.next_cursor is None:
            if job.reported_total == 0 and job.fetched_count == 0:
                job.state = "empty"
            elif job.reported_total == job.unique_count and job.duplicate_count == 0:
                job.state = "complete"
            else:
                job.state = "unstable"
                job.last_error = "unique_count_mismatch"
            job.completed_at = now
        else:
            job.state = "pending"

        _finish_fetch(
            source_fetch, now, "invalid" if job.state == "unstable" else "succeeded", job.last_error
        )
        job.available_at = None
        job.save()

        if job.state in ("complete", "empty"):
            _maybe_build_corpus_and_summary_job(game, job.audience)

    return job
