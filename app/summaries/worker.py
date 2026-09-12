"""Row-leased `SummaryJob` claim and attempt processing: the AI half of the worker's two job
types (`docs/design.md`). Same row-lease pattern as `reviews.collector`, on this app's own model.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import httpx
from django.db import transaction
from django.db.models import F, Q
from processing.clock import Clock
from reviews.models import ReviewCorpus

from summaries import contour, groq_adapter, quota
from summaries.groq_adapter import GroqApiError
from summaries.models import ReviewSummary, SummaryAttempt, SummaryClaim, SummaryJob

LEASE_TTL = timedelta(minutes=5)
MAX_AUTOMATIC_ATTEMPTS = 5
BACKOFF_STEPS = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=6),
)
MINIMUM_REVIEWS_FOR_A_SUMMARY = 3
GUARDED_RESERVATION_CEILING = 6800  # research/feasibility/ai-summary.md preflight ceiling


def _backoff_for(attempt_count: int) -> timedelta:
    index = min(attempt_count - 1, len(BACKOFF_STEPS) - 1)
    return BACKOFF_STEPS[index]


def ensure_job(corpus: ReviewCorpus) -> SummaryJob:
    """Idempotent: the same corpus + contour always resolves to the same job row (cache hit)."""
    job, _ = SummaryJob.objects.get_or_create(
        game=corpus.game,
        audience=corpus.audience,
        input_fingerprint=corpus.model_input_fingerprint,
        contour_fingerprint=contour.contour_fingerprint(),
        defaults={"source_corpus": corpus},
    )
    return job


def _recover_stale_leases(now: datetime) -> None:
    """A `running` job whose lease has expired was left mid-flight by a crashed/killed worker.
    Bumping the fencing token here immediately invalidates any late commit the presumed-dead
    worker might still attempt, even before anyone re-claims the row (same reasoning as
    `reviews.collector`'s stale-lease recovery)."""
    SummaryJob.objects.filter(state="running", lease_expires_at__lt=now).update(
        state="retryable",
        fencing_token=F("fencing_token") + 1,
        last_error="lease_expired",
    )


def claim_next_job(clock: Clock) -> SummaryJob | None:
    with transaction.atomic():
        now = clock.now_utc()
        _recover_stale_leases(now)
        job = (
            SummaryJob.objects.select_for_update(skip_locked=True)
            .filter(state__in=["pending", "retryable", "delayed_capacity"])
            .filter(Q(available_at__isnull=True) | Q(available_at__lte=now))
            .order_by("id")
            .first()
        )
        if job is None:
            return None
        job.fencing_token += 1
        job.lease_expires_at = now + LEASE_TTL
        job.state = "running"
        job.save(update_fields=["fencing_token", "lease_expires_at", "state"])
        return job


def _still_owned(job_id: int, expected_token: int) -> SummaryJob | None:
    job = SummaryJob.objects.select_for_update().get(pk=job_id)
    return job if job.fencing_token == expected_token else None


def process_job(
    client: httpx.Client, clock: Clock, job: SummaryJob, *, api_key: str, base_url: str
) -> SummaryJob:
    fencing_token = job.fencing_token
    now = clock.now_utc()
    corpus = job.source_corpus
    items = list(corpus.items.order_by("ordinal"))

    if corpus.unique_count < MINIMUM_REVIEWS_FOR_A_SUMMARY:
        with transaction.atomic():
            current = _still_owned(job.id, fencing_token)
            if current is None:
                return job
            job = current
            job.state = "insufficient_data"
            job.last_error = None
            job.save(update_fields=["state", "last_error"])
            ReviewSummary.objects.get_or_create(
                job=job,
                defaults={
                    "status": "insufficient_data",
                    "generated_at": now,
                    "insufficient_reason": "not_enough_meaningful_reviews",
                    "canonical_output_fingerprint": hashlib.sha256(
                        b"insufficient_data"
                    ).hexdigest(),
                },
            )
        return job

    if not quota.has_capacity(clock, GUARDED_RESERVATION_CEILING):
        with transaction.atomic():
            current = _still_owned(job.id, fencing_token)
            if current is None:
                return job
            job = current
            job.state = "delayed_capacity"
            job.available_at = now + timedelta(minutes=1)
            job.last_error = "quota_exhausted"
            job.save(update_fields=["state", "available_at", "last_error"])
        return job

    correlation_id = f"summary-job-{job.id}"
    reviews_payload = [{"id": item.prompt_review_id, "text": item.input_text} for item in items]
    attempt_no = job.attempt_count + 1

    with transaction.atomic():
        current = _still_owned(job.id, fencing_token)
        if current is None:
            return job
        job = current
        attempt = SummaryAttempt.objects.create(
            job=job,
            attempt_no=attempt_no,
            provider=contour.PROVIDER,
            api_kind=contour.API_KIND,
            requested_model=contour.REQUESTED_MODEL,
            contour_versions=contour.contour_versions(),
            generation_params=contour.GENERATION_PARAMS,
            estimated_prompt_tokens=corpus.guarded_prompt_tokens,
            reserved_total_tokens=GUARDED_RESERVATION_CEILING,
            started_at=now,
        )
        job.attempt_count = attempt_no
        job.save(update_fields=["attempt_count"])

    try:
        result = groq_adapter.generate_summary(
            client,
            api_key=api_key,
            base_url=base_url,
            correlation_id=correlation_id,
            audience=job.audience,
            reviews=reviews_payload,
        )
    except GroqApiError as error:
        completed_at = clock.now_utc()
        with transaction.atomic():
            current = _still_owned(job.id, fencing_token)
            if current is None:
                return job
            job = current
            if error.status == 429:
                outcome = "delayed_capacity"
                job.state = "delayed_capacity"
                job.available_at = completed_at + timedelta(
                    seconds=error.retry_after if error.retry_after else 60
                )
                error_code = "rate_limited"
            elif attempt_no < MAX_AUTOMATIC_ATTEMPTS:
                outcome = "retryable"
                job.state = "retryable"
                job.available_at = completed_at + _backoff_for(attempt_no)
                error_code = "transport_error"
            else:
                outcome = "failed"
                job.state = "failed"
                error_code = "transport_error"
            attempt.completed_at = completed_at
            attempt.outcome = outcome
            attempt.error_code = error_code
            attempt.save(update_fields=["completed_at", "outcome", "error_code"])
            job.last_error = error_code
            job.save(update_fields=["state", "available_at", "last_error"])
        return job

    completed_at = clock.now_utc()
    with transaction.atomic():
        current = _still_owned(job.id, fencing_token)
        if current is None:
            return job
        job = current
        attempt.completed_at = completed_at
        attempt.latency_ms = result.latency_ms
        attempt.returned_model = result.returned_model
        attempt.provider_system_fingerprint = result.provider_system_fingerprint
        attempt.actual_prompt_tokens = result.prompt_tokens
        attempt.actual_completion_tokens = result.completion_tokens
        attempt.actual_total_tokens = result.total_tokens

        if result.structural_errors:
            attempt.outcome = "retryable"
            attempt.error_code = "malformed_output"
            attempt.save()
            if attempt_no < MAX_AUTOMATIC_ATTEMPTS:
                job.state = "retryable"
                job.available_at = completed_at + _backoff_for(attempt_no)
            else:
                job.state = "failed"
            job.last_error = "malformed_output"
            job.save(update_fields=["state", "available_at", "last_error"])
            return job

        output = result.output
        if output is None:
            raise RuntimeError(
                "a successful GroqCallResult must carry output when structural_errors is empty"
            )
        status = output["status"]
        attempt.outcome = "succeeded" if status == "ok" else "insufficient_data"
        attempt.save()

        summary = ReviewSummary.objects.create(
            job=job,
            successful_attempt=attempt,
            method="model",
            status=status,
            generated_at=completed_at,
            insufficient_reason=output.get("insufficient_data_reason"),
            canonical_output_fingerprint=hashlib.sha256(
                contour.canonical_json(output).encode("utf-8")
            ).hexdigest(),
            normalization_notes=result.normalizations,
        )
        if status == "ok":
            items_by_prompt_id = {item.prompt_review_id: item for item in items}
            for polarity, field in (("like", "likes"), ("dislike", "dislikes")):
                for ordinal, claim in enumerate(output.get(field, []), start=1):
                    support_item = items_by_prompt_id.get(claim["support"][0])
                    if support_item is None:
                        continue
                    SummaryClaim.objects.create(
                        summary=summary,
                        polarity=polarity,
                        ordinal=ordinal,
                        claim=claim["claim"],
                        support_item=support_item,
                    )
        job.state = status if status == "insufficient_data" else "succeeded"
        job.last_error = None
        job.save(update_fields=["state", "last_error"])
    return job
