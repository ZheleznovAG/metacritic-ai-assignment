"""Placeholder durable job row for IMP-02; IMP-04 adds the fields it actually fetches with."""

from django.db import models


class ReviewCollectionJob(models.Model):
    AUDIENCE_CHOICES = [("critic", "critic"), ("user", "user")]
    STATE_CHOICES = [
        ("pending", "pending"),
        ("running", "running"),
        ("complete", "complete"),
        ("empty", "empty"),
        ("retryable", "retryable"),
        ("unstable", "unstable"),
        ("failed", "failed"),
    ]

    daily_candidate = models.ForeignKey(
        "processing.DailyCandidate", on_delete=models.PROTECT, related_name="review_jobs"
    )
    game_platform = models.ForeignKey(
        "catalog.GamePlatform", on_delete=models.PROTECT, related_name="review_jobs"
    )
    audience = models.CharField(max_length=8, choices=AUDIENCE_CHOICES)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["daily_candidate", "game_platform", "audience"],
                name="uq_review_job_candidate_platform_audience",
            )
        ]

    def __str__(self) -> str:
        return f"{self.audience} job for platform {self.game_platform_id}"
