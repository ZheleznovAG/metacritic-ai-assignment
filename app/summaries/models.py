"""Persistent AI jobs, provider attempts, canonical validation and claims, per `docs/design.md`'s
`summaries` module: never mixes audiences, never knows HTML/UI.
"""

from django.db import models


class SummaryJob(models.Model):
    AUDIENCE_CHOICES = [("critic", "critic"), ("user", "user")]
    STATE_CHOICES = [
        ("pending", "pending"),
        ("running", "running"),
        ("succeeded", "succeeded"),
        ("insufficient_data", "insufficient_data"),
        ("retryable", "retryable"),
        ("delayed_capacity", "delayed_capacity"),
        ("failed", "failed"),
    ]

    game = models.ForeignKey("catalog.Game", on_delete=models.PROTECT, related_name="summary_jobs")
    audience = models.CharField(max_length=8, choices=AUDIENCE_CHOICES)
    source_corpus = models.ForeignKey(
        "reviews.ReviewCorpus", on_delete=models.PROTECT, related_name="summary_jobs"
    )
    # Same (game, audience, input_fingerprint, contour_fingerprint) is a cache hit: unchanged
    # input/config never spends AI quota again (docs/design.md invariant 7).
    input_fingerprint = models.CharField(max_length=64)
    contour_fingerprint = models.CharField(max_length=64)
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default="pending")
    attempt_count = models.PositiveIntegerField(default=0)

    # Arrival time (not lease/claim time): backlog/oldest-age visibility per docs/design.md's
    # observability module and research/feasibility/ai-summary.md's fake-provider workload ask.
    created_at = models.DateTimeField(auto_now_add=True)
    available_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    fencing_token = models.PositiveBigIntegerField(default=0)
    last_error = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["game", "audience", "input_fingerprint", "contour_fingerprint"],
                name="uq_summary_job_game_audience_input_contour",
            )
        ]

    def __str__(self) -> str:
        return f"summary job {self.game_id}/{self.audience}:{self.state}"


class SummaryAttempt(models.Model):
    OUTCOME_CHOICES = [
        ("succeeded", "succeeded"),
        ("insufficient_data", "insufficient_data"),
        ("retryable", "retryable"),
        ("delayed_capacity", "delayed_capacity"),
        ("failed", "failed"),
        ("abandoned", "abandoned"),
    ]

    job = models.ForeignKey(SummaryJob, on_delete=models.PROTECT, related_name="attempts")
    attempt_no = models.PositiveIntegerField()
    fencing_token = models.PositiveBigIntegerField(default=0)
    request_sha256 = models.CharField(max_length=64, default="", blank=True)
    raw_prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    rate_limit_headers = models.JSONField(default=dict, blank=True)
    provider = models.CharField(max_length=32, default="groq")
    api_kind = models.CharField(max_length=32, default="chat_completions")
    requested_model = models.CharField(max_length=64)
    returned_model = models.CharField(max_length=64, null=True, blank=True)
    provider_system_fingerprint = models.CharField(max_length=128, null=True, blank=True)
    # Contour versions/hashes (prompt/schema/normalizer/adapter/tokenizer) — the exact set that
    # feeds contour_fingerprint. Never contains a secret, provider request ID, raw reasoning, or
    # raw response envelope (docs/design.md).
    contour_versions = models.JSONField()
    generation_params = models.JSONField()

    estimated_prompt_tokens = models.PositiveIntegerField()
    reserved_total_tokens = models.PositiveIntegerField()
    actual_prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    actual_completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    actual_total_tokens = models.PositiveIntegerField(null=True, blank=True)

    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES, null=True, blank=True)
    error_code = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "attempt_no"], name="uq_summary_attempt_job_no")
        ]

    def __str__(self) -> str:
        return f"attempt {self.attempt_no} for job {self.job_id}"


class ReviewSummary(models.Model):
    METHOD_CHOICES = [("model", "model"), ("rule", "rule")]
    STATUS_CHOICES = [("ok", "ok"), ("insufficient_data", "insufficient_data")]

    job = models.OneToOneField(SummaryJob, on_delete=models.PROTECT, related_name="summary")
    successful_attempt = models.ForeignKey(
        SummaryAttempt, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    method = models.CharField(max_length=16, choices=METHOD_CHOICES, default="model")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    generated_at = models.DateTimeField()
    insufficient_reason = models.CharField(max_length=64, null=True, blank=True)
    canonical_output_fingerprint = models.CharField(max_length=64)
    normalization_notes = models.JSONField(default=list, blank=True)

    def __str__(self) -> str:
        return f"summary for job {self.job_id}: {self.status}"


class SummaryClaim(models.Model):
    POLARITY_CHOICES = [("like", "like"), ("dislike", "dislike")]

    summary = models.ForeignKey(ReviewSummary, on_delete=models.PROTECT, related_name="claims")
    polarity = models.CharField(max_length=8, choices=POLARITY_CHOICES)
    ordinal = models.PositiveSmallIntegerField()
    claim = models.CharField(max_length=160)
    support_item = models.ForeignKey(
        "reviews.ReviewCorpusItem", on_delete=models.PROTECT, related_name="supported_claims"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["summary", "polarity", "ordinal"], name="uq_summary_claim_polarity_ordinal"
            )
        ]

    def __str__(self) -> str:
        return f"{self.polarity}: {self.claim[:40]}"
