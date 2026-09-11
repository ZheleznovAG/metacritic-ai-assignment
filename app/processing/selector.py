"""Deterministic batch formation per `research/feasibility/processing-state.md`'s 8-step
algorithm ("Детерминированное формирование партии"). Must run with `run`'s lease already held.
"""

from dataclasses import dataclass

from catalog.ingest import resolve_game_identity, save_fetch_evidence
from django.db import transaction
from metacritic.dto import GameIdentityDTO
from metacritic.gateway import GatewayProtocol

from processing.clock import Clock
from processing.lease import verify_fencing_token
from processing.models import DailyCandidate, DailyCycle, ProcessingRun
from processing.runner import process_candidate

BATCH_LIMIT = 20


@dataclass(frozen=True, slots=True)
class BatchResult:
    selected_count: int
    processed_count: int
    failed_count: int
    status: str  # succeeded | partial | failed


def _recover_stale_candidates() -> int:
    # Step 1. A fresh lease acquisition (a prerequisite for even calling this) proves no other
    # run can still be legitimately writing, so any leftover "processing" row is necessarily from
    # a run that crashed or lost the lease (PS-08) — never a currently-active one.
    return DailyCandidate.objects.filter(state="processing").update(
        state="retryable", last_error="interrupted"
    )


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

    _recover_stale_candidates()

    with transaction.atomic():
        verify_fencing_token(fencing_token)
        cycle, _ = DailyCycle.objects.select_for_update().get_or_create(
            business_date=run.business_day, timezone="UTC"
        )

    # Step 2/3: existing work first (retry-first), in original selection order.
    batch = list(
        DailyCandidate.objects.filter(cycle=cycle, state__in=("pending", "retryable"))
        .order_by("source_order")
        .select_related("game")
    )
    remaining = BATCH_LIMIT - len(batch)
    discovery_failed = False

    if remaining > 0 and cycle.phase == "new_releases_pending":
        # Step 4: first batch of the day is New Releases only; SEE ALL is not read this run
        # even if there is spare capacity (ASM-06).
        games, evidence = gateway.list_new_releases()
        save_fetch_evidence(evidence)
        if games is None:
            discovery_failed = True
        else:
            with transaction.atomic():
                verify_fencing_token(fencing_token)
                created = _append_candidates(cycle, games[:BATCH_LIMIT], clock)
                cycle.phase = "browse"
                cycle.save(update_fields=["phase"])
            batch.extend(created)
            remaining = BATCH_LIMIT - len(batch)

    elif remaining > 0 and cycle.phase == "browse":
        # Step 5/6: SEE ALL from the saved cursor, skipping already-known identities, until
        # capacity fills or the source confirms exhaustion; a page failure stops the scan without
        # advancing the cursor past it.
        while remaining > 0:
            page, evidence = gateway.iter_browse(cycle.browse_next_page)
            save_fetch_evidence(evidence)
            if page is None:
                discovery_failed = True
                break
            with transaction.atomic():
                verify_fencing_token(fencing_token)
                known = _existing_source_game_ids(cycle)
                new_identities = [g for g in page.games if g.source_game_id not in known]
                created = _append_candidates(cycle, new_identities[:remaining], clock)
                cycle.browse_next_page += 1
                if not page.has_next_page:
                    cycle.phase = "exhausted"
                cycle.save(update_fields=["browse_next_page", "phase"])
            batch.extend(created)
            remaining = BATCH_LIMIT - len(batch)
            if not page.has_next_page:
                break

    # Step 7: the batch is frozen here — a core failure below does not pull in a replacement.
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
    if not discovery_failed and failed_count == 0:
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
    )
