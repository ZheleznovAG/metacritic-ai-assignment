"""State model per `research/feasibility/processing-state.md` (`SPK-04`): one singleton
`ProcessingLease` guards one `ProcessingRun` at a time; `DailyCycle`/`DailyCandidate` track
per-business-day discovery progress; `CoreAttempt` is the per-candidate claim/outcome record.
"""

from django.db import models


class ProcessingRun(models.Model):
    STATUS_CHOICES = [
        ("queued", "queued"),
        ("running", "running"),
        ("succeeded", "succeeded"),
        ("partial", "partial"),
        ("failed", "failed"),
        ("skipped_duplicate", "skipped_duplicate"),
        ("skipped_overlap", "skipped_overlap"),
    ]

    trigger_key = models.CharField(max_length=64, unique=True)
    scheduled_slot = models.DateTimeField()
    business_day = models.DateField(null=True, blank=True)
    # Copied from ProcessingLease.fencing_token at acquisition; a later commit re-checks the
    # lease still carries this same token before writing (PS-INV-02 — a stale owner must not
    # commit after the token has moved on).
    fencing_token = models.PositiveBigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    selected_count = models.PositiveIntegerField(default=0)
    processed_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    batch_frozen_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.trigger_key}:{self.status}"


class ProcessingLease(models.Model):
    """Singleton row: `resource="ingestion"` is the only one ever created."""

    resource = models.CharField(max_length=32, unique=True, default="ingestion")
    fencing_token = models.PositiveBigIntegerField(default=0)
    owner_run = models.ForeignKey(
        ProcessingRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.resource} token={self.fencing_token}"


class DailyCycle(models.Model):
    business_date = models.DateField()
    timezone = models.CharField(max_length=64, default="UTC")
    phase = models.CharField(
        max_length=32,
        choices=[
            ("new_releases_pending", "new_releases_pending"),
            ("browse", "browse"),
            ("exhausted", "exhausted"),
        ],
        default="new_releases_pending",
    )
    # Next SEE ALL page to fetch; only advances past a page once it has been fully read and its
    # identities saved (PS-INV-07). `page=1`-indexed, matching the confirmed `?page=N` contract.
    browse_next_page = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["business_date", "timezone"], name="uq_daily_cycle_business_date_tz"
            )
        ]

    def __str__(self) -> str:
        return f"{self.business_date} ({self.timezone})"


class DailyCandidate(models.Model):
    STATE_CHOICES = [
        ("pending", "pending"),
        ("processing", "processing"),
        ("processed", "processed"),
        ("retryable", "retryable"),
        ("failed", "failed"),
    ]

    cycle = models.ForeignKey(DailyCycle, on_delete=models.PROTECT, related_name="candidates")
    game = models.ForeignKey("catalog.Game", on_delete=models.PROTECT, related_name="candidates")
    source_order = models.PositiveIntegerField()
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default="pending")
    attempt_count = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cycle", "game"], name="uq_daily_candidate_cycle_game"),
            models.UniqueConstraint(
                fields=["cycle", "source_order"], name="uq_daily_candidate_cycle_order"
            ),
        ]

    def __str__(self) -> str:
        return f"candidate({self.game_id}) in {self.cycle_id}"


class CoreAttempt(models.Model):
    OUTCOME_CHOICES = [("succeeded", "succeeded"), ("failed", "failed")]

    candidate = models.ForeignKey(DailyCandidate, on_delete=models.PROTECT, related_name="attempts")
    run = models.ForeignKey(ProcessingRun, on_delete=models.PROTECT, related_name="core_attempts")
    attempt_no = models.PositiveIntegerField()
    fencing_token = models.PositiveBigIntegerField()
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=16, choices=OUTCOME_CHOICES, null=True, blank=True)
    error_code = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["candidate", "attempt_no"], name="uq_core_attempt_candidate_no"
            )
        ]

    def __str__(self) -> str:
        return f"attempt {self.attempt_no} of candidate {self.candidate_id}"


class RunCandidate(models.Model):
    """BON-21: immutable batch membership, including candidates not yet attempted."""

    run = models.ForeignKey(ProcessingRun, on_delete=models.PROTECT, related_name="batch")
    candidate = models.ForeignKey(DailyCandidate, on_delete=models.PROTECT, related_name="batches")
    position = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "candidate"], name="uq_run_candidate"),
            models.UniqueConstraint(fields=["run", "position"], name="uq_run_position"),
            models.CheckConstraint(
                condition=models.Q(position__gte=1, position__lte=20), name="run_position_limit"
            ),
        ]


class ProcessHeartbeat(models.Model):
    """Observations only: a missing heartbeat never changes processing ownership."""

    role = models.CharField(
        max_length=16, choices=[("scheduler", "scheduler"), ("worker", "worker")]
    )
    slot = models.CharField(max_length=32, default="main")
    instance_id = models.UUIDField()
    generation = models.PositiveBigIntegerField(default=1)
    started_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    last_progress_at = models.DateTimeField()
    mode = models.CharField(max_length=16, default="idle")
    stage = models.CharField(max_length=32, default="idle")
    run_id = models.PositiveBigIntegerField(null=True, blank=True)
    job_id = models.PositiveBigIntegerField(null=True, blank=True)
    deadline_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "slot"], name="uq_process_role_slot")
        ]
