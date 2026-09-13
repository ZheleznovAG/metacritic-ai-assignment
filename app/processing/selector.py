"""Deterministic batch formation per `research/feasibility/processing-state.md`'s 8-step
algorithm ("Детерминированное формирование партии"). Must run with `run`'s lease already held.
"""

from dataclasses import dataclass
from time import monotonic

from catalog.ingest import resolve_game_identity, save_fetch_evidence
from django.db import transaction
from metacritic.dto import GameIdentityDTO
from metacritic.gateway import GatewayProtocol

from processing.clock import Clock
from processing.lease import verify_fencing_token
from processing.models import CoreAttempt, DailyCandidate, DailyCycle, ProcessingRun
from processing.runner import MAX_AUTOMATIC_ATTEMPTS, process_candidate

BATCH_LIMIT = 20
# Admission bounds for one discovery scan, not a source-volume/exhaustion limit. A fetched
# page is committed even if it finishes after the deadline; no further request is started.
BROWSE_PAGE_LIMIT = 100
BROWSE_TIME_LIMIT_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class BatchResult:
    selected_count: int
    processed_count: int
    failed_count: int
    status: str  # succeeded | partial | failed
    error_code: str | None = None


def _recover_stale_candidates(fencing_token: int, clock: Clock) -> None:
    # Step 1. A fresh lease acquisition (a prerequisite for even calling this) proves no other
    # run can still be legitimately writing, so any leftover "processing" row is necessarily from
    # a run that crashed or lost the lease (PS-08) — never a currently-active one.
    active = CoreAttempt.objects.filter(outcome__isnull=True, fencing_token=fencing_token)
    interrupted = DailyCandidate.objects.filter(state="processing").exclude(
        pk__in=active.values("candidate_id")
    )
    CoreAttempt.objects.filter(candidate__in=interrupted, outcome__isnull=True).update(
        outcome="failed", error_code="interrupted", ended_at=clock.now_utc()
    )
    interrupted.update(state="retryable", last_error="interrupted")
    # History, not an operator's state/counter edit, is the durable budget authority.
    exhausted = CoreAttempt.objects.filter(attempt_no__gte=MAX_AUTOMATIC_ATTEMPTS)
    for candidate in DailyCandidate.objects.filter(
        state__in=("pending", "retryable"), pk__in=exhausted.values("candidate_id")
    ):
        last = candidate.attempts.order_by("-attempt_no").first()
        candidate.state = "failed"
        candidate.attempt_count = max(
            candidate.attempt_count, last.attempt_no if last else MAX_AUTOMATIC_ATTEMPTS
        )
        candidate.last_error = "attempt_limit"
        candidate.save(update_fields=["state", "attempt_count", "last_error"])
    DailyCandidate.objects.filter(
        state__in=("pending", "retryable"), attempt_count__gte=MAX_AUTOMATIC_ATTEMPTS
    ).update(state="failed", last_error="attempt_limit")


def _existing_source_game_ids(cycle: DailyCycle) -> set[str]:
    return set(
        DailyCandidate.objects.filter(cycle=cycle).values_list("game__source_game_id", flat=True)
    )


def _append_candidates(
    cycle: DailyCycle, identities: list[GameIdentityDTO], clock: Clock
) -> list[DailyCandidate]:
    """Step 4/5 (save side): resolves each identity to a Game and creates its DailyCandidate,
    in source order, continuing the cycle's existing ordering. Caller wraps this in one atomic
    block alongside the phase/cursor advance it belongs with."""
    now = clock.now_utc()
    next_order = (
        DailyCandidate.objects.filter(cycle=cycle)
        .order_by("-source_order")
        .values_list("source_order", flat=True)
        .first()
        or 0
    )
    created: list[DailyCandidate] = []
    for identity in identities:
        next_order += 1
        game, _ = resolve_game_identity(identity, now)
        candidate = DailyCandidate.objects.create(
            cycle=cycle, game=game, source_order=next_order, state="pending"
        )
        created.append(candidate)
    return created


def run_batch(gateway: GatewayProtocol, clock: Clock, run: ProcessingRun) -> BatchResult:
    """`run.business_day`/`run.fencing_token` must already be set (the caller acquired the lease
    and created `run` before calling this). Discovers up to `BATCH_LIMIT` new candidates per the
    current `DailyCycle` phase, then processes the full batch (existing + newly discovered)."""
    if run.business_day is None or run.fencing_token is None:
        raise ValueError("run must have business_day/fencing_token set before run_batch")
    fencing_token = run.fencing_token

    with transaction.atomic():
        verify_fencing_token(fencing_token, owner_run_id=run.pk, now=clock.now_utc())
        _recover_stale_candidates(fencing_token, clock)
        cycle, _ = DailyCycle.objects.select_for_update().get_or_create(
            business_date=run.business_day, timezone="UTC"
        )

    # Step 2/3: existing work first (retry-first), in original selection order.
    batch = list(
        DailyCandidate.objects.filter(cycle=cycle, state__in=("pending", "retryable"))
        .order_by("source_order")
        .select_related("game")[:BATCH_LIMIT]
    )
    remaining = BATCH_LIMIT - len(batch)
    discovery_error = None

    if remaining > 0 and cycle.phase == "new_releases_pending":
        # Step 4: first batch of the day is New Releases only; SEE ALL is not read this run
        # even if there is spare capacity (ASM-06).
        games, evidence = gateway.list_new_releases()
        save_fetch_evidence(evidence)
        if games is None:
            discovery_error = evidence.error_code or "new_releases_failed"
        else:
            with transaction.atomic():
                verify_fencing_token(fencing_token, owner_run_id=run.pk, now=clock.now_utc())
                known = _existing_source_game_ids(cycle)
                unique_games = []
                for game in games:
                    if game.source_game_id not in known:
                        unique_games.append(game)
                        known.add(game.source_game_id)
                created = _append_candidates(cycle, unique_games[:remaining], clock)
                cycle.phase = "browse"
                cycle.save(update_fields=["phase"])
            batch.extend(created)
            remaining = BATCH_LIMIT - len(batch)

    elif remaining > 0 and cycle.phase == "browse":
        # Step 5/6: SEE ALL from the saved cursor, skipping already-known identities, until
        # capacity fills or the source confirms exhaustion; a page failure stops the scan without
        # advancing the cursor past it. A partial page is reread next time; the durable cycle
        # identity set skips its accepted prefix. Only a fully consumed page advances the cursor.
        deadline = monotonic() + BROWSE_TIME_LIMIT_SECONDS
        fetched_pages = 0
        seen_pages: set[frozenset[str]] = set()
        while remaining > 0:
            if fetched_pages >= BROWSE_PAGE_LIMIT:
                discovery_error = "browse_page_limit"
                break
            if monotonic() >= deadline:
                discovery_error = "browse_time_limit"
                break
            page, evidence = gateway.iter_browse(cycle.browse_next_page)
            fetched_pages += 1
            save_fetch_evidence(evidence)
            if page is None:
                discovery_error = evidence.error_code or "browse_fetch_failed"
                break
            signature = frozenset(game.source_game_id for game in page.games)
            if page.has_next_page and (not signature or signature in seen_pages):
                discovery_error = "browse_repeated_page" if signature else "browse_empty_page"
                break
            seen_pages.add(signature)
            with transaction.atomic():
                verify_fencing_token(fencing_token, owner_run_id=run.pk, now=clock.now_utc())
                known = _existing_source_game_ids(cycle)
                new_identities = []
                for game in page.games:
                    if game.source_game_id not in known:
                        new_identities.append(game)
                        known.add(game.source_game_id)
                created = _append_candidates(cycle, new_identities[:remaining], clock)
                if len(new_identities) <= remaining:
                    cycle.browse_next_page += 1
                    if not page.has_next_page:
                        cycle.phase = "exhausted"
                cycle.save(update_fields=["browse_next_page", "phase"])
            batch.extend(created)
            remaining = BATCH_LIMIT - len(batch)
            if not page.has_next_page:
                break

    # Step 7: the batch is frozen here — a core failure below does not pull in a replacement.
    run.selected_count = len(batch)
    run.save(update_fields=["selected_count"])
    processed_count = 0
    failed_count = 0
    for candidate in batch:
        candidate = process_candidate(gateway, clock, run, candidate)
        if candidate.state == "processed":
            processed_count += 1
        else:
            failed_count += 1

    # Step 8: exhausted + nothing selected is still a successful run with explicit zero counters.
    # "No progress" (processing-state.md's failed row) covers both an empty batch caused by a
    # discovery/execution failure and a non-empty batch where every selected item failed.
    if discovery_error is None and failed_count == 0:
        status = "succeeded"
    elif processed_count == 0:
        status = "failed"
    else:
        status = "partial"

    return BatchResult(
        selected_count=len(batch),
        processed_count=processed_count,
        failed_count=failed_count,
        status=status,
        error_code=discovery_error,
    )
