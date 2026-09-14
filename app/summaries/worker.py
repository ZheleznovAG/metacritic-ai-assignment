"""Durable AI admission: one leased attempt, one measured request, one terminal outcome."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import httpx
from django.db import transaction
from django.db.models import Q
from processing.clock import Clock
from reviews.models import ReviewCorpus

from summaries import contour, groq_adapter, preflight, quota
from summaries.groq_adapter import GroqApiError, GroqConfigError
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


def _backoff_for(attempt_count: int) -> timedelta:
    return BACKOFF_STEPS[min(attempt_count - 1, len(BACKOFF_STEPS) - 1)]


def ensure_job(corpus: ReviewCorpus) -> SummaryJob:
    job, _ = SummaryJob.objects.get_or_create(
        game=corpus.game,
        audience=corpus.audience,
        input_fingerprint=corpus.model_input_fingerprint,
        contour_fingerprint=contour.contour_fingerprint(),
        defaults={"source_corpus": corpus},
    )
    return job


def _recover_stale_leases(now: datetime) -> None:
    expired = SummaryJob.objects.select_for_update(skip_locked=True).filter(
        state="running", lease_expires_at__lte=now
    )
    for job in expired:
        job.attempts.filter(outcome__isnull=True).update(
            outcome="abandoned", error_code="lease_expired", completed_at=now
        )
        job.fencing_token += 1
        job.state = "failed" if job.attempt_count >= MAX_AUTOMATIC_ATTEMPTS else "retryable"
        job.available_at = now
        job.last_error = "lease_expired"
        job.save(update_fields=["state", "fencing_token", "available_at", "last_error"])


def claim_next_job(clock: Clock) -> SummaryJob | None:
    with transaction.atomic():
        now = clock.now_utc()
        _recover_stale_leases(now)
        SummaryJob.objects.filter(
            state__in=("pending", "retryable", "delayed_capacity"),
            attempt_count__gte=MAX_AUTOMATIC_ATTEMPTS,
        ).update(state="failed", last_error="attempt_limit")
        job = (
            SummaryJob.objects.select_for_update(skip_locked=True)
            .filter(state__in=["pending", "retryable", "delayed_capacity"])
            .filter(Q(available_at__isnull=True) | Q(available_at__lte=now))
            .order_by("id")
            .first()
        )
        if job is None:
            return None
        job.attempts.filter(outcome__isnull=True).update(
            outcome="abandoned", error_code="lease_expired", completed_at=now
        )
        job.fencing_token += 1
        job.lease_expires_at = now + LEASE_TTL
        job.state = "running"
        job.save(update_fields=["fencing_token", "lease_expires_at", "state"])
        return job


def _still_owned(
    job_id: int, expected_token: int, now: datetime, attempt_id: int | None = None
) -> SummaryJob | None:
    job = SummaryJob.objects.select_for_update().get(pk=job_id)
    if (
        job.fencing_token == expected_token
        and job.state == "running"
        and job.lease_expires_at is not None
        and job.lease_expires_at > now
    ):
        return job
    if attempt_id is not None:
        SummaryAttempt.objects.filter(
            pk=attempt_id, fencing_token=expected_token, outcome__isnull=True
        ).update(outcome="abandoned", error_code="lease_expired", completed_at=now)
    return None


def _local_failure(job: SummaryJob, code: str) -> SummaryJob:
    job.state = "failed"
    job.last_error = code
    job.save(update_fields=["state", "last_error"])
    return job


def _attempt_failure(
    job: SummaryJob,
    attempt: SummaryAttempt,
    now: datetime,
    code: str,
    *,
    terminal: bool = False,
    retry_after: float | None = None,
) -> SummaryJob:
    if terminal or job.attempt_count >= MAX_AUTOMATIC_ATTEMPTS:
        job.state = "failed"
    elif retry_after is not None:
        job.state = "delayed_capacity"
        job.available_at = now + timedelta(seconds=max(1, retry_after))
    else:
        job.state = "retryable"
        job.available_at = now + _backoff_for(job.attempt_count)
    attempt.completed_at = now
    attempt.outcome = job.state
    attempt.error_code = code
    attempt.save()
    job.last_error = code
    job.save(update_fields=["state", "available_at", "last_error"])
    return job


def process_job(
    client: httpx.Client, clock: Clock, job: SummaryJob, *, api_key: str, base_url: str
) -> SummaryJob:
    token = job.fencing_token
    with transaction.atomic():
        current = _still_owned(job.pk, token, clock.now_utc())
        if current is None:
            return SummaryJob.objects.get(pk=job.pk)
        job = current
        # A concurrent delivery of this same claim has already admitted its HTTP intent.
        if job.attempts.filter(outcome__isnull=True).exists():
            return job
        if job.attempt_count >= MAX_AUTOMATIC_ATTEMPTS:
            return _local_failure(job, "attempt_limit")
        if job.contour_fingerprint != contour.contour_fingerprint():
            return _local_failure(job, "contour_changed")
        corpus = job.source_corpus
        items = list(corpus.items.order_by("ordinal"))
        now = clock.now_utc()
        if corpus.unique_count < MINIMUM_REVIEWS_FOR_A_SUMMARY:
            job.state = "insufficient_data"
            job.last_error = None
            job.save(update_fields=["state", "last_error"])
            ReviewSummary.objects.get_or_create(
                job=job,
                defaults={
                    "method": "rule",
                    "status": "insufficient_data",
                    "generated_at": now,
                    "insufficient_reason": "not_enough_meaningful_reviews",
                    "canonical_output_fingerprint": hashlib.sha256(
                        b"insufficient_data"
                    ).hexdigest(),
                },
            )
            return job

        correlation_id = f"summary-job-{job.id}"
        reviews_payload = [{"id": item.prompt_review_id, "text": item.input_text} for item in items]
        try:
            base_url = groq_adapter.validate_base_url(base_url)
            prepared = preflight.prepare(correlation_id, job.audience, reviews_payload)
        except preflight.PreflightError as error:
            return _local_failure(job, str(error))
        except (GroqConfigError, OSError, RuntimeError):
            return _local_failure(job, "configuration_error")
        quota.lock_admission()
        if quota.budget_halted(job.contour_fingerprint):
            return _local_failure(job, "usage_budget_halted")
        if not quota.has_capacity(clock, prepared.reserved_tokens):
            job.state = "delayed_capacity"
            job.available_at = quota.next_available_at(clock, prepared.reserved_tokens)
            job.last_error = "quota_exhausted"
            job.save(update_fields=["state", "available_at", "last_error"])
            return job
        now = clock.now_utc()
        if job.lease_expires_at is None or job.lease_expires_at <= now:
            return job
        job.attempt_count += 1
        attempt = SummaryAttempt.objects.create(
            job=job,
            attempt_no=job.attempt_count,
            fencing_token=token,
            request_sha256=prepared.sha256,
            raw_prompt_tokens=prepared.raw_tokens,
            provider=contour.PROVIDER,
            api_kind=contour.API_KIND,
            requested_model=contour.REQUESTED_MODEL,
            contour_versions=contour.contour_versions(),
            generation_params=contour.GENERATION_PARAMS,
            estimated_prompt_tokens=prepared.guarded_tokens,
            reserved_total_tokens=prepared.reserved_tokens,
            started_at=now,
        )
        job.save(update_fields=["attempt_count"])

    # All DB locks are released before the one HTTP call. The same measured payload is sent.
    try:
        result = groq_adapter.generate_summary(
            client,
            api_key=api_key,
            base_url=base_url,
            correlation_id=correlation_id,
            audience=job.audience,
            reviews=reviews_payload,
            payload=prepared.payload,
        )
    except GroqApiError as error:
        now = clock.now_utc()
        with transaction.atomic():
            current = _still_owned(job.pk, token, now, attempt.pk)
            if current is None:
                return SummaryJob.objects.get(pk=job.pk)
            attempt.refresh_from_db()
            if attempt.outcome is not None:
                return current
            attempt.rate_limit_headers = error.rate_limit_headers
            return _attempt_failure(
                current,
                attempt,
                now,
                "rate_limited" if error.status == 429 else "transport_error",
                terminal=error.status is not None and error.status not in (429, 500, 502, 503, 504),
                retry_after=(error.retry_after or 60) if error.status == 429 else None,
            )

    now = clock.now_utc()
    with transaction.atomic():
        current = _still_owned(job.pk, token, now, attempt.pk)
        if current is None:
            return SummaryJob.objects.get(pk=job.pk)
        job = current
        attempt.refresh_from_db()
        if attempt.outcome is not None:
            return job
        attempt.completed_at = now
        attempt.latency_ms = result.latency_ms
        attempt.returned_model = result.returned_model
        attempt.provider_system_fingerprint = result.provider_system_fingerprint
        attempt.actual_prompt_tokens = result.prompt_tokens
        attempt.actual_completion_tokens = result.completion_tokens
        attempt.actual_total_tokens = result.total_tokens
        attempt.rate_limit_headers = result.rate_limit_headers
        if (
            (
                result.prompt_tokens is not None
                and result.prompt_tokens > attempt.estimated_prompt_tokens
            )
            or (
                result.completion_tokens is not None
                and result.completion_tokens > contour.MAX_COMPLETION_TOKENS
            )
            or (
                result.total_tokens is not None
                and result.total_tokens > attempt.reserved_total_tokens
            )
        ):
            return _attempt_failure(job, attempt, now, "usage_exceeds_budget", terminal=True)
        if result.structural_errors or result.output is None:
            return _attempt_failure(job, attempt, now, "malformed_output")
        output = result.output
        status = output["status"]
        attempt.outcome = "succeeded" if status == "ok" else "insufficient_data"
        attempt.save()
        summary = ReviewSummary.objects.create(
            job=job,
            successful_attempt=attempt,
            method="model",
            status=status,
            generated_at=now,
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
