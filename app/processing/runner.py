"""Per-candidate core processing: claim, fetch, apply, close — one candidate at a time.

Reuses `catalog.ingest`'s `fetch_and_prepare`/`apply_game_dto` (the same upsert core `IMP-02`
built and tested), but owns the `DailyCandidate`/`CoreAttempt` lifecycle itself instead of
`catalog.ingest.ingest_game`'s own simplified stand-in (that function stays as the manual
one-off proof tool; see its module docstring).
"""

from catalog.ingest import (
    IdentityConflict,
    PlatformIdentityConflict,
    apply_game_dto,
    ensure_jobs,
    fetch_and_prepare,
)
from django.db import transaction
from metacritic.gateway import ALLOWED_HOST, GatewayProtocol

from processing.clock import Clock
from processing.lease import verify_fencing_token
from processing.models import CoreAttempt, DailyCandidate, ProcessingRun

MAX_AUTOMATIC_ATTEMPTS = 5


def detail_url_for(candidate: DailyCandidate) -> str:
    return f"https://{ALLOWED_HOST}{candidate.game.canonical_locator}"


def process_candidate(
    gateway: GatewayProtocol, clock: Clock, run: ProcessingRun, candidate: DailyCandidate
) -> DailyCandidate:
    """Fetches and applies one candidate's core data. On success, transitions it to `processed`;
    on a classified failure, to `retryable` (never replaced within this run — `PS-INV-05`).

    Raises `processing.lease.StaleRun` if the lease has moved on since this run acquired it; the
    caller must stop processing further candidates in that case (`PS-INV-02`).
    """
    if run.fencing_token is None:
        raise ValueError("run must have an acquired fencing_token before processing candidates")
    fencing_token = run.fencing_token

    with transaction.atomic():
        verify_fencing_token(fencing_token, owner_run_id=run.pk, now=clock.now_utc())
        candidate = DailyCandidate.objects.select_for_update().get(pk=candidate.pk)
        if candidate.state not in ("pending", "retryable"):
            return candidate
        previous_attempt = candidate.attempts.order_by("-attempt_no").first()
        candidate.attempt_count = max(
            candidate.attempt_count, previous_attempt.attempt_no if previous_attempt else 0
        )
        if candidate.attempt_count >= MAX_AUTOMATIC_ATTEMPTS:
            candidate.state = "failed"
            candidate.last_error = "attempt_limit"
            candidate.save(update_fields=["state", "attempt_count", "last_error"])
            return candidate
        candidate.attempt_count += 1
        attempt_no = candidate.attempt_count
        attempt = CoreAttempt.objects.create(
            candidate=candidate,
            run=run,
            attempt_no=attempt_no,
            fencing_token=fencing_token,
            started_at=clock.now_utc(),
        )
        candidate.state = "processing"
        candidate.save(update_fields=["state", "attempt_count"])

    game_dto, fetch, platform_userscore_fetch = fetch_and_prepare(
        gateway, detail_url_for(candidate)
    )
    now = clock.now_utc()

    if game_dto is None:
        with transaction.atomic():
            verify_fencing_token(fencing_token, owner_run_id=run.pk, now=clock.now_utc())
            CoreAttempt.objects.filter(pk=attempt.pk, outcome__isnull=True).update(
                ended_at=now,
                outcome="failed",
                error_code=fetch.error_code,
            )
            candidate.state = "failed" if attempt_no >= MAX_AUTOMATIC_ATTEMPTS else "retryable"
            candidate.attempt_count = attempt_no
            candidate.last_error = fetch.error_code
            candidate.save(update_fields=["state", "attempt_count", "last_error"])
        return candidate

    try:
        with transaction.atomic():
            verify_fencing_token(fencing_token, owner_run_id=run.pk, now=clock.now_utc())
            applied = apply_game_dto(game_dto, fetch, platform_userscore_fetch, now)
            CoreAttempt.objects.filter(pk=attempt.pk, outcome__isnull=True).update(
                ended_at=clock.now_utc(),
                outcome="succeeded",
            )
            candidate.state = "processed"
            candidate.attempt_count = attempt_no
            candidate.last_error = None
            candidate.save(update_fields=["state", "attempt_count", "last_error"])
            ensure_jobs(candidate, applied.platforms)
    except (IdentityConflict, PlatformIdentityConflict) as error:
        with transaction.atomic():
            verify_fencing_token(fencing_token, owner_run_id=run.pk, now=clock.now_utc())
            CoreAttempt.objects.filter(pk=attempt.pk, outcome__isnull=True).update(
                ended_at=clock.now_utc(),
                outcome="failed",
                error_code=type(error).__name__,
            )
            candidate.state = "failed" if attempt_no >= MAX_AUTOMATIC_ATTEMPTS else "retryable"
            candidate.attempt_count = attempt_no
            candidate.last_error = str(error)[:255]
            candidate.save(update_fields=["state", "attempt_count", "last_error"])
    return candidate
