"""Collected review data and the built audience corpus, per `docs/design.md`'s `reviews` module:
saves downloaded review records/observations and builds the audience corpus; never translates,
paraphrases, or deletes history on a partial fetch.
"""

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

    # Arrival time (not lease/claim time): backlog/oldest-age visibility. Nullable only because
    # rows created before this field existed have no recorded arrival time; every row created
    # from here on gets one automatically.
    created_at = models.DateTimeField(null=True, blank=True, auto_now_add=True)

    # Collection progress (IMP-04). A generation is one attempt to reach a terminal snapshot of
    # this route; it restarts from the confirmed initial route URL (never `?page=N`, confirmed
    # dead for this route) and only advances `next_cursor` atomically with an accepted page.
    collection_generation = models.PositiveIntegerField(default=0)
    next_cursor = models.TextField(null=True, blank=True)
    reported_total = models.PositiveIntegerField(null=True, blank=True)
    fetched_count = models.PositiveIntegerField(default=0)
    unique_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    page_count = models.PositiveIntegerField(default=0)
    # SHA-256 of each accepted page's ordered identity-key list this generation, in page order —
    # detects a cursor loop / repeated page identity without a separate history table.
    visited_page_fingerprints = models.JSONField(default=list, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)

    # Row-level lease (SELECT ... FOR UPDATE SKIP LOCKED), distinct from processing's singleton
    # ProcessingLease: many review jobs are in flight at once, so each job row leases itself.
    available_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    fencing_token = models.PositiveBigIntegerField(default=0)
    last_error = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["daily_candidate", "game_platform", "audience"],
                name="uq_review_job_candidate_platform_audience",
            )
        ]

    def __str__(self) -> str:
        return f"{self.audience} job for platform {self.game_platform_id}"


class Review(models.Model):
    AUDIENCE_CHOICES = ReviewCollectionJob.AUDIENCE_CHOICES

    game_platform = models.ForeignKey(
        "catalog.GamePlatform", on_delete=models.PROTECT, related_name="reviews"
    )
    audience = models.CharField(max_length=8, choices=AUDIENCE_CHOICES)
    source_review_id = models.CharField(max_length=128, null=True, blank=True)
    # `id:<value>` when the source gives a stable review ID, else `fallback:<sha256>` of
    # audience + platform ID + review URL + author/source label + published label + score +
    # full normalized text (docs/design.md) — a changed fallback-identity review is a new logical
    # review, not a version of the old one.
    identity_key = models.CharField(max_length=140)
    author_label = models.CharField(max_length=255, null=True, blank=True)
    score_label = models.CharField(max_length=32, null=True, blank=True)
    date_label = models.CharField(max_length=64, null=True, blank=True)
    text_original = models.TextField()
    content_sha256 = models.CharField(max_length=64)
    first_seen_at = models.DateTimeField()
    supersedes = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="superseded_by"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["game_platform", "audience", "identity_key", "content_sha256"],
                name="uq_review_platform_audience_identity_content",
            )
        ]

    def __str__(self) -> str:
        return f"{self.audience}:{self.identity_key}"


class ReviewObservation(models.Model):
    collection_job = models.ForeignKey(
        ReviewCollectionJob, on_delete=models.PROTECT, related_name="observations"
    )
    collection_generation = models.PositiveIntegerField()
    source_fetch = models.ForeignKey(
        "catalog.SourceFetch", on_delete=models.PROTECT, related_name="review_observations"
    )
    review = models.ForeignKey(Review, on_delete=models.PROTECT, related_name="observations")
    page_position = models.PositiveIntegerField()
    route_global_position = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_fetch", "page_position"],
                name="uq_review_observation_fetch_position",
            ),
            models.UniqueConstraint(
                fields=["collection_job", "collection_generation", "review"],
                name="uq_review_observation_job_generation_review",
            ),
            models.UniqueConstraint(
                fields=["collection_job", "collection_generation", "route_global_position"],
                name="uq_review_observation_job_generation_position",
            ),
        ]

    def __str__(self) -> str:
        return f"observation {self.review_id} @ {self.route_global_position}"


class ReviewCorpus(models.Model):
    AUDIENCE_CHOICES = ReviewCollectionJob.AUDIENCE_CHOICES

    game = models.ForeignKey(
        "catalog.Game", on_delete=models.PROTECT, related_name="review_corpora"
    )
    audience = models.CharField(max_length=8, choices=AUDIENCE_CHOICES)
    policy_version = models.CharField(max_length=32)
    source_set_fingerprint = models.CharField(max_length=64)
    model_input_fingerprint = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    complete_route_count = models.PositiveIntegerField()
    empty_route_count = models.PositiveIntegerField()
    reported_count = models.PositiveIntegerField()
    fetched_count = models.PositiveIntegerField()
    unique_count = models.PositiveIntegerField()
    deduplicated_count = models.PositiveIntegerField()
    selected_count = models.PositiveIntegerField()

    tokenizer_id = models.CharField(max_length=32)
    tokenizer_version = models.CharField(max_length=32)
    raw_prompt_tokens = models.PositiveIntegerField()
    guarded_prompt_tokens = models.PositiveIntegerField()
    completion_reservation = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["game", "audience", "policy_version", "source_set_fingerprint"],
                name="uq_review_corpus_game_audience_policy_fingerprint",
            )
        ]
        verbose_name_plural = "review corpora"

    def __str__(self) -> str:
        return f"corpus {self.game_id}/{self.audience}/{self.policy_version}"


class ReviewCorpusItem(models.Model):
    corpus = models.ForeignKey(ReviewCorpus, on_delete=models.PROTECT, related_name="items")
    ordinal = models.PositiveSmallIntegerField()
    prompt_review_id = models.CharField(max_length=8)
    review = models.ForeignKey(Review, on_delete=models.PROTECT, related_name="corpus_items")
    input_text = models.TextField()
    input_token_count = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    was_truncated = models.BooleanField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["corpus", "ordinal"], name="uq_corpus_item_ordinal"),
            models.UniqueConstraint(
                fields=["corpus", "prompt_review_id"], name="uq_corpus_item_prompt_review_id"
            ),
            models.UniqueConstraint(fields=["corpus", "review"], name="uq_corpus_item_review"),
        ]

    def __str__(self) -> str:
        return f"{self.corpus_id}:{self.prompt_review_id}"
