"""Minimal daily-cycle/candidate rows for IMP-02; full SEL-01-03 selection is IMP-03."""

from django.db import models


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
    exhausted = models.BooleanField(default=False)
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
